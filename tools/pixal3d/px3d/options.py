"""低 VRAM モードの設定を読み取る純粋関数群。

ファイルシステムに触れるのは read_low_vram_setting() だけで、それ以外は文字列・辞書だけを
扱う純粋関数（引数だけから結果が決まり、ファイルにもネットワークにも触れない）。

入口ページ（tools/portal）が ``~/.config/pixal3d/pixal3d.env`` の ``PIXAL3D_LOW_VRAM`` を
書き換える想定なので、px3d 側は読むだけに徹する（config.LOW_VRAM_ENV_FILE / config.LOW_VRAM_ENV_VAR
は tools/portal と一致させること。変えない）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import config

_TRUE_VALUES = ("1", "true", "on", "yes")
_FALSE_VALUES = ("0", "false", "off", "no")


def low_vram_from_env(environ: Mapping[str, str]) -> bool:
    """環境変数 PIXAL3D_LOW_VRAM から低 VRAM モードの有効/無効を読む純粋関数。

    "1"/"true"/"on"/"yes"（大小文字を無視）を True、"0"/"false"/"off"/"no" を False とする。
    未設定や解釈できない値は既定値（config.LOW_VRAM_DEFAULT）にする。
    """

    raw = environ.get(config.LOW_VRAM_ENV_VAR)
    if raw is None:
        return config.LOW_VRAM_DEFAULT
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return config.LOW_VRAM_DEFAULT


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=VALUE` 形式のテキストを辞書にする純粋関数。`#` 行と空行は無視する。"""

    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip()
    return result


def read_low_vram_setting(env_file: Path | None = None) -> bool:
    """env ファイルを読んで、現在有効な低 VRAM モードを返す。

    ファイルが無い、または変数が書かれていなければ既定値（config.LOW_VRAM_DEFAULT）。
    """

    path = env_file if env_file is not None else config.LOW_VRAM_ENV_FILE
    if not path.is_file():
        return config.LOW_VRAM_DEFAULT
    values = parse_env_file(path.read_text(encoding="utf-8"))
    if config.LOW_VRAM_ENV_VAR not in values:
        return config.LOW_VRAM_DEFAULT
    return low_vram_from_env(values)
