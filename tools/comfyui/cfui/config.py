"""パス・ポート・固定コミット・モデルの一覧を一元管理する。

このモジュールはファイルシステムに書き込まず、ネットワークにも触れない。
定数を並べるだけなので、素の python からでも torch なしで import できる
（px3d/config.py と同じ設計方針）。
setup-server.sh と scripts/build-wtivo.sh は venv を作る前に git を操作するため、
同じ値を直値でも持っている。片方を変えたらもう片方も変えること。
"""

from __future__ import annotations

from pathlib import Path

# このファイルは tools/comfyui/cfui/config.py なので、2 つ上が tools/comfyui。
TOOL_DIR = Path(__file__).resolve().parents[1]

VENDOR_DIR = TOOL_DIR / "vendor"
COMFYUI_DIR = VENDOR_DIR / "ComfyUI"
CUSTOM_NODES_DIR = COMFYUI_DIR / "custom_nodes"
MODELS_DIR = COMFYUI_DIR / "models"
INPUT_DIR = COMFYUI_DIR / "input"
WORKFLOWS_DIR = COMFYUI_DIR / "user" / "default" / "workflows" / "PixelArtistry"
# 予備案（WTiVo を外したもの）の写しの置き場。scripts/adapt_workflows.py --fallback が書く。
FALLBACK_WORKFLOWS_DIR = COMFYUI_DIR / "user" / "default" / "workflows" / "PixelArtistry_noWTiVo"
EXTENSIONS_DIR = VENDOR_DIR / "extensions"
PIXELARTISTRY_DIR = VENDOR_DIR / "PixelArtistry-Watertight-Meshes"
WTIVO_SRC_DIR = VENDOR_DIR / "WTiVo-WatertightVoxel"
WTIVO_NODE_DIR = CUSTOM_NODES_DIR / "WTiVo-WatertightVoxel-ComfyuiNode"
# ノードの wtivo.py は ROOT と ROOT/build を sys.path に足してから wtivo_core / wtivo_gpupr /
# wtivo_vdb を import する（WTiVo-WatertightVoxel-ComfyuiNode/wtivo.py:44-49, 86-89）。
# Linux でビルドした .so はここへ置く。
WTIVO_NATIVE_DIR = WTIVO_NODE_DIR / "build"
TRELLIS2_NODE_DIR = CUSTOM_NODES_DIR / "ComfyUI-Trellis2"
PATCHES_DIR = TOOL_DIR / "patches"
SCRIPTS_DIR = TOOL_DIR / "scripts"
LOGS_DIR = TOOL_DIR / "logs"
VENV_PYTHON = TOOL_DIR / ".venv" / "bin" / "python"

HOST = "0.0.0.0"
PORT = 8188

# CUDA 拡張は 12.6 でビルドする（/usr/local/cuda は 13.2 で Hunyuan3D 用。触らない）。
CUDA_HOME = "/usr/local/cuda-12.6"
EXPECTED_NVCC_RELEASE = "12.6"
EXPECTED_TORCH_VERSION = "2.9.1+cu126"
EXPECTED_TORCH_CUDA = "12.6"
EXPECTED_GPU_SUBSTRING = "A30"

# Blender は snap の 5.x を使う。/usr/bin/blender は apt の 4.0.2 で、ワークフローの
# LODTailor / Bake Forger が前提にする版より古いので使わない。
# /snap/bin/blender（= /usr/bin/snap）は使わない。snap run が子を snap.blender.*.scope という別の
# cgroup に移すため、comfyui.service の MemoryHigh / MemoryMax も memory.peak も Blender に届かない。
# snap は classic confinement なので、本体を直接起動すれば呼び出し元の cgroup に残る（2026-10-03 実測）。
# /snap/blender/current は snap refresh で版が変わっても同じパスのまま。
BLENDER_PATH = "/snap/blender/current/blender"
# snap run 経由になるパス。doctor がこれを指していないか確かめる。
BLENDER_SNAP_LAUNCHER = "/usr/bin/snap"
# 以前の既定値。adapt_workflows.py は、この値で書いたままの（手直しされていない）写しだけを
# 今の既定値へ書き換える。
LEGACY_BLENDER_PATHS = ("/snap/bin/blender",)
BLENDER_MAJOR_REQUIRED = 5
# アドオンの干渉を避けるため、ComfyUI から呼ぶ Blender の利用者設定を空の場所へ向ける。
BLENDER_CLEAN_DIR = Path.home() / ".config" / "comfyui" / "blender-clean"
BLENDER_ENV_DIRS = {
    "BLENDER_USER_CONFIG": "config",
    "BLENDER_USER_SCRIPTS": "scripts",
    # Blender 4.2 以降、アドオンの多くは extensions に入る。scripts だけでは外せないので足す。
    "BLENDER_USER_EXTENSIONS": "extensions",
}

ENV_FILE = Path.home() / ".config" / "comfyui" / "comfyui.env"
# serve が main.py の後ろに足す追加引数（例: --lowvram）。env ファイルから読む想定。
EXTRA_ARGS_ENV_VAR = "COMFYUI_EXTRA_ARGS"

