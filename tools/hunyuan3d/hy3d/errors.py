"""生成・書き出しの失敗を診断し、疑わしいパラメータを言葉にする。

torch / gradio は import しない（`tools/hunyuan3d/.venv/bin/python -m pytest` を
torch なしでも走らせるため。`hy3d.config` の import は可）。

推測でパラメータのせいにしない。判定できない例外（`unknown`）は候補を挙げず、
元の例外をそのまま見せる。効きの順序（cuda_oom / host_oom とも）は実測に基づく。
根拠は tools/hunyuan3d/README.md と knowledge/10-silver/areas/hunyuan3d.md、
2026-09-24 の追加検証（Number of Chunks・Target Face Number）による。
"""

from __future__ import annotations

import html as _html
from typing import Any

# ---------------------------------------------------------------------------
# 失敗の分類
# ---------------------------------------------------------------------------

CUDA_OOM_MARKERS: tuple[str, ...] = (
    "CUDA out of memory",
    "OutOfMemoryError",
    "CUDA error: out of memory",
)

HOST_OOM_MARKERS: tuple[str, ...] = (
    "MemoryError",
    "Cannot allocate memory",
    "DefaultCPUAllocator: not enough memory",
    "bad_alloc",
)


def classify_failure(error_text: str) -> str:
    """例外の文面（traceback を含む全文）から失敗の種類を推定する。

    "cuda_oom" / "host_oom" / "unknown" のいずれかを返す。
    どちらのマーカーにも一致しなければ推測せず "unknown" にする。
    """

    for marker in CUDA_OOM_MARKERS:
        if marker in error_text:
            return "cuda_oom"
    for marker in HOST_OOM_MARKERS:
        if marker in error_text:
            return "host_oom"
    return "unknown"


# ---------------------------------------------------------------------------
# 候補の生成（実測に基づく効きの順序）
# ---------------------------------------------------------------------------

_OCTREE_DEFAULT = 256
_NUM_CHUNKS_SUGGESTED = 4000
_INFERENCE_STEPS_SUGGESTED = 10
_TARGET_FACE_NUMBER_SUGGESTED = 10000

_TEXTURE_WHY = (
    "実測でテクスチャ生成は形状のみより大幅に重い（形状のみ 21.7 秒・待機時 VRAM 5,365 MiB に対し、"
    "テクスチャ込みは 136.2 秒・生成ピーク VRAM 11,487 MiB）。Gen Shape（形状のみ）に切り替えるとピークが大きく下がる。"
)


def _texture_suspect_cuda() -> dict[str, Any]:
    return {
        "label": "Gen Textured Shape（テクスチャ生成）",
        "current": "有効（テクスチャまで生成）",
        "suggested": "無効にして Gen Shape（形状のみ）で試す",
        "why": _TEXTURE_WHY,
    }


def _texture_suspect_host() -> dict[str, Any]:
    return {
        "label": "Gen Textured Shape（テクスチャ生成）",
        "current": "有効（テクスチャまで生成）",
        "suggested": "無効にして Gen Shape（形状のみ）で試す",
        "why": "テクスチャ生成は追加のパイプライン（delight・paint）を読み込むため、RAM 使用量も増える。",
    }


def _octree_suspect(settings: dict[str, Any]) -> dict[str, Any] | None:
    current = settings.get("Octree Resolution")
    if current is None or current <= _OCTREE_DEFAULT:
        return None
    return {
        "label": "Octree Resolution（八分木の解像度）",
        "current": current,
        "suggested": _OCTREE_DEFAULT,
        "why": "解像度を上げるほど VRAM と生成時間が増える。既定の 256 へ戻す。",
    }


def _num_chunks_suspect(settings: dict[str, Any]) -> dict[str, Any] | None:
    current = settings.get("Number of Chunks")
    if current is None or current <= _NUM_CHUNKS_SUGGESTED:
        return None
    return {
        "label": "Number of Chunks（分割数）",
        "current": current,
        "suggested": _NUM_CHUNKS_SUGGESTED,
        # 実測: 大きいほど一度に処理する量が増えて VRAM を使う。OOM のときは上げるのではなく下げる。
        "why": "大きいほど一度に処理する量が増えて VRAM を使う（実測）。OOM のときは下げる方向が正しい。",
    }


def _inference_steps_suspect(settings: dict[str, Any]) -> dict[str, Any] | None:
    current = settings.get("Inference Steps")
    if current is None or current <= _INFERENCE_STEPS_SUGGESTED:
        return None
    return {
        "label": "Inference Steps（推論ステップ数）",
        "current": current,
        "suggested": _INFERENCE_STEPS_SUGGESTED,
        "why": "VRAM への効きは小さいが、下げれば生成時間が減り再試行しやすい。",
    }


def _target_face_number_suspect(settings: dict[str, Any]) -> dict[str, Any] | None:
    current = settings.get("Target Face Number")
    if current is None or current <= _TARGET_FACE_NUMBER_SUGGESTED:
        return None
    return {
        "label": "Target Face Number（書き出し時の目標面数）",
        "current": current,
        "suggested": _TARGET_FACE_NUMBER_SUGGESTED,
        "why": "書き出し時に減らす目標面数が大きいほど、面数削減の処理中に使う RAM が増える。",
    }


_CUDA_OOM_NOTE = (
    "Qwen が VRAM に載っていると足りなくなりますが、当て物 0001 で生成の直前に自動で降ろしています。"
    "入口ページで Pixal3D が動いていないかも確認してください（Hunyuan3D と Pixal3D は排他）。"
)

