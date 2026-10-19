#!/usr/bin/env bash
# A30 サーバーで推論エンジン Strata（v0.1.44.1）を組み立て、RVN-Qwen3.8-Flash-Next IQ3_S（Strata 用 pack 付き）を
# 動かせる状態にする（冪等。再実行は既存物を触らない）。
#
# 上流の ./setup.sh → setup.py は対話式で、足りないものを sudo apt / pip で入れ、Linux では engine を
# その場でコンパイルする（Linux 用のビルド済み engine は配布されていない。setup.py:2644-2702）。
# ここでは同じ手順を非対話で、sudo を使わずに行う。apt が要るものが無ければ、名前を示して止まる。
#
# モデル 約 89 GB と MTP の draft 層の材料 約 5 GB をダウンロードする。実行前に空きディスク（約 100 GB）と
# ネットワークを確認すること。
#
# --model coder でコード向け版（Qwen3.8-Flash-Next Coder IQ1_M、約 55 GiB）を足す。engine・venv・vendor・
# MTP の draft 層は汎用版と共有し、できていれば作り直さない。Coder の pack は HF に無いので手元で作る。
# --model official で公式版（非 abliterated の Qwen3.8-Flash-Next IQ3_XXS、約 70.6 GiB。shard 2 は Coder と同じファイルで、
# ハードリンクで置いてあれば取らない）を足す。pack は Coder と同じく手元で作る。
# --model official-iq3s で公式版の軽い量子化 IQ3_S（shard 1 約 51.1 GiB。shard 2 は公式版・Coder と同じファイル）を足す。
# --model swift で Swift 1.5（UkisAI の fine-tune、IQ3_XXS、2 shard 約 70.7 GiB。shard 2 は元とは別物）を足す。どちらも pack は手元で作る。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$TOOL_DIR/.venv"
VENDOR_DIR="$TOOL_DIR/vendor"
STRATA_DIR="$VENDOR_DIR/Strata"
LLAMA_CPP_DIR="$STRATA_DIR/third_party/llama.cpp"
BUILD_DIR="$STRATA_DIR/build"
ENGINE_DIR="$STRATA_DIR/engine"
LOG_DIR="$TOOL_DIR/logs"
RUNNER="$TOOL_DIR/run-strata"

# 雛形の書き出し（render_unit_file / render_unit_text）と、終わりに表示する URL のホスト（detect_server_host）
# shellcheck source=../../scripts/lib/render-unit.sh
source "$TOOL_DIR/../../scripts/lib/render-unit.sh"
# shellcheck source=../../scripts/lib/server-host.sh
source "$TOOL_DIR/../../scripts/lib/server-host.sh"

# stra/config.py の STRATA_* / LLAMA_CPP_* / CUDA_* と一致させること
# （venv 構築前に git 操作をするため、ここでは python を経由せず直値で持つ）。
STRATA_URL="https://github.com/Niko1221/Strata.git"
STRATA_TAG="v0.1.44.1"
STRATA_COMMIT="296b59d2f73c8f04a805df29c2fa97655adace78"
STRATA_ENGINE_VERSION="0.1.44.1"
LLAMA_CPP_URL="https://github.com/ggml-org/llama.cpp.git"
LLAMA_CPP_COMMIT="3cf03257f219afbe7334045ff7c6a06ac68c627d"
# CUDA 13.2 でビルドする。12.6 にすると setup.py は実験扱いの CUDA 12 engine（-DSTRATA_EXPERIMENTAL_SM60=ON、
# setup.py:2624-2628）になる。13.x は sm_75 以上に対応し、配布 engine と同じ系統（README 参照）。
CUDA_HOME_DIR="/usr/local/cuda-13.2"
CUDA_ARCH="80"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --skip-models   モデルと MTP の draft 層の取得を省略する（あとで run-strata fetch-models と
                  scripts/build-mtp.sh を手で実行する）
  --build-only    venv・上流取得・依存・engine のビルドまでで止める。モデルの取得・systemd ユニットの配置・
                  doctor は行わない
  --rebuild       engine を作り直す（build/ は残すので、変わったところだけコンパイルされる）
  --model NAME    対象のモデル。rvn（既定、汎用版、ポート 8082、unit strata）・
                  coder（コード向け版、ポート 8083、unit strata-coder）・
                  official（公式版・非 abliterated、ポート 8084、unit strata-official）・
                  official-iq3s（公式版の軽い量子化 IQ3_S、ポート 8085、unit strata-official-iq3s）・
                  swift（Swift 1.5 IQ3_XXS、ポート 8086、unit strata-swift）のどれか。engine などは共有する
  -h, --help      この説明を表示して終了