SERVICE_NAME = "comfyui"

COMFYUI_URL = "https://github.com/Comfy-Org/ComfyUI.git"
# GitHub の Releases 画面の最新は v0.38.0 だが、その後に版上げコミットの付いたタグ
# v0.38.1 / v0.38.2 がある。差分は API ノードとテンプレートの更新だけ（2026-10-02 確認）。
COMFYUI_TAG = "v0.38.2"
COMFYUI_COMMIT = "daeb5e53681e2b10a3f0727d9ec5bc90784bee10"

PIXELARTISTRY_URL = "https://github.com/pixelartistry/PixelArtistry-Watertight-Meshes.git"
PIXELARTISTRY_COMMIT = "5b3a0e9d2c5783ed05ba45bbcc157b9509fb267b"

WTIVO_SRC_URL = "https://github.com/Mstafa-awad/WTiVo-WatertightVoxel.git"
# タグは無い。VERSION ファイルが 1.0.0 の main の HEAD（2026-09-11）。
WTIVO_SRC_COMMIT = "7a0ac7cb24fd0588f2f7a78c787779d760d36f48"

# custom_nodes（フォルダ名, URL, コミット）。Mstafa-awad の 9 個は配布元 bat の SHA_* と同じ。
CUSTOM_NODES = (
    (
        "ComfyUI-Trellis2",
        "https://github.com/visualbruno/ComfyUI-Trellis2.git",
        "b0e84c0f29857a444e8bcb5b9be2ea218e96efd0",
    ),
    (
        "WTiVo-WatertightVoxel-ComfyuiNode",
        "https://github.com/Mstafa-awad/WTiVo-WatertightVoxel-ComfyuiNode.git",
        "fb9e9ea6a7deec965d3a4bf43ba7a4a9ff3856f3",
    ),
    (
        "ComfyUI-Mesh-Quad-Reconstruct",
        "https://github.com/Mstafa-awad/ComfyUI-Mesh-Quad-Reconstruct.git",
        "74048b3415537e26cc72b46b082a010cd0e357ce",
    ),
    (
        "ComfyUI-CuMesh-Decimate",
        "https://github.com/Mstafa-awad/ComfyUI-CuMesh-Decimate.git",
        "c4edeb96bf637239cecb731d2869469a3025d742",
    ),
    (
        "ComfyUI-Memory-Cleaner",
        "https://github.com/Mstafa-awad/ComfyUI-Memory-Cleaner.git",
        "3357282290278c96ffa0da180d43bc5eac5f2286",
    ),
    (
        "LODTailor-The-Mesh-Trimmer-ComfyuiNode",
        "https://github.com/Mstafa-awad/LODTailor-The-Mesh-Trimmer-ComfyuiNode.git",
        "3d25b7d4aa382fa5dac210eb5d8d0eadc4a4f183",
    ),
    (
        "LODTailor-Bake-Forger",
        "https://github.com/Mstafa-awad/LODTailor-Bake-Forger.git",
        "f13589c22558e3ca49dfa87dce709233eb3cc86b",
    ),
    (
        "Trellis2-Mesh-Encoder",
        "https://github.com/Mstafa-awad/Trellis2-Mesh-Encoder.git",
        "860313e67f0f69d402310dc325707bab8bec2fe9",
    ),
    (
        "ComfyUI_LODsmith_Merge_Watertight",
        "https://github.com/Mstafa-awad/ComfyUI_LODsmith_Merge_Watertight.git",
        "5da6dd69c02d0f3d4ae743d090cfac79aefe7f96",
    ),
    (
        "WTiVo-FastMergeByDistance",
        "https://github.com/Mstafa-awad/WTiVo-FastMergeByDistance.git",
        "5392949165ceed1e74448b1949d6e0dc9b34dd92",
    ),
)

# CUDA 拡張のソース（フォルダ名, URL, コミット）。vendor/extensions に置く。
# ComfyUI-Trellis2 の README（Custom Build）が指す visualbruno のフォークを使う。
# 同梱の wheels/Linux/Torch291 は cumesh が sm_86、他が sm_120 の SASS しか持たず、
# A30（sm_80）では "no kernel image is available" で落ちた（2026-10-02 実測）。
EXTENSION_SOURCES = (
    ("CuMesh", "https://github.com/visualbruno/CuMesh.git", "d10e54c30ddd03d11472c1431693f985501c7966"),
    ("FlexGEMM", "https://github.com/visualbruno/FlexGEMM.git", "db388bd17c34abc697792aa718dca780734c2783"),
    ("TRELLIS.2", "https://github.com/visualbruno/TRELLIS.2.git", "65d1e13b4a92296036044df0633242bb9e95abf6"),
    ("nvdiffrast", "https://github.com/NVlabs/nvdiffrast.git", "253ac4fcea7de5f396371124af597e6cc957bfae"),
)

# doctor が import を確かめる拡張（表示名, import 文）。
EXTENSION_IMPORTS = (
    ("cumesh", "import cumesh"),
    ("o_voxel", "import o_voxel"),
    ("flex_gemm", "import flex_gemm"),
    ("nvdiffrast", "import nvdiffrast.torch"),
)
WTIVO_MODULES = ("wtivo_core", "wtivo_gpupr", "wtivo_vdb")

