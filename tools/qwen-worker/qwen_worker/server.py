"""MCP stdio サーバー。Claude Code と Codex の双方から同じ実装を使う。

標準出力は MCP のプロトコル専用。ログは必ず標準エラーへ出す。
"""

from __future__ import annotations

import getpass
import json
import logging
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .agent import BudgetExceeded, QwenAgent
from .config import (
    DEDUPE_DIR,
    INFERENCE_LOCK_PATH,
    TASKS_DIR,
    ConfigError,
    WorkerConfig,
    load_config,
)
from .locking import LockBusy, exclusive_lock, lock_holder
from .ollama_client import OllamaChatClient
from .prompts import build_system_prompt, build_user_prompt
from .sandbox import AccessDenied, build_sandbox, resolve_project_root
from .worker_tools import ToolRunner, implement_tool_specs, read_only_tool_specs
from .working_copy import WorkingCopyError, detect_apply_conflicts, generate_diff, prepare_working_copy

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("qwen_worker.server")

# /api/tags（ダウンロード済みモデルの一覧）のキャッシュ。呼び出しごとに素朴に叩くと
# 無駄な往復が増えるため、この秒数だけ使い回す。プロセス内グローバル
# （_execute のたびに OllamaChatClient を作り直すため、キャッシュはクライアントの
# 外に持つ必要がある）。
_MODEL_CACHE_TTL_SEC = 60.0
_model_cache: dict[str, Any] = {"models": None, "fetched_at": 0.0}

server = MCPServer(
    name="qwen-worker",
    version=__version__,
    instructions=(
        "ローカルの Qwen をコード調査・実装ワーカーとして使う。"
        "qwen_research は読み取り専用の調査、qwen_implement は隔離された作業コピー内での実装、"
        "qwen_status は接続先と検証状況を返す。"
        "1 タスクに目的・範囲・制約・完了条件を明示すること。親の会話全体は渡さないこと。"
    ),
)


def _home_share_name() -> str:
    """ホームの SMB 共有名。Samba の [homes] は共有名がユーザー名になる。"""
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "<user>"


