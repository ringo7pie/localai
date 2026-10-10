"""tools/model-eval の試験の共通部品。

- ツールのディレクトリを sys.path に入れる（run_eval.py などを import するため）。
- work_tmp: 一時ディレクトリを work/pytest/<試験名>/ に作り、終わったら消す（/tmp を使わない約束）。
- fake_server: 偽の HTTP サーバー（Ollama / Strata の代わり）を 127.0.0.1 の空きポートで立てる。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


@pytest.fixture
def work_tmp(request):
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.name)[:80]
    path = TOOL_DIR / "work" / "pytest" / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)
    parent = path.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


class _Handler(BaseHTTPRequestHandler):
    """script(handler, method, path, body) に応答を任せる。"""

    script = None

    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else None
        try:
            type(self).script(self, method, self.path, body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 相手（試験の側）が先に切った

    def do_GET(self):  # noqa: N802 - http.server が決めた名前
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802 - http.server が決めた名前
        self._dispatch("POST")

    def log_message(self, *_args):
        return

    # 応答の小道具
    def send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def start_stream(self, content_type="application/x-ndjson"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def write_line(self, text: str):
        self.wfile.write((text + "\n").encode("utf-8"))
        self.wfile.flush()


@pytest.fixture
def fake_server():
    servers = []

    def start(script):
        handler = type("Handler", (_Handler,), {"script": staticmethod(script)})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()
