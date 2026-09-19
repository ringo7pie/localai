#!/usr/bin/env python3
"""qwen-worker MCP サーバーを stdio で 1 回呼ぶ検証用クライアント。

使い方: mcp_call.py <tool_name> <json_arguments> [timeout_sec]

本番の経路（Claude Code / Codex）とは別に、ワーカー単体を確かめるために使う。
応答を受け取るまで stdin を閉じない。閉じるとサーバーが終了し、
実行中のツール呼び出しが打ち切られる。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

LAUNCHER = str(Path(__file__).resolve().parent / "run-qwen-worker")


def main() -> int:
    tool_name = sys.argv[1]
    raw_arguments = sys.argv[2] if len(sys.argv) > 2 else "{}"
    # 引数が大きいとシェルの引数長制限に当たるため、@path でファイル指定もできる。
    if raw_arguments.startswith("@"):
        raw_arguments = Path(raw_arguments[1:]).read_text(encoding="utf-8")
    arguments = json.loads(raw_arguments)
    timeout_sec = float(sys.argv[3]) if len(sys.argv) > 3 else 2400.0

    process = subprocess.Popen(
        [LAUNCHER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines: list[str] = []

    def drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line)
            sys.stderr.write(line)

    threading.Thread(target=drain_stderr, daemon=True).start()

    def send(message: dict) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                     "clientInfo": {"name": "mcp_call", "version": "0"}}})
    assert process.stdout is not None
    process.stdout.readline()  # initialize の応答
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": tool_name, "arguments": arguments}})

    started = time.monotonic()
    payload: dict | None = None
    while time.monotonic() - started < timeout_sec:
        line = process.stdout.readline()
        if not line:
            break
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("id") == 2:
            payload = message
            break

    elapsed = round(time.monotonic() - started, 1)
    try:
        process.stdin.close()
        process.wait(timeout=10)
    except Exception:
        process.kill()

    if payload is None:
        print("応答が返りませんでした", file=sys.stderr)
        return 1
    if "error" in payload:
        print(json.dumps(payload["error"], ensure_ascii=False, indent=2))
        return 1

    result = payload["result"]
    structured = result.get("structuredContent")
    if structured is None:
        blocks = result.get("content") or []
        text = blocks[0].get("text") if blocks else None
        try:
            structured = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            structured = text
    print(json.dumps({"_client_elapsed_sec": elapsed, "isError": result.get("isError", False),
                      "result": structured}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
