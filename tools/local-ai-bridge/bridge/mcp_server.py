"""stdio MCP サーバー。CLI と同じ bridge.core を呼ぶ。

標準出力は MCP プロトコル専用。ログは必ず標準エラーへ出す
（デバッグ出力を混ぜるとクライアントが JSON を読めなくなる）。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, core
from .errors import BridgeError, DuplicateRequestError

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("local_ai_bridge.mcp")

server = MCPServer(
    name="local-ai-bridge",
    version=__version__,
    instructions=(
        "作業 PC の OpenCode を経由して、LAN 内 A30 サーバーのローカル Qwen へ"
        "実装作業を委譲する。submit_task は受付だけを行い task_id を返す。"
        "進捗は get_task_status、結果は get_task_result で取る。"
        "差分の適用・コミット・テスト実行はこちらでは行わない。"
    ),
)


def _config():
    return core.load_config()


def _error(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


@server.tool(
    name="submit_task",
    description=(
        "ローカル実装タスクを受け付けて task_id を返す。実行は別プロセスで続くので"
        "この応答を待っている必要はない。workspace_id と verify_profile は"
        "設定に登録済みの名前だけを受け付ける（任意のパスやコマンドは指定できない）。"
        "目的・変更可能範囲・変更禁止事項・合格条件を明示すること。"
        "進捗は wait_for_task で完了まで待てる。長い作業は get_task_status でも確認できる。"
    ),
)
def submit_task(
    request_id: str,
    workspace_id: str,
    goal: str,
    client_id: str = "mcp",
    allowed_scope: list[str] | None = None,
    forbidden: list[str] | None = None,
    acceptance: list[str] | None = None,
    base_commit: str | None = None,
    verify_profile: str | None = None,
    mode: str = "deep",
    on_dirty: str = "wait",
) -> dict[str, Any]:
    try:
        return core.submit(
            _config(),
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
    except DuplicateRequestError as exc:
        return {"ok": False, "duplicate": True, "task_id": exc.task_id, "error": str(exc)}
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="run_task",
    description=(
        "1 回の呼び出しで 委譲→完了待ち→6 フラグ判定→作業ツリーへ適用→"
        "登録済みコマンドで再検証→短い要約 まで行う。親はこれだけ呼べばよい。"
        "commit はしない。上限秒を過ぎたら timed_out=true で task_id を返す。"
    ),
)
def run_task(
    request_id: str,
    workspace_id: str,
    goal: str,
    client_id: str = "mcp",
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
    try:
        return core.run_task(
            _config(),
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
            max_wait_sec=max_wait_sec,
            apply=apply,
        )
    except DuplicateRequestError as exc:
        return {"ok": False, "duplicate": True, "task_id": exc.task_id, "error": str(exc)}
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="get_task_status",
    description="task_id の状態・段階・経過時間を返す。結果本文は含まない。",
)
def get_task_status(task_id: str) -> dict[str, Any]:
    try:
        return core.status(_config(), task_id)
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="get_task_result",
    description=(
        "task_id の結果を短く返す。変更概要・検証成否・未解決点・承認事項を優先する。"
        "大きな差分とログはローカルに保存されており、get_artifact で行範囲を指定して取る。"
    ),
)
def get_task_result(task_id: str, include_diff: bool = False) -> dict[str, Any]:
    try:
        return core.result(_config(), task_id, include_diff=include_diff)
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="wait_for_task",
    description=(
        "task_id が終わるまで待って get_task_result と同じ形で返す。"
        "上限秒を過ぎたら timed_out=true で状態だけ返す。"
    ),
)
def wait_for_task(
    task_id: str, max_wait_sec: int | None = None, include_diff: bool = True
) -> dict[str, Any]:
    try:
        return core.wait_for_task(
            _config(), task_id, max_wait_sec=max_wait_sec, include_diff=include_diff
        )
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="get_artifact",
    description=(
        "そのタスクの登録済み成果物だけを行範囲で取り出す。"
        "name は diff / result、または verify-*.log / events-*.jsonl / stderr-*.log。"
        "任意のローカルファイルは読めない。"
    ),
)
def get_artifact(
    task_id: str, name: str, start_line: int = 1, line_count: int = 200
) -> dict[str, Any]:
    try:
        return core.get_artifact(_config(), task_id, name, start_line, line_count)
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="cancel_task",
    description=(
        "そのタスクと子プロセスだけを止める。他のタスク・他の PC・Ollama サービスは"
        "巻き込まない。停止要求と停止確認は別に返す。"
    ),
)
def cancel_task(task_id: str) -> dict[str, Any]:
    try:
        return core.cancel(_config(), task_id)
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="resume_task",
    description=(
        "task_id に対応する作業ツリーとセッションを指定して再開する。"
        "最後のセッションを無条件には使わない。成功済みのタスクは再実行しない。"
    ),
)
def resume_task(task_id: str) -> dict[str, Any]:
    try:
        return core.resume(_config(), task_id)
    except BridgeError as exc:
        return _error(exc)


@server.tool(
    name="bridge_doctor",
    description=(
        "接続先・モデル・OpenCode の実効設定・登録済み作業場所を点検して返す。"
        "推論は行わない。取得できない値は未取得として返す。"
    ),
)
def bridge_doctor() -> dict[str, Any]:
    try:
        return core.doctor(_config())
    except BridgeError as exc:
        return _error(exc)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
