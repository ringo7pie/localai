"""パス・ポート・固定コミット・モデルの一覧を一元管理する。

このモジュールはファイルシステムに書き込まず、ネットワークにも触れない。
定数を並べるだけなので、素の python からでも import できる（cfui/config.py と同じ設計方針）。
setup-server.sh は venv を作る前に git を操作するため、同じ値を直値でも持っている。
片方を変えたらもう片方も変えること（tests/test_units.py が一致を確かめる）。

動かすモデルは 5 つある（同じ engine・venv・MTP の draft 層を共有し、同時には載せない）:
- rvn: RVN-Qwen3.8-Flash-Next IQ3_S（汎用版。ポート 8082、unit strata）。最初に入れたもの。
- coder: Qwen3.8-Flash-Next Coder IQ1_M（コード向け版。ポート 8083、unit strata-coder）。
- official: Qwen3.8-Flash-Next IQ3_XXS（公式・非 abliterated。ポート 8084、unit strata-official）。
- official-iq3s: Qwen3.8-Flash-Next IQ3_S（公式の軽い量子化。ポート 8085、unit strata-official-iq3s）。2026-10-16 に追加。
- swift: Swift 1.5 Qwen3.8-Flash-Next IQ3_XXS（思考を短く終える fine-tune。ポート 8086、unit strata-swift）。2026-10-16 に追加。
モデルごとの値は ModelSpec にまとめ、MODELS から --model の名前で引く。rvn の値は、以前からある
モジュール直下の定数（MODEL_DIR・GGUF_PATH・PORT ...）にも残す（既存の呼び出し元と試験の互換のため）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# このファイルは tools/strata/stra/config.py なので、2 つ上が tools/strata。
TOOL_DIR = Path(__file__).resolve().parents[1]

VENDOR_DIR = TOOL_DIR / "vendor"
STRATA_DIR = VENDOR_DIR / "Strata"
# setup.py と同じ置き場（上流の .gitignore が除外している）。上流の tools/_paths.py は gguf-py をここに探す。
LLAMA_CPP_DIR = STRATA_DIR / "third_party" / "llama.cpp"
BUILD_DIR = STRATA_DIR / "build"
ENGINE_DIR = STRATA_DIR / "engine"
ENGINE_EXE = ENGINE_DIR / "strata"
# server.py は engine/BUILD.json の version を読む（serve/server.py:582-583）。setup-server.sh が書く。
BUILD_STAMP = ENGINE_DIR / "BUILD.json"
EXPERT_PROFILE = STRATA_DIR / "data" / "expert-profile.bin"

MODELS_DIR = TOOL_DIR / "models"
MODEL_DIR = MODELS_DIR / "RVN-Qwen3.8-Flash-Next-IQ3_S"
GGUF_NAME = "RVN-Qwen3.8-Flash-Next-IQ3_S-merged.gguf"
GGUF_PATH = MODEL_DIR / GGUF_NAME
PACK_DIR = MODEL_DIR / "pack"
TOKENIZER_DIR = PACK_DIR / "tokenizer"
# MTP の draft 層（scripts/build-mtp.sh が作る）。RVN の pack には含まれない。engine は rt/ を読む。
# 元の Qwen3.8-Flash-Next の mtp.* から作るもので、Coder と公式版も同じものを使う（上流 setup.py も
# モデルに関わらず 1 つの mtp/rt を共有する。setup.py:4744-4760）。
MTP_DIR = MODELS_DIR / "mtp"
MTP_RT_DIR = MTP_DIR / "rt"

# serve が毎回書き直すサーバー設定（exe / args / cwd ...、docs/ORCA.md:53-76 の形）。
# server.py は Web 画面で変えた設定をこの隣（<名前>.shared-settings.json）に書くので、書ける場所に置く。
RUN_DIR = TOOL_DIR / "run"
SERVER_CONFIG = RUN_DIR / "strata-server.json"
LOGS_DIR = TOOL_DIR / "logs"
# エンジン（C++）の stderr の行き先。サーバー（python）の出力は journal に出る。
ENGINE_LOG = LOGS_DIR / "strata-engine.log"
VENV_PYTHON = TOOL_DIR / ".venv" / "bin" / "python"

HOST = "0.0.0.0"
# 8080（入口ページ）・8081・8000・8188（ComfyUI）は使用中。上流サーバーの既定 8095 も使わない。
PORT = 8082
# /v1/models が返す名前。Open WebUI の一覧は約 28 文字で切れるので短くする（server.py の model_name）。
MODEL_NAME = "strata-flash-next:IQ3_S"

# エンジンのビルドは CUDA 13.2 で行う。理由は README の「CUDA 13.2 でビルドした理由」。
CUDA_HOME = "/usr/local/cuda-13.2"
EXPECTED_NVCC_RELEASE = "13.2"
# A30 は sm_80。CMakeLists.txt:7-9 のとおり、エンジンは sm_80 以上だけを受け付ける。
CUDA_ARCH = "80"

STRATA_URL = "https://github.com/Niko1221/Strata.git"
STRATA_TAG = "v0.1.44.1"
STRATA_COMMIT = "296b59d2f73c8f04a805df29c2fa97655adace78"
# CMakeLists.txt の project(strata VERSION ...)。v0.1.44.1 は 4 桁目まで入っている。
STRATA_ENGINE_VERSION = "0.1.44.1"
# setup.py の LLAMA_CPP_COMMIT と同じ（ggml をこの版から静的に組み込む。third_party/ggml/VERSION.txt）。
LLAMA_CPP_URL = "https://github.com/ggml-org/llama.cpp.git"
LLAMA_CPP_COMMIT = "3cf03257f219afbe7334045ff7c6a06ac68c627d"

HF_BASE_URL = "https://huggingface.co"
MODEL_REPO = "jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata"
# 2026-10-07 に取得した時点のコミット（api/models の sha、lastModified 2026-10-01）。上流 setup.py と同じく
# 版を固定し、resolve/<コミット>/ から取る（main が差し替わっても同じものが入る）。
MODEL_REVISION = "17876139539724fc6f0b0fbfdcf7b1daa494d045"
# (リポジトリ内のパス, バイト数, sha256)。LFS の 2 つは HF の oid。残りは取得後に計算し、
# HF の git blob sha1 と一致することを確かめた値（2026-10-07）。
MODEL_FILES: tuple[tuple[str, int, str], ...] = (
    ("README.md", 7286, "5da79f5ed5042a478f1ac4b645e14adfd6af4b695747b43ff6dd71ae146969d4"),
    ("pack/compat-bf16.json", 52646, "3db32aa1f65249085be696fa1501249751dd811555cc1b339210a341946e98bf"),
    ("pack/index.txt", 93658, "5c99b418378081fef01e24dd468764eb428055b69ec1feb71af7fee07eb62d24"),
    ("pack/native_experts.txt", 3316, "034a1fd993938c6bbf75043e680721673323026758f188b8cfb23468eb63d0d4"),
    ("pack/tokenizer/chat_template.jinja", 8952, "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041"),
    ("pack/tokenizer/merges.txt", 3353258, "4ba698529766c7a2f5052083ea10cdf2485577f5237a332ee291054eb11e3332"),
    ("pack/tokenizer/token_type.json", 744960, "5088c8c298fc06af8382ddb3b76c888703ac2634e82263b97eedcc2ad202738b"),
    ("pack/tokenizer/tokenizer.json", 541, "c0bd435efbc6c3b28964b47999afe16c4ad268c7c7c4e8cb3af410796a6f30bf"),
    ("pack/tokenizer/vocab.json", 5737005, "4ba64f0332abcfb0b600b7df1537d1e836e68009d5fb7cdb77339738dc6365c4"),
    ("pack/dense.bin", 1538035200, "4f87fa3fb3bb87155fada5e0abb05df3d6c9a2872cd70cc3d9f3cc40a7d87eda"),
    (GGUF_NAME, 88882765184, "cb5958e5b0e97804fa2973f7ce36943a1b0d735b1b83fc1e52b8c3f3b97f87e6"),
)
# pack/native_experts.txt の見出しの total（48 層 x 512 エキスパートの合計バイト数、53.3 GiB）。
EXPERT_BYTES = 57252249600

# コンテキスト長。モデルの上限 262144（5 つの GGUF の context_length）。65536 → 131072（2026-10-07 の実測: 生成は 5〜7% 遅くなるだけで、
# RAM の固定は 38.53→39.42 GiB）→ 262144（2026-10-18、利用者の指示「A30 に収まる最大に」）と広げた。KV は int8 で VRAM に置く
# （約 13.7 KB/トークン。262144 で約 3.5 GiB）ので RAM はほぼ増えず、減るのは GPU のエキスパートの枠（10-07 の Coder の実測で
# 131072 → 262144 は 8138 → 7136）。通常モードは --kv-grow（使った分だけ KV を確保）で枠を取り戻す（各 ModelSpec の engine_extra_args）。
# env ファイルの STRATA_MAX_CONTEXT で変えられる。
DEFAULT_MAX_CONTEXT = 262144
ENV_FILE = Path.home() / ".config" / "strata" / "strata.env"
MAX_CONTEXT_ENV_VAR = "STRATA_MAX_CONTEXT"
# 思考の予算（トークン数）。0 で無効。設定 JSON の reasoning_budget_tokens に入る（run-strata serve が毎回書き直す）。
REASONING_BUDGET_ENV_VAR = "STRATA_REASONING_BUDGET_TOKENS"
# エンジンに足す引数（例: --stats）。シェルと同じ規則で分ける。
EXTRA_ARGS_ENV_VAR = "STRATA_EXTRA_ARGS"

SERVICE_NAME = "strata"
SERVICE_EXAMPLE = TOOL_DIR / "systemd" / "strata.service.example"

OLLAMA_URL = "http://127.0.0.1:11434"

# doctor の RAM の目安。engine は GPU が持たないエキスパートを RAM に写してページロックする（実測 40.56 GiB、
# 131072・MTP あり）。engine は空きから 4 GiB を残して写す量を決め、足りなければ一部をファイルから読む
# （遅くなるが動く）。全量を写すには 40.56 + 4 + engine の作業領域 約 1.5 で約 46 GiB の空きが要った。
# 2026-10-18 から 262144 と KV ストリーミング（--kv-resident 65536。KV 3.09 GiB を RAM に置く）で、落とせない分は
# 実測 46.2 GiB（shmem 44.67 + anon 1.50）。+ engine が残す 4 GiB で約 50 GiB。
MIN_AVAILABLE_RAM_GIB = 50
# 起動前に空いていてほしい VRAM。エキスパートのキャッシュは空き VRAM に合わせて決まる（--expert-cache auto）。
# Qwen（Ollama、約 22 GB）が載っていると、キャッシュがほとんど取れない。
MIN_FREE_VRAM_MIB = 20000
# memlock の上限の目安。エンジンはエキスパートの RAM 複製を cudaHostRegister で固定し、
# 固定できなかった残りを mlock で RAM に留める（src/core/pinned.cu:354-455）。
RECOMMENDED_MEMLOCK_BYTES = 48 * 1024**3


@dataclass(frozen=True)
class ModelSpec:
    """1 つのモデルを動かすのに要る値。stra の serve / doctor / fetch-models / wait-ready は --model でこれを選ぶ。"""

    # --model に渡す名前（rvn / coder / official）
    key: str
    # doctor・ログに出す人向けの名前
    title: str
    model_dir: Path
    # HF のリポジトリと固定コミット。files は (リポジトリ内のパス, バイト数, sha256)。
    # 置き場は model_dir / リポジトリ内のパス（HF と同じ並び）。
    repo: str
    revision: str
    files: tuple[tuple[str, int, str], ...]
    # engine の --native（分割された GGUF なら shard 1。iq_pack.py もこれを読む）と --ple-gguf
    # （PLE の n-gram 表 per_layer_token_embd.weight を持つ GGUF）。
    native_gguf: Path
    ple_gguf: Path
    pack_dir: Path
    # True なら pack は HF に無く、setup-server.sh が tools/iq_pack.py で手元に作る（files に含めない）。
    pack_built_locally: bool
    expert_profile: Path
    # pack/native_experts.txt の見出しの total（エキスパートの合計バイト数）
    expert_bytes: int
    model_name: str
    port: int
    service_name: str
    service_example: Path
    env_file: Path
    server_config: Path
    engine_log: Path
    # --resident-experts（low-RAM モードの resident 版）を付けるか。付けないとエキスパートを全部 RAM に写す。
    resident_experts: bool
    # --kv-resident の値（KV ストリーミング。KV を RAM に置き、VRAM には直近の窓だけ）。None なら付けない。
    kv_resident: int | None
    default_max_context: int
    # doctor の RAM の目安（止まっているときに要る MemAvailable）
    min_available_ram_gib: float
    recommended_memlock_bytes: int
    # 起動前に空いていてほしい VRAM（表示のみ）。エキスパートのキャッシュは起動時の空き VRAM で決まる。
    min_free_vram_mib: int = MIN_FREE_VRAM_MIB
    # 上流サーバーの設定 JSON に足す鍵（serve/server.py が読む sampling・reasoning_loop_recovery など）。
    # 汎用版・Coder・公式版とも reasoning_loop_recovery を足す（sampling の既定は足さない。CODER の注記）。
    server_options: Mapping[str, Any] = field(default_factory=dict)
    # 思考（thinking）の予算の既定（トークン数）。0 は予算なし。0 より大きければ、serve が上流の鍵
    # "reasoning_budget_tokens" として設定 JSON に足す（上流は予算に達すると wrap-up の文と </think> を差し込んで
    # 答えを書かせる。docs/DETAILS.md の "A hard thinking budget"）。env ファイルの STRATA_REASONING_BUDGET_TOKENS で変える。
    default_reasoning_budget_tokens: int = 0
    # モデル固有に engine へ足す引数（例: ("--adapt-async", "1")）。env の STRATA_EXTRA_ARGS と serve --extra はこの後ろに付く
    # （後ろのものが同じ引数を上書きできる）。2026-10-17〜18 の実測で採った速さの設定を置く（README の各モデルの節）。
    engine_extra_args: tuple[str, ...] = ()

    @property
    def tokenizer_dir(self) -> Path:
        return self.pack_dir / "tokenizer"


RVN = ModelSpec(
    key="rvn",
    title="RVN-Qwen3.8-Flash-Next IQ3_S（汎用版）",
    model_dir=MODEL_DIR,
    repo=MODEL_REPO,
    revision=MODEL_REVISION,
    files=MODEL_FILES,
    native_gguf=GGUF_PATH,
    # 1 ファイルに結合済みなので、PLE の表も同じ GGUF にある
    ple_gguf=GGUF_PATH,
    pack_dir=PACK_DIR,
    pack_built_locally=False,
    expert_profile=EXPERT_PROFILE,
    expert_bytes=EXPERT_BYTES,
    model_name=MODEL_NAME,
    port=PORT,
    service_name=SERVICE_NAME,
    service_example=SERVICE_EXAMPLE,
    env_file=ENV_FILE,
    server_config=SERVER_CONFIG,
    engine_log=ENGINE_LOG,
    resident_experts=True,
    # KV ストリーミング（KV を RAM に置き、VRAM には直近の 65536 セル）。2026-10-18 の実測（greedy・262144・--adapt-async 1）:
    # 無しだと 4K 入力・thinking あり 72.9 tok/s・枠 6,549、有りだと 76.0・枠 7,732（短い質問 53.9 → 60.3、4K thinking なし
    # 59.8 → 62.1）。RAM は +1.0 GiB（落とせない分 45.1 → 46.2 GiB）、起動 88 → 94 秒。公式 IQ3_S では差が 2% で RAM +2.3 GiB
    # だったので付けていない。README の「速さの設定と文脈長 262144」。
    kv_resident=65536,
    default_max_context=DEFAULT_MAX_CONTEXT,
    min_available_ram_gib=MIN_AVAILABLE_RAM_GIB,
    recommended_memlock_bytes=RECOMMENDED_MEMLOCK_BYTES,
    server_options={
        # Coder と同じ #728 の回復（理由と仕組みは CODER の server_options の注記）。2026-10-07、8082 で同じ 3D の
        # 問題が 130,597 トークンの上限まで thinking のまま答えを出さなかった（2 回。2498 秒）ので足した。
        # 再現では、反復の割合が 8,000 トークンで 0.228、24,000 トークン（effort low）で 0.293 になった。
        "reasoning_loop_recovery": "recover",
    },
    # 2026-10-07 の実測（8082、同じ 3D の問題、52 tok/s で約 10.5 分）: 予算なしでは 130,597 トークンの上限まで
    # thinking のまま答えが 0 トークンだった。16384 では (1) だけ正解、32768 で (1)〜(3) が正解。
    default_reasoning_budget_tokens=32768,
    # --adapt-async 1（GPU のキャッシュの入れ替えを生成の合間に裏で進める）。2026-10-18 の実測（131072、greedy）: 4K 入力・thinking あり
    # 64.5 → 73.3 tok/s（+14%）、短い質問 49.8 → 55.4、4K thinking なし 51.4 → 60.3。resident 版では --kv-grow は使えない（engine が無効にする）。
    engine_extra_args=("--adapt-async", "1"),
)

# ---------------------------------------------------------------- Coder（コード向け版）
# ISTA-DASLab の Coder: 各層 512 エキスパートのうち、コード・ツール使用・画像のデータで選んだ 256 を残したもの
# （上流 setup.py の FAMILIES["coder"]・MODELS["IQ1_M"]、docs/MODELS.md の Coder）。general.architecture は
# 汎用版と同じ qwen4exp。量子化は IQ1_M の 1 種類だけ（名前は IQ1_M だが、エキスパートは IQ3_S と同じ型で保存）。
# HF には GGUF しか無いので、pack（index.txt・dense.bin・native_experts.txt・tokenizer/）は手元で作る。
CODER_DIR = MODELS_DIR / "Qwen3.8-Flash-Next-Coder-IQ1_M"
CODER_REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF"
# 2026-10-07 時点の main（api/models の sha、lastModified 2026-09-29）。Apache-2.0。
CODER_REVISION = "5348543e0147355ac9cbcb031184a3546350988e"
CODER_SHARD1 = "IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf"
CODER_SHARD2 = "IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf"
# GGUF の 2 つは HF の LFS oid（= sha256）と大きさ（tree API の ?blobs=true、2026-10-07）。README は取得後に
# 計算し、HF の git blob sha1（e28ec637...）と一致することを確かめた値。画像用の mmproj（0.85 GiB）は取らない
# （画像入力は使わない）。
CODER_FILES: tuple[tuple[str, int, str], ...] = (
    ("README.md", 10814, "4f504b330ca771db689f358cacd5afdde27b1cede5dbd6b24de82b2286668927"),
    (CODER_SHARD1, 29608446496, "e11083ba855e7666b48ea3f2db6a9c3a20c18751a012cc24f948de91b7087fad"),
    (CODER_SHARD2, 28800138432, "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113"),
)

CODER = ModelSpec(
    key="coder",
    title="Qwen3.8-Flash-Next Coder IQ1_M（コード向け版）",
    model_dir=CODER_DIR,
    repo=CODER_REPO,
    revision=CODER_REVISION,
    files=CODER_FILES,
    native_gguf=CODER_DIR / CODER_SHARD1,
    # PLE の n-gram 表は shard 2 にある（gguf_reader で確かめた。shard 2 は元の Qwen と同じファイル）
    ple_gguf=CODER_DIR / CODER_SHARD2,
    pack_dir=CODER_DIR / "pack",
    pack_built_locally=True,
    # 上流同梱の Coder 用 profile（FAMILIES["coder"]["profile"]）
    expert_profile=STRATA_DIR / "data" / "expert-profile-coder.bin",
    # 手元で作った pack/native_experts.txt の見出しの total（48 層 x 256 エキスパート、23.42 GiB。2026-10-07）。
    # 上流 setup.py の MODELS["IQ1_M"]["arena_gb"] 23.4 と同じ。
    expert_bytes=25146163200,
    # 24 文字（Open WebUI の一覧は約 28 文字で切れる）
    model_name="strata-flash-coder:IQ1_M",
    port=8083,
    service_name="strata-coder",
    service_example=TOOL_DIR / "systemd" / "strata-coder.service.example",
    env_file=Path.home() / ".config" / "strata" / "strata-coder.env",
    server_config=RUN_DIR / "strata-server-coder.json",
    engine_log=LOGS_DIR / "strata-coder-engine.log",
    # 2026-10-07 の実測で決めた（README の「コード向け版（Coder）」）。エキスパート 23.42 GiB は RAM に全部載るので、
    # 全部を RAM に写す通常のモードにする（--resident-experts は RAM が 16.7 GiB で済むが、greedy でそろえて
    # 4K 入力・thinking ありが 90.1→80.3 tok/s と遅い）。--kv-resident 32768（上流 setup.py がこの機体で選ぶ
    # KV ストリーミング）も遅くなる（同 103→96 tok/s。キャッシュ命中率が元から 97〜99% で、枠を増やす利点が小さい）。
    resident_experts=False,
    kv_resident=None,
    # 262144（モデルの上限。2026-10-18 に 131072 から広げた。DEFAULT_MAX_CONTEXT の注記）。10-07 の実測では 131072 → 262144 で
    # キャッシュ枠が 8138→7136 に減り greedy で 9〜21% 遅かったが、通常モードなので --kv-grow で枠を取り戻せる（engine_extra_args）。
    # env ファイルの STRATA_MAX_CONTEXT で戻せる。
    default_max_context=DEFAULT_MAX_CONTEXT,
    # 落とせない分 約 26.2 GiB（ページロックしたエキスパート 23.42 GiB を含む）+ 余裕 約 4 GiB
    min_available_ram_gib=30,
    recommended_memlock_bytes=32 * 1024**3,
    server_options={
        # 上流の #728（既定は無効）: reasoning の直近 2,000 語の 25% 以上が 3 回以上出た 12 語の並びになったら、
        # low の effort に差し替えて続きから考え直させる（1 要求に 1 回まで。temperature を 1.0 以上・
        # presence_penalty を 1.5 以上に上げて続ける）。2026-10-07 の実測（コード生成の課題、thinking xhigh）:
        # 無しでは greedy の 3 回中 2 回が reasoning のまま 16384 トークンの上限まで同じ文を繰り返した（上流 issue
        # #1015）。有りでは反復を検出した 7 回すべてが考え直して答えまで届いた（日本語・英語、greedy・temp 1.0）。
        # 要求が送らないときのサンプリングの既定（"sampling"、GGUF の推奨 temp 1.0 / top_p 0.95 / top_k 20）は
        # 入れない。入れると日本語の課題で 3 回中 2 回が「実」の 1 トークンの繰り返しに陥り、答えが出なかった
        # （greedy では 5 回とも起きなかった）。README の「コード向け版（Coder）」。
        "reasoning_loop_recovery": "recover",
    },
    # 思考の予算は付けない。2026-10-07 の汎用版の要望（予算なしで答えが 0 トークン）の対象外で、
    # Coder は上の #728 の回復で足りている実測がある。env ファイルで足したいときは STRATA_REASONING_BUDGET_TOKENS。
    default_reasoning_budget_tokens=0,
    # 2026-10-17〜18 の実測（greedy）。--kv-grow は KV を使った分だけ VRAM に取り、残りをキャッシュの枠に回す（通常モード限定）:
    # 262144 でも枠 8,752（131072・kv-grow なしの 8,135 より多い）。--adapt-async 1 と合わせて 4K 入力・thinking あり 81.0 tok/s
    # （131072 の基準 78.2）、短い質問 78.7（基準 81.6）。Coder は回ごとの揺れが大きく（同じ条件で 78〜101）、差は誤差の範囲。
    engine_extra_args=("--adapt-async", "1", "--kv-grow"),
)

# ---------------------------------------------------------------- 公式版（非 abliterated）
# ISTA-DASLab の GSQ-RCO 量子化そのもの（abliteration をしていない元の Qwen3.8-Flash-Next）。上流 setup.py の
# FAMILIES["qwen"]・MODELS["IQ3_XXS"] にあたる。各層 512 エキスパートのまま（Coder のような間引きは無い）。
# 同じリポジトリに Q2_0 / IQ2_XS / IQ3_S もあるが、取るのは IQ3_XXS だけ。HF には GGUF しか無いので、
# pack は Coder と同じく手元で作る（run-strata build-pack --model official）。
OFFICIAL_DIR = MODELS_DIR / "Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS"
OFFICIAL_REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
# 2026-10-07 の HF API（api/models の sha、lastModified 2026-09-29）。Apache-2.0。上流 setup.py:66 の固定と同じコミット。
OFFICIAL_REVISION = "ed59f92082b1e93c0e96d60a8b11aab089b52f09"
OFFICIAL_SHARD1 = "IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf"
OFFICIAL_SHARD2 = "IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf"
# GGUF の 2 つは HF の LFS oid（= sha256）と大きさ（tree API の ?blobs=true、2026-10-07）。shard 2（PLE の n-gram 表）は
# Coder の shard 2 と大きさ・sha256 が同じファイル（同じリポジトリの他の量子化の shard 2 とも同じ）なので、
# ハードリンクで置ける。README は取得後に計算し、HF の git blob sha1（5e40a3fe...）と一致することを確かめた値。
# 画像用の mmproj（0.85 GiB）は取らない（画像入力は使わない）。
OFFICIAL_FILES: tuple[tuple[str, int, str], ...] = (
    ("README.md", 15693, "71496aac3c9126085519dbe3aa82e46eb9f5749ee122b089a66182a94b0db6a3"),
    (OFFICIAL_SHARD1, 47039860096, "219ea929900dfa9ef091f3aa473fdba6874b65fcb36526d7d851ac9e95856d15"),
    (OFFICIAL_SHARD2, 28800138432, "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113"),
)

OFFICIAL = ModelSpec(
    key="official",
    title="Qwen3.8-Flash-Next IQ3_XXS（公式・非 abliterated）",
    model_dir=OFFICIAL_DIR,
    repo=OFFICIAL_REPO,
    revision=OFFICIAL_REVISION,
    files=OFFICIAL_FILES,
    native_gguf=OFFICIAL_DIR / OFFICIAL_SHARD1,
    # PLE の n-gram 表は shard 2 にある（Coder と同じファイル。上流 docs/AMD_HIP.md の IQ3_XXS の起動例も
    # --ple-gguf に shard 2 を渡す）。build-pack は gguf_reader で表の有無を確かめてから作る。
    ple_gguf=OFFICIAL_DIR / OFFICIAL_SHARD2,
    pack_dir=OFFICIAL_DIR / "pack",
    pack_built_locally=True,
    # 汎用の profile（RVN と同じもの）。上流 FAMILIES["qwen"] は profile を持たず、既定の expert-profile.bin を使う。
    expert_profile=EXPERT_PROFILE,
    # TODO: 仮置き。pack を作ったら pack/native_experts.txt の見出しの total で直す（tests/test_units.py が照合する）。
    # 見込みの根拠: HF の tensor-allocation/...IQ3_XXS-00001-of-00002.rco-allocation.txt にある各層の
    # ffn_{gate,up,down}_exps の型（gate/up は IQ2_XXS〜IQ3_S、down は IQ4_NL か Q2_0）に、RVN の native_experts.txt から
    # 求めた 1 行列の要素数 1,638,400 と 512 エキスパートを掛けた合計（48 層、39.97 GiB）。上流 setup.py の
    # MODELS["IQ3_XXS"]["arena_gb"] 42.9 と GB（10^9）で合う（Coder の 23.4 は GiB で合っており、上流の単位はそろっていない）。
    expert_bytes=42912972800,
    # 23 文字（Open WebUI の一覧は約 28 文字で切れる）
    model_name="strata-official:IQ3_XXS",
    port=8084,
    service_name="strata-official",
    service_example=TOOL_DIR / "systemd" / "strata-official.service.example",
    env_file=Path.home() / ".config" / "strata" / "strata-official.env",
    server_config=RUN_DIR / "strata-server-official.json",
    engine_log=LOGS_DIR / "strata-official-engine.log",
    # 動かし方は 2026-10-17 の実測で決めた（greedy・同じ問題・3 回の中央値。README の「公式版」の「速さの設定」）。上流 setup.py も
    # この RAM なら --resident-experts の無い通常のモードを選ぶ（setup.py:2725 の low_ram_needed: RAM < arena_gb + 10 のときだけ low-RAM）。
    # - 通常のモード（エキスパート 39.97 GiB を全部 RAM に写してページロック。anon 41.45 GiB・shmem 0.49 GiB）: 4K 入力・thinking あり
    #   98.0 tok/s、短い質問 69.1、prefill 1,400。resident 版（shmem 28.4 GiB）は 89.8〜91.9 / 56.9〜57.9 / 1,254〜1,270 で 8〜20% 遅い。
    #   起動は 41 秒 vs 45 秒。落とせない分 約 42.3 GiB は MemoryHigh 50G に収まる（残り約 7.7 GiB が page cache）。
    resident_experts=False,
    kv_resident=None,
    default_max_context=DEFAULT_MAX_CONTEXT,
    min_available_ram_gib=46,
    recommended_memlock_bytes=48 * 1024**3,
    server_options={
        # 汎用版・Coder と同じ #728 の回復（理由と仕組みは CODER と RVN の server_options の注記）
        "reasoning_loop_recovery": "recover",
    },
    # 答えが必ず返るための安全弁（RVN の注記）。ただし RVN の 32768 より大きくする。2026-10-07 の実測で、3D の問題を
    # 予算なしで 2 回流すと 53,975 / 49,161 トークンで収束し 2 回とも全問正解だったが、どちらも thinking が 32,768 を
    # 超えていた（32768 では収束の前に打ち切る）。65536 は 60 tok/s で約 18 分。README の「公式版」の実測。
    # sampling の既定は入れない（同じ日の実験で、temperature 1.0・presence_penalty 1.0 のどれも RVN を収束させなかった）。
    default_reasoning_budget_tokens=65536,
    # 2026-10-17〜18 の実測（greedy、通常モード）: 131072 で --adapt-async 1 が 98.0 → 104.3 tok/s（4K 入力・thinking あり）、
    # 262144 + --adapt-async 1 + --kv-grow で 102.9・枠 10,452（131072・kv-grow なしの 9,728 より多い）。STRATA_IQ3S_MT1=1 は効かず、
    # --kv-grow 単独も 131072 では速さを変えない（枠だけ 10,593 に増える）。
    engine_extra_args=("--adapt-async", "1", "--kv-grow"),
)

# ---------------------------------------------------------------- 公式版 IQ3_S（同じ公式モデルの、軽い量子化）
# 公式版（IQ3_XXS）と同じリポジトリ・同じ固定リビジョンの IQ3_S。Q8_0 との KL は IQ3_XXS 0.202 → IQ3_S 0.144（上流 docs/QUANTS.md）で、
# 上流 setup.py の RECOMMENDED_SIZES（0.1.44）はこれ。1 トークンあたりは IQ3_XXS より 2〜3 割遅い見込み。
# 2026-10-16 に足した理由: AI モデル評価（Documents/AIモデル評価_2026-10-08.html）で Strata の弱点が「思考が終わらず予算で打ち切られる」
# ことで、量子化だけを変えた比較が無かった（Documents/Strata_コーディング性能の調査_2026-10-09.html）。
OFFICIAL_IQ3S_DIR = MODELS_DIR / "Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S"
OFFICIAL_IQ3S_SHARD1 = "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf"
OFFICIAL_IQ3S_SHARD2 = "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf"
# shard 1 は HF の tree API（?blobs=true、2026-10-16）の LFS oid と大きさ。README と shard 2 は公式版（IQ3_XXS）と同じファイル
# （shard 2 は Coder・公式版の shard 2 とも同じで、ハードリンクで置ける）。
OFFICIAL_IQ3S_FILES: tuple[tuple[str, int, str], ...] = (
    ("README.md", 15693, "71496aac3c9126085519dbe3aa82e46eb9f5749ee122b089a66182a94b0db6a3"),
    (OFFICIAL_IQ3S_SHARD1, 54817524224, "4c1eb2ceb4915e1192f4f386021897bde56a97f40a0bb78bb86465e0f7d2aca3"),
    (OFFICIAL_IQ3S_SHARD2, 28800138432, "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113"),
)

OFFICIAL_IQ3S = ModelSpec(
    key="official-iq3s",
    title="Qwen3.8-Flash-Next IQ3_S（公式・非 abliterated、軽い量子化）",
    model_dir=OFFICIAL_IQ3S_DIR,
    repo=OFFICIAL_REPO,
    revision=OFFICIAL_REVISION,
    files=OFFICIAL_IQ3S_FILES,
    native_gguf=OFFICIAL_IQ3S_DIR / OFFICIAL_IQ3S_SHARD1,
    # PLE の n-gram 表は shard 2（公式版と同じファイル）
    ple_gguf=OFFICIAL_IQ3S_DIR / OFFICIAL_IQ3S_SHARD2,
    pack_dir=OFFICIAL_IQ3S_DIR / "pack",
    pack_built_locally=True,
    expert_profile=EXPERT_PROFILE,
    # 手元で作った pack/native_experts.txt の見出しの total（48 層 x 512 エキスパート、46.84 GiB。2026-10-16）。上流コミュニティの実測
    # （bench/results/2026-10-09-community-rtx-3060-0141 の IQ3_S の experts.bin）と同じ値。tests/test_units.py が pack と照合する。
    expert_bytes=50292326400,
    # 21 文字（Open WebUI の一覧は約 28 文字で切れる）
    model_name="strata-official:IQ3_S",
    port=8085,
    service_name="strata-official-iq3s",
    service_example=TOOL_DIR / "systemd" / "strata-official-iq3s.service.example",
    env_file=Path.home() / ".config" / "strata" / "strata-official-iq3s.env",
    server_config=RUN_DIR / "strata-server-official-iq3s.json",
    engine_log=LOGS_DIR / "strata-official-iq3s-engine.log",
    # エキスパート 46.84 GiB は、全部を RAM に写す通常のモード（エキスパート + 約 10 GB）では MemoryHigh 50G に収まらないので、
    # RVN（53.3 GiB）と同じ low-RAM の resident 版（GPU が持たない分だけ RAM に写す。見込み 約 31 GiB）。
    resident_experts=True,
    kv_resident=None,
    default_max_context=DEFAULT_MAX_CONTEXT,
    min_available_ram_gib=46,
    recommended_memlock_bytes=48 * 1024**3,
    server_options={
        # ほかの 4 つと同じ #728 の回復（理由と仕組みは CODER と RVN の server_options の注記）
        "reasoning_loop_recovery": "recover",
    },
    # 公式版（IQ3_XXS）と同じ安全弁。3D の問題で公式版の thinking は 32,768 を超えてから収束した（OFFICIAL の注記）。
    default_reasoning_budget_tokens=65536,
    # 2026-10-17〜18 の実測（greedy、resident 版）: 131072 で --adapt-async 1 が 74.9 → 83.8 tok/s（4K 入力・thinking あり）、262144 では 83.1
    # （枠 7,146）。--kv-resident 65536 を足すと 84.8・枠 8,503 だが RAM が +2.3 GiB（落とせない分 39.5 → 40.5 GiB）で、差 2% は誤差の範囲なので付けない。
    engine_extra_args=("--adapt-async", "1"),
)

# ---------------------------------------------------------------- Swift 1.5（思考を短く終える fine-tune）
# UkisAI が Qwen3.8-Flash-Next を post-training した派生で、同じアーキテクチャ（qwen4exp、512 エキスパート/層）。作者の BF16・xhigh の
# 計測では思考トークンが中央値で 63% 減り、精度の差は 1% 未満（GPQA 89.8→89.6、AIME 98.7→96.7、LiveCodeBench 88.4→90.4）。
# 上流 Strata 0.1.44 は family "swift" として正式に対応し、「1 トークンの速さは元と同じ」と報告する（docs/DETAILS.md の
# "Or: Swift 1.5"）。量子化は ISTA の GSQ-RCO の allocation profile を再利用した UkisAI 自身の配布（同じ IQ3_XXS）。
# 2026-10-16 に足した理由は OFFICIAL_IQ3S と同じ（思考が終わらない症状にモデルの側から当たる）。
# ライセンスは Swift Open License v1.0（年商 100 万ドル以上の法人の商用利用は別契約。非商用・研究用途は可）+ 元の Qwen の
# Qwen Community License 1.0。この機体では個人・非商用の研究用途（2026-10-16 の利用者の判断）。NOTICE.md に書いてある。
SWIFT_DIR = MODELS_DIR / "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS"
SWIFT_REPO = "ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
# 2026-10-16 の HF API（api/models の sha、lastModified 2026-10-07。IQ3_S の tier を足した版）
SWIFT_REVISION = "99bb8f7f95c7aa7b24a36a7786a4f657b30f5d3d"
# HF のリポジトリはサブディレクトリを持たず、ルート直下に 4 サイズ分の GGUF を並べている（置き場も同じ並び）
SWIFT_SHARD1 = "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf"
SWIFT_SHARD2 = "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf"
# GGUF の 2 つは HF の LFS oid（= sha256。配布元の SHA256SUMS とも一致）と大きさ（tree API、2026-10-16）。
# README・LICENSE・LICENSE-QWEN・NOTICE は取得後に計算し、HF の git blob sha1 と一致することを確かめた値（2026-10-16）。
# 元の Qwen と違い shard 2 は別物（層 13〜47 のエキスパートが shard 2、PLE の n-gram 表が shard 1。上流 tools/iq_pack.py の注記）。
# 画像用の mmproj（0.91 GiB）は取らない（画像入力は使わない）。
SWIFT_FILES: tuple[tuple[str, int, str], ...] = (
    ("README.md", 9654, "c4bcb450391cb9cb5cd3ff63117993462bdcbf35b8b2c166c6d396a4c012502e"),
    ("LICENSE", 13323, "7a3af3e6b43fcb7c486ea8167252a36a9532dcbdf02d1704a749881872ec551c"),
    ("LICENSE-QWEN", 3235, "a0dc422560841fd68e06d974907f8b4c709bca44a67daad2b528437bdf676c08"),
    ("NOTICE", 1514, "adfc6658815ecb4ddb26b1e3018c819104866b6c54f15e6b63b73827fa40c884"),
    (SWIFT_SHARD1, 39785790560, "3bddaa667c750f63baca766df9433e1afd35a139f401c5ca5e7ff560ceff3d23"),
    (SWIFT_SHARD2, 36180282560, "b0b15f782af71eb471909d2f3313b2927c324962f86c084325c247cd411a0160"),
)

SWIFT = ModelSpec(
    key="swift",
    title="Swift 1.5 Qwen3.8-Flash-Next IQ3_XXS（思考を短く終える fine-tune、非 abliterated）",
    model_dir=SWIFT_DIR,
    repo=SWIFT_REPO,
    revision=SWIFT_REVISION,
    files=SWIFT_FILES,
    native_gguf=SWIFT_DIR / SWIFT_SHARD1,
    # PLE の n-gram 表は shard 1（build-pack が gguf_reader で確かめてから作る）
    ple_gguf=SWIFT_DIR / SWIFT_SHARD1,
    pack_dir=SWIFT_DIR / "pack",
    pack_built_locally=True,
    # 上流 FAMILIES["swift"] は profile を持たず、既定の expert-profile.bin（汎用・公式版と同じ）を使う
    expert_profile=EXPERT_PROFILE,
    # 手元で作った pack/native_experts.txt の見出しの total（48 層 x 512 エキスパート、39.97 GiB。2026-10-16）。ISTA の IQ3_XXS の
    # allocation profile を再利用しているので公式版（IQ3_XXS）と同じ値。層 12〜47 のエキスパートは shard 2 にある（native_experts.txt の
    # shard 列）。tests/test_units.py が pack と照合する。
    expert_bytes=42912972800,
    # 20 文字（Open WebUI の一覧は約 28 文字で切れる）
    model_name="strata-swift:IQ3_XXS",
    port=8086,
    service_name="strata-swift",
    service_example=TOOL_DIR / "systemd" / "strata-swift.service.example",
    env_file=Path.home() / ".config" / "strata" / "strata-swift.env",
    server_config=RUN_DIR / "strata-server-swift.json",
    engine_log=LOGS_DIR / "strata-swift-engine.log",
    # 公式版（IQ3_XXS）と同じ量子化・同じ大きさで、同じ通常モード（エキスパート 39.97 GiB を全部 RAM に写す）。2026-10-18 の実測
    # （greedy・262144・--adapt-async 1）: 通常モード + --kv-grow 105.9 tok/s（4K 入力・thinking あり、枠 10,452、anon 41.80 GiB）、
    # resident 版 94.9（枠 8,601、shmem 30.5 GiB）、resident 版 + --kv-resident 65536 97.9（枠 10,178）。RAM は増えるが MemoryHigh 50G に収まる。
    resident_experts=False,
    kv_resident=None,
    default_max_context=DEFAULT_MAX_CONTEXT,
    min_available_ram_gib=46,
    recommended_memlock_bytes=48 * 1024**3,
    server_options={
        # ほかの 4 つと同じ #728 の回復
        "reasoning_loop_recovery": "recover",
    },
    # 公式版と同じ安全弁。短く考えるモデルなので届かない見込みだが、届いたら答えを書かせる
    default_reasoning_budget_tokens=65536,
    # 公式版と同じ（上の resident_experts の注記の実測）
    engine_extra_args=("--adapt-async", "1", "--kv-grow"),
)

MODELS: dict[str, ModelSpec] = {spec.key: spec for spec in (RVN, CODER, OFFICIAL, OFFICIAL_IQ3S, SWIFT)}
DEFAULT_MODEL = "rvn"


def model_spec(key: str) -> ModelSpec:
    """--model の名前からモデルの値を返す。知らない名前なら ValueError。"""

    try:
        return MODELS[key]
    except KeyError:
        raise ValueError(f"知らないモデルです: {key}（{' / '.join(MODELS)} のどれか）") from None
