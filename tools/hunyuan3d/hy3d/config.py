"""パス・ポート・モデル ID を一元管理する。

このモジュールはファイルシステムに書き込まず、ネットワークにも触れない。
定数を並べるだけなので、素の python からでも torch なしで import できる。
"""

from __future__ import annotations

from pathlib import Path

# このファイルは tools/hunyuan3d/hy3d/config.py なので、2 つ上が tools/hunyuan3d。
TOOL_DIR = Path(__file__).resolve().parents[1]

VENDOR_DIR = TOOL_DIR / "vendor" / "Hunyuan3D-2"
MODELS_DIR = TOOL_DIR / "models"
OUTPUTS_DIR = TOOL_DIR / "outputs"
VENV_PYTHON = TOOL_DIR / ".venv" / "bin" / "python"

HOST = "0.0.0.0"
PORT = 7860

OLLAMA_URL = "http://127.0.0.1:11434"

SHAPE_REPO = "tencent/Hunyuan3D-2mv"
SHAPE_SUBFOLDER = "hunyuan3d-dit-v2-mv"
TEXGEN_REPO = "tencent/Hunyuan3D-2"
TEXGEN_SUBFOLDER = "hunyuan3d-paint-v2-0-turbo"
DELIGHT_SUBFOLDER = "hunyuan3d-delight-v2-0"

# --enable_flashvdm を渡すと、形状パイプラインが VAE を turbo 版に差し替える。
# これは 2mv 側ではなく tencent/Hunyuan3D-2 にあり、事前に落としておかないと
# 起動のたびに models/ の外（HF キャッシュ）へ落ちる。
VAE_TURBO_SUBFOLDER = "hunyuan3d-vae-v2-0-turbo"

# 重みと同じく models/ の下に閉じ込める実行時キャッシュ。
# HF キャッシュは Open WebUI（all-MiniLM-L6-v2）と共有されているので、
# このツールのぶんだけ別の場所へ向ける。
HF_HOME_DIR = MODELS_DIR / "hf"
U2NET_HOME_DIR = MODELS_DIR / "u2net"

# 形状モデルの重みのうち、実際に読み込まれるファイル。
# 同じ内容の model.fp16.ckpt（4.93GB）は不要なので落とさない。
SHAPE_WEIGHT_FILES = ("config.yaml", "model.fp16.safetensors")

UPSTREAM_URL = "https://github.com/Tencent-Hunyuan/Hunyuan3D-2"
UPSTREAM_COMMIT = "f8db63096c8282cb27354314d896feba5ba6ff8a"

VRAM_FREE_THRESHOLD_MIB = 1024
VRAM_WAIT_SECONDS = 60
