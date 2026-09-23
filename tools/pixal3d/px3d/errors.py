"""生成失敗時に「どの設定を下げればよいか」を診断する純粋関数群。

torch / gradio / PIL / numpy のいずれも import しない（px3d/config.py・px3d/framing.py と
同じ設計方針。`uvx --with pytest` の一時環境で torch なしで試験が走ることを前提にしている）。
`px3d.config` と `px3d.framing` の import は可（どちらも重い依存を持ち込まない）。

## 使い方（px3d/ui.py の `_generate` から）

    except Exception as exc:
        error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        failure_kind = classify_failure(error_text)
        diagnosis = diagnose(failure_kind, full_settings)
        markdown = format_failure_markdown(diagnosis, error_text)

## 効きの順序の根拠（実測。数値の出典）

- 低 VRAM モード・解像度: `px3d/help_texts.py` の `resolution_input` / `低VRAMモード` の説明と同じ
  実測値（低 VRAM モードを Off にすると解像度 1536 で VRAM ピーク 23.12 GiB、1024 でも 23.32 GiB
  まで伸びて CUDA out of memory になった。A30 の VRAM は 24576 MiB。低 VRAM モード On・解像度
  1024・4 枚入力なら VRAM ピークは 16.8〜17.3 GiB に収まる）。
- RAM の安全弁（MemoryHigh / MemoryMax）: `tools/pixal3d/systemd/pixal3d.service.example` に
  書いてある実測とコメントと同じ（低 VRAM モードは重みを CPU 側へ retreat させる分だけ RAM を
  強く使う。2026-09-24 時点の値は MemoryHigh=44G / MemoryMax=48G、RAM 62.5 GiB の機体向け）。
- 物体の大きさ（fill）と生成空間の関係: `px3d/help_texts.py` の `物体の大きさ` の説明と同じ
  （画面の外周約 9% は生成空間の外。fill を下げると外接矩形が画面の外周に近づきにくくなる）。

## `diagnose()` の返り値に含む `"kind"` について

返り値には `"headline"` / `"suspects"` / `"note"` に加えて `"kind"`（= 引数の `failure_kind`
をそのまま）も入れている。`format_failure_markdown` が「元の例外をどう見せるか」を
`failure_kind` ごとに変えるための内部の受け渡し用（診断結果を作った本人が一番よく知っている
ため、ここに載せておくのが素直）。呼び出し側は無視して構わない。
"""

from __future__ import annotations

from . import framing


# ---------------------------------------------------------------------------
# classify_failure
# ---------------------------------------------------------------------------

_CUDA_OOM_MARKERS = (
    "CUDA out of memory",
    "OutOfMemoryError",
    "CUDA error: out of memory",
)
_HOST_OOM_MARKERS = (
    "MemoryError",
    "Cannot allocate memory",
    "DefaultCPUAllocator: not enough memory",
    "bad_alloc",
)
_FRAMING_MARKERS = (
    "外接矩形",
    "fill",
    "canvas_size",
)


def classify_failure(error_text: str) -> str:
    """例外の文字列から失敗の種類を返す純粋関数。

    返り値は次のいずれか:
        "cuda_oom"  … CUDA out of memory（`torch.OutOfMemoryError` / `CUDA error: out of memory` を含む）
        "host_oom"  … ホスト側（RAM）のメモリ不足（`MemoryError` / `Cannot allocate memory` /
                      `DefaultCPUAllocator: not enough memory` / `bad_alloc` を含む）
        "framing"   … `px3d.framing.compute_uniform_layout` が投げる ValueError
                      （メッセージに「外接矩形」「fill」「canvas_size」のいずれかを含む）
        "unknown"   … 上記のどれにも一致しない

    判定は上から順（cuda_oom → host_oom → framing）に文字列の部分一致で行う。
    """

    if any(marker in error_text for marker in _CUDA_OOM_MARKERS):
        return "cuda_oom"
    if any(marker in error_text for marker in _HOST_OOM_MARKERS):
        return "host_oom"
    if any(marker in error_text for marker in _FRAMING_MARKERS):
        return "framing"
    return "unknown"


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------


def _suspect(label: str, current, suggested, why: str) -> dict:
    return {"label": label, "current": current, "suggested": suggested, "why": why}


def _tiered_suggestion(current, tiers: tuple):
    """`tiers`（降順の候補値）のうち `current` より小さい最初の値を返す。無ければ None。

    None は「もうこのパラメータでは下げようがない（既に最小）」を意味する。
    """

    for tier in tiers:
        if tier < current:
            return tier
    return None


_ALL_MINIMUM_NOTE = "設定はすべて最小です。入力画像の枚数を減らすか、Hunyuan3D を試してください。"

_HOST_OOM_MEMORY_NOTE = (
    "入口ページ（tools/portal）でこのサービスの MemoryHigh / MemoryMax を上げる手もある"
    "（2026-09-24 時点で MemoryHigh=44G / MemoryMax=48G。RAM 62.5 GiB の機体に合わせた値。"
    "tools/pixal3d/systemd/pixal3d.service.example 参照）。"
)


