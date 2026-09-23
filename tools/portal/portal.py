#!/usr/bin/env python3
"""ローカル AI サーバーの入口ページ（8080 番）。標準ライブラリだけで動く。

使い方:
    /usr/bin/python3 portal.py [--host 0.0.0.0] [--port 8080]

エンドポイント:
    GET  /                                    index.html を返す（このファイルと同じディレクトリから読む）
    GET  /api/status                          GPU / Ollama / 各サービスの状態を JSON で返す
    POST /api/service/<key>/<action>          Open WebUI・Hunyuan3D・Pixal3D の起動 (start) / 停止 (stop)。
                                               GET では 405。未導入の key・action 以外は 404/400。
                                               Hunyuan3D と Pixal3D は GPU を同時に使えないため、
                                               片方の起動時にもう片方が動いていれば自動で止めてから起動する。
    POST /api/option/<key>/low-vram/<on|off>  低 VRAM モードの切り替え（Hunyuan3D・Pixal3D のみ）。
                                               稼働中・起動中は 409（systemd の EnvironmentFile は
                                               起動時にしか読まれないため）。GET では 405。
    POST /api/memory/<key>/<high_gib>/<max_gib>  systemd のメモリ上限（MemoryHigh / MemoryMax）を
                                               GiB 単位の整数で設定する（Open WebUI・Hunyuan3D・Pixal3D
                                               のみ。ComfyUI・portal は 404）。稼働中でも再起動なしで
                                               即座に効く。GET では 405。

方針: nvidia-smi・Ollama・各ポート・各 systemd ユニット・/proc/meminfo への疎通確認はどれも
失敗しうる前提で書く。失敗しても /api/status は 500 を返さず、取れなかった項目を
available/reachable=false にして返す。/api/service/... や /api/option/... も同様に、systemctl や
設定ファイルの読み書きが失敗しても 500 ではなく {"ok": false, ...} を返す
（/api/memory/... も systemctl の失敗は同様。ただし /proc/meminfo が読めない場合のみ 500 を返す）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
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
GIB_BYTES = 1024 * 1024 * 1024
MEMINFO_PATH = Path("/proc/meminfo")

# メモリ上限（MemoryHigh / MemoryMax）の既定値・許容範囲。単位はすべて GiB。
# 根拠は knowledge/10-silver/areas/env.md（実測62.5 GiB の RAM。デスクトップ等で約10.5 GiB、
# Qwen が GPU に入りきらないときさらに約6 GiB を消費する）。
MEMORY_DEFAULT_HIGH_GIB = 44
MEMORY_DEFAULT_MAX_GIB = 48
MEMORY_MIN_GIB = 4
# 許容上限 = RAM 総量 - MEMORY_RESERVE_GIB（切り捨て）。これを超えると systemd-oomd が
# デスクトップごと止めるおそれがあるため、画面からもこれより大きい値は送れない。
MEMORY_RESERVE_GIB = 4
# 推奨上限 = RAM 総量 - MEMORY_RECOMMENDED_MARGIN_GIB（切り捨て）。デスクトップ等の常駐分と
# Qwen が GPU からあふれた分を差し引いた値。超えても拒否はしないが画面で警告する。
MEMORY_RECOMMENDED_MARGIN_GIB = 14

# 入口ページが表示するサービス一覧（ポート配置は knowledge/10-silver/areas/env.md の決定に従う）
# unit は systemd --user のユニット名。無い場合（ComfyUI）は None にし、起動・停止の対象から外す。
# portal 自身は絶対にここへ入れない（自分を止めたらページが死ぬ）。
#
# options を持つサービスは、入口ページから切り替えられる設定を持つ（今のところ低 VRAM モードのみ）。
# env_file はサービスの systemd ユニットが EnvironmentFile として読む設定ファイル、var はその中の
# 変数名、default はファイル・変数が無いときにみなす値。
SERVICES = [
    {"key": "open-webui", "name": "Open WebUI", "port": 8081, "unit": "open-webui"},
    {
        "key": "hunyuan3d",
        "name": "Hunyuan3D",
        "port": 7860,
        "unit": "hunyuan3d",
        "options": {
            "low_vram": {
                "env_file": "~/.config/hunyuan3d/hunyuan3d.env",
                "var": "HY3D_LOW_VRAM",
                "default": True,
            }
        },
    },
    {
        "key": "pixal3d",
        "name": "Pixal3D",
        "port": 7861,
        "unit": "pixal3d",
        "options": {
            "low_vram": {
                "env_file": "~/.config/pixal3d/pixal3d.env",
                "var": "PIXAL3D_LOW_VRAM",
                "default": True,
            }
        },
    },
    {"key": "comfyui", "name": "ComfyUI", "port": 8188, "unit": None},
]
SERVICES_BY_KEY = {service["key"]: service for service in SERVICES}

# GPU（VRAM）を排他的に使うサービス。どちらかを起動するとき、もう片方が動いていれば
# 先に止める（A30 は 1 枚しかなく、両方同時に載せると RAM 含めて枯れるため）。
GPU_EXCLUSIVE_KEYS = ("hunyuan3d", "pixal3d")

# POST /api/service/<key>/<action> で許可する action と、それぞれの操作の性質。
ALLOWED_ACTIONS = ("start", "stop")
ACTION_LABELS = {"start": "起動", "stop": "停止"}

SYSTEMCTL_SHOW_TIMEOUT_SEC = 5.0
SYSTEMCTL_START_TIMEOUT_SEC = 30.0  # Type=simple なのですぐ返る
SYSTEMCTL_STOP_TIMEOUT_SEC = 90.0  # Hunyuan3D は終了に時間がかかることがある
ACTION_TIMEOUTS = {"start": SYSTEMCTL_START_TIMEOUT_SEC, "stop": SYSTEMCTL_STOP_TIMEOUT_SEC}

SERVICE_ACTION_PATH_PREFIX = "/api/service/"

# POST /api/option/<key>/<option>/<value> の設定関連。
# URL 上は "low-vram"（ハイフン区切り）だが、SERVICES の options 辞書のキーは Python の識別子として
# "low_vram"（アンダースコア）を使っている。両者の対応をここで持つ。
OPTION_PATH_PREFIX = "/api/option/"
OPTION_URL_TO_KEY = {"low-vram": "low_vram"}
OPTION_VALUES = {"on": True, "off": False}

# POST /api/memory/<key>/<high_gib>/<max_gib> の設定関連。
MEMORY_ACTION_PATH_PREFIX = "/api/memory/"

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


def parse_env_file(text: str) -> dict[str, str]:
    """env ファイルの中身から `KEY=VALUE` を読む（純粋関数）。

    `#` で始まる行と空行は無視する。壊れた行（`=` が無い行）も無視し、例外は投げない。
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        key, separator, value = stripped_line.partition("=")
        if not separator:
            continue
        values[key.strip()] = value.strip()
    return values


