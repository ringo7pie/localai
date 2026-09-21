"""ビルド・テストの実行と、その証拠の記録。

LLM が「テストは通った」と書いたことは根拠にしない。ここで実際に起動した
コマンド・作業ディレクトリ・終了コード・時刻・ログ位置・検証した木のハッシュを
台帳へ残す。実行コマンドは設定に登録された argv だけで、シェルは介さない。

記録の置き場は worktree の外（state 配下）にする。編集担当が書き換えられる場所に
受け入れ基準と実行記録を置かないため。
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import VerifyProfile, git_binary

TEST_PATH_PATTERN = re.compile(r"(^|/)(tests?|spec|__tests__)(/|$)|(^|/)test_[^/]+$|_test\.[a-z]+$")


@dataclass
class VerifyResult:
    profile: str
    command: list[str]
    cwd: str
    exit_code: int | None
    started_at: float
    ended_at: float
    log_path: str
    tree_hash: str | None
    timed_out: bool = False
    tail: str = ""

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "timed_out": self.timed_out,
            "duration_sec": round(self.ended_at - self.started_at, 2),
            "log_path": self.log_path,
            "tree_hash": self.tree_hash,
        }


@dataclass
class TestIntegrity:
    """既存テストの削除・緩和・除外を検出した結果。"""

    deleted: list[str] = field(default_factory=list)
    shrunk: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return bool(self.deleted or self.shrunk)

    def as_dict(self) -> dict:
        return {
            "deleted_test_files": self.deleted,
            "shrunk_test_files": self.shrunk,
            "modified_test_files": self.modified,
            "suspicious": self.suspicious,
        }


def run_profile(
    *,
    profile: VerifyProfile,
    cwd: Path,
    log_path: Path,
    tree_hash: str | None,
    timeout_sec: int | None = None,
) -> VerifyResult:
    """登録済みプロファイルを実行する。shell=False。argv は設定由来のみ。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    limit = timeout_sec or profile.timeout_sec
    started = time.time()
    timed_out = False
    exit_code: int | None = None
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"# command: {profile.command}\n# cwd: {cwd}\n# started: {started}\n\n")
        log_file.flush()
        try:
            completed = subprocess.run(
                list(profile.command),
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limit,
                start_new_session=True,
            )
            log_file.write(completed.stdout)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            if exc.stdout:
                log_file.write(
                    exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace")
                )
            log_file.write(f"\n# タイムアウト: {limit} 秒\n")
        except FileNotFoundError as exc:
            log_file.write(f"\n# コマンドが見つかりません: {exc}\n")
            exit_code = 127
    ended = time.time()
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return VerifyResult(
        profile=profile.name,
        command=list(profile.command),
        cwd=str(cwd),
        exit_code=exit_code,
        started_at=started,
        ended_at=ended,
        log_path=str(log_path),
        tree_hash=tree_hash,
        timed_out=timed_out,
        tail="\n".join(text.splitlines()[-40:]),
    )


def check_test_integrity(worktree: Path, base_commit: str) -> TestIntegrity:
    """テストファイルが消された・短くされたのを検出する。

    行数が減っただけで不正と断定はしない。報告して人が見るための材料にする。
    """
    integrity = TestIntegrity()
    completed = subprocess.run(
        [git_binary(), "-C", str(worktree), "diff", "--cached", "--numstat", "-M", base_commit],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return integrity
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        added_raw, removed_raw, path = fields[0], fields[1], fields[-1]
        if not TEST_PATH_PATTERN.search(path):
            continue
        integrity.modified.append(path)
        if added_raw == "-" or removed_raw == "-":
            continue
        added, removed = int(added_raw), int(removed_raw)
        if not (worktree / path).exists():
            integrity.deleted.append(path)
        elif removed > added:
            integrity.shrunk.append(path)
    return integrity
