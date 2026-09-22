#!/usr/bin/env bash
# A30 サーバーで Pixal3D を 1 回の実行で導入する（冪等。再実行は既存物を触らない）。
#
# torch（cu126）と重み合計 約30GB をダウンロードする。実行前に空きディスクとネットワークを確認すること。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$TOOL_DIR/.venv"
VENDOR_DIR="$TOOL_DIR/vendor/Pixal3D"
TRELLIS_DIR="$TOOL_DIR/vendor/TRELLIS.2"
RUNNER="$TOOL_DIR/run-pixal3d"

# px3d/config.py の UPSTREAM_URL / UPSTREAM_COMMIT / TRELLIS_URL / TRELLIS_COMMIT と一致させること
# （venv 構築前に git 操作をするため、ここでは python を経由せず直値で持つ）。
UPSTREAM_URL="https://github.com/TencentARC/Pixal3D.git"
UPSTREAM_COMMIT="f7cf38429b0bd264f1995f0f8743a88b1c728b94"
TRELLIS_URL="https://github.com/microsoft/TRELLIS.2.git"
TRELLIS_COMMIT="75fbf0183001ed9876c8dbb35de6b68552ee08bd"

# torch / torchvision は cu126 の index から入れる（requirements.lock.txt には書かない）。
# venv に既に torch==2.6.0+cu126 が入っている状態を基準にしている（CUDA 12.6 を使うため）。
TORCH_INDEX_URL="https://download.pytorch.org/whl/cu126"
TORCH_SPEC="torch==2.6.0+cu126"
TORCHVISION_SPEC="torchvision==0.21.0+cu126"

# Pixal3D は /usr/local/cuda-12.6 を使う（/usr/local/cuda は 13.2 で Hunyuan3D 用。触らない）。
CUDA_HOME_DIR="/usr/local/cuda-12.6"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --skip-models   重みの取得を省略する（あとで run-pixal3d fetch-models を手で実行する）
  --no-autostart  PC 起動時の自動起動を有効にしない（使うときだけ手で起動する）
  --build-only    venv・上流取得・torch・依存・ネイティブ拡張・自前パッケージ（px3d）までで止める。
                  重みの取得・systemd ユニットの作成・doctor は行わない
                  （拡張ビルドだけを繰り返し検証したいときに使う）
  -h, --help      この説明を表示して終了
EOF
}

SKIP_MODELS=false
NO_AUTOSTART=false
BUILD_ONLY=false
while [ $# -gt 0 ]
do
  case "$1" in
    --skip-models)
      SKIP_MODELS=true
      shift
      ;;
    --no-autostart)
      NO_AUTOSTART=true
      shift
      ;;
    --build-only)
      BUILD_ONLY=true
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

echo "== Pixal3D 導入（A30 サーバー） =="

# ---------------------------------------------------------------- [1/10]
echo
echo "[1/10] CUDA 12.6 の確認"
if [ -x "$CUDA_HOME_DIR/bin/nvcc" ]; then
  NVCC_VERSION="$("$CUDA_HOME_DIR/bin/nvcc" --version | tail -1)"
  echo "nvcc: 確認しました（$CUDA_HOME_DIR/bin/nvcc, $NVCC_VERSION）"
else
  echo "$CUDA_HOME_DIR/bin/nvcc が見つかりません。Pixal3D は CUDA 12.6 を使います" >&2
  echo "（/usr/local/cuda は 13.2 で Hunyuan3D 用のため、代わりに使えません）。" >&2
  exit 1
fi

# ---------------------------------------------------------------- [2/10]
echo
echo "[2/10] uv と venv（Python 3.10）"
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
  "$UV_BIN" venv --python 3.10 "$VENV_DIR"
  echo "venv: 作成しました（$VENV_DIR）"
fi

# ---------------------------------------------------------------- [3/10]
echo
echo "[3/10] 上流の取得（Pixal3D $UPSTREAM_COMMIT / TRELLIS.2 $TRELLIS_COMMIT）"
fetch_pinned_repo() {
  # $1=URL $2=commit $3=取得先ディレクトリ $4=表示名
  local url="$1" commit="$2" dir="$3" label="$4"
  if [ -d "$dir/.git" ]; then
    local current_head
    current_head="$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo "")"
    if [ "$current_head" = "$commit" ]; then
      echo "$label: 既にあります（$dir, HEAD=$current_head）"
    else
      echo "$label は既にありますが、指定コミットではありません（HEAD=$current_head）。" >&2
      echo "勝手に張り替えないで終了します。確認して手動で対処してください: $dir" >&2
      exit 1
    fi
  else
    mkdir -p "$(dirname -- "$dir")"
    git init "$dir"
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch --depth 1 origin "$commit"
    git -C "$dir" checkout FETCH_HEAD
    echo "$label: 取得しました（$dir）"
  fi
}
fetch_pinned_repo "$UPSTREAM_URL" "$UPSTREAM_COMMIT" "$VENDOR_DIR" "Pixal3D"
fetch_pinned_repo "$TRELLIS_URL" "$TRELLIS_COMMIT" "$TRELLIS_DIR" "TRELLIS.2"