# WTiVo の core / vdb のビルドに要る apt パッケージ（sudo が要るので利用者が入れる）。
WTIVO_APT_PACKAGES = ("libcgal-dev", "libopenvdb-dev", "libtbb-dev", "libeigen3-dev")

HF_BASE_URL = "https://huggingface.co"

# モデル（置き先, ファイル名, repo, repo 内のパス, バイト数, sha256）。
# 置き先は vendor/ComfyUI/models/ からの相対パス。一覧は配布元 bat の :models（L407-417）と同じ。
# バイト数と sha256 は 2026-10-02 に HF の resolve/main の応答（x-linked-size / x-linked-etag）で確認した。
# json は LFS ではないため、取得したファイルの sha256 を書いている。
MODEL_FILES = (
    (
        "diffusion_models",
        "trellis_2_int8_convrot.safetensors",
        "Comfy-Org/TRELLIS.2",
        "diffusion_models/trellis_2_int8_convrot.safetensors",
        5253048192,
        "d01952ad137213f6a868f86b6b877026276f84af5eec23069217475a0bad3a31",
    ),
    (
        "diffusion_models",
        "pixal3d_int8_convrot.safetensors",
        "Comfy-Org/Pixal3D",
        "diffusion_models/pixal3d_int8_convrot.safetensors",
        5584555824,
        "4621eac3b715484f79303c7152af641fe0b2b14f4d0e3d394fd6922d00f955ec",
    ),
    (
        "vae",
        "trellis_2_shape_vae_bf16.safetensors",
        "Comfy-Org/Pixal3D",
        "vae/trellis_2_shape_vae_bf16.safetensors",
        1095844024,
        "de0cb4949a76c59ee5c091a995a69bcc8c51d5aeda939f0c641a50d2a72341f4",
    ),
    (
        "vae",
        "trellis_2_texture_vae_bf16.safetensors",
        "Comfy-Org/Pixal3D",
        "vae/trellis_2_texture_vae_bf16.safetensors",
        948461364,
        "714e5ebf094a610e12a8e3b5175c18a62f37f6ea4218acb6073644456b73ab0e",
    ),
    (
        "clip_vision",
        "dino_v3_L_naf_fp32.safetensors",
        "Comfy-Org/Pixal3D",
        "clip_vision/dino_v3_L_naf_fp32.safetensors",
        1215214176,
        "4ad2ec4e0879a5b5b04cd97325cc37da954a7b6edca5170b86510f17f2b2290f",
    ),
    (
        "geometry_estimation",
        "moge_2_vitl_normal_fp16.safetensors",
        "Comfy-Org/MoGe",
        "geometry_estimation/moge_2_vitl_normal_fp16.safetensors",
        661859924,
        "cb1a692d03235671e959e81360d7b4d9f44aefadb1f852d6ca6aa17799d5e31f",
    ),
    (
        "background_removal",
        "birefnet.safetensors",
        "Comfy-Org/BiRefNet",
        "background_removal/birefnet.safetensors",
        444473596,
        "9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154",
    ),
    (
        "Trellis2/encoders",
        "shape_enc_next_dc_f16c32_fp16.safetensors",
        "microsoft/TRELLIS.2-4B",
        "ckpts/shape_enc_next_dc_f16c32_fp16.safetensors",
        708797208,
        "f37c5ff5b983b68e9946060000f09bc131f3e84318a2c8b7430a81e4b4636c41",
    ),
    (
        "Trellis2/encoders",
        "shape_enc_next_dc_f16c32_fp16.json",
        "microsoft/TRELLIS.2-4B",
        "ckpts/shape_enc_next_dc_f16c32_fp16.json",
        653,
        "5a960a5c419d70f8d4a7a6b6e52ae689cd948c88bd7ed92346adfbf82cd12007",
    ),
)

# サンプル画像（配布元 bat の L179 と同じ URL）。input/ に置く。
SAMPLE_IMAGE_NAME = "viking_wolf_rune_axe.png"
SAMPLE_IMAGE_URL = (
    "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/refs/heads/main/input/"
    "viking_wolf_rune_axe.png"
)

# 配布元のワークフロー 4 本（vendor/PixelArtistry-Watertight-Meshes/workflows/ のファイル名）。
WORKFLOW_FILES = (
    "PixelArtistry_01_Image_to_Watertight_Mesh.json",
    "PixelArtistry_01b_Image_to_Watertight_Mesh_2K.json",
    "PixelArtistry_02_Image_to_GameReady_Asset.json",
    "PixelArtistry_03_Your_Mesh_to_GameReady_Asset.json",
)

# WTiVo の自己試験（配布元 bat の L457-484 と同じ条件）。
SELFTEST_SUBDIVISIONS = 4
SELFTEST_RADIUS = 0.5
SELFTEST_REMOVED_FACES = 60
SELFTEST_ARGS = {
    "input_res": 256,
    "final_res": 256,
    "proxy_points": 200_000,
    "threads": 4,
}

VRAM_FREE_THRESHOLD_MIB = 1024
