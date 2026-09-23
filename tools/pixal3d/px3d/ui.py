"""px3d 自前の Gradio 画面。

vendor/Pixal3D は単一画像（inference.py）または既知カメラの複数画像（inference_mv.py）を
入力に取る。inference_mv.py はスクリプトとして書かれていて、パイプラインを毎回ロードし直す
（1 回で数分かかる）。ここではパイプラインをプロセス起動時に 1 度だけロードして常駐させ、
4 方位（正面・右・背面・左）の画像枠を持つ Gradio 画面から使えるようにする。

`px3d.cli` の `serve` から `python -m px3d.ui` として `os.execve` で起動される。
モジュール先頭で torch / gradio / pixal3d を import してよいのはここだけ
（px3d.cli / px3d.config / px3d.ollama / px3d.options / px3d.framing は素の python からも
import できる必要があるため、重い依存を持ち込まない設計にしてある）。

## 縦長写真の前処理（頭が平らになる・足が壊れる問題への対策）

`vendor/Pixal3D/inference_mv.py` の `to_cond_tensor` は正方形へ単純に引き伸ばすだけで、
`make_rembg` は切り抜きも縮小もしない設計になっている（詳細は `px3d/framing.py` の
docstring と README.md を参照）。そこで `_generate` は上流へ渡す前に、4 視点の画像を
`px3d.framing.compute_uniform_layout` が決めた同じ縮尺で正方形キャンバスへ収め、
上下左右に余白を付けてから保存する。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

import gradio as gr
import numpy as np
import torch
from PIL import Image

from . import config, errors, framing, help_texts, ollama, presets, rembg_override

# vendor/Pixal3D を PYTHONPATH に通した状態で起動される（px3d.cli.build_serve_env）。
# inference_mv は上流のトップレベルスクリプトで、import するだけで ATTN_BACKEND などの
# 環境変数セットアップ（os.environ.setdefault）が走る。
import inference_mv  # noqa: E402
import o_voxel  # noqa: E402

# プロセスに 1 個だけ常駐させるパイプライン。main() が起動時に 1 度だけ入れる。
_PIPELINE = None

# 低 VRAM モードの実際の値。画面の設定項目ではないため、main() が起動時に決めた値を
# _generate（失敗時の診断 px3d.errors.diagnose に渡す settings）から参照できるようにここへ入れる。
_LOW_VRAM = False

# 前処理で使う正方形キャンバスの一辺。framing.DEFAULT_SETTINGS の fill と組み合わせて使う。
_CANVAS_SIZE = 1024

# アルファ判定の閾値。vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py の
# preprocess_image と同じ（0.8 * 255）。
_ALPHA_BBOX_THRESHOLD = 0.8 * 255

_BG_REMOVAL_CHOICES = [
    ("自動（アルファが無いときだけ背景を除去）", "auto"),
    ("常に行う", "always"),
]
_TEXTURE_SIZE_CHOICES = [1024, 2048, 4096]

# setting_inputs（build_demo 内）・_generate の引数・framing.DEFAULT_SETTINGS の並びと
# 常に 1 対 1 で対応させる（build_demo 内のアサーションで一致を確認する）。設定の
# 保存・読み込み（px3d.presets）はこの並びを使って dict <-> 個々の部品の値を相互変換する。
_SETTING_KEYS = (
    "resolution",
    "seed",
    "randomize_seed",
    "fill",
    "background_removal",
    "ss_steps",
    "ss_guidance_strength",
    "ss_guidance_rescale",
    "ss_rescale_t",
    "shape_steps",
    "shape_guidance_strength",
    "shape_guidance_rescale",
    "shape_rescale_t",
    "tex_steps",
    "tex_guidance_strength",
    "tex_guidance_rescale",
    "tex_rescale_t",
    "max_num_tokens",
    "decimation_target",
    "texture_size",
    "remesh",
)

# inference_mv.py の run_inference() の GLB 書き出し直前の回転行列と同じ。
_EXPORT_ROTATION = np.array(
    [
        [-1, 0, 0, 0],
        [0, 0, -1, 0],
        [0, -1, 0, 0],
        [0, 0, 0, 1],
    ],
    dtype=np.float64,
)


# ---------------------------------------------------------------------------
# 説明表示（マウスオーバーの title / 専門用語クリックのダイアログ）
#
# Gradio 6.17.3（このリポジトリの .venv で確認済み）の Blocks.launch() は
# head / js / css を受け取れる（`.venv/bin/python -c "import gradio, inspect;
# print(inspect.signature(gradio.Blocks.launch))"` で確認）。gr.HTML の中に書いた
# <script> は実行されないため、スクリプトはここで組み立てて main() の
# demo.launch(js=..., css=...) へ渡す。
#
# js は「ページ読み込み時に 1 度だけ実行される」（Gradio の仕様）。Gradio 自身は
# 画面を後から描画・再描画する（Svelte のコンポーネントマウント）ため、
# 1 度実行しただけでは間に合わない要素がある。そこで実際の探索・title 設定・
# クリックのハンドラ登録は、ページ読み込み時に仕込む MutationObserver と
# document へのイベント委譲（document.addEventListener）に任せ、再描画のたびに
# 効くようにしてある。
# ---------------------------------------------------------------------------

_HELP_CSS = """
.px3d-term {
    cursor: help;
    border-bottom: 1px dotted var(--body-text-color-subdued, currentColor);
}
.px3d-term:hover {
    border-bottom-style: solid;
}
.px3d-term-list {
    margin: 2px 0 10px 0;
    font-size: var(--text-sm, 0.875rem);
    color: var(--body-text-color-subdued, inherit);
}
.px3d-glossary-dialog {
    max-width: 560px;
    width: 90vw;
    max-height: 80vh;
    overflow-y: auto;
    border: 1px solid var(--border-color-primary, #888);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, Canvas);
    color: var(--body-text-color, CanvasText);
    padding: 20px;
}
.px3d-glossary-dialog::backdrop {
    background: rgba(0, 0, 0, 0.5);
}
.px3d-glossary-dialog h3 {
    margin-top: 0;
}
.px3d-glossary-dialog p {
    white-space: pre-wrap;
    line-height: 1.7;
}
.px3d-glossary-close {
    margin-top: 12px;
    padding: 6px 16px;
    border-radius: var(--radius-sm, 4px);
    border: 1px solid var(--border-color-primary, #888);
    background: var(--background-fill-secondary, transparent);
    color: var(--body-text-color, CanvasText);
    cursor: pointer;
}
"""

# TOOLTIPS / GLOSSARY の JSON は _build_help_assets() が実行時に埋め込む
# （プレースホルダを文字列置換する。f-string にすると JS の波括弧をすべて
# エスケープする必要があり読みにくくなるため、あえて置換方式にしてある）。
_HELP_JS_TEMPLATE = """
(function () {
    var TOOLTIPS = __PX3D_TOOLTIPS_JSON__;
    var GLOSSARY = __PX3D_GLOSSARY_JSON__;

    function applyAllTooltips() {
        Object.keys(TOOLTIPS).forEach(function (elemId) {
            var el = document.getElementById(elemId);
            if (!el) return;
            var text = TOOLTIPS[elemId];
            el.title = text;
            el.querySelectorAll(
                "input, button, textarea, select, label, [role='slider']"
            ).forEach(function (child) {
                child.title = text;
            });
        });
    }

    var scheduled = false;
    function scheduleApplyTooltips() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(function () {
            scheduled = false;
            applyAllTooltips();
        });
    }

    function ensureGlossaryDialog() {
        var dialog = document.getElementById("px3d-glossary-dialog");
        if (dialog) return dialog;

        dialog = document.createElement("dialog");
        dialog.id = "px3d-glossary-dialog";
        dialog.className = "px3d-glossary-dialog";

        var heading = document.createElement("h3");
        heading.id = "px3d-glossary-title";
        var body = document.createElement("div");
        body.id = "px3d-glossary-body";
        var closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "px3d-glossary-close";
        closeButton.textContent = "閉じる";
        closeButton.addEventListener("click", function () {
            dialog.close();
        });

        dialog.appendChild(heading);
        dialog.appendChild(body);
        dialog.appendChild(closeButton);

        // 背景（::backdrop）クリックで閉じる。dialog 自身の矩形の外をクリック
        // したときだけ閉じる（矩形内の余白クリックで誤って閉じないように）。
        dialog.addEventListener("click", function (event) {
            var rect = dialog.getBoundingClientRect();
            var inside =
                event.clientX >= rect.left &&
                event.clientX <= rect.right &&
                event.clientY >= rect.top &&
                event.clientY <= rect.bottom;
            if (!inside) dialog.close();
        });

        document.body.appendChild(dialog);
        return dialog;
    }

    function openGlossary(term) {
        var entry = GLOSSARY[term];
        if (!entry) return;
        var dialog = ensureGlossaryDialog();
        dialog.querySelector("#px3d-glossary-title").textContent = entry.title;
        var bodyEl = dialog.querySelector("#px3d-glossary-body");
        bodyEl.textContent = "";
        String(entry.body)
            .split("\\n\\n")
            .forEach(function (paragraph) {
                var p = document.createElement("p");
                p.textContent = paragraph;
                bodyEl.appendChild(p);
            });
        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "open");
        }
    }

    // Esc での閉じるはブラウザ標準の <dialog> の挙動に任せる（cancel イベント）。

    // イベント委譲: Gradio が要素を作り直しても document への登録は効き続ける。
    document.addEventListener("click", function (event) {
        var target =
            event.target && event.target.closest
                ? event.target.closest(".px3d-term")
                : null;
        if (!target) return;
        event.preventDefault();
        openGlossary(target.getAttribute("data-term"));
    });

    var observer = new MutationObserver(scheduleApplyTooltips);
    observer.observe(document.body, { childList: true, subtree: true });
    scheduleApplyTooltips();
})();
"""


def _term_span(term: str, label: str | None = None) -> str:
    """専門用語のクリック可能な span を作る（`data-term` が help_texts.GLOSSARY の
    キーと一致する必要がある。一致は tests/test_units.py が検証する）。
    """

    return f'<span class="px3d-term" data-term="{term}">{label if label is not None else term}</span>'


def _terms_legend(terms: list[str]) -> str:
    """セクションの冒頭に置く「この欄の用語: [X] [Y] …」の行（gr.HTML 用）。"""

    chips = " ".join(f"[{_term_span(term)}]" for term in terms)
    return f'<div class="px3d-term-list">この欄の用語: {chips}</div>'


def _build_help_assets() -> tuple[str, str]:
    """マウスオーバー説明・専門用語ダイアログ用の (css, js) を組み立てる。"""

    js = _HELP_JS_TEMPLATE.replace(
        "__PX3D_TOOLTIPS_JSON__", json.dumps(help_texts.TOOLTIPS, ensure_ascii=False)
    ).replace("__PX3D_GLOSSARY_JSON__", help_texts.glossary_json())
    return _HELP_CSS, js


def _build_transforms_json(filled_azimuths: list[str]) -> dict:
    """入っている枠だけから transforms.json の中身を組み立てる。

    frame 0 は常に正面（config.VIEW_AZIMUTHS の先頭）。config.py の行列は
    vendor/Pixal3D/assets/mv_images/example/transforms.json と同じ値。
    """

    frames = []
    for azimuth in filled_azimuths:
        frames.append(
            {
                "file_path": f"{azimuth}.png",
                "name": azimuth,
                "transform_matrix": config.VIEW_TRANSFORM_MATRICES[azimuth],
            }
        )
    return {
        "camera_angle_x": config.DEFAULT_CAMERA_ANGLE_X,
        "mesh_scale": config.DEFAULT_MESH_SCALE,
        "frames": frames,
    }


def _unload_ollama_before_generate() -> None:
    """生成の直前に Ollama のモデルを降ろす。失敗しても生成は続ける。

    hunyuan3d の patches/0001-free-vram-before-generation.patch と同じ考え方
    （A30 は 24GiB しかなく、Qwen を載せたままだと生成の途中で CUDA out of memory になる）。
    """

    try:
        unloaded = ollama.unload_all()
    except RuntimeError as exc:
        print(f"警告: Ollama の解放に失敗しました（生成は続けます）: {exc}", file=sys.stderr)
        return
    if unloaded:
        print(f"Ollama から解放しました: {', '.join(unloaded)}")
        ollama.wait_until_free(4096, 30)


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    """RGBA 画像から alpha > 0.8*255 の画素の外接矩形を求める（見つからなければ None）。

    vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py の preprocess_image と同じ閾値。
    bbox は (left, top, right, bottom) で right/bottom は含まない終端（framing.py と同じ規約）。
    """

    alpha = np.array(image.getchannel("A"))
    ys, xs = np.where(alpha > _ALPHA_BBOX_THRESHOLD)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _ensure_rgba_with_mask(image: Image.Image, background_removal: str, rembg_fn) -> Image.Image:
    """アルファ付きならそのまま使い、無ければ（または常に行う設定なら）背景除去する。

    vendor/Pixal3D/inference_mv.py の load_rgba と同じ判定（アルファ付きで全部が 255 なら
    「マスク無し」扱い）に、画面の「背景除去: 常に行う」設定を上乗せする。
    """

    has_mask = False
    if image.mode == "RGBA":
        alpha = np.array(image.getchannel("A"))
        has_mask = not np.all(alpha == 255)
    if has_mask and background_removal != "always":
        return image.convert("RGBA")
    return rembg_fn(image).convert("RGBA")


def _reframe(image: Image.Image, layout: dict) -> Image.Image:
    """画像全体を layout の縮尺で拡縮し、透明な正方形キャンバスの中央へ貼る。

    layout は framing.compute_uniform_layout() が返す 1 視点ぶんの辞書
    （"scale" と "paste_offset" を使う。"resized_size" は物体の外接矩形についての値なので
    ここでは使わない。元画像全体のリサイズには実際の image.size に scale を掛ける）。
    """

    resized_w = max(1, round(image.width * layout["scale"]))
    resized_h = max(1, round(image.height * layout["scale"]))
    resized = image.convert("RGBA").resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (_CANVAS_SIZE, _CANVAS_SIZE), (0, 0, 0, 0))
    canvas.paste(resized, layout["paste_offset"], resized)
    return canvas


def _preprocess_views(
    images: dict[str, Image.Image | None],
    filled_azimuths: list[str],
    fill: float,
    background_removal: str,
    rembg_fn,
) -> tuple[dict[str, Image.Image], dict[str, dict]]:
    """4 視点（のうち入っているもの）を同じ縮尺・正方形・余白付きに揃える。

    物体が見つからない視点があれば、どの視点かを名前で示して gr.Error で止める。
    """

    masked = {
        azimuth: _ensure_rgba_with_mask(images[azimuth], background_removal, rembg_fn)
        for azimuth in filled_azimuths
    }

    bboxes: dict[str, tuple[int, int, int, int]] = {}
    for azimuth in filled_azimuths:
        bbox = _alpha_bbox(masked[azimuth])
        if bbox is None:
            raise gr.Error(
                f"{config.VIEW_LABELS[azimuth]} の画像から物体を検出できませんでした"
                "（背景除去後に不透明な画素がありません）。"
            )
        bboxes[azimuth] = bbox

    layout = framing.compute_uniform_layout(bboxes, canvas_size=_CANVAS_SIZE, fill=fill)

    reframed = {azimuth: _reframe(masked[azimuth], layout[azimuth]) for azimuth in filled_azimuths}
    return reframed, layout


def _format_used_settings(
    filled_azimuths: list[str],
    full_settings: dict,
    seed,
    sampler_params: dict | None,
) -> str:
    """「使った設定一覧」の箇条書き（Markdown）。成功時の状態表示・失敗時の診断の両方から呼ぶ。

    失敗時にも同じ内容を出すのは、あとから見て「どの値で失敗したのか」が分かるようにするため。
    `sampler_params`（`framing.build_sampler_params` の返り値）は、それを計算する前に失敗した
    場合は None を渡す（pipeline_type・各サンプラーの行を省く）。
    """

    lines = [
        f"- 使用した視点: {', '.join(config.VIEW_LABELS[a] for a in filled_azimuths)}",
        f"- 解像度: {full_settings['resolution']}"
        + (f"（pipeline_type={sampler_params['pipeline_type']}）" if sampler_params else ""),
        f"- シード: {int(seed)}",
        f"- 物体の大きさ（fill）: {full_settings['fill']}",
        f"- 背景除去: {full_settings['background_removal']}",
    ]
    if sampler_params:
        lines += [
            f"- 疎構造サンプラー: {sampler_params['sparse_structure_sampler_params']}",
            f"- 形状サンプラー: {sampler_params['shape_slat_sampler_params']}",
            f"- テクスチャサンプラー: {sampler_params['tex_slat_sampler_params']}",
        ]
    lines += [
        f"- max_num_tokens: {full_settings['max_num_tokens']}",
        f"- 書き出し: decimation_target={int(full_settings['decimation_target'])}, "
        f"texture_size={int(full_settings['texture_size'])}, remesh={bool(full_settings['remesh'])}",
        f"- 低 VRAM モード: {'有効' if full_settings['low_vram'] else '無効'}",
    ]
    return "\n".join(lines)


def _generate(
    front_image,
    right_image,
    back_image,
    left_image,
    resolution,
    seed,
    randomize_seed,
    fill,
    background_removal,
    ss_steps,
    ss_guidance_strength,
    ss_guidance_rescale,
    ss_rescale_t,
    shape_steps,
    shape_guidance_strength,
    shape_guidance_rescale,
    shape_rescale_t,
    tex_steps,
    tex_guidance_strength,
    tex_guidance_rescale,
    tex_rescale_t,
    max_num_tokens,
    decimation_target,
    texture_size,
    remesh,
):
    if front_image is None:
        # check_main_view は frame 0 を正面と仮定して警告を出すだけで止めはしないが、
        # ここでは画面側で先に弾く（正面が無いと出力の向きが上流の学習時と揃わない）。
        # これは利用者がすぐ直せる操作ミスなので、gr.Error（赤帯）のまま残す。
        raise gr.Error(
            "正面（0°）の画像は必須です。Pixal3D の check_main_view が frame 0 を"
            "正面前提で扱うため、正面が無いと出力の向きがずれます。"
        )

    if _PIPELINE is None:
        raise gr.Error("パイプラインが読み込まれていません（起動処理が失敗している可能性があります）")

    if randomize_seed:
        seed = random.randint(0, 2147483647)

    images = {"front": front_image, "right": right_image, "back": back_image, "left": left_image}
    filled_azimuths = [azimuth for azimuth in config.VIEW_AZIMUTHS if images[azimuth] is not None]

    # 失敗時の診断（px3d.errors.diagnose）に渡す設定一覧。画面の全項目 + low_vram
    # （画面には無く main() が起動時に決めた値。モジュール変数 _LOW_VRAM 経由で参照する）。
    full_settings = {
        "resolution": int(resolution),
        "fill": fill,
        "background_removal": background_removal,
        "ss_steps": ss_steps,
        "ss_guidance_strength": ss_guidance_strength,
        "ss_guidance_rescale": ss_guidance_rescale,
        "ss_rescale_t": ss_rescale_t,
        "shape_steps": shape_steps,
        "shape_guidance_strength": shape_guidance_strength,
        "shape_guidance_rescale": shape_guidance_rescale,
        "shape_rescale_t": shape_rescale_t,
        "tex_steps": tex_steps,
        "tex_guidance_strength": tex_guidance_strength,
        "tex_guidance_rescale": tex_guidance_rescale,
        "tex_rescale_t": tex_rescale_t,
        "max_num_tokens": max_num_tokens,
        "decimation_target": decimation_target,
        "texture_size": texture_size,
        "remesh": remesh,
        "low_vram": _LOW_VRAM,
    }

    # _preprocess_views が成功していれば入る（前処理後の画像。失敗時のプレビューにも使う）。
    reframed: dict | None = None
    # framing.build_sampler_params が成功していれば入る（失敗時の設定一覧にも使う）。
    sampler_params: dict | None = None

    try:
        _unload_ollama_before_generate()

        sampler_params = framing.build_sampler_params(full_settings)

        with tempfile.TemporaryDirectory(prefix="px3d-views-") as tmp_dir:
            tmp_path = Path(tmp_dir)

            reframed, layout = _preprocess_views(
                images, filled_azimuths, fill, background_removal, inference_mv.make_rembg(_PIPELINE)
            )
            for azimuth in filled_azimuths:
                reframed[azimuth].save(tmp_path / f"{azimuth}.png")
            transforms = _build_transforms_json(filled_azimuths)
            (tmp_path / "transforms.json").write_text(
                json.dumps(transforms, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 前処理済みの画像はすでにアルファ付きなので、load_views 内の load_rgba は
            # 背景除去をやり直さない（二重に背景除去しない）。
            views = inference_mv.load_views(
                str(tmp_path), rembg=inference_mv.make_rembg(_PIPELINE)
            )
            inference_mv.check_main_view(views)

            torch.manual_seed(int(seed))
            torch.cuda.reset_peak_memory_stats()
            start = time.monotonic()

            mesh_list, (_shape_slat, _tex_slat, res) = _PIPELINE.run_mv(
                views,
                seed=int(seed),
                sparse_structure_sampler_params=sampler_params["sparse_structure_sampler_params"],
                shape_slat_sampler_params=sampler_params["shape_slat_sampler_params"],
                tex_slat_sampler_params=sampler_params["tex_slat_sampler_params"],
                return_latent=True,
                pipeline_type=sampler_params["pipeline_type"],
                max_num_tokens=sampler_params["max_num_tokens"],
            )
            mesh = mesh_list[0]

            # 以下、vendor/Pixal3D/inference_mv.py の run_inference から。
            # パイプラインを常駐させるため、run_inference 自体は呼べず該当部分だけを写している。
            glb = o_voxel.postprocess.to_glb(
                vertices=mesh.vertices,
                faces=mesh.faces,
                attr_volume=mesh.attrs,
                coords=mesh.coords,
                attr_layout=_PIPELINE.pbr_attr_layout,
                grid_size=res,
                aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                decimation_target=int(decimation_target),
                texture_size=int(texture_size),
                remesh=bool(remesh),
                remesh_band=1,
                remesh_project=0,
                use_tqdm=True,
            )
            glb.apply_transform(_EXPORT_ROTATION)

            elapsed_sec = time.monotonic() - start
            peak_vram_mib = torch.cuda.max_memory_allocated() / (1024 * 1024)

            config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = config.OUTPUTS_DIR / f"{timestamp}.glb"
            glb.export(str(output_path), extension_webp=True)

        scale_lines = "\n".join(
            f"  - {config.VIEW_LABELS[a]}: 縮尺 {layout[a]['scale']:.4f}" for a in filled_azimuths
        )
        status = (
            f"生成しました: {output_path.name}\n\n"
            f"{_format_used_settings(filled_azimuths, full_settings, seed, sampler_params)}\n"
            f"- 前処理の縮尺（視点ごと）:\n{scale_lines}\n"
            f"- 所要時間: {elapsed_sec:.1f} 秒\n"
            f"- VRAM ピーク: {peak_vram_mib:.0f} MiB"
        )
        preview_images = [reframed[a] for a in filled_azimuths]
        return str(output_path), str(output_path), status, preview_images, int(seed)

    except gr.Error:
        # 正面が無い・物体が検出できない、など利用者がすぐ直せる操作ミス。
        # そのまま Gradio の赤帯表示に任せる（診断は挟まない）。
        raise
    except Exception as exc:  # 診断のためあえて広く捕まえる。握りつぶさず標準エラーへ出す。
        traceback.print_exc()
        error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        failure_kind = errors.classify_failure(error_text)
        diagnosis = errors.diagnose(failure_kind, full_settings)
        failure_markdown = errors.format_failure_markdown(diagnosis, error_text)
        status = (
            "生成に失敗しました。使った設定:\n\n"
            f"{_format_used_settings(filled_azimuths, full_settings, seed, sampler_params)}\n\n"
            f"{failure_markdown}"
        )
        # 前処理まで終わっていれば、どの画像で失敗したのかが分かるようにギャラリーに出す。
        preview_images = [reframed[a] for a in filled_azimuths] if reframed is not None else []
        return None, None, status, preview_images, int(seed)


def build_demo(*, default_resolution: int, low_vram: bool) -> gr.Blocks:
    defaults = framing.DEFAULT_SETTINGS

    with gr.Blocks(title="Pixal3D") as demo:
        gr.HTML(
            "<h1>Pixal3D（複数視点から 3D メッシュ生成）</h1>"
            "<p>正面・右・背面・左の 4 方向のうち、<strong>正面（0°）は必須</strong>です"
            "（Pixal3D の check_main_view が " + _term_span("frame 0") + " を正面前提で扱うため）。"
            "残り 3 枚は無くても生成できますが、枚数が少ないほど背面・側面の形状精度は落ちます。</p>"
            "<p><strong>写真は縦長でも構いません。</strong> 4 枚を同じ縮尺の正方形に揃え、"
            "上下に余白を付けてからモデルに渡します（画面いっぱいに写した縦長写真をそのまま渡すと、"
            "頭頂や足が生成範囲の外に出て切れてしまうため）。</p>"
            f"<p>{_term_span('低VRAMモード', '低 VRAM モード')}: {'有効' if low_vram else '無効'}</p>"
        )
        with gr.Row():
            front_input = gr.Image(
                label=config.VIEW_LABELS["front"], type="pil", image_mode="RGBA", elem_id="front_input"
            )
            right_input = gr.Image(
                label=config.VIEW_LABELS["right"], type="pil", image_mode="RGBA", elem_id="right_input"
            )
            back_input = gr.Image(
                label=config.VIEW_LABELS["back"], type="pil", image_mode="RGBA", elem_id="back_input"
            )
            left_input = gr.Image(
                label=config.VIEW_LABELS["left"], type="pil", image_mode="RGBA", elem_id="left_input"
            )

        gr.HTML(_terms_legend(["VRAM", "解像度", "シード"]))
        with gr.Row():
            resolution_input = gr.Radio(
                choices=[1024, 1536],
                value=default_resolution,
                label="解像度",
                info="生成に使う pipeline_type を決める（1024_cascade / 1536_cascade）。多視点では 512 は使えない。",
                elem_id="resolution_input",
            )
            seed_input = gr.Number(
                value=defaults["seed"], precision=0, minimum=0, maximum=2147483647, label="シード",
                elem_id="seed_input",
            )
            randomize_seed_input = gr.Checkbox(
                value=defaults["randomize_seed"], label="毎回ランダム",
                info="オンだと生成のたびにシードを乱数で決め、使ったシードをこの欄に書き戻す。",
                elem_id="randomize_seed_input",
            )

        gr.HTML(_terms_legend(["物体の大きさ", "背景除去"]))
        with gr.Row():
            fill_input = gr.Slider(
                0.60, 0.95, value=defaults["fill"], step=0.01,
                label="物体の大きさ（画面に占める割合）",
                info="大きすぎると頭や足が生成範囲からはみ出して切れる。0.85 が上流作例に近い。",
                elem_id="fill_input",
            )
            bg_removal_input = gr.Radio(
                choices=_BG_REMOVAL_CHOICES,
                value=defaults["background_removal"],
                label="背景除去",
                info="「自動」はアルファ（透過）が無い画像だけ背景を除去する。",
                elem_id="bg_removal_input",
            )

        with gr.Accordion("詳細設定（サンプラー）", open=False, elem_id="sampler_accordion"):
            gr.HTML(
                _terms_legend(
                    ["手数", "guidance strength", "guidance rescale", "rescale t", "max_num_tokens"]
                )
            )
            gr.HTML(f"<p><strong>{_term_span('疎構造', '疎構造（sparse structure）')}</strong></p>")
            with gr.Row():
                ss_steps_input = gr.Slider(
                    1, 50, value=defaults["ss_steps"], step=1, label="手数", elem_id="ss_steps_input"
                )
                ss_guidance_strength_input = gr.Slider(
                    1.0, 10.0, value=defaults["ss_guidance_strength"], step=0.1,
                    label="guidance strength", elem_id="ss_guidance_strength_input",
                )
                ss_guidance_rescale_input = gr.Slider(
                    0.0, 1.0, value=defaults["ss_guidance_rescale"], step=0.01,
                    label="guidance rescale", elem_id="ss_guidance_rescale_input",
                )
                ss_rescale_t_input = gr.Slider(
                    1.0, 6.0, value=defaults["ss_rescale_t"], step=0.1, label="rescale t",
                    elem_id="ss_rescale_t_input",
                )
            gr.HTML(f"<p><strong>{_term_span('形状SLat', '形状（shape slat）')}</strong></p>")
            with gr.Row():
                shape_steps_input = gr.Slider(
                    1, 50, value=defaults["shape_steps"], step=1, label="手数",
                    elem_id="shape_steps_input",
                )
                shape_guidance_strength_input = gr.Slider(
                    1.0, 10.0, value=defaults["shape_guidance_strength"], step=0.1,
                    label="guidance strength", elem_id="shape_guidance_strength_input",
                )
                shape_guidance_rescale_input = gr.Slider(
                    0.0, 1.0, value=defaults["shape_guidance_rescale"], step=0.01,
                    label="guidance rescale", elem_id="shape_guidance_rescale_input",
                )
                shape_rescale_t_input = gr.Slider(
                    1.0, 6.0, value=defaults["shape_rescale_t"], step=0.1, label="rescale t",
                    elem_id="shape_rescale_t_input",
                )
            gr.HTML(f"<p><strong>{_term_span('テクスチャSLat', 'テクスチャ（tex slat）')}</strong></p>")
            with gr.Row():
                tex_steps_input = gr.Slider(
                    1, 50, value=defaults["tex_steps"], step=1, label="手数", elem_id="tex_steps_input"
                )
                tex_guidance_strength_input = gr.Slider(
                    1.0, 10.0, value=defaults["tex_guidance_strength"], step=0.1,
                    label="guidance strength", elem_id="tex_guidance_strength_input",
                )
                tex_guidance_rescale_input = gr.Slider(
                    0.0, 1.0, value=defaults["tex_guidance_rescale"], step=0.01,
                    label="guidance rescale", elem_id="tex_guidance_rescale_input",
                )
                tex_rescale_t_input = gr.Slider(
                    1.0, 6.0, value=defaults["tex_rescale_t"], step=0.1, label="rescale t",
                    elem_id="tex_rescale_t_input",
                )
            max_num_tokens_input = gr.Slider(
                16384, 65536, value=defaults["max_num_tokens"], step=4096, label="max_num_tokens",
                elem_id="max_num_tokens_input",
            )

        with gr.Accordion("書き出し設定", open=False, elem_id="export_accordion"):
            gr.HTML(
                _terms_legend(
                    ["decimation", "テクスチャ解像度", "リメッシュ", "PBRテクスチャ", "GLB"]
                )
            )
            decimation_target_input = gr.Slider(
                100000, 1000000, value=defaults["decimation_target"], step=10000,
                label="面数の上限（decimation_target）", elem_id="decimation_target_input",
            )
            texture_size_input = gr.Radio(
                choices=_TEXTURE_SIZE_CHOICES, value=defaults["texture_size"], label="テクスチャ解像度",
                elem_id="texture_size_input",
            )
            remesh_input = gr.Checkbox(
                value=defaults["remesh"], label="リメッシュ", elem_id="remesh_input"
            )

        with gr.Accordion("設定の保存・読み込み", open=False, elem_id="preset_accordion"):
            gr.HTML(_terms_legend(["プリセット"]))
            with gr.Row():
                preset_name_input = gr.Textbox(
                    label="名前", placeholder="例: 高精細・低VRAM", elem_id="preset_name_input",
                )
                save_preset_button = gr.Button("保存", elem_id="save_preset_button")
            with gr.Row():
                preset_dropdown = gr.Dropdown(
                    choices=presets.list_presets(), value=None, label="保存済みの設定",
                    allow_custom_value=False, elem_id="preset_dropdown",
                )
                load_preset_button = gr.Button("読み込み", elem_id="load_preset_button")
                delete_preset_button = gr.Button("削除", elem_id="delete_preset_button")
            preset_status_output = gr.Markdown(elem_id="preset_status_output")

        with gr.Row():
            generate_button = gr.Button("生成", variant="primary", elem_id="generate_button")
            reset_button = gr.Button("既定に戻す", elem_id="reset_button")

        status_output = gr.Markdown()
        with gr.Row():
            model_output = gr.Model3D(label="プレビュー")
            download_output = gr.File(label="ダウンロード")
        preview_gallery = gr.Gallery(label="前処理後の入力（モデルに渡した画像）", columns=4)

        setting_inputs = [
            resolution_input,
            seed_input,
            randomize_seed_input,
            fill_input,
            bg_removal_input,
            ss_steps_input,
            ss_guidance_strength_input,
            ss_guidance_rescale_input,
            ss_rescale_t_input,
            shape_steps_input,
            shape_guidance_strength_input,
            shape_guidance_rescale_input,
            shape_rescale_t_input,
            tex_steps_input,
            tex_guidance_strength_input,
            tex_guidance_rescale_input,
            tex_rescale_t_input,
            max_num_tokens_input,
            decimation_target_input,
            texture_size_input,
            remesh_input,
        ]

        # setting_inputs は framing.DEFAULT_SETTINGS と同じキー・同じ順序で並んでいる前提
        # （_SETTING_KEYS はプリセットの保存・読み込みで dict <-> 部品値を対応付けるのに使う）。
        # 崩れたら起動時にすぐ気づけるようにアサーションで確認する。
        assert list(_SETTING_KEYS) == list(defaults.keys()), (
            "_SETTING_KEYS が framing.DEFAULT_SETTINGS の並びと一致していません"
        )
        assert len(setting_inputs) == len(_SETTING_KEYS), (
            "setting_inputs と _SETTING_KEYS の項目数が一致していません"
        )

        def _reset_to_defaults():
            return (
                default_resolution,
                defaults["seed"],
                defaults["randomize_seed"],
                defaults["fill"],
                defaults["background_removal"],
                defaults["ss_steps"],
                defaults["ss_guidance_strength"],
                defaults["ss_guidance_rescale"],
                defaults["ss_rescale_t"],
                defaults["shape_steps"],
                defaults["shape_guidance_strength"],
                defaults["shape_guidance_rescale"],
                defaults["shape_rescale_t"],
                defaults["tex_steps"],
                defaults["tex_guidance_strength"],
                defaults["tex_guidance_rescale"],
                defaults["tex_rescale_t"],
                defaults["max_num_tokens"],
                defaults["decimation_target"],
                defaults["texture_size"],
                defaults["remesh"],
            )

        reset_button.click(_reset_to_defaults, inputs=[], outputs=setting_inputs)

        def _save_preset(name, *values):
            """『保存』ボタンのハンドラ。setting_inputs の現在値を presets.save_preset に渡す。"""

            settings = dict(zip(_SETTING_KEYS, values))
            try:
                path = presets.save_preset(name, settings)
            except ValueError as exc:
                return gr.update(choices=presets.list_presets()), f"保存できませんでした: {exc}"
            return gr.update(choices=presets.list_presets()), f"保存しました: {path.stem}"

        def _load_preset(current_name):
            """『読み込み』ボタンのハンドラ。setting_inputs 全部品へ値を返す

            （_reset_to_defaults と同じ並び。_SETTING_KEYS で対応付ける）。一覧の選択が
            空のときは何もせず、その旨だけを結果表示に出す。
            """

            no_change = tuple(gr.update() for _ in _SETTING_KEYS)
            if not current_name:
                return (*no_change, "設定が選ばれていません。一覧から選んでください。")

            try:
                result = presets.load_preset(current_name)
            except (FileNotFoundError, ValueError) as exc:
                return (*no_change, f"読み込めませんでした: {exc}")

            settings = result["settings"]
            ignored = result["ignored"]
            values = tuple(settings[key] for key in _SETTING_KEYS)

            message = f"読み込みました: {current_name}"
            if ignored:
                message += f"\n\n{'、'.join(ignored)} は範囲外だったので既定値にしました。"
            return (*values, message)

        def _delete_preset(current_name):
            """『削除』ボタンのハンドラ。"""

            if not current_name:
                return (
                    gr.update(choices=presets.list_presets()),
                    "設定が選ばれていません。一覧から選んでください。",
                )
            deleted = presets.delete_preset(current_name)
            choices = presets.list_presets()
            if not deleted:
                return gr.update(choices=choices), f"見つかりませんでした: {current_name}"
            return gr.update(choices=choices, value=None), f"削除しました: {current_name}"

        save_preset_button.click(
            _save_preset,
            inputs=[preset_name_input] + setting_inputs,
            outputs=[preset_dropdown, preset_status_output],
        )
        load_preset_button.click(
            _load_preset,
            inputs=[preset_dropdown],
            outputs=setting_inputs + [preset_status_output],
        )
        delete_preset_button.click(
            _delete_preset,
            inputs=[preset_dropdown],
            outputs=[preset_dropdown, preset_status_output],
        )

        generate_button.click(
            _generate,
            inputs=[front_input, right_input, back_input, left_input] + setting_inputs,
            outputs=[model_output, download_output, status_output, preview_gallery, seed_input],
        )
    return demo


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="px3d.ui", description="Pixal3D の Gradio 画面")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--resolution", type=int, choices=(1024, 1536), default=1536)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--low-vram", dest="low_vram", action="store_true", default=None)
    group.add_argument("--no-low-vram", dest="low_vram", action="store_false", default=None)
    return parser


def main() -> None:
    global _PIPELINE, _LOW_VRAM

    args = build_arg_parser().parse_args()
    low_vram = args.low_vram if args.low_vram is not None else config.LOW_VRAM_DEFAULT
    _LOW_VRAM = low_vram

    # pipeline_mv.json の rembg_model（briaai/RMBG-2.0、ゲート付き）を、非ゲートの
    # config.REMBG_MODEL に強制する。init_pipeline（内部で from_pretrained を呼ぶ）より前に
    # 呼ぶ必要がある（px3d/rembg_override.py の docstring を参照）。
    rembg_override.force_rembg_model(config.REMBG_MODEL)

    print(f"[px3d.ui] パイプラインを読み込んでいます（低 VRAM モード: {'有効' if low_vram else '無効'}）...")
    # model_path にはローカルディレクトリではなく HF のリポジトリ ID をそのまま渡す。
    # Pipeline.from_pretrained（vendor/Pixal3D/pixal3d/pipelines/base.py）は
    # f"{path}/{config_file}" が存在するときだけローカル読みし、無ければ HF_HOME のキャッシュ
    # （hf_hub_download 経由）から読む。実機で動作を確認できたのはこのキャッシュ方式のみで、
    # 重みをプレーンなローカルディレクトリへ展開すると約 24GB のキャッシュと二重に保存されてしまう。
    _PIPELINE = inference_mv.init_pipeline(
        model_path=config.MODEL_REPO,
        config_file=config.PIPELINE_CONFIG,
        low_vram=low_vram,
    )
    print("[px3d.ui] パイプラインの読み込みが完了しました。")

    demo = build_demo(default_resolution=args.resolution, low_vram=low_vram)
    help_css, help_js = _build_help_assets()
    # share=True は絶対に使わない（vendor/Pixal3D/app.py は固定で使っているが、
    # LAN 内サービスなので不要かつ危険）。
    # css / js は Blocks.launch() へ渡す（Gradio 6.17.3 でこの版から移った引数。
    # _build_help_assets() の docstring を参照）。
    demo.launch(
        server_name=args.host, server_port=args.port, share=False, css=help_css, js=help_js
    )


if __name__ == "__main__":
    main()