systemd ユニットは配置と daemon-reload だけを行い、enable（自動起動）はしない。
EOF
}

SKIP_MODELS=false
BUILD_ONLY=false
REBUILD=false
MODEL_KEY="rvn"
while [ $# -gt 0 ]
do
  case "$1" in
    --model)
      if [ $# -lt 2 ]; then
        echo "--model には rvn・coder・official・official-iq3s・swift のどれかを続けてください" >&2
        exit 2
      fi
      MODEL_KEY="$2"
      shift 2
      ;;
    --model=*)
      MODEL_KEY="${1#--model=}"
      shift
      ;;
    --skip-models)
      SKIP_MODELS=true
      shift
      ;;
    --build-only)
      BUILD_ONLY=true
      shift
      ;;
    --rebuild)
      REBUILD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知の引数: $1" >&2
      usage
      exit 2
      ;;
  esac
done

# モデルごとの名前（stra/config.py の MODELS と一致させること。tests/test_units.py が確かめる）。
# PACK_BUILT_LOCALLY は config.py の pack_built_locally（HF に pack が無く、[6/8] で build-pack を呼ぶか）。
case "$MODEL_KEY" in
  rvn)
    SERVICE_NAME="strata"
    MODEL_PORT="8082"
    ENV_NAME="strata.env"
    PACK_BUILT_LOCALLY=false
    ;;
  coder)
    SERVICE_NAME="strata-coder"
    MODEL_PORT="8083"
    ENV_NAME="strata-coder.env"
    PACK_BUILT_LOCALLY=true
    ;;
  official)
    SERVICE_NAME="strata-official"
    MODEL_PORT="8084"
    ENV_NAME="strata-official.env"
    PACK_BUILT_LOCALLY=true
    ;;
  official-iq3s)
    SERVICE_NAME="strata-official-iq3s"
    MODEL_PORT="8085"
    ENV_NAME="strata-official-iq3s.env"
    PACK_BUILT_LOCALLY=true
    ;;
  swift)
    SERVICE_NAME="strata-swift"
    MODEL_PORT="8086"
    ENV_NAME="strata-swift.env"
    PACK_BUILT_LOCALLY=true
    ;;
  *)
    echo "知らないモデルです: $MODEL_KEY（rvn・coder・official・official-iq3s・swift のどれか）" >&2
    exit 2
    ;;
esac

mkdir -p "$LOG_DIR"
echo "== Strata 導入（A30 サーバー、モデル: $MODEL_KEY） =="

# ---------------------------------------------------------------- [1/8]
echo
echo "[1/8] CUDA 13.2 と C++ コンパイラの確認"
if [ -x "$CUDA_HOME_DIR/bin/nvcc" ]; then
  NVCC_VERSION="$("$CUDA_HOME_DIR/bin/nvcc" --version | tail -1)"
  echo "nvcc: 確認しました（$CUDA_HOME_DIR/bin/nvcc, $NVCC_VERSION）"
else
  echo "$CUDA_HOME_DIR/bin/nvcc が見つかりません。engine は CUDA 13.2 でビルドします。" >&2
  echo "上流の自動導入（sudo apt-get install cuda-toolkit-13-0、setup.py:2556-2565）はここでは行いません。" >&2
  exit 1
fi
# 上流の setup.py は g++ が無ければ sudo apt-get install build-essential を実行する（setup.py:2552-2553）。
# ここでは入れずに止める。
MISSING_APT=()
for compiler in g++ gcc
do
  if ! command -v "$compiler" >/dev/null 2>&1; then
    MISSING_APT+=(build-essential)
    break
  fi
done
if ! command -v git >/dev/null 2>&1; then
  MISSING_APT+=(git)
fi
if ! command -v curl >/dev/null 2>&1; then
  MISSING_APT+=(curl)
fi
if [ "${#MISSING_APT[@]}" -gt 0 ]; then
  echo "apt のパッケージが足りません: ${MISSING_APT[*]}" >&2
  echo "利用者が入れてください: sudo apt-get install -y ${MISSING_APT[*]}" >&2
  exit 3
fi
echo "C++ コンパイラ: 確認しました（$(g++ --version | head -1)）"

