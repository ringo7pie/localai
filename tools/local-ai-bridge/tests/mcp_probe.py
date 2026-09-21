"""stdio MCP サーバーを直接叩いて確かめる小さな道具。

  .venv/bin/python tests/mcp_probe.py list
  .venv/bin/python tests/mcp_probe.py call <tool> '<json>'

標準入力を開いたままにしないとサーバーが呼び出し中に終了するので Popen を使う。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LAUNCHER = str(Path(__file__).resolve().parents[1] / "run-local-ai-bridge")


def _frame(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "probe", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    if argv[1] == "list":
        requests.append({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    elif argv[1] == "call":
        arguments = json.loads(argv[3]) if len(argv) > 3 else {}
        requests.append({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": argv[2], "arguments": arguments}})
    else:
        print("list か call を指定する", file=sys.stderr)
        return 2

    process = subprocess.Popen(
        [LAUNCHER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    assert process.stdin and process.stdout
    for request in requests:
        process.stdin.write(_frame(request))
        process.stdin.flush()

    responses = []
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(f"!! 標準出力に JSON でない行が混ざった: {line[:200]}", file=sys.stderr)
            continue
        responses.append(message)
        if message.get("id") == 2:
            break
    process.stdin.close()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
    print(json.dumps(responses[-1] if responses else {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
