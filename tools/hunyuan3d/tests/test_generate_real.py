"""実機（A30）で 4 ビュー → GLB まで通ることを確かめる試験。モック試験とは別。

GPU と重みを実際に使い、数分かかる。Hunyuan3D のサービスが動いていると VRAM が
足りないので、先に止めること。

実行:
    systemctl --user stop hunyuan3d
    tools/hunyuan3d/.venv/bin/python tools/hunyuan3d/tests/test_generate_real.py
    tools/hunyuan3d/.venv/bin/python tools/hunyuan3d/tests/test_generate_real.py --no-texture

測るもの: 段階ごとの所要時間と、nvidia-smi で見た VRAM のピーク。
出力先: tools/hunyuan3d/outputs/smoke/
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

from hy3d import config, ollama  # noqa: E402

# hy3dgen は pip で入れていない。上流のディレクトリから読む。
sys.path.insert(0, str(config.VENDOR_DIR))

# 重みと実行時キャッシュの置き場は serve と揃える（import より前に立てる必要がある）。
os.environ["HY3DGEN_MODELS"] = str(config.MODELS_DIR)
os.environ["HF_HOME"] = str(config.HF_HOME_DIR)
os.environ["U2NET_HOME"] = str(config.U2NET_HOME_DIR)

EXAMPLE_DIR = config.VENDOR_DIR / "assets" / "example_mv_images" / "2"
OUTPUT_DIR = config.OUTPUTS_DIR / "smoke"
VRAM_HEADROOM_MIB = 2048


class VramSampler:
    """nvidia-smi を 0.5 秒ごとに読み、VRAM 使用量のピークを記録する。"""

    def __init__(self) -> None:
        self.peak_mib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            used = ollama.gpu_used_mib()
            if used is not None and used > self.peak_mib:
                self.peak_mib = used
            self._stop.wait(0.5)

    def __enter__(self) -> VramSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def load_views() -> dict:
    """上流の例画像（front / left / back）を読む。right は同梱されていない。"""

    from PIL import Image

    views = {}
    for view_name in ("front", "left", "back", "right"):
        path = EXAMPLE_DIR / f"{view_name}.png"
        if path.is_file():
            views[view_name] = Image.open(path)
    return views


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="実機で 4 ビュー → GLB を確かめる")
    parser.add_argument("--no-texture", action="store_true", help="形状生成だけを確かめる")
    parser.add_argument("--steps", type=int, default=30, help="拡散のステップ数（既定 30）")
    args = parser.parse_args(argv)

    used_before = ollama.gpu_used_mib()
    if used_before is None:
        print("NG: nvidia-smi を実行できません", file=sys.stderr)
        return 1
    if used_before > VRAM_HEADROOM_MIB:
        print(
            f"NG: VRAM が {used_before} MiB 使われています。"
            "先に systemctl --user stop hunyuan3d を実行してください。",
            file=sys.stderr,
        )
        return 1

    views = load_views()
    if not views:
        print(f"NG: 例画像が見つかりません: {EXAMPLE_DIR}", file=sys.stderr)
        return 1
    print(f"入力: {', '.join(sorted(views))}（{EXAMPLE_DIR}）")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    with VramSampler() as sampler:
        import torch
        from hy3dgen.rembg import BackgroundRemover
        from hy3dgen.shapegen import FaceReducer, Hunyuan3DDiTFlowMatchingPipeline
        from hy3dgen.shapegen.pipelines import export_to_trimesh

        start = time.time()
        remover = BackgroundRemover()
        for view_name, image in views.items():
            if image.mode == "RGB":
                views[view_name] = remover(image.convert("RGB"))
        timings["背景除去"] = time.time() - start

        start = time.time()
        shape_pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            config.SHAPE_REPO, subfolder=config.SHAPE_SUBFOLDER
        )
        shape_pipeline.enable_flashvdm(mc_algo="mc")
        timings["形状モデルのロード"] = time.time() - start

        start = time.time()
        generator = torch.Generator().manual_seed(1234)
        outputs = shape_pipeline(
            image=views,
            num_inference_steps=args.steps,
            guidance_scale=7.5,
            generator=generator,
            octree_resolution=256,
            num_chunks=200000,
            output_type="mesh",
        )
        mesh = export_to_trimesh(outputs)[0]
        timings["形状生成"] = time.time() - start
        print(f"メッシュ: 頂点 {len(mesh.vertices)} / 面 {len(mesh.faces)}")

        shape_path = OUTPUT_DIR / "smoke_shape.glb"
        mesh.export(str(shape_path))
        print(f"出力（形状のみ）: {shape_path}（{shape_path.stat().st_size / 2 ** 20:.1f} MiB）")

        textured_path = None
        if not args.no_texture:
            del shape_pipeline
            torch.cuda.empty_cache()

            start = time.time()
            from hy3dgen.texgen import Hunyuan3DPaintPipeline

            paint_pipeline = Hunyuan3DPaintPipeline.from_pretrained(config.TEXGEN_REPO)
            paint_pipeline.enable_model_cpu_offload()
            timings["テクスチャモデルのロード"] = time.time() - start

            start = time.time()
            mesh = FaceReducer()(mesh)
            timings["面の削減"] = time.time() - start

            start = time.time()
            textured_mesh = paint_pipeline(mesh, views["front"])
            timings["テクスチャ生成"] = time.time() - start

            textured_path = OUTPUT_DIR / "smoke_textured.glb"
            textured_mesh.export(str(textured_path))
            print(
                f"出力（テクスチャ付き）: {textured_path}"
                f"（{textured_path.stat().st_size / 2 ** 20:.1f} MiB）"
            )

    print()
    print("段階ごとの所要時間:")
    for label, seconds in timings.items():
        print(f"  {label}: {seconds:.1f} 秒")
    print(f"合計: {sum(timings.values()):.1f} 秒")
    print(f"VRAM のピーク: {sampler.peak_mib} MiB / 24576 MiB")

    if sampler.peak_mib >= 24576:
        print("NG: VRAM を使い切りました", file=sys.stderr)
        return 1
    if not shape_path.is_file() or shape_path.stat().st_size == 0:
        print("NG: 形状の GLB が出力されていません", file=sys.stderr)
        return 1
    if textured_path is not None and (not textured_path.is_file() or textured_path.stat().st_size == 0):
        print("NG: テクスチャ付きの GLB が出力されていません", file=sys.stderr)
        return 1

    print("合格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
