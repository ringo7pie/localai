"""CLI と MCP が共通で呼ぶ処理。別々の実装にしない。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from . import config as config_module
from . import opencode, procs, worktree
from . import verify as verify_module
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

# wait_for_task が待ち終わりとみなす状態。終端に加えて、人の判断を待つ 2 つを含める
# （どちらも実行管理プロセスは進まないので、待ち続けても状態は変わらない）。
WAIT_END_STATES = TERMINAL_STATES | {"awaiting_approval", "awaiting_input"}

# 台帳を見に行く間隔（秒）。短くしても状態は早く進まないので、SQLite を無駄に叩かない。
WAIT_POLL_SECONDS = 5


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
        "note": (
            "進捗は wait_for_task で完了まで待てる。"
            "長い作業は get_task_status でも確認できる。"
        ),
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


def wait_for_task(
    cfg: config_module.Config,
    task_id: str,
    max_wait_sec: int | None = None,
    include_diff: bool = True,
) -> dict[str, Any]:
    """待ち終わりまでブロックして、result() と同じ形で返す。

    呼び出し側が status を何度も叩かずに済ませるためのもの。上限は設定側で決め、
    ここで無限に待たない。上限に達したときは結果ではなく状態だけを返す。
    """
    limit = cfg.limits.wait_for_task_max_sec
    if max_wait_sec is not None:
        # 設定の上限は越えさせない（MCP 側のツールタイムアウトの内側に収めるため）。
        limit = max(0, min(int(max_wait_sec), limit))

    ledger = Ledger(cfg.ledger_path)
    deadline = _now() + limit
    while True:
        task = ledger.get(task_id)
        if task is None:
            raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
        state = task["state"]
        if state in WAIT_END_STATES:
            return result(cfg, task_id, include_diff=include_diff)

        if state in ("running", "cancelling") and not procs.alive(task.get("runner_boot_id")):
            # 実行管理プロセスが died していれば状態はもう進まない。無限に待たずに返す。
            report = status(cfg, task_id)
            if report.get("state_inconsistent"):
                return report

        remaining = deadline - _now()
        if remaining <= 0:
            report = status(cfg, task_id)
            report["timed_out"] = True
            report["hint"] = "get_task_status で続きを見る"
            return report
        time.sleep(min(WAIT_POLL_SECONDS, remaining))


# --- run_task（一括実行） ---------------------------------------------
# 親（クラウド側）のターン数を減らすための入口。submit → 待ち → 判定 → 適用 →
# 再検証 までを 1 回の呼び出しで行う。判定に使う条件は result() が返す 6 つだけで、
# ここで新しい基準を作らない。commit / push / stash / reset / clean は行わない。
RUN_CHECK_NAMES = (
    'state == "awaiting_approval"',
    "verification.passed is True",
    "changes.out_of_scope == []",
    "test_integrity.suspicious is False",
    "changes.blocked_secret_paths == []",
    "changes.applies_to_original is True",
)


def _run_checks(outcome: dict[str, Any]) -> list[str]:
    """合格しなかった条件名を返す。verification / changes が無いときは偽扱い。"""
    verification = outcome.get("verification")
    changes = outcome.get("changes")
    integrity = outcome.get("test_integrity")
    results = (
        outcome.get("state") == "awaiting_approval",
        verification is not None and verification.get("passed") is True,
        changes is not None and changes.get("out_of_scope") == [],
        integrity is not None and integrity.get("suspicious") is False,
        changes is not None and changes.get("blocked_secret_paths") == [],
        changes is not None and changes.get("applies_to_original") is True,
    )
    return [name for name, ok in zip(RUN_CHECK_NAMES, results) if not ok]


def _verify_brief(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {
        "command": record.get("command"),
        "exit_code": record.get("exit_code"),
        "passed": record.get("passed"),
        "log_path": record.get("log_path"),
    }


def apply_task(cfg: config_module.Config, task_id: str, *, verify: bool = True) -> dict[str, Any]:
    """判定 → git apply --check → 作業ツリーへ適用 → 登録済みコマンドで再検証 →

    不合格なら git apply -R で戻す、の一連を task_id だけで完結させる。
    run_task（委譲直後の自動適用）と CLI の apply サブコマンド（後からの手動適用）の
    両方から呼ぶ。判定に使う条件は result() が返す 6 つだけで、ここで新しい基準を
    作らない。commit / push / stash / reset / clean は行わない。

    verify=False なら適用後の再検証を省く（適用だけ行って判定は人に任せる）。
    """
    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(task_id)
    if task is None:
        raise NotFoundError(f"task_id {task_id!r} は台帳にありません。")
    workspace_id = task["workspace_id"]

    outcome = result(cfg, task_id, include_diff=False)
    reasons = _run_checks(outcome)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "workspace_id": workspace_id,
        "applied": False,
        "reasons": reasons,
        "verification": _verify_brief(outcome.get("verification")),
        "apply_hint": outcome.get("apply_hint"),
    }
    if reasons:
        return payload

    workspace = cfg.workspace(workspace_id)
    diff_raw = task["diff_path"]
    if not diff_raw:
        payload["reasons"] = ["台帳に差分ファイルの記録が無い"]
        return payload

    diff_path = Path(diff_raw)
    git = config_module.git_binary()
    applies, apply_error = worktree.verify_applies(workspace.path, diff_path)
    if not applies:
        already = subprocess.run(
            [git, "-C", str(workspace.path), "apply", "--check", "-R", "-p1", str(diff_path)],
            capture_output=True,
            text=True,
        )
        if already.returncode == 0:
            payload["reasons"] = ["already_applied"]
            return payload
        payload["reasons"] = ["git apply --check が失敗"]
        ledger.add_event(task_id, "apply_check_failed", {"detail": apply_error[:400]})
        return payload

    try:
        subprocess.run(
            [git, "-C", str(workspace.path), "apply", "-p1", str(diff_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        # --check を通ったのに当たらなかった場合。握りつぶさない。
        raise BridgeError(
            f"git apply が失敗しました（{exc.returncode}）: "
            f"{(exc.stderr or '').strip()[:400]}"
        ) from exc
    payload["applied"] = True

    if not verify:
        return payload

    profile = workspace.profile(task["verify_profile"])
    if profile is None:
        # 適用は済ませたまま人の確認へ回す。勝手に戻さない。
        payload["reasons"] = ["検証プロファイル未登録のため再検証していない"]
        return payload

    verify_result = verify_module.run_profile(
        profile=profile,
        cwd=workspace.path,
        log_path=cfg.tasks_dir / task_id / "verify-applied.log",
        tree_hash=None,
        timeout_sec=min(profile.timeout_sec, cfg.limits.verify_timeout_sec),
    )
    payload["verification"] = _verify_brief(verify_result.as_dict())
    if verify_result.passed:
        ledger.compare_and_set_state(task_id, "awaiting_approval", "succeeded", ended_at=_now())
        ledger.add_event(
            task_id,
            "applied_by_run",
            {
                "workspace_id": workspace_id,
                "workspace_path": str(workspace.path),
                "diff_path": str(diff_path),
                "verify_profile": profile.name,
                "verify_exit_code": verify_result.exit_code,
            },
        )
        return payload

    reverted = subprocess.run(
        [git, "-C", str(workspace.path), "apply", "-R", "-p1", str(diff_path)],
        capture_output=True,
        text=True,
    )
    payload["applied"] = reverted.returncode != 0
    revert_reasons = [f"適用後の再検証が不合格（終了コード {verify_result.exit_code}）"]
    if reverted.returncode != 0:
        revert_reasons.append("戻し（git apply -R）も失敗した。作業ツリーを人が確認すること")
    payload["reasons"] = revert_reasons
    ledger.add_event(
        task_id,
        "apply_reverted",
        {
            "workspace_path": str(workspace.path),
            "diff_path": str(diff_path),
            "verify_exit_code": verify_result.exit_code,
            "revert_ok": reverted.returncode == 0,
            "revert_error": reverted.stderr.strip()[:400],
        },
    )
    return payload


def run_task(
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
    max_wait_sec: int | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    """委譲 → 完了待ち → 判定 → 適用 → 再検証 を 1 回で行う。"""
    accepted = submit(
        cfg,
        request_id=request_id,
        client_id=client_id,
        workspace_id=workspace_id,
        goal=goal,
        allowed_scope=allowed_scope,
        forbidden=forbidden,
        acceptance=acceptance,
        base_commit=base_commit,
        verify_profile=verify_profile,
        mode=mode,
        on_dirty=on_dirty,
    )
    task_id = accepted["task_id"]

    waited = wait_for_task(cfg, task_id, max_wait_sec=max_wait_sec, include_diff=False)
    if waited.get("timed_out"):
        return {
            "task_id": task_id,
            "state": waited.get("state"),
            "timed_out": True,
            "judged_ok": False,
            "applied": False,
            "hint": (
                f"local-ai-task wait {task_id} --max-wait 540 を 1 回だけ呼んで続きを受け取る"
            ),
        }
    if waited.get("state_inconsistent"):
        return {
            "task_id": task_id,
            "state": waited.get("state"),
            "state_inconsistent": True,
            "judged_ok": False,
            "applied": False,
            "hint": (
                f"実行管理プロセスが落ちている。resume_task('{task_id}') で引き継いでから"
                f" wait で受け取る"
            ),
        }

    outcome = result(cfg, task_id, include_diff=False)
    reasons = _run_checks(outcome)
    final_state = outcome.get("state")
    applied = False
    verify_record = _verify_brief(outcome.get("verification"))

    if not reasons and apply:
        applied_result = apply_task(cfg, task_id, verify=True)
        applied = applied_result["applied"]
        reasons = applied_result["reasons"]
        if applied_result.get("verification") is not None:
            verify_record = applied_result["verification"]
        if applied and not reasons:
            final_state = "succeeded"

    changes = outcome.get("changes") or {}
    summary = outcome.get("summary") or ""
    limit_chars = cfg.limits.result_summary_max_chars
    if len(summary) > limit_chars:
        summary = summary[: limit_chars - 1] + "…"

    payload: dict[str, Any] = {
        "task_id": task_id,
        "state": final_state,
        "judged_ok": not reasons,
        "applied": applied,
        "reasons": reasons,
        "changed_files": {
            "added": changes.get("added") or [],
            "modified": changes.get("modified") or [],
            "deleted": changes.get("deleted") or [],
        },
        "verify": verify_record,
        "open_questions": outcome.get("open_questions") or [],
        "summary": summary,
        "local_usage": (outcome.get("usage") or {}).get("local_inference"),
    }
    if not applied:
        payload["apply_hint"] = outcome.get("apply_hint")

    # 8 KiB を超えるなら差分の本文ではなくファイル名の一覧を落とす（JSON は壊さない）。
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > cfg.limits.result_max_bytes:
        payload["changed_files"] = {
            key: f"{len(value)} 件（多いので省略。get_artifact(task_id, 'diff') で見る）"
            for key, value in payload["changed_files"].items()
        }
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


# --- workspace 登録（CLI 専用。MCP には出さない） ----------------------
def _detect_verify_candidates(resolved: Path) -> dict[str, list[str]]:
    """テスト実行コマンドの候補を検出する。表示するだけで、登録は明示指定のみ行う。"""
    candidates: dict[str, list[str]] = {}
    has_pytest_project = (
        (resolved / "pyproject.toml").is_file()
        or (resolved / "pytest.ini").is_file()
        or (resolved / "tests").is_dir()
    )
    if has_pytest_project:
        venv_python = resolved / ".venv" / "bin" / "python"
        python_bin = ".venv/bin/python" if venv_python.is_file() else "python3"
        candidates["pytest"] = [python_bin, "-m", "pytest", "-q"]

    package_json = resolved / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts") if isinstance(data, dict) else None
        if isinstance(scripts, dict) and scripts.get("test"):
            candidates["npm"] = ["npm", "test"]

    makefile = resolved / "Makefile"
    if makefile.is_file():
        try:
            text = makefile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if re.search(r"^test:", text, re.MULTILINE):
            candidates["make"] = ["make", "test"]
    return candidates


def _atomic_write_text(path: Path, text: str) -> None:
    """path と同じディレクトリに一時ファイルを書き、os.replace (mv 相当) で置き換える。"""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(text)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _backup_config_file(config_path: Path) -> Path:
    backup_path = config_path.with_name(
        f"{config_path.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    )
    shutil.copy2(config_path, backup_path)
    return backup_path


def workspace_add(
    cfg: config_module.Config,
    *,
    path: str,
    workspace_id: str | None = None,
    verify_profiles: dict[str, list[str]] | None = None,
    default_verify: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """許可ルート（[registration] allowed_roots）配下の Git リポジトリだけを登録する。

    モデルや依頼者が任意のパスを登録できないよう、人が bridge.toml に書いた
    allowed_roots の配下でなければ拒否する。CLI からだけ呼ぶ想定で、MCP には出さない。
    """
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise BridgeError(f"path が存在しません: {path} ({exc})") from exc
    if not resolved.is_dir():
        raise BridgeError(f"path がディレクトリではありません: {resolved}")

    roots = cfg.registration_roots
    if not roots:
        raise BridgeError(
            "[registration] allowed_roots が未設定です。bridge.toml に人が書いてください。"
        )
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise BridgeError(
            f"{resolved} は許可ルート外です。"
            f" 登録済みルート: {', '.join(str(root) for root in roots)}"
        )

    if not worktree.is_git_repo(resolved):
        raise BridgeError(f"{resolved} は Git リポジトリではありません。")

    new_id = workspace_id or re.sub(r"[^A-Za-z0-9_-]", "-", resolved.name)
    if new_id in cfg.workspaces:
        raise BridgeError(f"workspace_id {new_id!r} は既に登録されています。")
    for existing in cfg.workspaces.values():
        if existing.path == resolved:
            raise BridgeError(
                f"{resolved} は既に workspace {existing.workspace_id!r} として登録されています。"
            )

    suggested = _detect_verify_candidates(resolved)

    verify_profiles = dict(verify_profiles or {})
    for name, command in verify_profiles.items():
        if not command:
            raise BridgeError(f"--verify {name} の --cmd が空です。")
    if default_verify is not None and default_verify not in verify_profiles:
        raise BridgeError(
            f"default_verify {default_verify!r} は --verify で指定されていません。"
        )

    result: dict[str, Any] = {
        "workspace_id": new_id,
        "path": str(resolved),
        "verify_profiles": verify_profiles,
        "default_verify": default_verify,
        "suggested_verify": suggested,
        "config_path": str(cfg.config_path),
        "backup_path": None,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    lines = ["", f"[workspace.{new_id}]", f"path = {json.dumps(str(resolved))}"]
    if default_verify:
        lines.append(f"default_verify = {json.dumps(default_verify)}")
    for name, command in verify_profiles.items():
        lines.append("")
        lines.append(f"[workspace.{new_id}.verify.{name}]")
        lines.append(f"command = {json.dumps(list(command))}")
        lines.append("timeout_sec = 600")
    addition = "\n".join(lines) + "\n"

    config_path = cfg.config_path
    original_text = config_path.read_text(encoding="utf-8")
    new_text = original_text + addition
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise BridgeError(f"追記後の bridge.toml が TOML として読めません: {exc}") from exc

    backup_path = _backup_config_file(config_path)
    _atomic_write_text(config_path, new_text)

    result["backup_path"] = str(backup_path)
    return result


def workspace_list(cfg: config_module.Config) -> list[dict[str, Any]]:
    return [
        {
            "workspace_id": ws.workspace_id,
            "path": str(ws.path),
            "verify_profiles": sorted(ws.verify_profiles),
            "default_verify": ws.default_verify,
        }
        for ws in cfg.workspaces.values()
    ]


def workspace_which(cfg: config_module.Config, path: str) -> str | None:
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None
    best: tuple[int, str] | None = None
    for ws in cfg.workspaces.values():
        if resolved == ws.path or ws.path in resolved.parents:
            depth = len(ws.path.parts)
            if best is None or depth > best[0]:
                best = (depth, ws.workspace_id)
    return best[1] if best else None


def workspace_remove(cfg: config_module.Config, workspace_id: str) -> dict[str, Any]:
    if workspace_id not in cfg.workspaces:
        raise NotFoundError(f"workspace_id {workspace_id!r} は登録されていない。")

    config_path = cfg.config_path
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    header_re = re.compile(r"^\[workspace\." + re.escape(workspace_id) + r"(\.|\])")
    other_re = re.compile(r"^\[workspace\.")

    start: int | None = None
    end = len(lines)
    for i, line in enumerate(lines):
        if header_re.match(line):
            if start is None:
                start = i
            continue
        if start is not None and other_re.match(line):
            end = i
            break
    if start is None:
        raise NotFoundError(f"workspace_id {workspace_id!r} のブロックが見つかりません。")

    block_start = start
    while block_start > 0 and lines[block_start - 1].strip() == "":
        block_start -= 1

    new_text = "".join(lines[:block_start] + lines[end:])
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise BridgeError(f"削除後の bridge.toml が TOML として読めません: {exc}") from exc

    backup_path = _backup_config_file(config_path)
    _atomic_write_text(config_path, new_text)

    return {
        "workspace_id": workspace_id,
        "config_path": str(config_path),
        "backup_path": str(backup_path),
    }
