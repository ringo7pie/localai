#!/usr/bin/env python3
"""ローカル AI サーバーの入口ページ（8080 番）。標準ライブラリだけで動く。

使い方:
    /usr/bin/python3 portal.py [--host 0.0.0.0] [--port 8080]

エンドポイント:
    GET  /                             index.html を返す（このファイルと同じディレクトリから読む）
    GET  /api/status                   GPU / Ollama / 各サービスの状態を JSON で返す
    POST /api/service/<key>/<action>   Open WebUI・Hunyuan3D の起動 (start) / 停止 (stop)。
                                        GET では 405。未導入の key・action 以外は 404/400。

方針: nvidia-smi・Ollama・各ポート・各 systemd ユニットへの疎通確認はどれも失敗しうる前提で書く。
失敗しても /api/status は 500 を返さず、取れなかった項目を
available/reachable=false にして返す。/api/service/... も同様に、systemctl が失敗しても
500 ではなく {"ok": false, ...} を返す。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import create_connection
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"

OLLAMA_STATUS_URL = "http://127.0.0.1:11434/api/ps"
NVIDIA_SMI_TIMEOUT_SEC = 2.0
OLLAMA_TIMEOUT_SEC = 2.0
PORT_CHECK_TIMEOUT_SEC = 0.3
MIB_BYTES = 1024 * 1024

# 入口ページが表示するサービス一覧（ポート配置は knowledge/10-silver/areas/env.md の決定に従う）
# unit は systemd --user のユニット名。無い場合（ComfyUI）は None にし、起動・停止の対象から外す。
# portal 自身は絶対にここへ入れない（自分を止めたらページが死ぬ）。
SERVICES = [
    {"key": "open-webui", "name": "Open WebUI", "port": 8081, "unit": "open-webui"},
    {"key": "hunyuan3d", "name": "Hunyuan3D", "port": 7860, "unit": "hunyuan3d"},
    {"key": "comfyui", "name": "ComfyUI", "port": 8188, "unit": None},
]
SERVICES_BY_KEY = {service["key"]: service for service in SERVICES}

# POST /api/service/<key>/<action> で許可する action と、それぞれの操作の性質。
ALLOWED_ACTIONS = ("start", "stop")
ACTION_LABELS = {"start": "起動", "stop": "停止"}

SYSTEMCTL_SHOW_TIMEOUT_SEC = 5.0
SYSTEMCTL_START_TIMEOUT_SEC = 30.0  # Type=simple なのですぐ返る
SYSTEMCTL_STOP_TIMEOUT_SEC = 90.0  # Hunyuan3D は終了に時間がかかることがある
ACTION_TIMEOUTS = {"start": SYSTEMCTL_START_TIMEOUT_SEC, "stop": SYSTEMCTL_STOP_TIMEOUT_SEC}

SERVICE_ACTION_PATH_PREFIX = "/api/service/"

# 起動・停止の要求に必須のヘッダ。入口ページ自身の JavaScript だけが付ける。
# 単純な POST（ヘッダ無し）は他サイトからでもブラウザが送れてしまうため、独自ヘッダを必須にして
# クロスオリジンの事前確認（preflight）を強制する。こちらは preflight に応答しないので、
# 他サイトの JavaScript からは操作できない。curl から叩くときは -H で付ける。
REQUIRED_ACTION_HEADER = "X-Portal-Request"
REQUIRED_ACTION_HEADER_VALUE = "1"


def port_is_open(port: int, host: str = "127.0.0.1", timeout: float = PORT_CHECK_TIMEOUT_SEC) -> bool:
    """指定ポートが待受中かどうかを実際に接続して確かめる。失敗はすべて False。"""
    try:
        connection = create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    connection.close()
    return True


def parse_nvidia_smi(output_text: str) -> dict[str, int] | None:
    """`nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits` の出力を解釈する。

    例: "4, 24576" -> {"used_mib": 4, "total_mib": 24576}
    壊れた入力・空文字では例外を投げず None を返す。
    """
    if not output_text or not output_text.strip():
        return None
    first_line = output_text.strip().splitlines()[0]
    fields = [field.strip() for field in first_line.split(",")]
    if len(fields) < 2:
        return None
    try:
        used_mib = int(fields[0])
        total_mib = int(fields[1])
    except ValueError:
        return None
    return {"used_mib": used_mib, "total_mib": total_mib}


def read_nvidia_smi(timeout: float = NVIDIA_SMI_TIMEOUT_SEC) -> dict[str, int] | None:
    """nvidia-smi を短いタイムアウトで呼び出す。コマンドが無い・失敗した場合は None。"""
    try:
        process = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        return None
    return parse_nvidia_smi(process.stdout)


def parse_ollama_ps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Ollama `/api/ps` の JSON を `[{"name":..., "size_vram_mib":...}, ...]` へ変換する。

    `payload` の形が想定と違っても例外を投げず、読み取れた分だけ返す。
    """
    models: list[dict[str, Any]] = []
    entries = payload.get("models") if isinstance(payload, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        model_name = entry.get("name") or entry.get("model") or "?"
        size_vram_bytes = entry.get("size_vram") or 0
        try:
            size_vram_mib = round(int(size_vram_bytes) / MIB_BYTES)
        except (TypeError, ValueError):
            size_vram_mib = 0
        models.append({"name": model_name, "size_vram_mib": size_vram_mib})
    return models


def read_ollama_ps(timeout: float = OLLAMA_TIMEOUT_SEC) -> list[dict[str, Any]] | None:
    """Ollama の `/api/ps` を短いタイムアウトで呼び出す。到達できなければ None。"""
    try:
        with urllib.request.urlopen(OLLAMA_STATUS_URL, timeout=timeout) as response:
            response_body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return parse_ollama_ps(payload)


def unit_state(active_state: str, load_state: str, port_open: bool) -> str:
    """systemd の ActiveState / LoadState とポート開放状況から画面表示用の 4 状態を決める（純粋関数）。

    - "running"       ポートが開いている（すぐ使える）
    - "starting"      ユニットは active/activating だが、ポートはまだ開いていない
                       （Hunyuan3D はモデルの読み込みに 50〜140 秒かかるため、この状態が長く続く）
    - "stopped"       ユニットは動いていない
    - "not_installed" ユニットが存在しない（load_state が "loaded" 以外。ComfyUI が該当）
    """
    if load_state != "loaded":
        return "not_installed"
    if port_open:
        return "running"
    if active_state in ("active", "activating"):
        return "starting"
    return "stopped"


def is_controllable(service: dict[str, Any]) -> bool:
    """このサービスを起動・停止できるか（純粋関数）。

    `service` は少なくとも "unit" と "state" を持つ辞書。unit が None、または
    state が "not_installed" のときは操作できない。
    """
    if service.get("unit") is None:
        return False
    if service.get("state") == "not_installed":
        return False
    return True


def read_unit_state(unit: str, timeout: float = SYSTEMCTL_SHOW_TIMEOUT_SEC) -> tuple[str, str]:
    """`systemctl --user show <unit> --property=ActiveState --property=LoadState` を実行する。

    出力は `Key=Value` 形式で 1 行ずつ受け取り、キー名で拾う。`--value` は使わない。実機で確認したところ、
    systemd は `--property` を指定した順序どおりには出力しない（コマンドラインでの並びに関係なく
    LoadState を先に出す）ため、行の位置ではなくキー名で照合する必要がある。
    失敗（コマンドが無い・タイムアウト・想定外の出力）した場合は例外を投げず ("unknown", "not-found") を返す。
    """
    try:
        process = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                unit,
                "--property=ActiveState",
                "--property=LoadState",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ("unknown", "not-found")
    if process.returncode != 0:
        return ("unknown", "not-found")
    properties: dict[str, str] = {}
    for line in process.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key.strip()] = value.strip()
    active_state = properties.get("ActiveState")
    load_state = properties.get("LoadState")
    if not active_state or not load_state:
        return ("unknown", "not-found")
    return (active_state, load_state)