_HOST_OOM_NOTE = (
    "入口ページでこのサービスの MemoryHigh / MemoryMax を上げる手もあります"
    "（RAM 62.5 GiB、推奨上限 48 GiB、既定 44/48）。"
)

_UNKNOWN_HEADLINE = "設定が原因とは限りません"
_UNKNOWN_NOTE_TEMPLATE = "自動判定できませんでした。下に表示する元の例外を確認してください。\n\n例外の先頭 300 文字: {preview}"


def diagnose(failure_kind: str, settings: dict[str, Any], textured: bool) -> dict[str, Any]:
    """failure_kind と設定値から、疑わしいパラメータを効きの大きい順に並べる。

    戻り値: {"headline": str, "suspects": [{"label", "current", "suggested", "why"}, ...], "note": str}
    いまの値がすでに提案先と同じか、それ以下（＝これ以上下げる提案ができない）ものは suspects に入れない。
    """

    if failure_kind == "cuda_oom":
        suspects: list[dict[str, Any]] = []
        if textured:
            suspects.append(_texture_suspect_cuda())
        for candidate in (
            _octree_suspect(settings),
            _num_chunks_suspect(settings),
            _inference_steps_suspect(settings),
        ):
            if candidate is not None:
                suspects.append(candidate)

        note = _CUDA_OOM_NOTE
        if not suspects:
            note = "主要な設定はすでに最小に近く、これ以上下げても効果は薄いかもしれません。" + note

        return {
            "headline": "VRAM 不足（CUDA out of memory）の可能性があります",
            "suspects": suspects,
            "note": note,
        }

    if failure_kind == "host_oom":
        suspects = []
        for candidate in (
            _target_face_number_suspect(settings),
            _octree_suspect(settings),
        ):
            if candidate is not None:
                suspects.append(candidate)
        if textured:
            suspects.append(_texture_suspect_host())

        note = _HOST_OOM_NOTE
        if not suspects:
            note = "主要な設定はすでに最小に近く、これ以上下げても効果は薄いかもしれません。" + note

        return {
            "headline": "システムメモリ（RAM）不足の可能性があります",
            "suspects": suspects,
            "note": note,
        }

    # unknown: 推測でパラメータのせいにしない。
    return {
        "headline": _UNKNOWN_HEADLINE,
        "suspects": [],
        "note": "自動判定できませんでした。下に表示する元の例外を確認してください。",
    }


# ---------------------------------------------------------------------------
# 画面に出す文章の組み立て
# ---------------------------------------------------------------------------

_SETTINGS_ORDER: tuple[str, ...] = (
    "Inference Steps",
    "Octree Resolution",
    "Guidance Scale",
    "Number of Chunks",
    "Seed",
    "Randomize seed",
    "Remove Background",
    "File Type",
    "Simplify Mesh",
    "Target Face Number",
)


def _format_settings_list(settings: dict[str, Any]) -> str:
    ordered_keys = [key for key in _SETTINGS_ORDER if key in settings]
    remaining_keys = [key for key in settings if key not in _SETTINGS_ORDER]
    items = []
    for key in ordered_keys + remaining_keys:
        label = _html.escape(str(key))
        value = _html.escape(str(settings[key]))
        items.append(f"<li>{label}: {value}</li>")
    if not items:
        return "<p>（設定値を受け取れませんでした）</p>"
    return "<ul>" + "".join(items) + "</ul>"


def _format_suspects_list(suspects: list[dict[str, Any]]) -> str:
    if not suspects:
        return "<p>有力な候補は見つかりませんでした。</p>"
    items = []
    for suspect in suspects:
        label = _html.escape(str(suspect["label"]))
        current = _html.escape(str(suspect["current"]))
        suggested = _html.escape(str(suspect["suggested"]))
        why = _html.escape(str(suspect["why"]))
        items.append(
            f"<li><b>{label}</b>: いま {current} → {suggested} にする（{why}）</li>"
        )
    return "<ol>" + "".join(items) + "</ol>"


def format_failure_markdown(diagnosis: dict[str, Any], settings: dict[str, Any], error_text: str) -> str:
    """診断結果を、画面（gr.HTML）にそのまま出せる文字列に組み立てる。

    見出し・その生成で使った設定一覧・原因の候補（効きの大きい順）・案内文の後に、
    元の例外の全文を <details> で折りたたんで置く（例外の文字列は html.escape 済み）。
    """

    headline = _html.escape(str(diagnosis.get("headline", "")))
    note = _html.escape(str(diagnosis.get("note", "")))
    suspects = diagnosis.get("suspects") or []

    preview = error_text[:300]
    if len(error_text) > 300:
        preview += "…"
    preview_html = _html.escape(preview)

    escaped_error_text = _html.escape(error_text)

    parts = [
        f"<h3>{headline}</h3>",
        f"<p>{note}</p>",
        f"<p><b>エラー概要（先頭 300 文字）:</b> {preview_html}</p>",
        "<p><b>その生成で使った設定:</b></p>",
        _format_settings_list(settings),
        "<p><b>疑わしいパラメータ（効きの大きい順）:</b></p>",
        _format_suspects_list(suspects),
        "<details><summary>元の例外の全文</summary>"
        f"<pre style=\"white-space: pre-wrap;\">{escaped_error_text}</pre></details>",
    ]
    return "\n".join(parts)