def _host_info() -> dict[str, Any]:
    """このワーカーが動いているホストの情報。

    他の PC から SSH 越しに呼ばれたとき、親は project_root や成果物のパスを
    「このホスト側のパス」で扱う必要がある。翻訳の手がかりをここで返す。
    IP は取得できなければ None にする（推測で埋めない）。
    """
    hostname = socket.gethostname()
    address: str | None = None
    try:
        # UDP ソケットの接続先は実際には送信しない。経路選択で自分の LAN 側 IP が分かる。
        # 接続先は RFC 5737 の文書用アドレス（192.0.2.0/24）。既定経路の側の IP が返る。
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
    except OSError:
        address = None
    smb_root = f"\\\\{address or hostname}\\{_home_share_name()}"
    return {
        "hostname": hostname,
        "lan_address": address,
        "paths_are_on_this_host": True,
        "smb_share_of_home": smb_root,
        "tasks_dir_via_smb": smb_root + "\\.local\\state\\qwen-worker\\tasks",
        "note": (
            "project_root / allowed_*_paths はこのホスト上の絶対パス（例 /home/<user>/Proj/xxx）で渡す。"
            "SMB パスや他 PC 側のマウントパスは受け付けない。"
        ),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load() -> WorkerConfig:
    return load_config()


def _new_task_dir(kind: str) -> tuple[str, Path]:
    task_id = f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    task_dir = TASKS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    return task_id, task_dir


def _cached_models(client: OllamaChatClient) -> list[dict[str, Any]] | None:
    """/api/tags の結果を _MODEL_CACHE_TTL_SEC 秒だけキャッシュして返す。

    取得できなければ None（0 件と取得失敗を混同しない。古い値でごまかさない）。
    """
    now = time.monotonic()
    if _model_cache["models"] is not None and now - _model_cache["fetched_at"] < _MODEL_CACHE_TTL_SEC:
        return _model_cache["models"]
    models = client.list_models()
    if models is not None:
        _model_cache["models"] = models
        _model_cache["fetched_at"] = now
    return models


def _resolve_model(
    client: OllamaChatClient, requested: str | None, default_model: str
) -> tuple[str | None, list[dict[str, Any]] | None, str | None]:
    """呼び出しごとの model 引数を検証する。

    戻り値は (使うモデル名 or None, 取得できたモデル一覧 or None, エラーメッセージ or None)。
    エラーメッセージが None でなければ実行前に打ち切ること（存在しないモデルで
    実際に呼んで失敗させるより、親がすぐ選び直せるようにするため）。

    /api/tags が取得できない場合は、指定モデルの存在確認をあきらめて
    そのまま通す（警告ログのみ）。一覧が取れないことを理由に、親が明示的に
    選んだモデルの実行そのものを止めたくないため。実在しなければ、この後の
    /api/chat がそのとき失敗する。
    """
    if not requested:
        return default_model, None, None
    models = _cached_models(client)
    if models is None:
        logger.warning(
            "モデル一覧（/api/tags）を取得できなかったため、%s の存在確認をせずに進めます",
            requested,
        )
        return requested, None, None
    names = {m.get("name") for m in models if isinstance(m, dict) and m.get("name")}
    if requested not in names:
        # ollama はタグ省略を :latest とみなす。親が "名前" だけを渡したときに
        # 一覧と一致しないだけで弾かれないよう、:latest を補って再照合する。
        if ":" not in requested and f"{requested}:latest" in names:
            return f"{requested}:latest", models, None
        available = "\n".join(f"- {name}" for name in sorted(names)) or "（一覧が空です）"
        return (
            None,
            models,
            f"モデル {requested!r} は使えません。使えるのは次のとおり:\n{available}",
        )
    return requested, models, None


def _fingerprint(payload: dict[str, Any]) -> str:
    import hashlib

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _claim_fingerprint(fingerprint: str) -> Path | None:
    """同じ依頼が既に走っていないかを見る。空いていれば印を置いて返す。"""
    DEDUPE_DIR.mkdir(parents=True, exist_ok=True)
    marker = DEDUPE_DIR / f"{fingerprint}.json"
    if marker.exists():
        age = time.time() - marker.stat().st_mtime
        if age < 3600:
            return None
    marker.write_text(json.dumps({"claimed_at": _now_iso()}), encoding="utf-8")
    return marker


def _error_result(task_id: str | None, status: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "summary": message,
    }
    payload.update(extra)
    return payload


def _write_report(task_dir: Path, name: str, content: str) -> str:
    path = task_dir / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _run_metrics(agent_result) -> dict[str, Any]:
    return {
        "rounds_used": len(agent_result.rounds),
        "estimated_input_tokens": agent_result.estimated_input_tokens,
        "estimated_input_tokens_note": "推定値。Ollama 0.34.2 に /api/tokenize が無いため厳密計測不可",
        "peak_prompt_eval_count": agent_result.peak_prompt_eval_count,
        "total_eval_count": agent_result.total_eval_tokens(),
        "per_round": [
            {"round": r.index, "tool_calls": r.tool_calls, "had_error": r.had_error, **r.metrics}
            for r in agent_result.rounds
        ],
    }


@server.tool(
    name="qwen_status",
    description=(
        "ローカル Qwen ワーカーの状態を返す。接続先、既定モデル、使えるモデルの一覧"
        "（名前とサイズ。qwen_research / qwen_implement の model 引数に渡せる候補）、"
        "有効なプロファイル、検証状況、実行中タスク、許可ルートを含む。推論は行わない。"
        "他の PC から SSH 越しに使っている場合は、このホストのパスと SMB 共有の対応も返す。"
    ),
)
def qwen_status() -> dict[str, Any]:
    try:
        config = _load()
    except ConfigError as exc:
        return {"status": "misconfigured", "error": str(exc)}

    client = OllamaChatClient(
        config.ollama.base_url, config.ollama.model, config.ollama.read_timeout_sec
    )
    running = client.running_models()
    available_models = _cached_models(client)
    holder = lock_holder(INFERENCE_LOCK_PATH)

    verification_path = TASKS_DIR.parent / "verification.json"
    verification = None
    if verification_path.is_file():
        try:
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            verification = {"error": "verification.json を読めませんでした"}

    return {
        "worker_version": __version__,
        "config_path": str(config.source_path),
        "ollama": {
            "base_url": config.ollama.base_url,
            "model": config.ollama.model,
            "version": client.version(),
            "reachable": client.version() is not None,
            "loaded_models": running if running is not None else "未取得",
            "structured_output": config.ollama.structured_output,
        },
        "available_models": (
            [
                {"name": m.get("name"), "size_bytes": m.get("size")}
                for m in available_models
                if isinstance(m, dict)
            ]
            if available_models is not None
            else "未取得（/api/tags に到達できません）"
        ),
        "profiles": {
            name: {
                "num_ctx": p.num_ctx,
                "num_predict": p.num_predict,
                "think": p.think,
                "input_budget_tokens_estimate": p.input_budget_tokens,
                "enabled": p.enabled,
                "disabled_reason": p.disabled_reason or None,
            }
            for name, p in config.profiles.items()
        },
        "limits": {
            "job_deadline_sec": config.limits.job_deadline_sec,
            "max_rounds": config.limits.max_rounds,
            "max_repair_retries": config.limits.max_repair_retries,
            "lock_wait_sec": config.limits.lock_wait_sec,
        },
        "web": {
            "enabled": config.web.enabled,
            "max_searches_per_task": config.web.max_searches_per_task,
            "max_fetches_per_task": config.web.max_fetches_per_task,
        },
        "allowed_roots": [str(p) for p in config.allowed_roots],
        "host": _host_info(),
        "concurrency": {
            "max_concurrent_inferences": 1,
            "mechanism": f"flock({INFERENCE_LOCK_PATH})",
            "currently_held_by": holder or "（空き）",
        },
        "tasks_dir": str(TASKS_DIR),
        "verification": verification or "未実施（verification.json が無い）",
        "privacy_note": (
            "推論はローカルの Ollama で行うが、返した要約と差分は親エージェント経由で "
            "クラウドへ送られる。すべてがローカルに留まるわけではない。"
        ),
    }


_MODEL_DESCRIPTION = (
    "model は省略可（既定 qwen3.8:27b、23〜26 tok/s、実績あり）。"
    "速さ優先なら gemma4:e4b（9.6GB・81.5 tok/s、下調べ・要約向き）、"
    "賢さと速さの両方なら gemma4:31b-ctx32k（18.9GB・29.9 tok/s）。"
    "巨大モデル（flash-next 系等）は VRAM に載り切らず CPU に溢れて遅いため勧めない。"
    "存在しない名前は実行前にエラーとし使えるモデル一覧を返す。切替はロードに"
    "13〜60 秒かかるため 1 タスクは 1 モデルに固定すること（qwen_status で一覧を取れる）。"
)


@server.tool(
    name="qwen_research",
    description=(
        "ローカル Qwen にコード・資料・ログの調査をさせる。読み取り専用。"
        "Qwen 自身が検索と読み取りを繰り返し、根拠となるファイルと行番号を付けて返す。"
        "目的・範囲・完了条件を明示すること。親の会話全体は渡さないこと。"
        "project_root と allowed_read_paths は、ワーカーが動いているホスト上の絶対パス"
        "（例 /home/<user>/Proj/xxx）。他の PC から使うときも SMB パスではなくこのホスト側のパスで渡す。"
        + _MODEL_DESCRIPTION
    ),
)
def qwen_research(
    project_root: str,
    task: str,
    allowed_read_paths: list[str] | None = None,
    constraints: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    context_profile: str = "standard",
    model: str | None = None,
) -> dict[str, Any]:
    return _run_job(
        kind="research",
        project_root=project_root,
        task=task,
        allowed_read_paths=allowed_read_paths or [],
        allowed_write_paths=[],
        constraints=constraints or [],
        acceptance_criteria=acceptance_criteria or [],
        context_profile=context_profile,
        model=model,
    )


@server.tool(
    name="qwen_implement",
    description=(
        "ローカル Qwen に実装とテストコード作成をさせる。編集は隔離された作業コピー内で行い、"
        "元の作業ツリーには一切書き込まない。成果物として差分を返す"
        "（短ければ diff_text に本文、常に diff_path にファイル）。"
        "差分の適用・コミット・テスト実行は行わない。親が確認してから親の権限で行うこと。"
        "project_root と allowed_*_paths は、ワーカーが動いているホスト上の絶対パス"
        "（例 /home/<user>/Proj/xxx）。他の PC から使うときも SMB パスではなくこのホスト側のパスで渡す。"
        + _MODEL_DESCRIPTION
    ),
)
def qwen_implement(
    project_root: str,
    task: str,
    allowed_write_paths: list[str],
    allowed_read_paths: list[str] | None = None,
    constraints: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    context_profile: str = "standard",
    model: str | None = None,
) -> dict[str, Any]:
    if not allowed_write_paths:
        return _error_result(None, "blocked", "allowed_write_paths は必須です。空にはできません。")
    return _run_job(
        kind="implement",
        project_root=project_root,
        task=task,
        allowed_read_paths=allowed_read_paths or [],
        allowed_write_paths=allowed_write_paths,
        constraints=constraints or [],
        acceptance_criteria=acceptance_criteria or [],
        context_profile=context_profile,
        model=model,
    )


def _run_job(
    *,
    kind: str,
    project_root: str,
    task: str,
    allowed_read_paths: list[str],
    allowed_write_paths: list[str],
    constraints: list[str],
    acceptance_criteria: list[str],
    context_profile: str,
    model: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        config = _load()
    except ConfigError as exc:
        return _error_result(None, "blocked", f"設定が不正です: {exc}")

    try:
        profile = config.profile(context_profile)
    except ConfigError as exc:
        return _error_result(None, "blocked", str(exc))

    # モデルの検証は実行前に行う。存在しない名前で最後まで走らせてから
    # 失敗させるより、親がすぐ選び直せるようにするため。
    probe_client = OllamaChatClient(
        config.ollama.base_url, config.ollama.model, config.ollama.read_timeout_sec
    )
    resolved_model, _available_models, model_error = _resolve_model(
        probe_client, model, config.ollama.model
    )
    if model_error is not None:
        return _error_result(None, "blocked", model_error)

    try:
        root = resolve_project_root(project_root, config.allowed_roots)
        sandbox = build_sandbox(root, allowed_read_paths, allowed_write_paths, config.denied_globs)
    except AccessDenied as exc:
        return _error_result(None, "blocked", f"アクセス範囲の指定が不正です: {exc}")

    fingerprint = _fingerprint(
        {
            "kind": kind,
            "root": str(root),
            "task": task,
            "read": sorted(allowed_read_paths),
            "write": sorted(allowed_write_paths),
            "profile": context_profile,
            # モデルを指紋に含めないと、同じ依頼を別モデルで出し直したときに
            # 「実行中」と誤判定され 1 時間 busy になる（実際に踏む不具合）。
            "model": resolved_model,
        }
    )
    marker = _claim_fingerprint(fingerprint)
    if marker is None:
        return _error_result(
            None,
            "busy",
            "同じ依頼が 1 時間以内に既に開始されています。重複実行を防ぐため受け付けません。"
            f"（fingerprint={fingerprint}）再実行したい場合は "
            f"{DEDUPE_DIR / (fingerprint + '.json')} を消してください。",
        )

    task_id, task_dir = _new_task_dir(kind)
    logger.info(
        "task %s start (profile=%s model=%s root=%s)", task_id, context_profile, resolved_model, root
    )

    try:
        deadline = started + config.limits.job_deadline_sec
        with exclusive_lock(INFERENCE_LOCK_PATH, config.limits.lock_wait_sec):
            return _execute(
                kind=kind,
                config=config,
                profile=profile,
                sandbox=sandbox,
                root=root,
                task=task,
                task_id=task_id,
                task_dir=task_dir,
                allowed_read_paths=allowed_read_paths,
                allowed_write_paths=allowed_write_paths,
                constraints=constraints,
                acceptance_criteria=acceptance_criteria,
                deadline=deadline,
                started=started,
                model=resolved_model,
            )
    except LockBusy as exc:
        return _error_result(task_id, "busy", str(exc))
    except WorkingCopyError as exc:
        return _error_result(task_id, "blocked", f"作業コピーを準備できませんでした: {exc}")
    except BudgetExceeded as exc:
        return _error_result(task_id, "blocked", str(exc))
    except Exception as exc:  # noqa: BLE001 - 親には必ず構造化した結果を返す
        logger.exception("task %s failed", task_id)
        return _error_result(task_id, "failed", f"ワーカー内部でエラーが発生しました: {exc!r}")
    finally:
        marker.unlink(missing_ok=True)


def _execute(
    *,
    kind: str,
    config: WorkerConfig,
    profile,
    sandbox,
    root: Path,
    task: str,
    task_id: str,
    task_dir: Path,
    allowed_read_paths: list[str],
    allowed_write_paths: list[str],
    constraints: list[str],
    acceptance_criteria: list[str],
    deadline: float,
    started: float,
    model: str,
) -> dict[str, Any]:
    client = OllamaChatClient(config.ollama.base_url, model, config.ollama.read_timeout_sec)

    working_copy = None
    if kind == "implement":
        working_copy = prepare_working_copy(task_dir, root, sandbox)
        # 以降、Qwen が触るのは作業コピーだけ。元ツリーを指すサンドボックスは捨てる。
        sandbox = build_sandbox(
            working_copy.work_dir,
            [str(Path(p)) for p in (allowed_read_paths or [])],
            [str(Path(p)) for p in allowed_write_paths],
            config.denied_globs,
        )
        tool_specs = implement_tool_specs(web_enabled=config.web.enabled)
        runner = ToolRunner(
            sandbox,
            config.limits.max_tool_result_chars,
            allow_write=True,
            web_enabled=config.web.enabled,
            max_web_searches=config.web.max_searches_per_task,
            max_web_fetches=config.web.max_fetches_per_task,
        )
        display_root = str(working_copy.work_dir)
    else:
        tool_specs = read_only_tool_specs(web_enabled=config.web.enabled)
        runner = ToolRunner(
            sandbox,
            config.limits.max_tool_result_chars,
            allow_write=False,
            web_enabled=config.web.enabled,
            max_web_searches=config.web.max_searches_per_task,
            max_web_fetches=config.web.max_fetches_per_task,
        )
        display_root = str(root)

    agent = QwenAgent(
        client=client,
        tool_runner=runner,
        tool_specs=tool_specs,
        profile=profile,
        sampling=config.sampling_for(profile.think, model=model),
        limits=config.limits,
        token_estimation=config.token_estimation_for(model),
    )

    system_prompt = build_system_prompt("implement" if kind == "implement" else "research")
    user_prompt = build_user_prompt(
        task=task,
        project_root=display_root,
        allowed_read_paths=allowed_read_paths,
        allowed_write_paths=allowed_write_paths,
        constraints=constraints,
        acceptance_criteria=acceptance_criteria,
    )

    agent_result = agent.run(system_prompt, user_prompt, deadline)
    elapsed = round(time.monotonic() - started, 1)
    metrics = _run_metrics(agent_result)
    metrics["elapsed_sec"] = elapsed
    # 設定の既定ではなく、実際にこの実行で使ったモデル名を記録する。
    # そうしないと、どのモデルで得た結果か metrics.json から分からなくなる。
    metrics["model"] = model
    metrics["ollama_version"] = client.version()
    metrics["profile"] = {
        "name": profile.name,
        "num_ctx": profile.num_ctx,
        "num_predict": profile.num_predict,
        "think": profile.think,
    }
    metrics["sampling"] = config.sampling_for(profile.think, model=model).as_options()
    running = client.running_models()
    metrics["ollama_ps_after_run"] = running if running is not None else "未取得"

    # 長い思考出力と全ログは別ファイルへ。親へはパスだけ返す。
    transcript_path = _write_report(
        task_dir,
        "transcript.json",
        json.dumps(agent_result.messages, ensure_ascii=False, indent=2),
    )
    metrics_path = _write_report(
        task_dir, "metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2)
    )

    payload = agent_result.final_payload or {}
    result: dict[str, Any] = {
        "task_id": task_id,
        "status": agent_result.status,
        "summary": str(payload.get("summary") or "（要約が返りませんでした）")[:4000],
        "artifacts_dir": str(task_dir),
        "transcript_path": transcript_path,
        "metrics_path": metrics_path,
        "metrics_brief": {
            "model": model,
            "rounds_used": metrics["rounds_used"],
            "elapsed_sec": elapsed,
            "peak_prompt_eval_count": metrics["peak_prompt_eval_count"],
            "total_eval_count": metrics["total_eval_count"],
            "estimated_input_tokens": metrics["estimated_input_tokens"],
        },
        "unresolved": list(agent_result.notes),
        "access_denied_attempts": runner.denied_attempts,
    }

    if kind == "research":
        result["evidence"] = payload.get("evidence") or []
        result["open_questions"] = payload.get("open_questions") or []
        if not result["evidence"] and agent_result.status == "completed":
            result["status"] = "needs_review"
            result["unresolved"].append("根拠が 1 件も付いていません。")
    else:
        diff_text, changed = generate_diff(working_copy)
        diff_path = _write_report(task_dir, "changes.diff", diff_text)
        conflicts = detect_apply_conflicts(working_copy)
        result["changed_files"] = changed
        result["diff_path"] = diff_path
        diff_line_count = len(diff_text.splitlines())
        result["diff_line_count"] = diff_line_count
        # 他の PC から SSH 越しに使う親は tasks/ を直接開けない。短い差分は本文でも返す。
        if diff_line_count <= config.limits.inline_diff_max_lines:
            result["diff_text"] = diff_text
        else:
            result["diff_text_omitted"] = (
                f"差分が {diff_line_count} 行あり上限 {config.limits.inline_diff_max_lines} 行を超えるため "
                "本文は省略。diff_path を読むこと。"
            )
        result["baseline"] = {
            "git_head": working_copy.git_head,
            "dirty_files_at_copy_time": working_copy.git_dirty_files,
            "provenance_path": str(task_dir / "provenance.json"),
        }
        result["apply_conflicts"] = conflicts
        result["original_tree_modified"] = False
        result["tests_added"] = payload.get("tests_added") or []
        result["verification_done"] = []
        result["verification_not_done"] = (payload.get("unverified") or []) + [
            "テスト実行（ワーカーはシェルを実行しない。親の権限管理下で行うこと）",
            "差分の適用（未適用。親のレビュー後に親が行うこと）",
        ]
        if agent_result.status == "completed" and not changed:
            result["status"] = "needs_review"
            result["unresolved"].append("作業コピーに差分がありません。実装されていません。")
        if conflicts:
            result["unresolved"].append(
                "取り込み後に元ファイルが変わっています。適用前に確認してください: "
                + "; ".join(conflicts)
            )

    if agent_result.hit_generation_limit:
        result["unresolved"].append(
            f"生成上限 num_predict={profile.num_predict} に到達しました。"
            "作業を分割するか、上限を上げて再試行してください。"
        )
    if agent_result.hit_round_limit:
        result["unresolved"].append(
            f"ラウンド上限 {config.limits.max_rounds} に到達しました。完了していません。"
        )

    result["next_decision_needed"] = _next_decision(result)
    _write_report(task_dir, "result.json", json.dumps(result, ensure_ascii=False, indent=2))
    logger.info("task %s done status=%s elapsed=%ss", task_id, result["status"], elapsed)
    return result


def _next_decision(result: dict[str, Any]) -> str:
    if result["status"] == "completed" and result.get("diff_path"):
        return "差分をレビューし、問題なければ親の権限で適用してからビルドとテストを実行する。"
    if result["status"] == "completed":
        return "根拠を確認し、次のタスクを切り出す。"
    if result["status"] == "needs_review":
        return "未解決事項を見て、情報を足して再依頼するか、親が引き取るかを決める。"
    return "失敗理由を確認する。文脈長不足と決めつけず、情報不足・ツール不具合・モデルの判断ミスも切り分ける。"


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