# ---------------------------------------------------------------- [2/8]
echo
echo "[2/8] uv と venv（uv 管理の Python 3.12）"
if [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
elif command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
else
  echo "uv がありません。導入方法:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "導入後にこのスクリプトを再実行してください。" >&2
  exit 2
fi

if [ -d "$VENV_DIR" ]; then
  echo "venv: 既にあります（$VENV_DIR）"
else
  # 上流の setup.sh はシステムの python3 -m venv を使い、python3-venv が無ければ sudo apt で入れる。
  # ここでは uv 管理の 3.12 に固定する（comfyui / Hunyuan3D / Pixal3D と同じ考え方）。
  "$UV_BIN" venv --managed-python --python 3.12 "$VENV_DIR"
  echo "venv: 作成しました（$VENV_DIR）"
fi

# ---------------------------------------------------------------- 共通の取得関数
# 固定コミットで浅く取得する。既にあって HEAD が違えば、勝手に張り替えずに止める。
fetch_pinned_repo() {
  # $1=URL $2=commit $3=取得先ディレクトリ $4=表示名
  local url="$1" commit="$2" dir="$3" label="$4"
  if [ -d "$dir/.git" ]; then
    local current_head
    current_head="$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo "")"
    if [ "$current_head" = "$commit" ]; then
      echo "  $label: 既にあります（HEAD=$current_head）"
    else
      echo "  $label は既にありますが、指定コミットではありません（HEAD=$current_head）。" >&2
      echo "  勝手に張り替えないで終了します。確認して手動で対処してください: $dir" >&2
      exit 1
    fi
  else
    mkdir -p "$(dirname -- "$dir")"
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 origin "$commit"
    git -C "$dir" checkout -q FETCH_HEAD
    echo "  $label: 取得しました（$commit）"
  fi
}

# ---------------------------------------------------------------- [3/8]
echo
echo "[3/8] Strata 本体（$STRATA_TAG = $STRATA_COMMIT）と llama.cpp（$LLAMA_CPP_COMMIT）"
fetch_pinned_repo "$STRATA_URL" "$STRATA_COMMIT" "$STRATA_DIR" "Strata"
# setup.py の get_llama_cpp() は GitHub の zip を third_party/llama.cpp に展開する（setup.py:1389-1419）。
# ここでは同じコミットを git で取る（zip は中身の同一性が保証されないため）。置き場は同じなので、
# 上流の tools/_paths.py が gguf-py を見つけられる。
fetch_pinned_repo "$LLAMA_CPP_URL" "$LLAMA_CPP_COMMIT" "$LLAMA_CPP_DIR" "llama.cpp（ggml と gguf-py）"
if [ ! -f "$LLAMA_CPP_DIR/ggml/CMakeLists.txt" ] || [ ! -d "$LLAMA_CPP_DIR/gguf-py" ]; then
  echo "llama.cpp に ggml/CMakeLists.txt か gguf-py がありません: $LLAMA_CPP_DIR" >&2
  exit 1
fi

# ---------------------------------------------------------------- [4/8]
echo
echo "[4/8] Python の依存（上流の requirements.txt、版固定）と自前パッケージ（stra）"
# 上流 setup.py の pip_install と同じ一覧（numpy, jinja2, regex, ..., cmake, ninja）。cmake と ninja は
# engine のビルドに使う（setup.py:2575-2577 も venv の cmake / ninja を探す）。
# setup.py が ready-made engine 用に入れる nvidia-cublas / nvidia-cuda-runtime の wheel は入れない
# （ローカルビルドの engine はツールキットの lib64 を使う。setup.py:2695-2696 と同じ）。
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -r "$STRATA_DIR/requirements.txt" >/dev/null
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -e "$TOOL_DIR" >/dev/null
echo "依存: 導入しました（$("$VENV_DIR/bin/cmake" --version | head -1), ninja $("$VENV_DIR/bin/ninja" --version)）"

# ---------------------------------------------------------------- [5/8]
echo
echo "[5/8] engine のビルド（CUDA 13.2、sm_$CUDA_ARCH）"
# setup.py の build_engine() / cmake_build() と同じ引数（setup.py:2575-2598, 2681-2686）。
# 違いは CUDA のパスを固定すること（setup.py の find_nvcc は一番新しい nvcc を選ぶ）と、
# --target strata の並列数（setup.py は CPU 数の半分。i7-12700 の 20 スレッドで 10）。
ENGINE_EXE="$ENGINE_DIR/strata"
BUILD_STAMP="$ENGINE_DIR/BUILD.json"
STAMP_OK=false
if [ -x "$ENGINE_EXE" ] && [ -f "$BUILD_STAMP" ] \
    && grep -q "\"src\": \"$STRATA_COMMIT\"" "$BUILD_STAMP" \
    && grep -q "\"cuda\": \"$CUDA_HOME_DIR\"" "$BUILD_STAMP"; then
  STAMP_OK=true
fi
if $STAMP_OK && ! $REBUILD; then
  echo "engine: 既にあります（$ENGINE_EXE、$BUILD_STAMP の src と cuda が一致）"
else
  CONFIGURE_LOG="$LOG_DIR/build-strata-configure.log"
  BUILD_LOG="$LOG_DIR/build-strata.log"
  BUILD_JOBS=10
  echo "  cmake の構成（ログ: $CONFIGURE_LOG）"
  # `| tee` でつながないこと。終了コードが握り潰される。
  if ! env PATH="$CUDA_HOME_DIR/bin:$VENV_DIR/bin:$PATH" CUDACXX="$CUDA_HOME_DIR/bin/nvcc" \
      "$VENV_DIR/bin/cmake" -G Ninja -DCMAKE_MAKE_PROGRAM="$VENV_DIR/bin/ninja" \
        -S "$STRATA_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release \
        -DSTRATA_ENABLE_CUDA=ON -DSTRATA_BUILD_TESTS=OFF \
        -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \
        -DCMAKE_CUDA_COMPILER="$CUDA_HOME_DIR/bin/nvcc" \
        -DCUDAToolkit_ROOT="$CUDA_HOME_DIR" \
        -DSTRATA_GGML_DIR="$LLAMA_CPP_DIR" \
        > "$CONFIGURE_LOG" 2>&1; then
    echo "cmake の構成に失敗しました。$CONFIGURE_LOG を確認してください" >&2
    exit 1
  fi
  echo "  コンパイル（-j $BUILD_JOBS、初回は数十分。ログ: $BUILD_LOG）"
  # 上流と同じく 1 回だけやり直す: CUDA 13 の ptxas がまれに書いたばかりの PTX を読めず止まり、
  # 同じコマンドで先へ進む（setup.py:2594-2598, issue #45）。2 回目は残りだけをコンパイルする。
  build_once() {
    env PATH="$CUDA_HOME_DIR/bin:$VENV_DIR/bin:$PATH" \
      "$VENV_DIR/bin/cmake" --build "$BUILD_DIR" --target strata -j "$BUILD_JOBS" >> "$BUILD_LOG" 2>&1
  }
  : > "$BUILD_LOG"
  if ! build_once; then
    echo "  （ビルドが止まりました。1 回だけやり直します）"
    if ! build_once; then
      echo "engine のビルドに失敗しました。$BUILD_LOG を確認してください" >&2
      exit 1
    fi
  fi
  mkdir -p "$ENGINE_DIR"
  cp -p "$BUILD_DIR/strata" "$ENGINE_EXE"
  # server.py は engine/BUILD.json の version を表示に使う（serve/server.py:582-583）。
  # 書式は setup.py:2697-2700 に合わせ、ビルドに使ったコミットと CUDA のパスを足す（再実行の判定に使う）。
  cat > "$BUILD_STAMP" <<EOF
{
 "source": "local",
 "version": "$STRATA_ENGINE_VERSION",
 "archs": [$CUDA_ARCH],
 "vision": "none",
 "cuda_dirs": ["$CUDA_HOME_DIR/bin", "$CUDA_HOME_DIR/lib64"],
 "src": "$STRATA_COMMIT",
 "tag": "$STRATA_TAG",
 "cuda": "$CUDA_HOME_DIR",
 "built_by": "tools/strata/setup-server.sh"
}
EOF
  echo "engine: ビルドしました（$ENGINE_EXE）"
fi

if $BUILD_ONLY; then
  echo
  echo "--build-only が指定されたため、ここで終了します。"
  echo "次にやること:"
  echo "  - モデルの取得: $RUNNER fetch-models --model $MODEL_KEY"
  echo "  - systemd ユニット: このスクリプトを --build-only 無しで再実行する"
  echo "  - 点検: $RUNNER doctor --model $MODEL_KEY"
  exit 0
fi

# ---------------------------------------------------------------- [6/8]
echo
echo "[6/8] モデル（HF の resolve URL、途中から再開できる）と MTP の draft 層"
if $SKIP_MODELS; then
  echo "モデル取得: 省略しました（--skip-models）。あとで '$RUNNER fetch-models --model $MODEL_KEY' と"
  if $PACK_BUILT_LOCALLY; then
    echo "  '$RUNNER build-pack --model $MODEL_KEY' と"
  fi
  echo "  '$TOOL_DIR/scripts/build-mtp.sh' を実行してください"
else
  # 取得の直後に sha256 を確かめる（固定コミットの値と違えば止まる）
  "$RUNNER" fetch-models --model "$MODEL_KEY"
  echo "モデル取得: 完了しました"
  if $PACK_BUILT_LOCALLY; then
    # Coder と公式版は HF に pack が無い。上流 setup.py:4732-4737 と同じく tools/iq_pack.py で作る（できていれば何もしない）。
    "$RUNNER" build-pack --model "$MODEL_KEY"
  fi
  # RVN の pack は MTP を含まない。上流 setup.py と同じく元の Qwen のチェックポイントから作る（任意だが、
  # 実測で生成が最大 1.45 倍になった。README の「実機試験の結果」）。Coder と公式版も同じ draft 層を使う（共有、冪等）。
  "$TOOL_DIR/scripts/build-mtp.sh"
fi

# ---------------------------------------------------------------- [7/8]
echo
echo "[7/8] systemd user ユニットと env ファイル（enable はしない）"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/$SERVICE_NAME.service"
SERVICE_EXAMPLE="$TOOL_DIR/systemd/$SERVICE_NAME.service.example"
if [ -f "$SERVICE_FILE" ]; then
  echo "systemd ユニット: 既にあります（$SERVICE_FILE）"
  # 手で直したものかもしれないので上書きしない。雛形と違えば知らせるだけにする。
  # 雛形はリポジトリのパスが印（@REPO_ROOT@）のままなので、置き換えた中身と比べる。
  if ! cmp -s <(render_unit_text "$SERVICE_EXAMPLE") "$SERVICE_FILE"; then
    echo "  （雛形 $SERVICE_EXAMPLE の @REPO_ROOT@ を $LOCALAI_REPO_ROOT にしたものと中身が違います。diff で確かめ、必要なら手で写してください）"
  fi
else
  mkdir -p "$SYSTEMD_USER_DIR"
  # 雛形のリポジトリのパス（@REPO_ROOT@）をこの clone の絶対パスにして置く
  render_unit_file "$SERVICE_EXAMPLE" "$SERVICE_FILE"
  echo "systemd ユニット: 作成しました（$SERVICE_FILE）"
fi

ENV_DIR="$HOME/.config/strata"
ENV_FILE="$ENV_DIR/$ENV_NAME"
mkdir -p "$ENV_DIR"
if [ -f "$ENV_FILE" ]; then
  echo "env ファイル: 既にあります（$ENV_FILE）"
else
  cat > "$ENV_FILE" <<EOF
# $SERVICE_NAME.service が読む環境変数（run-strata serve --model $MODEL_KEY に渡る）。書式は KEY=値（シェルの展開はされない）。
# コンテキスト長（既定 131072。2026-10-07 の実測で決めた。README の「実機試験の結果」）。
# STRATA_MAX_CONTEXT=131072
# 思考の予算（トークン。既定は rvn が 32768、official・official-iq3s・swift が 65536、coder が 0。0 で無効。README の「汎用版で thinking が終わらないとき」）。
# STRATA_REASONING_BUDGET_TOKENS=32768
# engine に足す引数（シェルと同じ規則で分ける）。例: 統計を engine のログに出す
# STRATA_EXTRA_ARGS=--stats
# API キー（LAN に開いているので、付けるならここ）。server.py が読む。空の値にすると起動しない（上流の仕様）。
# STRATA_API_KEY=好きな文字列
EOF
  chmod 600 "$ENV_FILE"
  echo "env ファイル: 作成しました（$ENV_FILE、設定は空）"
fi

systemctl --user daemon-reload
echo "自動起動: 設定していません（enable しない方針）"
echo "手で起動する: systemctl --user start $SERVICE_NAME ／ 止める: systemctl --user stop $SERVICE_NAME"
echo "（strata・strata-coder・strata-official・strata-official-iq3s・strata-swift は Conflicts= で互いを止める。同時には載らない）"

# ---------------------------------------------------------------- [8/8]
echo
echo "[8/8] 点検"
DOCTOR_RC=0
"$RUNNER" doctor --model "$MODEL_KEY" || DOCTOR_RC=$?
if [ "$DOCTOR_RC" -eq 0 ]; then
  echo "点検: 合格しました"
else
  echo "点検: 一部 NG があります（終了コード $DOCTOR_RC）。上の出力を確認してください"
fi

SERVER_HOST="$(detect_server_host)"
echo
echo "次にやること:"
echo "  - 手動起動: $RUNNER serve --model $MODEL_KEY"
echo "  - systemd 経由: systemctl --user start $SERVICE_NAME（API が応答するまで戻らない。最大 15 分）"
echo "  - API: http://$SERVER_HOST:$MODEL_PORT/v1（モデル名は run-strata doctor --model $MODEL_KEY の表示を参照）"
exit "$DOCTOR_RC"