# 上流への当て物があれば、固定コミットに対して当てる（今のところ無いが hy3d に倣い型だけ用意する）。
PATCH_DIR="$TOOL_DIR/patches"
if [ -d "$PATCH_DIR" ]; then
  for patch_file in "$PATCH_DIR"/*.patch
  do
    [ -e "$patch_file" ] || continue
    patch_name="$(basename -- "$patch_file")"
    if git -C "$VENDOR_DIR" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
      echo "パッチ $patch_name: 既に当たっています"
    elif git -C "$VENDOR_DIR" apply --check "$patch_file" >/dev/null 2>&1; then
      git -C "$VENDOR_DIR" apply "$patch_file"
      echo "パッチ $patch_name: 当てました"
    else
      echo "パッチ $patch_name を当てられません。上流の内容を確認してください。" >&2
      exit 1
    fi
  done
fi

# ---------------------------------------------------------------- [4/10]
echo
echo "[4/10] torch（$TORCH_INDEX_URL）"
if "$VENV_DIR/bin/python" -c "import torch" >/dev/null 2>&1; then
  echo "torch: 既にあります"
else
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" \
    --index-url "$TORCH_INDEX_URL" \
    "$TORCH_SPEC" "$TORCHVISION_SPEC"
  echo "torch: 導入しました（$TORCH_SPEC, $TORCHVISION_SPEC）"
fi

# ---------------------------------------------------------------- [5/10]
echo
echo "[5/10] 依存（requirements.lock.txt）"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -r "$TOOL_DIR/requirements.lock.txt"
echo "依存: 導入しました"

# ---------------------------------------------------------------- [6/10]
# ネイティブ拡張の取得元。上流 TRELLIS.2 の setup.sh はコミットを固定しないが、
# 再現性のため 2026-09-22 にビルドが通った版に固定する。
FLEXGEMM_URL="https://github.com/JeffreyXiang/FlexGEMM.git"
FLEXGEMM_COMMIT="6dd94a859c26ee8246888502eada3dd8ad85532e"
CUMESH_URL="https://github.com/JeffreyXiang/CuMesh.git"
CUMESH_COMMIT="12289e1062f0603f2f0d0771b02e1395d247f26f"
NVDIFFREC_URL="https://github.com/JeffreyXiang/nvdiffrec.git"
NVDIFFREC_COMMIT="b296927cc7fd01c2ac1087c8065c4d7248f72da4"
NVDIFFRAST_URL="https://github.com/NVlabs/nvdiffrast.git"
NVDIFFRAST_COMMIT="253ac4fcea7de5f396371124af597e6cc957bfae"
NATTEN_VERSION="0.21.0"

# 拡張のソースを固定コミットで取ってくる。既にあれば何もしない。
clone_extension() {
  extension_name="$1"
  extension_url="$2"
  extension_commit="$3"
  clone_mode="$4"
  target="$EXT_DIR/$extension_name"
  if [ -d "$target/.git" ]; then
    echo "  $extension_name のソース: 既にあります"
    return 0
  fi
  mkdir -p "$EXT_DIR"
  if [ "$clone_mode" = recursive ]; then
    git clone --recursive "$extension_url" "$target"
  else
    git clone "$extension_url" "$target"
  fi
  git -C "$target" checkout -q "$extension_commit"
  if [ "$clone_mode" = recursive ]; then
    git -C "$target" submodule update --init --recursive
  fi
  echo "  $extension_name のソース: 取得しました（$extension_commit）"
}

# 2026-09-22 に A30（sm80）/ CUDA 12.6 / gcc 13.3 / torch 2.6.0+cu126 で実測した手順。
# 合計およそ 17 分。natten だけが 11 分を占める。
#
# flash-attn は入れない。上流 README が ATTN_BACKEND=sdpa で動くと明記しており、
# sdpa なら Ampere で追加のビルドが要らない。
EXT_DIR="$TOOL_DIR/vendor/extensions"

# 拡張を 1 本ビルドして入れる。ログは各拡張ごとのファイルへ落とす。
# `| tee` でつながないこと。終了コードが握り潰される。
#
# 第 3 引数以降は env に渡す KEY=VALUE。pip 側に足したい引数は、呼ぶ直前に
# EXTRA_PIP_ARGS に入れる（使い切りで、呼び出しのたびに空に戻す）。
EXTRA_PIP_ARGS=()
install_extension() {
  extension_name="$1"
  extension_path="$2"
  shift 2
  log_file="$EXT_DIR/build-$extension_name.log"
  echo "  $extension_name をビルドしています（ログ: $log_file）"
  if ! env \
      CUDA_HOME="$CUDA_HOME_DIR" \
      CUDACXX="$CUDA_HOME_DIR/bin/nvcc" \
      CUDAToolkit_ROOT="$CUDA_HOME_DIR" \
      PATH="$CUDA_HOME_DIR/bin:$PATH" \
      TORCH_CUDA_ARCH_LIST=8.0 \
      MAX_JOBS=4 \
      "$@" \
      "$UV_BIN" pip install --python "$VENV_DIR/bin/python" \
        "$extension_path" --no-build-isolation "${EXTRA_PIP_ARGS[@]}" \
        > "$log_file" 2>&1; then
    EXTRA_PIP_ARGS=()
    echo "  $extension_name のビルドに失敗しました。$log_file を確認してください。" >&2
    return 1
  fi
  EXTRA_PIP_ARGS=()
  echo "  $extension_name: 入りました"
}

build_native_extensions() {
  mkdir -p "$EXT_DIR"

  # o-voxel は TRELLIS.2 に同梱されている（上流 setup.sh も cp してからビルドする）。
  # --no-deps が要る: pyproject が cumesh と flex_gemm を git+URL の実行時依存に持っており、
  # そのままだと uv がコミット未固定の clone を勝手にビルドしてしまう。
  # 実行時に要る純 Python の依存（plyfile・zstandard・easydict など）は
  # requirements.lock.txt 側で入っている。
  if ! "$VENV_DIR/bin/python" -c "import o_voxel" >/dev/null 2>&1; then
    rm -rf "$EXT_DIR/o-voxel"
    cp -r "$TRELLIS_DIR/o-voxel" "$EXT_DIR/o-voxel"
    EXTRA_PIP_ARGS=(--no-deps)
    install_extension o-voxel "$EXT_DIR/o-voxel" || return 1
  fi

  clone_extension FlexGEMM "$FLEXGEMM_URL" "$FLEXGEMM_COMMIT" recursive || return 1
  if ! "$VENV_DIR/bin/python" -c "import flex_gemm" >/dev/null 2>&1; then
    install_extension FlexGEMM "$EXT_DIR/FlexGEMM" || return 1
  fi

  clone_extension CuMesh "$CUMESH_URL" "$CUMESH_COMMIT" recursive || return 1
  if ! "$VENV_DIR/bin/python" -c "import cumesh" >/dev/null 2>&1; then
    install_extension CuMesh "$EXT_DIR/CuMesh" || return 1
  fi

  clone_extension nvdiffrec "$NVDIFFREC_URL" "$NVDIFFREC_COMMIT" plain || return 1
  if ! "$VENV_DIR/bin/python" -c "import nvdiffrec_render" >/dev/null 2>&1; then
    install_extension nvdiffrec "$EXT_DIR/nvdiffrec" || return 1
  fi

  clone_extension nvdiffrast "$NVDIFFRAST_URL" "$NVDIFFRAST_COMMIT" plain || return 1
  if ! "$VENV_DIR/bin/python" -c "import nvdiffrast.torch" >/dev/null 2>&1; then
    install_extension nvdiffrast "$EXT_DIR/nvdiffrast" || return 1
  fi

  # natten は wheel を使わずソースからビルドする。
  # whl.natten.org の 0.21.0 は torch 2.7.0 用しか無く、上流の
  # requirements-hfdemo.txt にある wheel は「H 系 GPU 用」と明記されていて
  # sm80 のカーネルを含む保証が無い。sdist に cutlass が同梱されているので追加取得は不要。
  # NATTEN_BUILD_DIR を固定パスにしておくと、途中で落ちても作り直しから再開できる。
  if ! "$VENV_DIR/bin/python" -c "import natten" >/dev/null 2>&1; then
    natten_src="$EXT_DIR/natten-src/natten-$NATTEN_VERSION"
    if [ ! -d "$natten_src" ]; then
      mkdir -p "$EXT_DIR/natten-src"
      curl -sSL -o "$EXT_DIR/natten-src/natten-$NATTEN_VERSION.tar.gz" \
        "https://files.pythonhosted.org/packages/source/n/natten/natten-$NATTEN_VERSION.tar.gz"
      tar xzf "$EXT_DIR/natten-src/natten-$NATTEN_VERSION.tar.gz" -C "$EXT_DIR/natten-src"
    fi
    echo "  natten は 10 分ほどかかります（157 本のカーネルをコンパイルします）"
    install_extension natten "$natten_src" \
      NATTEN_CUDA_ARCH=8.0 \
      NATTEN_N_WORKERS=8 \
      NATTEN_BUILD_DIR="$EXT_DIR/natten-build" || return 1
  fi
}
echo
echo "[6/10] ネイティブ拡張（o-voxel / FlexGEMM / CuMesh / nvdiffrast / nvdiffrec / natten）"
build_native_extensions
if "$VENV_DIR/bin/python" -c "import o_voxel, cumesh, flex_gemm, nvdiffrast.torch, nvdiffrec_render" >/dev/null 2>&1; then
  echo "拡張ビルド: 確認しました（すべて import できました）"
else
  echo "拡張ビルド: 未完了です（build_native_extensions は骨格のみ。手動で導入するか、検証済みの手順を待ってください）"
fi

# ---------------------------------------------------------------- [7/10]
echo
echo "[7/10] 自前パッケージ（px3d）"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -e "$TOOL_DIR"
echo "px3d: 導入しました"

if $BUILD_ONLY; then
  echo
  echo "--build-only が指定されたため、ここで終了します。"
  echo "次にやること:"
  echo "  - 重みの取得: $RUNNER fetch-models"
  echo "  - systemd ユニットの作成: このスクリプトを --build-only 無しで再実行する"
  echo "  - 点検: $RUNNER doctor"
  exit 0
fi

# ---------------------------------------------------------------- [8/10]
echo
echo "[8/10] 重みの取得"
if $SKIP_MODELS; then
  echo "重み取得: 省略しました（--skip-models）。あとで '$RUNNER fetch-models' を実行してください"
else
  "$RUNNER" fetch-models
  echo "重み取得: 完了しました"
fi

# ---------------------------------------------------------------- [9/10]
echo
echo "[9/10] systemd user ユニットと低 VRAM の env ファイル"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/pixal3d.service"
if [ -f "$SERVICE_FILE" ]; then
  echo "systemd ユニット: 既にあります（$SERVICE_FILE）"
else
  mkdir -p "$SYSTEMD_USER_DIR"
  cp -p "$TOOL_DIR/systemd/pixal3d.service.example" "$SERVICE_FILE"
  echo "systemd ユニット: 作成しました（$SERVICE_FILE）"
fi

ENV_DIR="$HOME/.config/pixal3d"
ENV_FILE="$ENV_DIR/pixal3d.env"
if [ -f "$ENV_FILE" ]; then
  echo "env ファイル: 既にあります（$ENV_FILE）"
else
  mkdir -p "$ENV_DIR"
  # tools/portal（入口ページ）が書き換える前提の既定値。px3d/config.py の LOW_VRAM_DEFAULT と同じ（有効）。
  printf 'PIXAL3D_LOW_VRAM=1\n' > "$ENV_FILE"
  chmod 644 "$ENV_FILE"
  echo "env ファイル: 作成しました（$ENV_FILE, PIXAL3D_LOW_VRAM=1）"
fi

systemctl --user daemon-reload
if $NO_AUTOSTART; then
  echo "自動起動: 設定しませんでした（--no-autostart）"
  echo "手で起動する: systemctl --user start pixal3d"
else
  systemctl --user enable --now pixal3d
  echo "自動起動: 有効にしました（PC 起動時に立ち上がります）"
  echo "止める: systemctl --user stop pixal3d ／ 自動起動をやめる: systemctl --user disable pixal3d"
fi

# ---------------------------------------------------------------- [10/10]
echo
echo "[10/10] 点検"
DOCTOR_RC=0
"$RUNNER" doctor || DOCTOR_RC=$?
if [ "$DOCTOR_RC" -eq 0 ]; then
  echo "点検: 合格しました"
else
  echo "点検: 一部 NG があります（終了コード $DOCTOR_RC）。上の出力を確認してください"
fi

echo
echo "次にやること:"
echo "  - 手動起動: $RUNNER serve"
echo "  - systemd 経由: systemctl --user start pixal3d"
echo "  - ブラウザ（直接）: http://<server-ip>:7861"
echo "  - 入口ページ経由: http://<server-ip>:8080"
exit "$DOCTOR_RC"
