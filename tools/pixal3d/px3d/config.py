"""パス・ポート・モデル ID を一元管理する。

このモジュールはファイルシステムに書き込まず、ネットワークにも触れない。
定数を並べるだけなので、素の python からでも torch なしで import できる
（hy3d/config.py と同じ設計方針）。
"""

from __future__ import annotations

from pathlib import Path

# このファイルは tools/pixal3d/px3d/config.py なので、2 つ上が tools/pixal3d。
TOOL_DIR = Path(__file__).resolve().parents[1]

VENDOR_DIR = TOOL_DIR / "vendor" / "Pixal3D"
TRELLIS_DIR = TOOL_DIR / "vendor" / "TRELLIS.2"
MODELS_DIR = TOOL_DIR / "models"
OUTPUTS_DIR = TOOL_DIR / "outputs"
VENV_PYTHON = TOOL_DIR / ".venv" / "bin" / "python"

HOST = "0.0.0.0"
PORT = 7861

# 入口ページ（tools/portal）のポート。doctor の待受確認にだけ使う。pixal3d が制御するものではない。
PORTAL_PORT = 8080

OLLAMA_URL = "http://127.0.0.1:11434"

MODEL_REPO = "TencentARC/Pixal3D"
PIPELINE_CONFIG = "pipeline_mv.json"

# Pipeline.from_pretrained(path, config_file) は f"{path}/{config_file}" があればローカル読み、
# 無ければ hf_hub_download に落ちる（vendor/Pixal3D/pixal3d/pipelines/base.py:22-50）。
# 実機で動作確認できたのは、path に MODEL_REPO（リポジトリ ID の文字列）をそのまま渡し、
# HF の標準キャッシュ（HF_HOME_DIR）から読ませる方式。プレーンなローカルディレクトリに
# 展開すると、キャッシュとあわせて重み約 24GB が二重に保存されるため、この方式は採らない。
# スナップショットの実体は px3d.cli.resolve_model_snapshot_dir() が指す場所にある
# （config.py はファイルシステムに触れない方針のため、走査する関数は cli.py 側に置く）。

# 背景除去モデル。pipeline_mv.json の rembg_model は briaai/RMBG-2.0 を指しているが、
# これは HF のゲート付きリポジトリで、ログインと利用規約への同意が無いと 401 GatedRepoError に
# なりダウンロードできない（実機で確認済み）。vendor/Pixal3D/pixal3d/pipelines/rembg/BiRefNet.py の
# BiRefNet クラスの既定値である、非ゲート・MIT ライセンスのこちらを代わりに使う
# （副次的に RMBG-2.0 の CC BY-NC 非商用制約も外れる）。px3d/rembg_override.py で、
# from_pretrained が組み立てる rembg_model をこの名前で強制する。
REMBG_MODEL = "ZhengPeng7/BiRefNet"

# 重みと同じく models/ の下に閉じ込める実行時キャッシュ。
# 既定の ~/.cache/huggingface のままだと Open WebUI（all-MiniLM-L6-v2）や、BiRefNet・DINOv3 の
# ミラーなど実行時に自動で落ちるモデルが Open WebUI の HF キャッシュと混ざる。
# このツールのぶんだけ別の場所へ向ける。
HF_HOME_DIR = MODELS_DIR / "hf"
# NAF（高解像度段の特徴アップサンプラ）は torch.hub 経由で valeoai/NAF を取りに行く。
# 既定のままだと ~/.cache/torch へ落ちるので、このツールの下へ向ける。
TORCH_HOME_DIR = MODELS_DIR / "torch"

# flash_attn は入れていない（vendor/Pixal3D/README.md が明記する代替経路）。
# inference_mv.py は os.environ.setdefault("ATTN_BACKEND", "flash_attn") なので、
# 起動前にこちらで先に設定しておかないと上書きされない。
ATTN_BACKEND = "sdpa"

UPSTREAM_URL = "https://github.com/TencentARC/Pixal3D.git"
UPSTREAM_COMMIT = "f7cf38429b0bd264f1995f0f8743a88b1c728b94"
TRELLIS_URL = "https://github.com/microsoft/TRELLIS.2.git"
TRELLIS_COMMIT = "75fbf0183001ed9876c8dbb35de6b68552ee08bd"

VRAM_FREE_THRESHOLD_MIB = 1024
VRAM_WAIT_SECONDS = 60

# 低 VRAM モード（--low_vram 相当）の切り替え。VRAM を RAM と引き換える設定。
# env ファイルのパスと変数名は tools/portal（入口ページ）と必ず一致させる。変えないこと。
# 入口ページが同じユーザーとしてこのファイルを書き換える想定なので、px3d 側は読むだけにする。
LOW_VRAM_ENV_FILE = Path.home() / ".config" / "pixal3d" / "pixal3d.env"
LOW_VRAM_ENV_VAR = "PIXAL3D_LOW_VRAM"
LOW_VRAM_DEFAULT = True

# 既定視点（vendor/Pixal3D/assets/mv_images/example/transforms.json と同じ値）。
# 4 方位を毎回orbitで 90 度ずつ回した rig（仰角 0、水平 FOV 20 度）。
DEFAULT_CAMERA_ANGLE_X = 0.3490658503988659  # 20 度（ラジアン）
DEFAULT_CAMERA_DISTANCE = 3.1192049980163574
DEFAULT_MESH_SCALE = 1.0

# 4 方位の並び順。frame 0（先頭）が正面固定 = check_main_view が前提とする正準姿勢。
VIEW_AZIMUTHS = ("front", "right", "back", "left")

VIEW_LABELS = {
    "front": "正面（0°）",
    "right": "右 90°",
    "back": "背面（180°）",
    "left": "左 270°",
}

# camera-to-world の 4x4（Z-up world、カメラは自分の -Z を向き +Y が上）。
# vendor/Pixal3D/assets/mv_images/example/transforms.json の frame 0〜3 と同じ値。
VIEW_TRANSFORM_MATRICES = {
    "front": [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, -DEFAULT_CAMERA_DISTANCE],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    "right": [
        [0.0, 0.0, 1.0, DEFAULT_CAMERA_DISTANCE],
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    "back": [
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, DEFAULT_CAMERA_DISTANCE],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    "left": [
        [0.0, 0.0, -1.0, -DEFAULT_CAMERA_DISTANCE],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
}

# Pixal3D は CUDA 12.6 を使う（/usr/local/cuda は 13.2 で Hunyuan3D 用。触らない）。
CUDA_HOME = "/usr/local/cuda-12.6"