def control_unit(unit: str, action: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """`systemctl --user <action> <unit>` を実行する。呼び出し元がタイムアウトを選ぶ。

    ここに渡す unit は必ず SERVICES 由来のもの。利用者が渡した文字列をそのまま渡してはならない。
    """
    return subprocess.run(
        ["systemctl", "--user", action, unit],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def perform_service_action(service: dict[str, Any], action: str) -> dict[str, Any]:
    """SERVICES の 1 件に対して start/stop を実行し、結果を JSON 化できる辞書で返す。

    どんな失敗（タイムアウト・systemctl 自体の異常終了）でも例外を外に投げない。
    戻り値は常に {"ok": bool, "message": str, "state": str}。
    """
    unit = service["unit"]
    timeout = ACTION_TIMEOUTS[action]
    action_label = ACTION_LABELS[action]

    try:
        process = control_unit(unit, action, timeout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "message": f"{action_label}がタイムアウトしました（{timeout:.0f} 秒以内に終わりませんでした）。",
            "state": "unknown",
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "message": f"systemctl の実行に失敗しました: {error}", "state": "unknown"}

    port_open = port_is_open(service["port"])
    active_state, load_state = read_unit_state(unit)
    state = unit_state(active_state, load_state, port_open)

    if process.returncode == 0:
        if action == "start":
            message = (
                f"{service['name']} の起動を要求しました。準備できるまで数十秒〜数分かかる場合があります。"
            )
        else:
            message = f"{service['name']} の停止を要求しました。"
        return {"ok": True, "message": message, "state": state}

    error_text = (process.stderr or process.stdout or "").strip() or "詳細不明のエラーです。"
    return {
        "ok": False,
        "message": f"{service['name']} の{action_label}に失敗しました: {error_text}",
        "state": state,
    }


def parse_service_action_path(path: str) -> tuple[str, str] | None:
    """`/api/service/<key>/<action>` を解釈する（純粋関数）。形が違えば None。"""
    if not path.startswith(SERVICE_ACTION_PATH_PREFIX):
        return None
    remainder = path[len(SERVICE_ACTION_PATH_PREFIX):]
    segments = remainder.split("/")
    if len(segments) != 2:
        return None
    key, action = segments
    if not key or not action:
        return None
    return key, action


def build_service_status(
    service: dict[str, Any],
    port_open: bool,
    active_state: str,
    load_state: str,
) -> dict[str, Any]:
    """SERVICES の 1 件と実測値から `/api/status` の services[] に載せる 1 件を組み立てる（純粋関数）。"""
    state = unit_state(active_state, load_state, port_open)
    controllable = is_controllable({"unit": service["unit"], "state": state})
    return {
        "key": service["key"],
        "name": service["name"],
        "port": service["port"],
        "up": port_open,
        "state": state,
        "controllable": controllable,
    }


def build_status(
    gpu: dict[str, int] | None,
    ollama_models: list[dict[str, Any]] | None,
    services: list[dict[str, Any]],
) -> dict[str, Any]:
    """`/api/status` が返す JSON 形状を組み立てる（純粋関数。ネットワークにも GPU にも触らない）。

    `gpu` は `parse_nvidia_smi` の戻り値（取れなければ None）。
    `ollama_models` は `parse_ollama_ps` の戻り値（到達できなければ None）。
    `services` は `build_service_status` が返す辞書（"key","name","port","up","state","controllable"）のリスト。
    この関数はそれをそのまま素通しするだけで、内容の加工はしない。
    """
    if gpu is not None:
        gpu_status = {
            "used_mib": gpu["used_mib"],
            "total_mib": gpu["total_mib"],
            "available": True,
        }
    else:
        gpu_status = {"used_mib": None, "total_mib": None, "available": False}

    if ollama_models is not None:
        ollama_status = {"reachable": True, "models": ollama_models}
    else:
        ollama_status = {"reachable": False, "models": []}

    return {
        "gpu": gpu_status,
        "ollama": ollama_status,
        "services": list(services),
    }


def collect_status() -> dict[str, Any]:
    """実際に nvidia-smi・Ollama・各ポート・各 systemd ユニットへ問い合わせて `/api/status` の中身を作る。"""
    gpu = read_nvidia_smi()
    ollama_models = read_ollama_ps()
    services = []
    for service in SERVICES:
        port_open = port_is_open(service["port"])
        unit = service["unit"]
        if unit:
            active_state, load_state = read_unit_state(unit)
        else:
            active_state, load_state = ("unknown", "not-found")
        services.append(build_service_status(service, port_open, active_state, load_state))
    return build_status(gpu, ollama_models, services)


class PortalRequestHandler(BaseHTTPRequestHandler):
    server_version = "PortalHTTP/1.0"

    def log_message(self, format_string: str, *args: Any) -> None:
        # /api/status は 5 秒ごとに来るのでログを出さない（うるさいため）。
        if self.path.startswith("/api/status"):
            return
        message = format_string % args
        sys.stderr.write(f"{self.address_string()} - - [{self.log_date_time_string()}] {message}\n")

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._serve_index()
        elif self.path == "/api/status":
            self._serve_status()
        elif self.path.startswith(SERVICE_ACTION_PATH_PREFIX):
            # 起動・停止は POST 専用。ブラウザのプリフェッチや履歴で誤って起動されないように、
            # GET でこのパスを叩かれても何も実行せず 405 を返す。
            self._send_json(405, {"ok": False, "message": "GET では操作できません。POST を使ってください。"})
        else:
            self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        if not self.path.startswith(SERVICE_ACTION_PATH_PREFIX):
            self.send_error(404, "Not Found")
            return
        parsed_path = parse_service_action_path(self.path)
        if parsed_path is None:
            self._send_json(404, {"ok": False, "message": "パスが不正です。"})
            return
        key, action = parsed_path
        self._handle_service_action(key, action)

    def _serve_index(self) -> None:
        try:
            body = INDEX_FILE.read_bytes()
        except OSError as error:
            self.send_error(500, f"index.html を読めません: {error}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self) -> None:
        try:
            status = collect_status()
        except Exception:
            # ここに来るのは想定外の不具合のとき。それでも 500 は返さず空の状態を返す。
            status = build_status(None, None, [])
        self._send_json(200, status)

    def _handle_service_action(self, key: str, action: str) -> None:
        # 5 秒ごとには来ない操作なので、/api/status と違って必ずログに残す（誰が何をしたか分かるように）。
        sys.stderr.write(
            f"portal: 操作要求 {self.address_string()} - [{self.log_date_time_string()}] "
            f"/api/service/{key}/{action}\n"
        )

        if self.headers.get(REQUIRED_ACTION_HEADER) != REQUIRED_ACTION_HEADER_VALUE:
            self._send_json(
                403,
                {
                    "ok": False,
                    "message": (
                        f"{REQUIRED_ACTION_HEADER} ヘッダが要ります"
                        "（入口ページ以外からの操作を防ぐため）。"
                    ),
                },
            )
            return

        service = SERVICES_BY_KEY.get(key)
        if service is None:
            self._send_json(404, {"ok": False, "message": "そのサービスは存在しません。"})
            return

        if action not in ALLOWED_ACTIONS:
            self._send_json(400, {"ok": False, "message": "action は start か stop のみです。"})
            return

        unit = service["unit"]
        port_open = port_is_open(service["port"])
        if unit:
            active_state, load_state = read_unit_state(unit)
        else:
            active_state, load_state = ("unknown", "not-found")
        current_state = unit_state(active_state, load_state, port_open)

        if not is_controllable({"unit": unit, "state": current_state}):
            self._send_json(
                409,
                {"ok": False, "message": "未導入です。操作できません。", "state": current_state},
            )
            return

        # ここに来るのは SERVICES 由来の unit のみ。利用者が渡した文字列をコマンドへ渡すことはない。
        result = perform_service_action(service, action)
        self._send_json(200, result)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ローカル AI サーバーの入口ページ")
    parser.add_argument("--host", default="0.0.0.0", help="待受アドレス（既定 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8080, help="待受ポート（既定 8080）")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    arguments = parse_args(argv)
    server = ThreadingHTTPServer((arguments.host, arguments.port), PortalRequestHandler)
    sys.stderr.write(f"portal: http://{arguments.host}:{arguments.port} で待受を開始します\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("portal: 終了します\n")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