def _cuda_oom_suspects(settings: dict) -> list[dict]:
    suspects: list[dict] = []

    if settings.get("low_vram") is False:
        suspects.append(
            _suspect(
                "低 VRAM モード",
                "無効（Off）",
                "有効（On）",
                "低 VRAM モードを Off にすると、解像度 1536 で VRAM ピーク 23.12 GiB、1024 でも "
                "23.32 GiB まで伸びて CUDA out of memory になった実測がある（A30 の VRAM は "
                "24576 MiB）。入口ページ（tools/portal）のスイッチで On にすれば、解像度 1024・"
                "4 枚入力で VRAM ピークは 16.8〜17.3 GiB に収まる。",
            )
        )

    resolution = int(settings.get("resolution", framing.DEFAULT_SETTINGS["resolution"]))
    suggested = _tiered_suggestion(resolution, (1024,))
    if suggested is not None:
        suspects.append(
            _suspect(
                "解像度",
                resolution,
                suggested,
                "解像度が下がるとパイプラインが 1024_cascade になり、扱う潜在表現・中間データが"
                "小さくなって VRAM 使用量が減る。",
            )
        )

    max_num_tokens = int(settings.get("max_num_tokens", framing.DEFAULT_SETTINGS["max_num_tokens"]))
    suggested = _tiered_suggestion(max_num_tokens, (32768, 16384))
    if suggested is not None:
        suspects.append(
            _suspect(
                "max_num_tokens",
                max_num_tokens,
                suggested,
                "高解像度段でパイプラインに渡す最大トークン数。小さくするほど VRAM 使用量が減る。",
            )
        )

    texture_size = int(settings.get("texture_size", framing.DEFAULT_SETTINGS["texture_size"]))
    suggested = _tiered_suggestion(texture_size, (2048, 1024))
    if suggested is not None:
        suspects.append(
            _suspect(
                "テクスチャ解像度",
                texture_size,
                suggested,
                "書き出し時に焼き込むテクスチャ画像の一辺。小さくすると焼き込み中の VRAM 使用量が減る。",
            )
        )

    decimation_target = int(
        settings.get("decimation_target", framing.DEFAULT_SETTINGS["decimation_target"])
    )
    suggested = _tiered_suggestion(decimation_target, (500000, 100000))
    if suggested is not None:
        suspects.append(
            _suspect(
                "面数の上限（decimation_target）",
                decimation_target,
                suggested,
                "書き出す GLB の目標頂点数。小さくすると decimation・remesh・テクスチャ焼き込みで"
                "扱う中間データが減る。",
            )
        )

    return suspects


def _host_oom_suspects(settings: dict) -> list[dict]:
    suspects: list[dict] = []

    texture_size = int(settings.get("texture_size", framing.DEFAULT_SETTINGS["texture_size"]))
    suggested = _tiered_suggestion(texture_size, (2048, 1024))
    if suggested is not None:
        suspects.append(
            _suspect(
                "テクスチャ解像度",
                texture_size,
                suggested,
                "テクスチャの焼き込み・書き出しはホスト側（RAM）でも画像バッファを確保する。"
                "小さくすると RAM 使用量が減る。",
            )
        )

    decimation_target = int(
        settings.get("decimation_target", framing.DEFAULT_SETTINGS["decimation_target"])
    )
    suggested = _tiered_suggestion(decimation_target, (500000, 100000))
    if suggested is not None:
        suspects.append(
            _suspect(
                "面数の上限（decimation_target）",
                decimation_target,
                suggested,
                "頂点数が多いほど、間引き（decimation）とリメッシュの途中で RAM 上に持つ中間データが"
                "大きくなる。小さくすると RAM 使用量が減る。",
            )
        )

    remesh = bool(settings.get("remesh", framing.DEFAULT_SETTINGS["remesh"]))
    if remesh:
        suspects.append(
            _suspect(
                "リメッシュ",
                "オン",
                "オフ",
                "リメッシュは三角形分割を作り直す追加処理で、ホスト側の中間データを余分に使う。"
                "オフにするとその分の RAM 使用が減る。",
            )
        )

    resolution = int(settings.get("resolution", framing.DEFAULT_SETTINGS["resolution"]))
    suggested = _tiered_suggestion(resolution, (1024,))
    if suggested is not None:
        suspects.append(
            _suspect(
                "解像度",
                resolution,
                suggested,
                "解像度が下がるとパイプラインが扱う中間データ全体が小さくなり、RAM 使用量も減る"
                "（VRAM ほどの効き目ではないが無関係ではない）。",
            )
        )

    return suspects


def _framing_suspects(settings: dict, bounds: dict | None) -> list[dict]:
    fill = float(settings.get("fill", framing.DEFAULT_SETTINGS["fill"]))
    suggested = round(max(0.60, fill - 0.1), 2)
    if suggested >= fill:
        return []

    why = (
        "fill が大きいほど、前処理で正方形キャンバスへ収めた物体の外接矩形が画面の外周"
        "（生成空間の外側、目安 9%）に近づく。fill を下げて余白を増やすと、外接矩形の計算や"
        "キャンバスへの収まりで失敗しにくくなる。"
    )
    if bounds:
        why += f" 実際に検出した外接矩形: {bounds}。"

    return [_suspect("物体の大きさ（fill）", fill, suggested, why)]