def render_env_file(text: str, var: str, value: str) -> str:
    """env ファイルの中身に `var=value` を反映した文字列を返す（純粋関数。書き込みはしない）。

    既存の行・コメントはそのまま保つ。`var` の行があれば値だけ差し替え、無ければ末尾に追記する。
    `text` が空文字（ファイルが存在しない場合も含む）なら、見出しコメント付きで新規に組み立てる。
    """
    if not text.strip():
        header = (
            f"# {var} の設定。systemd の EnvironmentFile として読み込まれるため、\n"
            "# 反映にはサービスの再起動が要る（稼働中に書き換えても効かない）。\n"
        )
        return f"{header}{var}={value}\n"

    lines = text.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        existing_key, separator, _ = stripped_line.partition("=")
        if separator and existing_key.strip() == var:
            lines[index] = f"{var}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{var}={value}")
    return "\n".join(lines) + "\n"


def expand_env_file_path(env_file: str) -> Path:
    """設定に書かれた `~` 始まりのパスを実際のパスへ展開する。"""
    return Path(env_file).expanduser()


def read_option_value(option_config: dict[str, Any]) -> bool:
    """SERVICES の options 1 件の現在値を env ファイルから読む（真偽値。既定は on）。

    ファイルが存在しない・変数が書かれていない場合は option_config["default"] を返す。
    読み込み失敗はすべて「未設定」として扱い、例外は投げない。
    """
    path = expand_env_file_path(option_config["env_file"])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    values = parse_env_file(text)
    raw_value = values.get(option_config["var"])
    if raw_value is None:
        return bool(option_config["default"])
    return raw_value.strip() == "1"


