"""設定（画面のパラメータ一式）を名前を付けて JSON に保存し、あとから読み込むための純粋な関数群。

torch / gradio / PIL / numpy はいずれも import しない（px3d/config.py・px3d/framing.py と
同じ設計方針。`uvx --with pytest` の一時環境で torch なしで試験が走ることを前提にしている）。
`px3d.config`（保存先ディレクトリ）と `px3d.framing`（既定値・検証の基準）の import のみ行う。

## 保存先

`config.TOOL_DIR / "presets"`（= `tools/pixal3d/presets/`）に `<名前>.json` として保存する。
実際のディレクトリは `_presets_dir()` を経由してその都度求める（定数として固定しないのは、
試験が monkeypatch でこの関数を差し替え、本物の `presets/` を汚さずに試験できるようにする
ため）。

## 名前の検証（`validate_preset_name`）

ファイル名としてそのまま使うため、パス外への書き込み（パストラバーサル）を防ぐ目的で
文字種を強く制限する。使えるのは日本語（ひらがな・カタカナ・漢字・長音「ー」）、英数字、
Windows / SMB で使えない文字だけを弾く。`/`・`\\`・`..`・先頭の `.`・制御文字は、それぞれ理由を
分けて具体的に NG を返す。`preset_path()` はこの検証に加えて、実際に組み立てたパスが
`presets/` の直下であることも確認する（検証をすり抜ける細工があった場合の二重の防御）。

## 読み込み時の値の検証（`load_preset`）

古い設定ファイルが新しいコードでも読めるよう、`framing.DEFAULT_SETTINGS` を土台にファイルの
値で上書きする。ファイルに無いキーは既定値のまま、ファイルにあって `DEFAULT_SETTINGS` に
無いキー（画面から消えた古い項目）は無視する。型・範囲が既定値の想定から外れている値は
既定値に落とし、落とした項目名を `"ignored"` に列挙して返す（画面側で「〇〇は範囲外だった
ので既定値にしました」と表示できるように）。

## 使い方（px3d/ui.py から）

    path = presets.save_preset(name, settings)          # 保存
    result = presets.load_preset(name)                  # 読み込み
    result["settings"]  # dict（framing.DEFAULT_SETTINGS のキーがすべて揃っている）
    result["ignored"]   # 既定値に落とした項目名のリスト
    presets.list_presets()                              # 一覧（五十音・アルファベット順）
    presets.delete_preset(name)                          # 削除（bool）
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import config, framing


def _presets_dir() -> Path:
    """保存先ディレクトリ。試験は monkeypatch でこの関数を差し替え、本物の presets/ を汚さない。"""

    return config.TOOL_DIR / "presets"


# ---------------------------------------------------------------------------
# 名前の検証
# ---------------------------------------------------------------------------

# 使える文字を絞り込むのではなく、危ない文字だけを弾く。全角の括弧やスペース、かぎ括弧なども
# 普通に使いたいため（許可制にすると「高精細（試し）」のような自然な名前が通らない）。
# 弾く文字は Windows / SMB で使えないものに合わせる。この presets/ は git で追跡し、
# リモートが CIFS マウント（/mnt/nas）なので、Windows で無効な名前だと push で困る。
_FORBIDDEN_NAME_CHARS = '/\\:*?"<>|'
_FORBIDDEN_NAME_CHARS_TEXT = " ".join(_FORBIDDEN_NAME_CHARS)

_MAX_NAME_LENGTH = 64


def validate_preset_name(name: str) -> str | None:
    """名前が保存に使えるかを確かめる純粋関数。問題が無ければ None、あれば日本語の理由を返す。

    ファイル名としてそのまま `<名前>.json` に使うため、パス外への書き込み（パストラバー
    サル）を防ぐ目的で文字種を強く制限している。`preset_path()` はここでの検証に加えて、
    実際に組み立てたパスが `presets/` の直下であることも確認する（二重の防御）。
    """

    if name is None or not str(name).strip():
        return "名前を入力してください（空白だけの名前は使えません）"

    if len(name) > _MAX_NAME_LENGTH:
        return f"名前は{_MAX_NAME_LENGTH}文字以内にしてください（いま{len(name)}文字です）"

    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
        return "制御文字は使えません"

    if "/" in name:
        return "名前に「/」は使えません（保存先ディレクトリの外を指すおそれがあるため）"

    if "\\" in name:
        return "名前に「\\」は使えません（保存先ディレクトリの外を指すおそれがあるため）"

    if ".." in name:
        return "名前に「..」は使えません（保存先ディレクトリの外を指すおそれがあるため）"

    if name.startswith("."):
        return "名前の先頭に「.」は使えません（隠しファイルになるおそれがあるため）"

    invalid_chars = sorted({ch for ch in name if ch in _FORBIDDEN_NAME_CHARS})
    if invalid_chars:
        return (
            "名前に使えない文字があります（" + " ".join(invalid_chars) + "）。"
            f"{_FORBIDDEN_NAME_CHARS_TEXT} は Windows と SMB でファイル名に使えません。"
        )

    if name.endswith(" ") or name.endswith("."):
        return "名前の末尾の半角空白と「.」は使えません（Windows がファイル名から取り除いてしまうため）"

    return None


def preset_path(name: str) -> Path:
    """`presets/<name>.json` を返す。

    まず `validate_preset_name` で検証し、問題があれば ValueError（理由付き）。
    さらに、実際に解決したパスが presets ディレクトリの直下でなければ ValueError にする
    （検証をすり抜ける細工があっても、保存先の外へは書けないようにする二重の防御）。
    """

    reason = validate_preset_name(name)
    if reason is not None:
        raise ValueError(reason)

    presets_dir = _presets_dir().resolve()
    candidate = (presets_dir / f"{name}.json").resolve()
    if candidate.parent != presets_dir:
        raise ValueError("不正な名前です（保存先ディレクトリの外を指しています）")
    return candidate


# ---------------------------------------------------------------------------
# 一覧・保存・読み込み・削除
# ---------------------------------------------------------------------------


def list_presets() -> list[str]:
    """保存済みプリセット名を五十音・アルファベット順で返す（ディレクトリが無ければ空リスト）。"""

    presets_dir = _presets_dir()
    if not presets_dir.is_dir():
        return []
    return sorted(path.stem for path in presets_dir.glob("*.json") if path.is_file())


def save_preset(name: str, settings: dict) -> Path:
    """`settings` のうち `framing.DEFAULT_SETTINGS` のキーだけを取り出して JSON で保存する。

    画面に無い値（`low_vram` など）や巨大な値は書かない。親ディレクトリが無ければ作る。
    同じ名前で保存し直すと上書きする。
    """

    path = preset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)

    filtered = {key: settings[key] for key in framing.DEFAULT_SETTINGS if key in settings}
    payload = {
        "format": 1,
        "tool": "pixal3d",
        "saved_at": datetime.now().astimezone().isoformat(),
        "settings": filtered,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# 値の妥当性検査。画面の部品の範囲・選択肢（px3d/ui.py の build_demo）と一致させること。
_CHOICE_SPECS: dict[str, tuple] = {
    "resolution": (1024, 1536),
    "background_removal": ("auto", "always"),
    "texture_size": (1024, 2048, 4096),
}
_INT_RANGE_SPECS: dict[str, tuple[int, int]] = {
    "seed": (0, 2147483647),
    "ss_steps": (1, 50),
    "shape_steps": (1, 50),
    "tex_steps": (1, 50),
    "max_num_tokens": (16384, 65536),
    "decimation_target": (100000, 1000000),
}
_FLOAT_RANGE_SPECS: dict[str, tuple[float, float]] = {
    "fill": (0.60, 0.95),
    "ss_guidance_strength": (1.0, 10.0),
    "ss_guidance_rescale": (0.0, 1.0),
    "ss_rescale_t": (1.0, 6.0),
    "shape_guidance_strength": (1.0, 10.0),
    "shape_guidance_rescale": (0.0, 1.0),
    "shape_rescale_t": (1.0, 6.0),
    "tex_guidance_strength": (1.0, 10.0),
    "tex_guidance_rescale": (0.0, 1.0),
    "tex_rescale_t": (1.0, 6.0),
}
_BOOL_KEYS = ("randomize_seed", "remesh")


def _is_valid_setting_value(key: str, value) -> bool:
    """`load_preset` が読んだ値を、画面の許容範囲・型に照らして検査する。

    bool は int のサブクラスなので、int/float 系の判定より先に弾く（True/False が
    誤って範囲チェックを通り抜けないように）。
    """

    if key in _BOOL_KEYS:
        return isinstance(value, bool)

    if key in _CHOICE_SPECS:
        if isinstance(value, bool):
            return False
        return value in _CHOICE_SPECS[key]

    if key in _INT_RANGE_SPECS:
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        low, high = _INT_RANGE_SPECS[key]
        return low <= value <= high

    if key in _FLOAT_RANGE_SPECS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        low, high = _FLOAT_RANGE_SPECS[key]
        return low <= float(value) <= high

    # framing.DEFAULT_SETTINGS に無いキーは load_preset 側で先に弾かれるため、ここには来ない。
    return True


def load_preset(name: str) -> dict:
    """保存済み設定を読み込む。

    返り値は `{"settings": {...}, "ignored": [キー名, ...]}`。`settings` は
    `framing.DEFAULT_SETTINGS` を土台に、ファイルにある妥当な値だけで上書きしたもの
    （足りないキーは既定値のまま、`DEFAULT_SETTINGS` に無いキーは無視する）。型・範囲が
    既定値の想定から外れている値は既定値に落とし、そのキー名を `ignored` に列挙する。

    ファイルが無ければ FileNotFoundError、JSON が壊れていれば ValueError（日本語の
    メッセージ）。
    """

    path = preset_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"プリセットが見つかりません: {name}")

    text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"プリセットファイルの JSON が壊れています（{name}）: {exc}") from exc

    stored = raw.get("settings") if isinstance(raw, dict) else None
    if not isinstance(stored, dict):
        raise ValueError(f"プリセットファイルの形式が不正です（settings がありません）: {name}")

    settings = dict(framing.DEFAULT_SETTINGS)
    ignored: list[str] = []
    for key, value in stored.items():
        if key not in framing.DEFAULT_SETTINGS:
            continue
        if _is_valid_setting_value(key, value):
            settings[key] = value
        else:
            ignored.append(key)

    return {"settings": settings, "ignored": ignored}


def delete_preset(name: str) -> bool:
    """保存済み設定を消す。見つからなければ False。"""

    path = preset_path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True
