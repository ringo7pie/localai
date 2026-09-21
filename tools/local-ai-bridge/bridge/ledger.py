"""作業台帳（SQLite）。CLI と MCP は同じこのファイルを読み書きする。

台帳はローカルディスク上にだけ置く（共有 NAS 上に置くと SQLite のロックが壊れる）。
置き場の検証は config.load() が行う。
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

# 状態。依頼の分類に対応させる。
#   queued            待機
#   running           実行中
#   awaiting_input    入力待ち（未コミット変更など、人の判断が要る）
#   awaiting_approval 承認待ち（権限が要る操作）
#   succeeded         成功
#   failed            失敗
#   aborted           中断（予算・上限・タイムアウト）
#   cancelling        停止要求中
#   cancelled         停止確認済み
TERMINAL_STATES = {"succeeded", "failed", "aborted", "cancelled"}
ALL_STATES = TERMINAL_STATES | {
    "queued",
    "running",
    "awaiting_input",
    "awaiting_approval",
    "cancelling",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id            TEXT PRIMARY KEY,
    request_id         TEXT NOT NULL,
    client_id          TEXT NOT NULL,
    workspace_id       TEXT NOT NULL,
    workspace_path     TEXT NOT NULL,
    goal               TEXT NOT NULL,
    scope_json         TEXT NOT NULL,
    forbidden_json     TEXT NOT NULL,
    acceptance_json    TEXT NOT NULL,
    base_commit        TEXT,
    verify_profile     TEXT,
    mode               TEXT NOT NULL,
    budget_json        TEXT NOT NULL,
    state              TEXT NOT NULL,
    stage              TEXT,
    worktree_path      TEXT,
    diff_path          TEXT,
    new_files_json     TEXT,
    attempt_count      INTEGER NOT NULL DEFAULT 0,
    open_questions_json TEXT,
    runner_pid         INTEGER,
    runner_host        TEXT,
    runner_boot_id     TEXT,
    created_at         REAL NOT NULL,
    started_at         REAL,
    ended_at           REAL,
    queue_wait_sec     REAL,
    model_name         TEXT,
    model_digest       TEXT,
    effective_json     TEXT,
    tool_versions_json TEXT,
    usage_json         TEXT,
    summary            TEXT,
    cancel_requested_at REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_request
    ON tasks (client_id, request_id);

CREATE TABLE IF NOT EXISTS sessions (
    task_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    session_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (task_id, role, session_id)
);

CREATE TABLE IF NOT EXISTS verifications (
    task_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    profile    TEXT NOT NULL,
    command    TEXT NOT NULL,
    cwd        TEXT NOT NULL,
    exit_code  INTEGER,
    started_at REAL NOT NULL,
    ended_at   REAL,
    log_path   TEXT NOT NULL,
    tree_hash  TEXT,
    stale      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (task_id, seq)
);

CREATE TABLE IF NOT EXISTS events (
    task_id  TEXT NOT NULL,
    ts       REAL NOT NULL,
    kind     TEXT NOT NULL,
    detail   TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_task ON events (task_id, ts);
"""


@dataclass
class Task:
    row: sqlite3.Row

    def __getitem__(self, key: str) -> Any:
        return self.row[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self.row[key]
        except (IndexError, KeyError):
            return default

    def as_dict(self) -> dict[str, Any]:
        return dict(self.row)


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # --- タスク --------------------------------------------------------
    def insert_task(self, values: dict[str, Any]) -> None:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO tasks ({columns}) VALUES ({placeholders})", tuple(values.values())
            )

    def find_by_request(self, client_id: str, request_id: str) -> Task | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE client_id = ? AND request_id = ?",
                (client_id, request_id),
            ).fetchone()
        return Task(row) if row else None

    def get(self, task_id: str) -> Task | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return Task(row) if row else None

    def update(self, task_id: str, **values: Any) -> None:
        if not values:
            return
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                (*values.values(), task_id),
            )

    def compare_and_set_state(self, task_id: str, expected: str, new: str, **extra: Any) -> bool:
        """expected の状態のときだけ new にする。二重実行の防止に使う。"""
        assignments = ", ".join(["state = ?"] + [f"{key} = ?" for key in extra])
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ? AND state = ?",
                (new, *extra.values(), task_id, expected),
            )
            return cursor.rowcount == 1

    def list_tasks(self, limit: int = 50, state: str | None = None) -> list[Task]:
        query = "SELECT * FROM tasks"
        params: tuple[Any, ...] = ()
        if state:
            query += " WHERE state = ?"
            params = (state,)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self.connect() as connection:
            rows = connection.execute(query, (*params, limit)).fetchall()
        return [Task(row) for row in rows]

    # --- 付随テーブル --------------------------------------------------
    def add_session(self, task_id: str, role: str, session_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO sessions (task_id, role, session_id, created_at)"
                " VALUES (?, ?, ?, ?)",
                (task_id, role, session_id, time.time()),
            )

    def sessions(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT role, session_id, created_at FROM sessions WHERE task_id = ?"
                " ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def session_for_role(self, task_id: str, role: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT session_id FROM sessions WHERE task_id = ? AND role = ?"
                " ORDER BY created_at DESC LIMIT 1",
                (task_id, role),
            ).fetchone()
        return row["session_id"] if row else None

    def add_verification(self, task_id: str, record: dict[str, Any]) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM verifications WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            seq = int(row["next"])
            connection.execute(
                "INSERT INTO verifications"
                " (task_id, seq, profile, command, cwd, exit_code, started_at, ended_at,"
                "  log_path, tree_hash, stale)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    task_id,
                    seq,
                    record["profile"],
                    json.dumps(record["command"], ensure_ascii=False),
                    record["cwd"],
                    record.get("exit_code"),
                    record["started_at"],
                    record.get("ended_at"),
                    record["log_path"],
                    record.get("tree_hash"),
                ),
            )
        return seq

    def mark_verifications_stale(self, task_id: str, current_tree_hash: str | None) -> int:
        """検証後に変更が入ったものを失効させる。tree_hash が違えば stale。"""
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE verifications SET stale = 1"
                " WHERE task_id = ? AND stale = 0 AND (tree_hash IS NULL OR tree_hash != ?)",
                (task_id, current_tree_hash or ""),
            )
            return cursor.rowcount

    def verifications(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM verifications WHERE task_id = ? ORDER BY seq", (task_id,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["command"] = json.loads(item["command"])
            item["stale"] = bool(item["stale"])
            result.append(item)
        return result

    def add_event(self, task_id: str, kind: str, detail: Any = None) -> None:
        payload = detail if isinstance(detail, str) or detail is None else json.dumps(
            detail, ensure_ascii=False
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO events (task_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                (task_id, time.time(), kind, payload),
            )

    def events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT ts, kind, detail FROM events WHERE task_id = ? ORDER BY ts LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
