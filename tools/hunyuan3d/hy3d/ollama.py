"""Ollama の常駐モデルを確認・解放するための薄いクライアント。

標準ライブラリのみで実装する（hy3d 自体を torch なしで動かすため）。
HTTP は urllib.request を使い、タイムアウトを必ず指定する。
例外は握りつぶさない。ただし loaded_models() は「Ollama に繋がらない」を
呼び出し側が毎回 try/except せずに済むよう、空リストという形で表す。
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from . import config

_CONNECT_TIMEOUT_SEC = 5.0


def loaded_models() -> list[dict[str, Any]]:
    """/api/ps に載っているモデルの一覧を返す。

    繋がらなければ（Ollama が落ちている等）空リストを返す。
    """

    url = f"{config.OLLAMA_URL}/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=_CONNECT_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []

    models = payload.get("models") or []
    result: list[dict[str, Any]] = []
    for model in models:
        name = model.get("name") or model.get("model")
        if name is None:
            continue
        result.append({"name": name, "size_vram": model.get("size_vram")})
    return result


def unload_all() -> list[str]:
    """載っているモデルをすべて keep_alive=0 で降ろす。

    降ろした（POST が成功した）モデル名の一覧を返す。
    途中で失敗したら例外を送出する（呼び出し側が状況を判断できるように、握りつぶさない）。
    """

    unloaded: list[str] = []
    for model in loaded_models():
        name = model["name"]
        body = json.dumps({"model": name, "prompt": "", "keep_alive": 0, "stream": False}).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            f"{config.OLLAMA_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_CONNECT_TIMEOUT_SEC) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"{name} の解放に失敗しました: {exc}") from exc
        unloaded.append(name)
    return unloaded


def gpu_used_mib() -> int | None:
    """nvidia-smi から使用中 VRAM (MiB) を取得する。失敗したら None を返す。"""

    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    output = completed.stdout.strip()
    if not output:
        return None
    first_line = output.splitlines()[0].strip()
    try:
        return int(first_line)
    except ValueError:
        return None


def wait_until_free(threshold_mib: int, timeout_seconds: float) -> bool:
    """VRAM 使用量が threshold_mib 未満になるまで 1 秒ごとに待つ。成否を bool で返す。

    gpu_used_mib() が None（nvidia-smi 失敗）を返し続けた場合は、
    threshold 未満とは判断せず、タイムアウトまで待って False を返す。
    """

    deadline = time.monotonic() + timeout_seconds
    while True:
        used = gpu_used_mib()
        if used is not None and used < threshold_mib:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)
