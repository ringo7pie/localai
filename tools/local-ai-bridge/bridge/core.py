"""CLI と MCP が共通で呼ぶ処理。別々の実装にしない。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from . import config as config_module
from . import opencode, procs, worktree
from .errors import BridgeError, DuplicateRequestError, NotFoundError
from .ledger import TERMINAL_STATES, Ledger

MODES = ("standard", "deep", "exhaustive")
ON_DIRTY = ("wait", "use_head", "include_uncommitted")

# 取り出してよい成果物。ここに無いものは返さない（任意のファイルを読む API にしない）。
ARTIFACTS = {
    "diff": "changes.diff",
    "result": "result.json",
}
ARTIFACT_PREFIXES = ("verify-", "events-", "stderr-")


def _now() -> float:
    return time.time()


def _new_task_id() -> str:
    return "task_" + uuid.uuid4().hex[:16]


def load_config(path: Path | None = None) -> config_module.Config:
    cfg = config_module.load(path)
    cfg.ensure_dirs()
    return cfg


# --- doctor -----------------------------------------------------------
def doctor(cfg: config_module.Config) -> dict[str, Any]:
    """接続と前提の点検。取得できない値は推測で埋めず未取得と書く。"""
    report: dict[str, Any] = {
        "config_path": str(cfg.config_path),
        "checks": [],
        "warnings": [],
    }

    def check(name: str, ok: bool | None, detail: str) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    # 1. Ollama
    try:
        with urllib.request.urlopen(
            f"{cfg.ollama_base_url}/api/version", timeout=cfg.limits.connect_timeout_sec
        ) as response:
            version = json.loads(response.read().decode("utf-8")).get("version")
        check("ollama 接続", True, f"{cfg.ollama_base_url} version={version}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        check("ollama 接続", False, f"{cfg.ollama_base_url} へ到達できない: {exc}")
        version = None

    # 2. モデルの実在と digest
    digest = None
    try:
        with urllib.request.urlopen(
            f"{cfg.ollama_base_url}/api/tags", timeout=cfg.limits.connect_timeout_sec
        ) as response:
            models = json.loads(response.read().decode("utf-8")).get("models", [])
        match = next((item for item in models if item.get("name") == cfg.model), None)
        if match:
            digest = match.get("digest")
            check(
                "モデル",
                True,
                f"{cfg.model} digest={str(digest)[:16]} "
                f"quant={match.get('details', {}).get('quantization_level')}",
            )
        else:
            check(
                "モデル",
                False,
                f"{cfg.model} が Ollama の一覧にない。存在するのは: "
                + ", ".join(item.get("name", "?") for item in models),
            )
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        check("モデル", None, f"一覧を取得できなかった: {exc}")

    # 3. OpenCode の実体
    try:
        completed = subprocess.run(
            [str(cfg.opencode_binary), "--version"], capture_output=True, text=True, timeout=60
        )
        check(
            "opencode",
            completed.returncode == 0,
            f"{cfg.opencode_binary} version={completed.stdout.strip()}",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        check("opencode", False, f"{cfg.opencode_binary} を実行できない: {exc}")

    # 4. 隔離プロファイル
    profile = opencode.Profile(cfg.opencode_profile_dir, cfg.opencode_config_source)
    try:
        applied = profile.ensure()
        check("隔離プロファイル", True, "; ".join(applied["actions"]))
    except OSError as exc:
        check("隔離プロファイル", False, str(exc))

    stray = profile.stray_config_paths()
    if stray:
        report["warnings"].append(
            "XDG の差し替えでは隔離されない設定ファイルがある（実効設定が混ざる）: "
            + ", ".join(str(path) for path in stray)
        )

    # 5. 実効設定（置いただけで効いたと判断しない）
    try:
        completed = subprocess.run(
            [str(cfg.opencode_binary), "debug", "config"],
            cwd=str(next(iter(cfg.workspaces.values())).path) if cfg.workspaces else str(Path.home()),
            env=profile.child_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        resolved = json.loads(completed.stdout) if completed.returncode == 0 else {}
        providers = resolved.get("enabled_providers")
        model_setting = resolved.get("model")
        small = resolved.get("small_model")
        ok = providers == ["ollama"] and model_setting == f"ollama/{cfg.model}"
        check(
            "実効設定",
            ok,
            f"enabled_providers={providers} model={model_setting} small_model={small} "
            f"share={resolved.get('share')} autoupdate={resolved.get('autoupdate')} "
            f"subagent_depth={resolved.get('subagent_depth')}",
        )
        report["resolved_permission"] = resolved.get("permission")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        check("実効設定", None, f"opencode debug config を読めなかった: {exc}")

    # 6. 見えるモデルがローカルだけか
    try:
        completed = subprocess.run(
            [str(cfg.opencode_binary), "models"],
            env=profile.child_env(),
            capture_output=True,
            text=True,
            timeout=180,
        )
        visible = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        only_local = bool(visible) and all(line.startswith("ollama/") for line in visible)
        check("見えるモデル", only_local, ", ".join(visible) or "(取得できず)")
    except (OSError, subprocess.TimeoutExpired) as exc:
        check("見えるモデル", None, f"opencode models を読めなかった: {exc}")

    # 7. 台帳
    try:
        ledger = Ledger(cfg.ledger_path)
        running = len(ledger.list_tasks(limit=200, state="running"))
        check("台帳", True, f"{cfg.ledger_path}（実行中 {running} 件）")
    except Exception as exc:  # noqa: BLE001
        check("台帳", False, f"{cfg.ledger_path}: {exc}")

    # 8. 登録済みの作業場所
    for workspace in cfg.workspaces.values():
        is_git = worktree.is_git_repo(workspace.path)
        dirty = len(worktree.dirty_entries(workspace.path)) if is_git else 0
        check(
            f"workspace {workspace.workspace_id}",
            is_git,
            f"{workspace.path} git={is_git} 未コミット={dirty} "
            f"検証プロファイル={sorted(workspace.verify_profiles) or '(なし)'}",
        )
    if not cfg.workspaces:
        report["warnings"].append("作業場所が 1 つも登録されていない。bridge.toml に追加すること。")

    report["summary"] = {
        "ok": sum(1 for item in report["checks"] if item["ok"] is True),
        "ng": sum(1 for item in report["checks"] if item["ok"] is False),
        "unknown": sum(1 for item in report["checks"] if item["ok"] is None),
    }
    return report


# --- submit -----------------------------------------------------------
def submit(
    cfg: config_module.Config,
    *,
    request_id: str,
    client_id: str,
    workspace_id: str,
    goal: str,
    allowed_scope: list[str] | None = None,
    forbidden: list[str] | None = None,
    acceptance: list[str] | None = None,
    base_commit: str | None = None,
    verify_profile: str | None = None,
    mode: str = "deep",
    on_dirty: str = "wait",
    budget_overrides: dict[str, int] | None = None,
) -> dict[str, Any]:
    """受付だけを行い、task_id を返す。実行は別プロセスに任せる。"""
    if mode not in MODES:
        raise BridgeError(f"mode は {MODES} のいずれかにしてください: {mode!r}")
    if on_dirty not in ON_DIRTY:
        raise BridgeError(f"on_dirty は {ON_DIRTY} のいずれかにしてください: {on_dirty!r}")
    if not goal.strip():
        raise BridgeError("goal が空です。")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id or ""):
        raise BridgeError("request_id は英数字と . _ : - の 1〜128 文字にしてください。")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", client_id or ""):
        raise BridgeError("client_id は英数字と . _ : - の 1〜64 文字にしてください。")

    workspace = cfg.workspace(workspace_id)
    workspace.profile(verify_profile)  # 未登録なら NotFoundError

    ledger = Ledger(cfg.ledger_path)
    existing = ledger.find_by_request(client_id, request_id)
    if existing is not None:
        raise DuplicateRequestError(
            f"request_id {request_id!r} は既に受け付け済みです（state={existing['state']}）。"
            " 同じ依頼を作り直さず、status / result で確認してください。",
            task_id=existing["task_id"],
        )

    task_id = _new_task_id()
    work_dir = cfg.worktrees_dir / task_id
    prepared = worktree.prepare(
        repo=workspace.path,
        worktree=work_dir,
        base_commit=base_commit,
        on_dirty=on_dirty,
    )

    budget = {
        "max_job_seconds": cfg.limits.max_job_seconds,
        "max_model_calls": cfg.limits.max_model_calls,
        "max_tool_calls": cfg.limits.max_tool_calls,
        "max_repair_rounds": cfg.limits.repair_rounds.get(mode, 1),
    }
    if budget_overrides:
        budget.update({key: int(value) for key, value in budget_overrides.items()})

    ledger.insert_task(
        {
            "task_id": task_id,
            "request_id": request_id,
            "client_id": client_id,
            "workspace_id": workspace_id,
            "workspace_path": str(workspace.path),
            "goal": goal.strip(),
            "scope_json": json.dumps(allowed_scope or [], ensure_ascii=False),
            "forbidden_json": json.dumps(forbidden or [], ensure_ascii=False),
            "acceptance_json": json.dumps(acceptance or [], ensure_ascii=False),
            "base_commit": prepared.base_commit,
            "verify_profile": verify_profile or workspace.default_verify,
            "mode": mode,
            "budget_json": json.dumps(budget, ensure_ascii=False),
            "state": "queued",
            "stage": "queued",
            "worktree_path": str(work_dir),
            "created_at": _now(),
            "model_name": cfg.model,
        }
    )
    ledger.add_event(
        task_id,
        "submitted",
        {
            "workspace_id": workspace_id,
            "mode": mode,
            "on_dirty": on_dirty,
            "copied_dirty": prepared.copied_dirty,
            "skipped_secrets": prepared.skipped_secrets,
        },
    )
    _spawn_runner(cfg, task_id)
    return {
        "task_id": task_id,
        "state": "queued",
        "base_commit": prepared.base_commit,
        "worktree": str(work_dir),
        "mode": mode,
        "verify_profile": verify_profile or workspace.default_verify,
        "budget": budget,
        "copied_uncommitted_files": prepared.copied_dirty,
        "skipped_secret_files": prepared.skipped_secrets,
        "note": "受付のみ完了。進捗は get_task_status / local-ai-task status で確認する。",
    }


def _spawn_runner(cfg: config_module.Config, task_id: str) -> None:
    """実行管理プロセスを切り離して起動する。CLI / MCP の寿命とは切り離す。"""
    log_path = cfg.tasks_dir / task_id / "runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LOCAL_AI_BRIDGE_CONFIG"] = str(cfg.config_path)
    with log_path.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "bridge.runner", task_id],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )


# --- status / result --------------------------------------------------
def status(cfg: config_module.Config, task_id: str) -> dict[str, Any]:
    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(task_id)
    if task is None:
        raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
    runner_alive = procs.alive(task.get("runner_boot_id"))
    state = task["state"]
    inconsistent = state in ("running", "cancelling") and not runner_alive
    return {
        "task_id": task_id,
        "state": state,
        "stage": task["stage"],
        "runner_alive": runner_alive,
        "state_inconsistent": inconsistent,
        "note": (
            "台帳では実行中だが実行管理プロセスが生きていない。resume で引き継ぐか、"
            "result で途中成果を確認すること。"
            if inconsistent
            else None
        ),
        "attempt_count": task["attempt_count"],
        "mode": task["mode"],
        "workspace_id": task["workspace_id"],
        "queue_wait_sec": task["queue_wait_sec"],
        "elapsed_sec": round((task["ended_at"] or _now()) - (task["started_at"] or task["created_at"]), 1),
        "cancel_requested": bool(task["cancel_requested_at"]),
        "summary": task["summary"],
    }


def result(cfg: config_module.Config, task_id: str, include_diff: bool = False) -> dict[str, Any]:
    """通常は短く返す。大きな差分やログはローカルに置き、パスだけ返す。"""
    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(task_id)
    if task is None:
        raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
    task_dir = cfg.tasks_dir / task_id
    detail: dict[str, Any] = {}
    result_file = task_dir / "result.json"
    if result_file.is_file():
        try:
            detail = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            detail = {}

    verifications = ledger.verifications(task_id)
    latest = verifications[-1] if verifications else None
    payload: dict[str, Any] = {
        "task_id": task_id,
        "state": task["state"],
        "summary": task["summary"],
        "changes": detail.get("changes"),
        "verification": (
            {
                "profile": latest["profile"],
                "command": latest["command"],
                "exit_code": latest["exit_code"],
                "passed": latest["exit_code"] == 0,
                "stale": latest["stale"],
                "log_path": latest["log_path"],
                "tree_hash": latest["tree_hash"],
            }
            if latest
            else None
        ),
        "test_integrity": detail.get("test_integrity"),
        "open_questions": json.loads(task["open_questions_json"] or "[]"),
        "usage": json.loads(task["usage_json"] or "null"),
        "sessions": ledger.sessions(task_id),
        "artifacts": _artifact_index(task_dir),
        "approval_required": task["state"] == "awaiting_approval",
        "apply_hint": None,
    }
    if task["diff_path"]:
        payload["apply_hint"] = (
            f"確認してから当てる: git -C {task['workspace_path']} apply --check -p1 {task['diff_path']}"
            f" && git -C {task['workspace_path']} apply -p1 {task['diff_path']}"
            "  （連携層は元リポジトリへ適用しない。commit / push もしない）"
        )
    if include_diff and task["diff_path"] and Path(task["diff_path"]).is_file():
        diff_text = Path(task["diff_path"]).read_text(encoding="utf-8", errors="replace")
        payload["diff_text"] = diff_text

    encoded = json.dumps(payload, ensure_ascii=False)
    limit = cfg.limits.result_max_bytes
    if len(encoded.encode("utf-8")) > limit:
        # JSON を壊して切り詰めない。大きい項目を外して、取り出し方を書く。
        dropped = []
        for key in ("diff_text",):
            if key in payload:
                del payload[key]
                dropped.append(key)
        payload["omitted"] = {
            "fields": dropped,
            "how_to_get": "get_artifact(task_id, name='diff', start_line=..., line_count=...) で範囲指定して取得する。",
        }
    if payload.get("usage"):
        payload["usage"]["returned_bytes"] = len(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
    return payload


def _artifact_index(task_dir: Path) -> list[dict[str, Any]]:
    items = []
    if not task_dir.is_dir():
        return items
    for path in sorted(task_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        key = next((alias for alias, filename in ARTIFACTS.items() if filename == name), None)
        if key is None and not name.startswith(ARTIFACT_PREFIXES):
            continue
        items.append(
            {
                "name": key or name,
                "path": str(path),
                "bytes": path.stat().st_size,
                "lines": sum(1 for _ in path.open("rb")),
            }
        )
    return items


def get_artifact(
    cfg: config_module.Config,
    task_id: str,
    name: str,
    start_line: int = 1,
    line_count: int = 200,
) -> dict[str, Any]:
    """登録済み成果物だけを、行範囲を指定して取り出す。任意のファイルは読めない。"""
    ledger = Ledger(cfg.ledger_path)
    if ledger.get(task_id) is None:
        raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
    task_dir = (cfg.tasks_dir / task_id).resolve()
    filename = ARTIFACTS.get(name, name)
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise BridgeError("成果物名にパスは指定できません。")
    if name not in ARTIFACTS and not filename.startswith(ARTIFACT_PREFIXES):
        raise BridgeError(
            f"{name!r} は取り出せる成果物ではありません。"
            f" 使えるのは {sorted(ARTIFACTS)} と {ARTIFACT_PREFIXES} で始まるログです。"
        )
    target = (task_dir / filename).resolve()
    if not str(target).startswith(str(task_dir) + os.sep):
        raise BridgeError("タスクディレクトリの外は読めません。")
    if not target.is_file():
        raise NotFoundError(f"成果物がありません: {filename}")
    line_count = max(1, min(int(line_count), 2000))
    start_line = max(1, int(start_line))
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[start_line - 1 : start_line - 1 + line_count]
    return {
        "task_id": task_id,
        "name": name,
        "path": str(target),
        "total_lines": len(lines),
        "start_line": start_line,
        "returned_lines": len(chunk),
        "text": "\n".join(chunk),
    }


# --- cancel / resume --------------------------------------------------
def cancel(cfg: config_module.Config, task_id: str) -> dict[str, Any]:
    """停止要求と停止確認を分ける。他タスクや Ollama サービスは巻き込まない。"""
    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(task_id)
    if task is None:
        raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
    if task["state"] in TERMINAL_STATES:
        return {"task_id": task_id, "state": task["state"], "action": "既に終了しているため何もしない"}

    ledger.update(task_id, cancel_requested_at=_now(), state="cancelling")
    ledger.add_event(task_id, "cancel_requested")
    outcome = "requested"
    if task["runner_pid"] and procs.alive(task.get("runner_boot_id")):
        outcome = procs.terminate_tree(int(task["runner_pid"]))

    # OpenCode の子は独立セッションなので、runner の停止だけでは残りうる。
    # runner が先に消えていた場合も含め、記録した PID を必ず後始末する。
    child_outcome = None
    pid_file = cfg.tasks_dir / task_id / "child.pid"
    if pid_file.is_file():
        try:
            child_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            child_pid = None
        if child_pid:
            child_outcome = procs.terminate_tree(child_pid, grace_seconds=5.0)
        pid_file.unlink(missing_ok=True)

    confirmed = not procs.alive(task.get("runner_boot_id"))
    if confirmed:
        ledger.update(task_id, state="cancelled", ended_at=_now(), summary="停止要求により停止した。")
    return {
        "task_id": task_id,
        "state": "cancelled" if confirmed else "cancelling",
        "process_action": outcome,
        "child_process_action": child_outcome,
        "stop_confirmed": confirmed,
        "note": (
            "作業 PC 側のプロセスは止めた。A30 側で既に始まっている 1 回の生成は"
            "そのまま終わることがある。HTTP 切断だけで GPU 側の停止は確認していない。"
        ),
    }


def resume(cfg: config_module.Config, task_id: str) -> dict[str, Any]:
    """task_id に対応するものだけを再開する。最後のセッションを無条件には使わない。"""
    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(task_id)
    if task is None:
        raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
    if task["state"] == "succeeded":
        raise BridgeError("成功済みのタスクは再実行しません（同じ request_id の二重編集を防ぐため）。")
    if procs.alive(task.get("runner_boot_id")):
        return {
            "task_id": task_id,
            "state": task["state"],
            "action": "実行管理プロセスが生きているため何もしない",
        }
    work_dir = Path(task["worktree_path"]) if task["worktree_path"] else None
    if work_dir is None or not work_dir.is_dir():
        raise BridgeError(
            f"作業ツリーが見当たりません: {work_dir}。再開できません。新しい依頼として出し直してください。"
        )

    # 設定やモデルが変わっていないか照合する。
    drift: list[str] = []
    if task["model_name"] and task["model_name"] != cfg.model:
        drift.append(f"モデルが {task['model_name']} から {cfg.model} に変わっている")
    recorded = json.loads(task["effective_json"] or "{}")
    if recorded and recorded.get("opencode_binary") not in (None, str(cfg.opencode_binary)):
        drift.append("opencode の実体パスが変わっている")

    ledger.update(
        task_id,
        state="queued",
        stage="queued",
        cancel_requested_at=None,
        runner_pid=None,
        runner_boot_id=None,
        ended_at=None,
    )
    ledger.add_event(task_id, "resumed", {"drift": drift})
    _spawn_runner(cfg, task_id)
    return {
        "task_id": task_id,
        "state": "queued",
        "resumed_sessions": ledger.sessions(task_id),
        "worktree": str(work_dir),
        "config_drift": drift,
        "note": "再開を受け付けた。進捗は status で確認する。",
    }


def list_tasks(cfg: config_module.Config, limit: int = 20, state: str | None = None) -> list[dict[str, Any]]:
    ledger = Ledger(cfg.ledger_path)
    return [
        {
            "task_id": task["task_id"],
            "state": task["state"],
            "stage": task["stage"],
            "workspace_id": task["workspace_id"],
            "mode": task["mode"],
            "client_id": task["client_id"],
            "request_id": task["request_id"],
            "created_at": task["created_at"],
            "summary": (task["summary"] or "")[:120],
        }
        for task in ledger.list_tasks(limit=limit, state=state)
    ]
