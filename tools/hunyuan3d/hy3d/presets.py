"""Gradio 画面の設定（パラメータ）を名前を付けて保存・読み込みするための純粋ロジック。

torch も gradio も import しない。`hy3d.config` の import のみ許可する
（`tools/hunyuan3d/.venv/bin/python -m pytest` を torch なしで走らせるため、
また素の `/usr/bin/python3` からも import できるようにするため）。

保存先は `tools/hunyuan3d/presets/`（`hy3d.config.TOOL_DIR` から組み立てる）。
ファイル名は利用者が入力した設定名をそのまま使うため、`validate_preset_name` /
`preset_path` でパス外（`presets/` の外）への書き込み・読み出しを防いでいる。

保存する JSON の形式:
    {
        "format": 1,
        "tool": "hunyuan3d",
        "saved_at": "<ISO8601>",
        "settings": {...}
    }

この保存・読み込みを画面へ出すのは、上流への当て物 0005（save-load-presets）。当て物は
Tencent Hunyuan 3D 2.0 Community License の地域制限のため公開版に含まない。当て物が無い環境では
どこからも import されない。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hy3d import config

# ---------------------------------------------------------------------------
# 保存先
# ---------------------------------------------------------------------------

PRESETS_DIR = config.TOOL_DIR / "presets"

FORMAT_VERSION = 1
TOOL_NAME = "hunyuan3d"

# ---------------------------------------------------------------------------
# 画面の設定の既定値。vendor/Hunyuan3D-2/gradio_app.py の build_app() 内の
# 各ウィジェットの value= と必ず一致させること（ズレは
# tests/test_units.py の test_default_settings_match_gradio_app が検出する）。
# ---------------------------------------------------------------------------

# gradio_app.py の MAX_SEED = int(1e7) と一致させる（Seed スライダーの上限）。
_MAX_SEED = int(1e7)

DEFAULT_SETTINGS: dict[str, Any] = {
    # Inference Steps: gradio_app.py は `5 if 'turbo' in args.subfolder else 30` で既定値を
    # 切り替えるが、このサーバーの起動引数は config.SHAPE_SUBFOLDER = "hunyuan3d-dit-v2-mv"
    # （'turbo' を含まない）で固定のため、実際に動く既定値は常に 30 になる。
    "num_steps": 30,
    "cfg_scale": 5.0,
    "seed": 1234,
    "randomize_seed": True,
    "octree_resolution": 256,
    "check_box_rembg": True,
    "num_chunks": 8000,
    "file_type": "glb",
    "reduce_face": False,
    "export_texture": False,
    "target_face_num": 10000,
}

# 読み込み時の型・範囲検査に使う。gradio_app.py 側のスライダーの minimum/maximum・
# Dropdown の choices と一致させる。
SETTING_RANGES: dict[str, dict[str, Any]] = {
    "num_steps": {"type": "int", "min": 1, "max": 100},
    "cfg_scale": {"type": "float", "min": 0.0, "max": 100.0},
    "seed": {"type": "int", "min": 0, "max": _MAX_SEED},
    "randomize_seed": {"type": "bool"},
    "octree_resolution": {"type": "int", "min": 16, "max": 512},
    "check_box_rembg": {"type": "bool"},
    "num_chunks": {"type": "int", "min": 1000, "max": 5000000},
    "file_type": {"type": "choice", "choices": ("glb", "obj", "ply", "stl")},
    "reduce_face": {"type": "bool"},
    "export_texture": {"type": "bool"},
    "target_face_num": {"type": "int", "min": 100, "max": 1000000},
}


# ---------------------------------------------------------------------------
# 設定名の検査
# ---------------------------------------------------------------------------

# 使ってよい文字だけを許可する（ホワイトリスト方式）。
# - 日本語: ひらがな（぀-ゟ）、カタカナ・長音「ー」（゠-ヿ）、漢字（一-鿿）
# - 英数字、半角空白、_ - ( )
# これ以外（/ \ 等のパス区切り、制御文字、その他の記号）はファイル名としてそのまま使うと
# 保存先が presets/ の外を指す・OS 上不正なファイル名になるおそれがあるため、個別のメッセージで弾く。
# Windows / SMB がファイル名に使えない文字。ここだけを弾き、それ以外（全角の括弧や
# 「」、全角スペースなど）は自由に使えるようにする。
_FORBIDDEN_CHARS = '/\\:*?"<>|'
_FORBIDDEN_CHARS_TEXT = ' '.join(_FORBIDDEN_CHARS)

_MAX_NAME_LENGTH = 64


def validate_preset_name(name: str) -> str | None:
    """設定名が保存に使えるか確かめる。問題が無ければ None、あれば日本語の理由を返す。

    ファイルシステムには触れない純粋関数。
    """

    if name is None or name == "":
        return "設定名を入力してください（空にはできません）"
    if name.strip() == "":
        return "空白だけの名前は使えません"
    if len(name) > _MAX_NAME_LENGTH:
        return f"設定名は{_MAX_NAME_LENGTH}文字以内にしてください（現在{len(name)}文字）"
    # パス外（presets/ の外）への書き込み・読み出しを防ぐため、パス区切り文字・
    # 親ディレクトリ参照・隠しファイルになる先頭 "." は個別に弾く。
    if "/" in name or "\\" in name:
        return "「/」と「\\」は使えません（ファイルパスの区切り文字と解釈されるため）"
    if ".." in name:
        return "「..」は使えません（親ディレクトリを指す記法のため、保存先の外を指すおそれがあります）"
    if name.startswith("."):
        return "先頭が「.」の名前は使えません（隠しファイルとして扱われるため）"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return "改行やタブなどの制御文字は使えません"
    # 使える文字を絞り込むのではなく、危ない文字だけを弾く。全角の括弧やスペース、「」・
    # なども普通に使いたいため（許可制にすると「高精細（試し）」のような自然な名前が通らない）。
    # 弾く文字は Windows / SMB で使えないものに合わせる。presets/ を Windows や SMB 共有（CIFS）に
    # 置いたり git で別の PC へ持って行ったりしても、Windows で無効な名前で困らないようにするため。
    invalid_chars = sorted({ch for ch in name if ch in _FORBIDDEN_CHARS})
    if invalid_chars:
        return (
            "次の文字は使えません: " + " ".join(invalid_chars)
            + f"（{_FORBIDDEN_CHARS_TEXT} は Windows と SMB でファイル名に使えないため）"
        )
    if name.endswith(" ") or name.endswith("."):
        return "末尾の半角空白と「.」は使えません（Windows がファイル名から取り除いてしまうため）"
    return None


def preset_path(name: str) -> Path:
    """設定ファイルのパス（presets/<name>.json）を返す。

    `validate_preset_name` に通ったうえで、解決済みパスの親が presets/ 直下であることを
    確かめる（通っていれば理屈上ここで弾かれることは無いが、保存先を presets/ の外に
    出さないための最終防衛線として置く）。
    """

    reason = validate_preset_name(name)
    if reason is not None:
        raise ValueError(reason)

    presets_root = PRESETS_DIR.resolve()
    candidate = (PRESETS_DIR / f"{name}.json").resolve()
    if candidate.parent != presets_root:
        raise ValueError("設定ファイルの保存先が presets ディレクトリの外を指しています")
    return candidate


# ---------------------------------------------------------------------------
# 保存・読み込み・一覧・削除
# ---------------------------------------------------------------------------


def list_presets() -> list[str]:
    """保存済みの設定名を並べ替えて返す（無ければ空リスト）。"""

    if not PRESETS_DIR.exists():
        return []
    names = [path.stem for path in PRESETS_DIR.glob("*.json") if path.is_file()]
    return sorted(names)


def save_preset(name: str, settings: dict[str, Any]) -> Path:
    """settings のうち DEFAULT_SETTINGS のキーだけを presets/<name>.json に保存する。"""

    path = preset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)

    filtered_settings = {key: settings[key] for key in DEFAULT_SETTINGS if key in settings}
    payload = {
        "format": FORMAT_VERSION,
        "tool": TOOL_NAME,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "settings": filtered_settings,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _is_valid_value(key: str, value: Any) -> bool:
    spec = SETTING_RANGES.get(key)
    if spec is None:
        return False
    kind = spec["type"]
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        return spec["min"] <= value <= spec["max"]
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return spec["min"] <= value <= spec["max"]
    if kind == "choice":
        return isinstance(value, str) and value in spec["choices"]
    return False


def load_preset(name: str) -> dict[str, Any]:
    """presets/<name>.json を読み込む。

    DEFAULT_SETTINGS を土台に、ファイルにあるキーだけを上書きする（知らないキーは無視、
    足りないキーは既定値のまま）。型・範囲が SETTING_RANGES から外れている値は既定値に
    落とし、落とした項目名を "ignored" に載せる。

    戻り値: {"settings": {...}, "ignored": [キー名, ...]}
    ファイルが無ければ FileNotFoundError、JSON が壊れていれば日本語メッセージの ValueError。
    """

    path = preset_path(name)
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {name}")

    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"設定ファイルの形式が壊れています（JSON として読めません）: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("設定ファイルの形式が不正です（JSON オブジェクトではありません）")

    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict):
        raw_settings = {}

    settings = dict(DEFAULT_SETTINGS)
    ignored: list[str] = []
    for key in DEFAULT_SETTINGS:
        if key not in raw_settings:
            continue
        value = raw_settings[key]
        if _is_valid_value(key, value):
            settings[key] = value
        else:
            ignored.append(key)

    return {"settings": settings, "ignored": ignored}


def delete_preset(name: str) -> bool:
    """presets/<name>.json を削除する。無ければ False、削除できれば True。"""

    path = preset_path(name)
    if not path.exists():
        return False
    path.unlink()
    return True