def _diagnose_cuda_oom(settings: dict) -> dict:
    suspects = _cuda_oom_suspects(settings)
    return {
        "headline": "CUDA out of memory（GPU の VRAM 不足）で失敗しました。",
        "suspects": suspects,
        "note": _ALL_MINIMUM_NOTE if not suspects else "",
        "kind": "cuda_oom",
    }


def _diagnose_host_oom(settings: dict) -> dict:
    suspects = _host_oom_suspects(settings)
    note = _HOST_OOM_MEMORY_NOTE
    if not suspects:
        note = _ALL_MINIMUM_NOTE + " " + _HOST_OOM_MEMORY_NOTE
    return {
        "headline": "ホスト側のメモリ不足（RAM）で失敗しました。",
        "suspects": suspects,
        "note": note,
        "kind": "host_oom",
    }


def _diagnose_framing(settings: dict, bounds: dict | None) -> dict:
    suspects = _framing_suspects(settings, bounds)
    note = "" if suspects else "物体の大きさ（fill）はすでに最小です。入力画像そのもの（背景除去の失敗など）を確認してください。"
    return {
        "headline": "前処理（4 視点を同じ縮尺の正方形キャンバスへ収める処理）で失敗しました。",
        "suspects": suspects,
        "note": note,
        "kind": "framing",
    }


def _diagnose_unknown() -> dict:
    return {
        "headline": "設定が原因とは限りません（不明なエラーです）。",
        "suspects": [],
        "note": "この失敗のパターンからは、どの設定が原因かを特定できませんでした。下の例外を確認してください。",
        "kind": "unknown",
    }


def diagnose(failure_kind: str, settings: dict, bounds: dict | None = None) -> dict:
    """失敗の種類と画面の設定値から、疑わしいパラメータを効きの大きい順に並べる。

    引数:
        failure_kind: `classify_failure` の返り値（"cuda_oom" / "host_oom" / "framing" / "unknown"）。
        settings: 画面の全設定に `low_vram`（bool）を加えた辞書。キーは px3d/ui.py の
            `_generate` の引数名と同じ（`resolution` / `fill` / `max_num_tokens` /
            `decimation_target` / `texture_size` / `remesh` / `low_vram` など）。
            無いキーは `px3d.framing.DEFAULT_SETTINGS` の値を仮定する。
        bounds: 予約引数。`framing` のとき、呼び出し側が実際に検出した外接矩形
            （視点名 → `(left, top, right, bottom)`）などの追加情報を持っていれば渡せる
            （無くても動作する。px3d/ui.py の現在の呼び出しでは渡していない — 失敗を
            捕まえる `_generate` の except 節から `_preprocess_views` 内部の bboxes には
            届かないため）。

    返り値: `{"headline": str, "suspects": [{"label", "current", "suggested", "why"}, ...],
    "note": str, "kind": str}`。`suspects` は効きの大きい順。いまの値が既に最小の
    パラメータは含めない。全部が最小なら `suspects` は空になり、`note` にその旨を書く。
    """

    if failure_kind == "cuda_oom":
        return _diagnose_cuda_oom(settings)
    if failure_kind == "host_oom":
        return _diagnose_host_oom(settings)
    if failure_kind == "framing":
        return _diagnose_framing(settings, bounds)
    return _diagnose_unknown()


# ---------------------------------------------------------------------------
# format_failure_markdown
# ---------------------------------------------------------------------------


def format_failure_markdown(diagnosis: dict, error_text: str) -> str:
    """`diagnose()` の返り値と元の例外テキストから、画面に出す Markdown を組み立てる。

    見出し → 疑わしい設定の箇条書き（ラベル・いまの値・下げ先・理由）→ note → 元の例外
    （`framing` / `unknown` のときは本文にも短く見せる。それ以外も含め、常に折りたたみで
    全文を添える）。
    """

    lines = ["## 生成に失敗しました", "", f"**{diagnosis['headline']}**"]

    suspects = diagnosis.get("suspects") or []
    if suspects:
        lines += ["", "### 疑わしい設定（効きが大きい順）", ""]
        for suspect in suspects:
            lines.append(
                f"- **{suspect['label']}**: いま {suspect['current']} → "
                f"{suspect['suggested']} に下げる（{suspect['why']}）"
            )

    note = diagnosis.get("note") or ""
    if note:
        lines += ["", note]

    kind = diagnosis.get("kind")
    if kind == "framing":
        lines += ["", f"元の例外: {error_text}"]
    elif kind == "unknown":
        lines += ["", f"例外の先頭 300 文字: {error_text[:300]}"]

    lines += [
        "",
        "<details>",
        "<summary>元の例外（全文）</summary>",
        "",
        "```",
        error_text,
        "```",
        "",
        "</details>",
    ]

    return "\n".join(lines)
