"""px3d 自前の Gradio 画面。

vendor/Pixal3D は単一画像（inference.py）または既知カメラの複数画像（inference_mv.py）を
入力に取る。inference_mv.py はスクリプトとして書かれていて、パイプラインを毎回ロードし直す
（1 回で数分かかる）。ここではパイプラインをプロセス起動時に 1 度だけロードして常駐させ、
4 方位（正面・右・背面・左）の画像枠を持つ Gradio 画面から使えるようにする。

`px3d.cli` の `serve` から `python -m px3d.ui` として `os.execve` で起動される。
モジュール先頭で torch / gradio / pixal3d を import してよいのはここだけ
（px3d.cli / px3d.config / px3d.ollama / px3d.options は素の python からも import できる
必要があるため、重い依存を持ち込まない設計にしてある）。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import gradio as gr
import numpy as np
import torch

from . import config, ollama, rembg_override

# vendor/Pixal3D を PYTHONPATH に通した状態で起動される（px3d.cli.build_serve_env）。
# inference_mv は上流のトップレベルスクリプトで、import するだけで ATTN_BACKEND などの
# 環境変数セットアップ（os.environ.setdefault）が走る。
import inference_mv  # noqa: E402
import o_voxel  # noqa: E402

# プロセスに 1 個だけ常駐させるパイプライン。main() が起動時に 1 度だけ入れる。
_PIPELINE = None

# vendor/Pixal3D/inference_mv.py の run_inference() のサンプラー既定値と同じ
# （画面には出さない。上流 CLI の既定を素直に踏襲する）。
_SS_SAMPLER_OVERRIDE = {
    "steps": 12,
    "guidance_strength": 7.5,
    "guidance_rescale": 0.7,
    "rescale_t": 5.0,
}
_SHAPE_SAMPLER_OVERRIDE = {
    "steps": 12,
    "guidance_strength": 7.5,
    "guidance_rescale": 0.5,
    "rescale_t": 3.0,
}
_TEX_SAMPLER_OVERRIDE = {
    "steps": 12,
    "guidance_strength": 1.0,
    "guidance_rescale": 0.0,
    "rescale_t": 3.0,
}
_MAX_NUM_TOKENS = 49152

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


def _generate(front_image, right_image, back_image, left_image, resolution, seed):
    if front_image is None:
        # check_main_view は frame 0 を正面と仮定して警告を出すだけで止めはしないが、
        # ここでは画面側で先に弾く（正面が無いと出力の向きが上流の学習時と揃わない）。
        raise gr.Error(
            "正面（0°）の画像は必須です。Pixal3D の check_main_view が frame 0 を"
            "正面前提で扱うため、正面が無いと出力の向きがずれます。"
        )

    images = {"front": front_image, "right": right_image, "back": back_image, "left": left_image}
    filled_azimuths = [azimuth for azimuth in config.VIEW_AZIMUTHS if images[azimuth] is not None]

    _unload_ollama_before_generate()

    if _PIPELINE is None:
        raise gr.Error("パイプラインが読み込まれていません（起動処理が失敗している可能性があります）")

    with tempfile.TemporaryDirectory(prefix="px3d-views-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        for azimuth in filled_azimuths:
            images[azimuth].save(tmp_path / f"{azimuth}.png")
        transforms = _build_transforms_json(filled_azimuths)
        (tmp_path / "transforms.json").write_text(
            json.dumps(transforms, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # inference_mv.load_views / check_main_view から。
        views = inference_mv.load_views(
            str(tmp_path), rembg=inference_mv.make_rembg(_PIPELINE)
        )
        inference_mv.check_main_view(views)

        torch.manual_seed(int(seed))
        torch.cuda.reset_peak_memory_stats()
        start = time.monotonic()

        pipeline_type = f"{int(resolution)}_cascade"
        mesh_list, (_shape_slat, _tex_slat, res) = _PIPELINE.run_mv(
            views,
            seed=int(seed),
            sparse_structure_sampler_params=_SS_SAMPLER_OVERRIDE,
            shape_slat_sampler_params=_SHAPE_SAMPLER_OVERRIDE,
            tex_slat_sampler_params=_TEX_SAMPLER_OVERRIDE,
            return_latent=True,
            pipeline_type=pipeline_type,
            max_num_tokens=_MAX_NUM_TOKENS,
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
            decimation_target=1000000,
            texture_size=4096,
            remesh=True,
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

    status = (
        f"生成しました: {output_path.name}\n\n"
        f"- 使用した視点: {', '.join(config.VIEW_LABELS[a] for a in filled_azimuths)}\n"
        f"- 解像度: {int(resolution)}\n"
        f"- 所要時間: {elapsed_sec:.1f} 秒\n"
        f"- VRAM ピーク: {peak_vram_mib:.0f} MiB"
    )
    return str(output_path), str(output_path), status


def build_demo(*, default_resolution: int, low_vram: bool) -> gr.Blocks:
    with gr.Blocks(title="Pixal3D") as demo:
        gr.Markdown(
            "# Pixal3D（複数視点から 3D メッシュ生成）\n\n"
            "正面・右・背面・左の 4 方向のうち、**正面（0°）は必須**です"
            "（Pixal3D の check_main_view が frame 0 を正面前提で扱うため）。"
            "残り 3 枚は無くても生成できますが、枚数が少ないほど背面・側面の形状精度は落ちます。\n\n"
            f"低 VRAM モード: {'有効' if low_vram else '無効'}"
        )
        with gr.Row():
            front_input = gr.Image(label=config.VIEW_LABELS["front"], type="pil", image_mode="RGBA")
            right_input = gr.Image(label=config.VIEW_LABELS["right"], type="pil", image_mode="RGBA")
            back_input = gr.Image(label=config.VIEW_LABELS["back"], type="pil", image_mode="RGBA")
            left_input = gr.Image(label=config.VIEW_LABELS["left"], type="pil", image_mode="RGBA")
        with gr.Row():
            resolution_input = gr.Radio(
                choices=[1024, 1536], value=default_resolution, label="解像度"
            )
            seed_input = gr.Number(value=42, precision=0, label="シード")
        generate_button = gr.Button("生成", variant="primary")
        status_output = gr.Markdown()
        with gr.Row():
            model_output = gr.Model3D(label="プレビュー")
            download_output = gr.File(label="ダウンロード")

        generate_button.click(
            _generate,
            inputs=[front_input, right_input, back_input, left_input, resolution_input, seed_input],
            outputs=[model_output, download_output, status_output],
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
    global _PIPELINE

    args = build_arg_parser().parse_args()
    low_vram = args.low_vram if args.low_vram is not None else config.LOW_VRAM_DEFAULT

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
    # share=True は絶対に使わない（vendor/Pixal3D/app.py は固定で使っているが、
    # LAN 内サービスなので不要かつ危険）。
    demo.launch(server_name=args.host, server_port=args.port, share=False)


if __name__ == "__main__":
    main()