def write_option_value(option_config: dict[str, Any], enabled: bool) -> None:
    """SERVICES の options 1 件の値を env ファイルへ書く。

    同じディレクトリの一時ファイルへ書いてから `os.replace` で置き換える。書き込みの途中で
    プロセスが落ちても、既存の設定ファイルが半端な状態で壊れて残らないようにするため。
    親ディレクトリが無ければ作る。
    """
    path = expand_env_file_path(option_config["env_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    value_text = "1" if enabled else "0"
    rendered = render_env_file(text, option_config["var"], value_text)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(rendered, encoding="utf-8")
    os.replace(temporary_path, path)


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


def services_to_stop_before_start(key: str, states: dict[str, str]) -> list[str]:
    """`key` を起動する前に止めるべき、同じ GPU 占有グループの他サービスの key 一覧を返す（純粋関数）。

    `states` は {"hunyuan3d": "running", "pixal3d": "stopped", ...} のように、キーが
    サービスの key、値が unit_state() の戻り値（4 状態のどれか）の辞書。
    `key` が GPU_EXCLUSIVE_KEYS に属さないときは常に空リスト。自分自身は対象に含めない。
    """
    if key not in GPU_EXCLUSIVE_KEYS:
        return []
    return [
        other_key
        for other_key in GPU_EXCLUSIVE_KEYS
        if other_key != key and states.get(other_key) in ("running", "starting")
    ]


def find_service_option(service: dict[str, Any], option_key: str) -> dict[str, Any] | None:
    """サービスが `option_key`（例 "low_vram"）という設定を持つならその定義を返す（純粋関数）。

    持たないサービス（Open WebUI・ComfyUI など）や、未知の option_key では None。
    """
    options = service.get("options")
    if not options:
        return None
    return options.get(option_key)


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


def parse_option_path(path: str) -> tuple[str, str, str] | None:
    """`/api/option/<key>/<option>/<value>` を解釈する（純粋関数）。形が違えば None。

    ここではパスの形だけを見る。key・option・value がそれぞれ実在するかどうかの判定は
    呼び出し元（ハンドラ側）の役目。
    """
    if not path.startswith(OPTION_PATH_PREFIX):
        return None
    remainder = path[len(OPTION_PATH_PREFIX):]
    segments = remainder.split("/")
    if len(segments) != 3:
        return None
    key, option_name, value = segments
    if not key or not option_name or not value:
        return None
    return key, option_name, value


def parse_meminfo_total_gib(text: str) -> float | None:
    """`/proc/meminfo` の本文から MemTotal を GiB で返す（純粋関数）。

    MemTotal は kB（1024 バイト単位）で書かれている。行が無い・壊れている場合は None。
    """
    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line.startswith("MemTotal"):
            continue
        fields = stripped_line.split()
        if len(fields) < 2:
            return None
        try:
            total_kib = int(fields[1])
        except ValueError:
            return None
        return total_kib / (1024 * 1024)
    return None


def memory_bounds(total_gib: float) -> dict[str, Any]:
    """RAM 総量（GiB）から、メモリ上限の許容範囲・推奨範囲を組み立てる（純粋関数）。

    - allowed_max_gib: これを超える MemoryMax は画面からも設定させない（systemd-oomd が
      デスクトップごと止めるおそれがあるため）。RAM 総量 - MEMORY_RESERVE_GIB を切り捨てた値。
    - recommended_max_gib: 超えても拒否はしないが警告を出す目安。RAM 総量 -
      MEMORY_RECOMMENDED_MARGIN_GIB を切り捨てた値。
    """
    return {
        "total_gib": total_gib,
        "allowed_max_gib": math.floor(total_gib - MEMORY_RESERVE_GIB),
        "recommended_max_gib": math.floor(total_gib - MEMORY_RECOMMENDED_MARGIN_GIB),
        "min_gib": MEMORY_MIN_GIB,
    }


def validate_memory_limits(high_gib: Any, max_gib: Any, bounds: dict[str, Any]) -> str | None:
    """MemoryHigh / MemoryMax の指定値が妥当かを確かめる（純粋関数）。

    問題が無ければ None、あれば日本語の理由を返す。規則: 整数であること、
    `min_gib <= high <= max <= allowed_max_gib`。

    理由の文には**どちらの値が大きすぎる（小さすぎる）のか**と、いま入っている値、
    許される範囲を必ず入れる。「MemoryHigh は MemoryMax 以下にしてください」のように
    数値の無い文だけを返すと、利用者がどちらをいくつに直せばよいか分からないため。
    """
    for label, value in (("MemoryHigh", high_gib), ("MemoryMax", max_gib)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{label} は整数で指定してください（いまの値: {value!r}）。"
        if float(value) != int(value):
            return f"{label} は整数で指定してください（いまの値: {value}）。"

    high_value = int(high_gib)
    max_value = int(max_gib)
    min_gib = bounds["min_gib"]
    allowed_max_gib = bounds["allowed_max_gib"]

    if high_value < min_gib:
        return (
            f"MemoryHigh が小さすぎます（いまの値: {high_value} GiB）。"
            f"{min_gib} GiB 以上にしてください。"
        )
    if high_value > max_value:
        return (
            f"MemoryHigh が MemoryMax より大きすぎます"
            f"（MemoryHigh {high_value} GiB > MemoryMax {max_value} GiB）。"
            f"MemoryHigh を {max_value} GiB 以下に下げるか、MemoryMax を {high_value} GiB 以上に上げてください。"
        )
    if max_value > allowed_max_gib:
        return (
            f"MemoryMax が大きすぎます（いまの値: {max_value} GiB）。"
            f"{allowed_max_gib} GiB 以下にしてください"
            f"（RAM 総量 {bounds['total_gib']:.1f} GiB から {MEMORY_RESERVE_GIB} GiB を残す上限です）。"
        )
    return None


def memory_warning(max_gib: Any, bounds: dict[str, Any]) -> str | None:
    """`max_gib` が推奨上限を超えているときに見せる警告文を返す（純粋関数）。拒否はしない。"""
    recommended_max_gib = bounds.get("recommended_max_gib")
    if recommended_max_gib is None:
        return None
    if max_gib > recommended_max_gib:
        return (
            f"MemoryMax（{int(max_gib)} GiB）が推奨上限（{recommended_max_gib} GiB）を超えています。"
            "使いすぎたときにデスクトップごと止まるおそれがあります。"
        )
    return None


def parse_memory_properties(stdout: str) -> dict[str, float | None]:
    """`systemctl show --property=MemoryHigh --property=MemoryMax --property=MemoryCurrent` の
    出力を `{"high_gib":..., "max_gib":..., "current_gib":...}`（GiB、float）へ変換する（純粋関数）。

    値はバイト数の整数、`infinity`（上限無し）、`[not set]`（停止中の MemoryCurrent）のいずれか。
    `infinity` と `[not set]` は None にする。行の順序には依存しない（read_unit_state と同じ理由）。
    """
    properties: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key.strip()] = value.strip()

    def to_gib(raw_value: str | None) -> float | None:
        if raw_value is None or raw_value in ("infinity", "[not set]"):
            return None
        try:
            return int(raw_value) / GIB_BYTES
        except ValueError:
            return None

    return {
        "high_gib": to_gib(properties.get("MemoryHigh")),
        "max_gib": to_gib(properties.get("MemoryMax")),
        "current_gib": to_gib(properties.get("MemoryCurrent")),
    }


def build_set_property_commands(unit: str, high_gib: Any, max_gib: Any) -> list[list[str]]:
    """`systemctl --user set-property` のコマンド列を 2 本組み立てる（純粋関数）。

    1 本目（`--runtime` 無し）は恒久設定（PC 再起動後も残る）、2 本目（`--runtime` 付き）は
    ランタイム設定（再起動で消えるが、恒久設定より優先度が高い）。両方に同じ値を書くことで、
    以前 `--runtime` で書かれた値が残っていても画面で決めた値が必ず効くようにする。
    どちらも稼働中のユニットへ再起動なしで即座に効く。
    """
    high_value = f"MemoryHigh={int(high_gib)}G"
    max_value = f"MemoryMax={int(max_gib)}G"
    return [
        ["systemctl", "--user", "set-property", unit, high_value, max_value],
        ["systemctl", "--user", "set-property", "--runtime", unit, high_value, max_value],
    ]


def parse_memory_path(path: str) -> tuple[str, str, str] | None:
    """`/api/memory/<key>/<high>/<max>` を解釈する（純粋関数）。形だけを見る。

    `key`・`high`・`max` が実在する値か、整数として解釈できるかの判定は呼び出し元（ハンドラ側）の役目。
    """
    if not path.startswith(MEMORY_ACTION_PATH_PREFIX):
        return None
    remainder = path[len(MEMORY_ACTION_PATH_PREFIX):]
    segments = remainder.split("/")
    if len(segments) != 3:
        return None
    key, high_raw, max_raw = segments
    if not key or not high_raw or not max_raw:
        return None
    return key, high_raw, max_raw


def build_service_status(
    service: dict[str, Any],
    port_open: bool,
    active_state: str,
    load_state: str,
    option_values: dict[str, Any] | None = None,
    memory_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SERVICES の 1 件と実測値から `/api/status` の services[] に載せる 1 件を組み立てる（純粋関数）。

    `option_values` はそのサービスが持つ設定の現在値（例 {"low_vram": True}）。設定ファイルを
    読むのは呼び出し元（collect_status）の役目で、この関数はそれをそのまま "options" として
    素通しするだけ。渡さなければ空の辞書になる（設定を持たないサービス向け）。
    `memory_values` は unit を持つサービスの現在のメモリ上限（parse_memory_properties の戻り値）。
    unit を持たないサービス（ComfyUI）では None のまま渡す。
    """
    state = unit_state(active_state, load_state, port_open)
    controllable = is_controllable({"unit": service["unit"], "state": state})
    return {
        "key": service["key"],
        "name": service["name"],
        "port": service["port"],
        "up": port_open,
        "state": state,
        "controllable": controllable,
        "options": dict(option_values) if option_values else {},
        "memory": dict(memory_values) if memory_values is not None else None,
    }


def build_ram_status(total_gib: float | None) -> dict[str, Any]:
    """`/api/status` の `ram` フィールドを組み立てる（純粋関数）。

    `total_gib` が None（/proc/meminfo を読めなかった）なら available: false で残りは None。
    `default_high_gib` / `default_max_gib` は RAM 総量に関係なく常に定数を返す
    （画面の「既定に戻す」ボタンが使うため）。
    """
    if total_gib is None:
        return {
            "total_gib": None,
            "allowed_max_gib": None,
            "recommended_max_gib": None,
            "min_gib": MEMORY_MIN_GIB,
            "default_high_gib": MEMORY_DEFAULT_HIGH_GIB,
            "default_max_gib": MEMORY_DEFAULT_MAX_GIB,
            "available": False,
        }
    bounds = memory_bounds(total_gib)
    return {
        "total_gib": bounds["total_gib"],
        "allowed_max_gib": bounds["allowed_max_gib"],
        "recommended_max_gib": bounds["recommended_max_gib"],
        "min_gib": bounds["min_gib"],
        "default_high_gib": MEMORY_DEFAULT_HIGH_GIB,
        "default_max_gib": MEMORY_DEFAULT_MAX_GIB,
        "available": True,
    }


def build_status(
    gpu: dict[str, int] | None,
    ollama_models: list[dict[str, Any]] | None,
    services: list[dict[str, Any]],
    total_ram_gib: float | None = None,
) -> dict[str, Any]:
    """`/api/status` が返す JSON 形状を組み立てる（純粋関数。ネットワークにも GPU にも触らない）。

    `gpu` は `parse_nvidia_smi` の戻り値（取れなければ None）。
    `ollama_models` は `parse_ollama_ps` の戻り値（到達できなければ None）。
    `services` は `build_service_status` が返す辞書（"key","name","port","up","state","controllable",
    "options","memory"）のリスト。この関数はそれをそのまま素通しするだけで、内容の加工はしない。
    `total_ram_gib` は `parse_meminfo_total_gib` の戻り値（取れなければ None）。
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
        "ram": build_ram_status(total_ram_gib),
    }


def read_meminfo_total_gib() -> float | None:
    """`/proc/meminfo` を読んで MemTotal を GiB で返す。読めなければ None。"""
    try:
        text = MEMINFO_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_meminfo_total_gib(text)


def read_memory_properties(unit: str, timeout: float = SYSTEMCTL_SHOW_TIMEOUT_SEC) -> dict[str, float | None]:
    """`systemctl --user show <unit> --property=MemoryHigh --property=MemoryMax
    --property=MemoryCurrent` を実行し、`parse_memory_properties` で解釈する。

    失敗（コマンドが無い・タイムアウト・異常終了）した場合は例外を投げず、すべて None にする。
    """
    try:
        process = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                unit,
                "--property=MemoryHigh",
                "--property=MemoryMax",
                "--property=MemoryCurrent",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return {"high_gib": None, "max_gib": None, "current_gib": None}
    if process.returncode != 0:
        return {"high_gib": None, "max_gib": None, "current_gib": None}
    return parse_memory_properties(process.stdout)


def set_unit_memory_limits(
    unit: str, high_gib: Any, max_gib: Any, timeout: float = SYSTEMCTL_SHOW_TIMEOUT_SEC
) -> list[dict[str, Any]]:
    """`build_set_property_commands` の 2 本を順に実行する。

    ここに渡す unit は必ず SERVICES 由来のもの。利用者が渡した文字列をそのまま渡してはならない。
    戻り値は 2 件のリスト（恒久設定 → `--runtime`）、各要素は `{"ok": bool, "stderr": str}`。
    どちらも例外を外に投げない。
    """
    results: list[dict[str, Any]] = []
    for command in build_set_property_commands(unit, high_gib, max_gib):
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            results.append({"ok": False, "stderr": str(error)})
            continue
        if process.returncode == 0:
            results.append({"ok": True, "stderr": ""})
        else:
            results.append({"ok": False, "stderr": (process.stderr or process.stdout or "").strip()})
    return results


def collect_status() -> dict[str, Any]:
    """実際に nvidia-smi・Ollama・各ポート・各 systemd ユニット・各設定ファイル・/proc/meminfo へ
    問い合わせて `/api/status` の中身を作る。
    """
    gpu = read_nvidia_smi()
    ollama_models = read_ollama_ps()
    total_ram_gib = read_meminfo_total_gib()
    services = []
    for service in SERVICES:
        port_open = port_is_open(service["port"])
        unit = service["unit"]
        if unit:
            active_state, load_state = read_unit_state(unit)
            memory_values = read_memory_properties(unit)
        else:
            active_state, load_state = ("unknown", "not-found")
            memory_values = None
        option_values = {
            option_key: read_option_value(option_config)
            for option_key, option_config in service.get("options", {}).items()
        }
        services.append(
            build_service_status(
                service, port_open, active_state, load_state, option_values, memory_values
            )
        )
    return build_status(gpu, ollama_models, services, total_ram_gib)


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
        elif (
            self.path.startswith(SERVICE_ACTION_PATH_PREFIX)
            or self.path.startswith(OPTION_PATH_PREFIX)
            or self.path.startswith(MEMORY_ACTION_PATH_PREFIX)
        ):
            # 起動・停止・設定変更はどれも POST 専用。ブラウザのプリフェッチや履歴で誤って
            # 実行されないように、GET でこれらのパスを叩かれても何もせず 405 を返す。
            self._send_json(405, {"ok": False, "message": "GET では操作できません。POST を使ってください。"})
        else:
            self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        if self.path.startswith(SERVICE_ACTION_PATH_PREFIX):
            parsed_path = parse_service_action_path(self.path)
            if parsed_path is None:
                self._send_json(404, {"ok": False, "message": "パスが不正です。"})
                return
            key, action = parsed_path
            self._handle_service_action(key, action)
            return
        if self.path.startswith(OPTION_PATH_PREFIX):
            parsed_option_path = parse_option_path(self.path)
            if parsed_option_path is None:
                self._send_json(404, {"ok": False, "message": "パスが不正です。"})
                return
            key, option_name, value = parsed_option_path
            self._handle_option_action(key, option_name, value)
            return
        if self.path.startswith(MEMORY_ACTION_PATH_PREFIX):
            parsed_memory_path = parse_memory_path(self.path)
            if parsed_memory_path is None:
                self._send_json(404, {"ok": False, "message": "パスが不正です。"})
                return
            key, high_raw, max_raw = parsed_memory_path
            self._handle_memory_action(key, high_raw, max_raw)
            return
        self.send_error(404, "Not Found")

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

    def _current_service_state(self, service: dict[str, Any]) -> str:
        """このサービスの現在の 4 状態（running/starting/stopped/not_installed）を実測する。"""
        unit = service["unit"]
        port_open = port_is_open(service["port"])
        if unit:
            active_state, load_state = read_unit_state(unit)
        else:
            active_state, load_state = ("unknown", "not-found")
        return unit_state(active_state, load_state, port_open)

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

        current_state = self._current_service_state(service)

        if not is_controllable({"unit": service["unit"], "state": current_state}):
            self._send_json(
                409,
                {"ok": False, "message": "未導入です。操作できません。", "state": current_state},
            )
            return

        stopped_keys: list[str] = []
        if action == "start" and key in GPU_EXCLUSIVE_KEYS:
            # Hunyuan3D と Pixal3D は GPU を排他的に使う。起動する前に、同じグループで
            # 動いている（running / starting）他サービスを止める。
            states = {
                exclusive_key: self._current_service_state(SERVICES_BY_KEY[exclusive_key])
                for exclusive_key in GPU_EXCLUSIVE_KEYS
                if exclusive_key in SERVICES_BY_KEY
            }
            for key_to_stop in services_to_stop_before_start(key, states):
                other_service = SERVICES_BY_KEY[key_to_stop]
                stop_result = perform_service_action(other_service, "stop")
                if not stop_result["ok"]:
                    # 両方立ち上がって RAM が枯れるのを防ぐため、停止に失敗したら起動しない。
                    self._send_json(
                        200,
                        {
                            "ok": False,
                            "message": (
                                f"{other_service['name']} の停止に失敗したため、起動を中止しました: "
                                f"{stop_result['message']}"
                            ),
                            "state": current_state,
                        },
                    )
                    return
                stopped_keys.append(key_to_stop)

        # ここに来るのは SERVICES 由来の unit のみ。利用者が渡した文字列をコマンドへ渡すことはない。
        result = perform_service_action(service, action)
        if stopped_keys:
            result = dict(result)
            stopped_names = "、".join(SERVICES_BY_KEY[stopped_key]["name"] for stopped_key in stopped_keys)
            result["stopped"] = stopped_keys
            result["message"] = f"{stopped_names} を停止してから起動しました。{result['message']}"
        self._send_json(200, result)

    def _handle_option_action(self, key: str, option_name: str, value: str) -> None:
        # 起動・停止と同じく、設定変更も必ずログに残す。
        sys.stderr.write(
            f"portal: 設定変更要求 {self.address_string()} - [{self.log_date_time_string()}] "
            f"/api/option/{key}/{option_name}/{value}\n"
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

        option_key = OPTION_URL_TO_KEY.get(option_name)
        if option_key is None:
            self._send_json(400, {"ok": False, "message": "その設定は存在しません。"})
            return

        if value not in OPTION_VALUES:
            self._send_json(400, {"ok": False, "message": "値は on か off のみです。"})
            return

        option_config = find_service_option(service, option_key)
        if option_config is None:
            self._send_json(400, {"ok": False, "message": f"{service['name']} にはその設定がありません。"})
            return

        # 稼働中・起動中は変更させない。systemd の EnvironmentFile は起動時にしか読まれないため、
        # 動いている間に書き換えても反映されず、利用者が「変えたのに変わらない」と誤解するため。
        current_state = self._current_service_state(service)
        if current_state in ("running", "starting"):
            self._send_json(
                409,
                {"ok": False, "message": "変更するには先に停止してください。", "state": current_state},
            )
            return

        enabled = OPTION_VALUES[value]
        try:
            write_option_value(option_config, enabled)
        except OSError as error:
            self._send_json(500, {"ok": False, "message": f"設定の書き込みに失敗しました: {error}"})
            return

        state_label = "オン" if enabled else "オフ"
        self._send_json(
            200,
            {"ok": True, "message": f"低 VRAM モードを{state_label}にしました。", "value": enabled},
        )

    def _handle_memory_action(self, key: str, high_raw: str, max_raw: str) -> None:
        # 起動・停止・設定変更と同じく、メモリ上限の変更も必ずログに残す（誰がいくつにしたか）。
        sys.stderr.write(
            f"portal: メモリ設定要求 {self.address_string()} - [{self.log_date_time_string()}] "
            f"/api/memory/{key}/{high_raw}/{max_raw}\n"
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
        if service is None or service["unit"] is None:
            self._send_json(404, {"ok": False, "message": "そのサービスは存在しません。"})
            return

        try:
            high_gib = int(high_raw)
            max_gib = int(max_raw)
        except ValueError:
            self._send_json(400, {"ok": False, "message": "high と max は整数（GiB）で指定してください。"})
            return

        total_ram_gib = read_meminfo_total_gib()
        if total_ram_gib is None:
            self._send_json(500, {"ok": False, "message": "RAM の総量（/proc/meminfo）を取得できませんでした。"})
            return

        bounds = memory_bounds(total_ram_gib)
        invalid_reason = validate_memory_limits(high_gib, max_gib, bounds)
        if invalid_reason is not None:
            self._send_json(400, {"ok": False, "message": invalid_reason})
            return

        unit = service["unit"]
        persistent_result, runtime_result = set_unit_memory_limits(unit, high_gib, max_gib)
        ok = persistent_result["ok"] and runtime_result["ok"]

        if ok:
            message = (
                f"{service['name']} を MemoryHigh={high_gib}G / MemoryMax={max_gib}G にしました"
                "（再起動不要。PC を再起動しても残ります）"
            )
        elif not persistent_result["ok"]:
            message = f"{service['name']} の設定変更に失敗しました: {persistent_result['stderr']}"
        else:
            message = (
                f"{service['name']} の恒久設定は書き込みましたが、即時反映（--runtime）に失敗しました: "
                f"{runtime_result['stderr']}"
            )

        warning = memory_warning(max_gib, bounds)
        memory_values = read_memory_properties(unit)
        self._send_json(
            200,
            {"ok": ok, "message": message, "warning": warning, "memory": memory_values},
        )

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
