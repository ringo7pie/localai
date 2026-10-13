#!/usr/bin/env bash
# A30 サーバーで ComfyUI と PixelArtistry の防水メッシュ用ワークフロー 4 本を 1 回の実行で導入する
# （冪等。再実行は既存物を触らない）。配布元の Windows 用インストーラ
# （vendor/PixelArtistry-Watertight-Meshes/watertightMeshes_win_installer.bat）の処理を Linux で置き換える。
#
# torch（cu126）と重み合計 約 16GB をダウンロードする。実行前に空きディスクとネットワークを確認すること。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$TOOL_DIR/.venv"
VENDOR_DIR="$TOOL_DIR/vendor"
COMFYUI_DIR="$VENDOR_DIR/ComfyUI"
NODES_DIR="$COMFYUI_DIR/custom_nodes"
EXT_DIR="$VENDOR_DIR/extensions"
LOG_DIR="$TOOL_DIR/logs"
RUNNER="$TOOL_DIR/run-comfyui"

# 雛形の書き出し（render_unit_file）と、終わりに表示する URL のホスト（detect_server_host）
# shellcheck source=../../scripts/lib/render-unit.sh
source "$TOOL_DIR/../../scripts/lib/render-unit.sh"
# shellcheck source=../../scripts/lib/server-host.sh
source "$TOOL_DIR/../../scripts/lib/server-host.sh"

# cfui/config.py の COMFYUI_* / CUSTOM_NODES / EXTENSION_SOURCES / PIXELARTISTRY_* と一致させること
# （venv 構築前に git 操作をするため、ここでは python を経由せず直値で持つ）。
COMFYUI_URL="https://github.com/Comfy-Org/ComfyUI.git"
COMFYUI_TAG="v0.38.2"
COMFYUI_COMMIT="daeb5e53681e2b10a3f0727d9ec5bc90784bee10"
PIXELARTISTRY_URL="https://github.com/pixelartistry/PixelArtistry-Watertight-Meshes.git"
PIXELARTISTRY_COMMIT="5b3a0e9d2c5783ed05ba45bbcc157b9509fb267b"

# custom_nodes（フォルダ名 URL コミット）。Mstafa-awad の 9 個は配布元 bat の SHA_*（PIN_DATE=2026-09-26）。
CUSTOM_NODE_PINS="
ComfyUI-Trellis2 https://github.com/visualbruno/ComfyUI-Trellis2.git b0e84c0f29857a444e8bcb5b9be2ea218e96efd0
WTiVo-WatertightVoxel-ComfyuiNode https://github.com/Mstafa-awad/WTiVo-WatertightVoxel-ComfyuiNode.git fb9e9ea6a7deec965d3a4bf43ba7a4a9ff3856f3
ComfyUI-Mesh-Quad-Reconstruct https://github.com/Mstafa-awad/ComfyUI-Mesh-Quad-Reconstruct.git 74048b3415537e26cc72b46b082a010cd0e357ce
ComfyUI-CuMesh-Decimate https://github.com/Mstafa-awad/ComfyUI-CuMesh-Decimate.git c4edeb96bf637239cecb731d2869469a3025d742
ComfyUI-Memory-Cleaner https://github.com/Mstafa-awad/ComfyUI-Memory-Cleaner.git 3357282290278c96ffa0da180d43bc5eac5f2286
LODTailor-The-Mesh-Trimmer-ComfyuiNode https://github.com/Mstafa-awad/LODTailor-The-Mesh-Trimmer-ComfyuiNode.git 3d25b7d4aa382fa5dac210eb5d8d0eadc4a4f183
LODTailor-Bake-Forger https://github.com/Mstafa-awad/LODTailor-Bake-Forger.git f13589c22558e3ca49dfa87dce709233eb3cc86b
Trellis2-Mesh-Encoder https://github.com/Mstafa-awad/Trellis2-Mesh-Encoder.git 860313e67f0f69d402310dc325707bab8bec2fe9
ComfyUI_LODsmith_Merge_Watertight https://github.com/Mstafa-awad/ComfyUI_LODsmith_Merge_Watertight.git 5da6dd69c02d0f3d4ae743d090cfac79aefe7f96
WTiVo-FastMergeByDistance https://github.com/Mstafa-awad/WTiVo-FastMergeByDistance.git 5392949165ceed1e74448b1949d6e0dc9b34dd92
"

# torch / torchvision / torchaudio は cu126 の index から入れる（requirements.lock.txt には書かない）。
# 指定の 2.9.1+cu126 が index に実在することを 2026-10-02 に確認した。
TORCH_INDEX_URL="https://download.pytorch.org/whl/cu126"
TORCH_SPEC="torch==2.9.1+cu126"
TORCHVISION_SPEC="torchvision==0.24.1+cu126"
TORCHAUDIO_SPEC="torchaudio==2.9.1+cu126"

# ComfyUI-Mesh-Quad-Reconstruct の install.py は `python -m pip` を呼ぶ。uv の venv には pip が無いので、
# install.py を走らせる間だけこの版を入れて、終わったら外す。
PIP_SPEC="pip==25.2"

# CUDA 拡張は 12.6 でビルドする（/usr/local/cuda は 13.2 で Hunyuan3D 用。触らない）。
CUDA_HOME_DIR="/usr/local/cuda-12.6"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --skip-models          重みの取得を省略する（あとで run-comfyui fetch-models を手で実行する）
  --build-only           venv・上流取得・torch・依存・CUDA 拡張・WTiVo・自前パッケージ（cfui）までで止める。
                         重みの取得・ワークフローの書き出し・systemd ユニットの配置・doctor は行わない
  --fallback-workflows   予備案（WTiVo を外したもの）の写しも書き出す。WTiVo が使えないときは
                         指定しなくても書き出す
  -h, --help             この説明を表示して終了

systemd ユニットは配置と daemon-reload だけを行い、enable（自動起動）はしない。
EOF
}

SKIP_MODELS=false
BUILD_ONLY=false
FALLBACK_WORKFLOWS=false
while [ $# -gt 0 ]
do
  case "$1" in
    --skip-models)
      SKIP_MODELS=true
      shift
      ;;
    --build-only)
      BUILD_ONLY=true
      shift
      ;;
    --fallback-workflows)
      FALLBACK_WORKFLOWS=true
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

mkdir -p "$LOG_DIR"
echo "== ComfyUI 導入（A30 サーバー） =="

# ---------------------------------------------------------------- [1/12]
echo
echo "[1/12] CUDA 12.6 の確認"
if [ -x "$CUDA_HOME_DIR/bin/nvcc" ]; then
  NVCC_VERSION="$("$CUDA_HOME_DIR/bin/nvcc" --version | tail -1)"
  echo "nvcc: 確認しました（$CUDA_HOME_DIR/bin/nvcc, $NVCC_VERSION）"
else
  echo "$CUDA_HOME_DIR/bin/nvcc が見つかりません。CUDA 拡張は CUDA 12.6 でビルドします" >&2
  echo "（/usr/local/cuda は 13.2 で Hunyuan3D 用のため、代わりに使えません）。" >&2
  exit 1
fi

# ---------------------------------------------------------------- [2/12]
echo
echo "[2/12] uv と venv（uv 管理の Python 3.12）"
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
  # システムの python3.12 は apt の更新で変わるため、uv 管理の 3.12 に固定する（Hunyuan3D / Pixal3D と同じ考え方）。
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

# ---------------------------------------------------------------- [3/12]
echo
echo "[3/12] ComfyUI 本体（$COMFYUI_TAG = $COMFYUI_COMMIT）"
fetch_pinned_repo "$COMFYUI_URL" "$COMFYUI_COMMIT" "$COMFYUI_DIR" "ComfyUI"
# 配布元 bat と同じ判定: Pixal3D / TRELLIS.2 の標準ノードが無い ComfyUI は古すぎる。
for core_node in comfy_extras/nodes_trellis2.py comfy_extras/nodes_mesh_postprocess.py
do
  if [ ! -f "$COMFYUI_DIR/$core_node" ]; then
    echo "ComfyUI に $core_node がありません。v0.34.0 以降が要ります。" >&2
    exit 1
  fi
done
echo "  標準ノード（nodes_trellis2.py / nodes_mesh_postprocess.py）: 確認しました"

# ---------------------------------------------------------------- [4/12]
echo
echo "[4/12] custom_nodes（10 個、コミット固定）"
while read -r node_name node_url node_commit
do
  [ -n "$node_name" ] || continue
  fetch_pinned_repo "$node_url" "$node_commit" "$NODES_DIR/$node_name" "$node_name"
done <<< "$CUSTOM_NODE_PINS"

# ---------------------------------------------------------------- [5/12]
echo
echo "[5/12] torch（$TORCH_INDEX_URL）"
if "$VENV_DIR/bin/python" -c "import torch" >/dev/null 2>&1; then
  echo "torch: 既にあります（$("$VENV_DIR/bin/python" -c 'import torch; print(torch.__version__)')）"
else
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" \
    --index-url "$TORCH_INDEX_URL" \
    "$TORCH_SPEC" "$TORCHVISION_SPEC" "$TORCHAUDIO_SPEC"
  echo "torch: 導入しました（$TORCH_SPEC, $TORCHVISION_SPEC, $TORCHAUDIO_SPEC）"
fi

# ---------------------------------------------------------------- [6/12]
echo
echo "[6/12] 依存（requirements.lock.txt）"
# lock は torch を含まない。入っている torch==2.9.1+cu126 を入れ替えさせないため、版の制約を付ける
# （PEP 440 では ==2.9.1 は 2.9.1+cu126 も満たす）。
TORCH_CONSTRAINTS="$LOG_DIR/torch-constraints.txt"
printf 'torch==2.9.1\ntorchvision==0.24.1\ntorchaudio==2.9.1\n' > "$TORCH_CONSTRAINTS"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" \
  -r "$TOOL_DIR/requirements.lock.txt" -c "$TORCH_CONSTRAINTS"
echo "依存: 導入しました"

# ---------------------------------------------------------------- [7/12]
# CUDA 拡張のソース。ComfyUI-Trellis2 の README（Custom Build）が指す visualbruno のフォークを使う。
# cumesh は Quad Reconstruct が cumesh.remeshing.reconstruct_mesh_dc_quad を使うため visualbruno/CuMesh が要る。
#
# ComfyUI-Trellis2 同梱の wheels/Linux/Torch291 は使わない。2026-10-02 に使い捨ての venv で試すと、
# cumesh は sm_86、flex_gemm / nvdiffrast / o_voxel / nvdiffrec_render は sm_120 の SASS・PTX しか持たず
# （cuobjdump --list-elf で確認）、A30（sm_80）では cumesh・nvdiffrast・flex_gemm のカーネルが
# "no kernel image is available for execution on the device" で落ちた。
# nvdiffrec_render は ComfyUI-Trellis2 も Mstafa-awad のノードも import しないので入れない。
CUMESH_URL="https://github.com/visualbruno/CuMesh.git"
CUMESH_COMMIT="d10e54c30ddd03d11472c1431693f985501c7966"
FLEXGEMM_URL="https://github.com/visualbruno/FlexGEMM.git"
FLEXGEMM_COMMIT="db388bd17c34abc697792aa718dca780734c2783"
TRELLIS_URL="https://github.com/visualbruno/TRELLIS.2.git"
TRELLIS_COMMIT="65d1e13b4a92296036044df0633242bb9e95abf6"
NVDIFFRAST_URL="https://github.com/NVlabs/nvdiffrast.git"
NVDIFFRAST_COMMIT="253ac4fcea7de5f396371124af597e6cc957bfae"

# 拡張のソースを固定コミットで取ってくる（サブモジュール込み）。既にあれば何もしない。
clone_extension() {
  local extension_name="$1" extension_url="$2" extension_commit="$3"
  local target="$EXT_DIR/$extension_name"
  if [ -d "$target/.git" ]; then
    local current_head
    current_head="$(git -C "$target" rev-parse HEAD 2>/dev/null || echo "")"
    if [ "$current_head" != "$extension_commit" ]; then
      echo "  $extension_name のソースが指定コミットではありません（HEAD=$current_head）: $target" >&2
      return 1
    fi
    echo "  $extension_name のソース: 既にあります"
    return 0
  fi
  mkdir -p "$EXT_DIR"
  git clone -q "$extension_url" "$target"
  git -C "$target" checkout -q "$extension_commit"
  git -C "$target" submodule update -q --init --recursive
  echo "  $extension_name のソース: 取得しました（$extension_commit）"
}

# 拡張を 1 本ビルドして入れる。ログは各拡張ごとのファイルへ落とす。
# `| tee` でつながないこと。終了コードが握り潰される。
# ビルド設定は tools/pixal3d/setup-server.sh と同じ（2026-09-22 に A30 で実績がある組み合わせ）。
EXTRA_PIP_ARGS=()
install_extension() {
  local extension_name="$1" extension_path="$2"
  local log_file="$LOG_DIR/build-$extension_name.log"
  echo "  $extension_name をビルドしています（ログ: $log_file）"
  if ! env \
      CUDA_HOME="$CUDA_HOME_DIR" \
      CUDACXX="$CUDA_HOME_DIR/bin/nvcc" \
      CUDAToolkit_ROOT="$CUDA_HOME_DIR" \
      PATH="$CUDA_HOME_DIR/bin:$PATH" \
      TORCH_CUDA_ARCH_LIST=8.0 \
      MAX_JOBS=4 \
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

# 上流への当て物を patches/ から git apply で当てる。当たっていれば何もしない
# （上流の作業ツリーには手で書かない）。
apply_patch() {
  local repo_dir="$1" patch_file="$2"
  local patch_name
  patch_name="$(basename -- "$patch_file")"
  if git -C "$repo_dir" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
    echo "  パッチ $patch_name: 既に当たっています"
  elif git -C "$repo_dir" apply --check "$patch_file" >/dev/null 2>&1; then
    git -C "$repo_dir" apply "$patch_file"
    echo "  パッチ $patch_name: 当てました"
  else
    echo "  パッチ $patch_name を当てられません。上流の内容を確認してください: $repo_dir" >&2
    return 1
  fi
}

build_cuda_extensions() {
  # torch の libc10.so にリンクしているので、torch を先に import してから確かめる。
  clone_extension CuMesh "$CUMESH_URL" "$CUMESH_COMMIT" || return 1
  # visualbruno 版の setup.py は cubvh の Eigen を third_party/cubvh/third_party/eigen に探すが、
  # この版はそこを持たず repo 直下の Eigen/ に同梱している（2026-10-02 のビルドで Eigen/Dense が見つからず失敗）。
  apply_patch "$EXT_DIR/CuMesh" "$TOOL_DIR/patches/cumesh-eigen-include.patch" || return 1
  if ! "$VENV_DIR/bin/python" -c "import torch, cumesh; assert callable(cumesh.remeshing.reconstruct_mesh_dc_quad)" >/dev/null 2>&1; then
    # pyproject の依存（torch, tqdm）は lock 側で入っているので、torch を入れ替えさせないよう --no-deps。
    EXTRA_PIP_ARGS=(--no-deps)
    install_extension CuMesh "$EXT_DIR/CuMesh" || return 1
  fi

  clone_extension FlexGEMM "$FLEXGEMM_URL" "$FLEXGEMM_COMMIT" || return 1
  if ! "$VENV_DIR/bin/python" -c "import torch, flex_gemm" >/dev/null 2>&1; then
    EXTRA_PIP_ARGS=(--no-deps)
    install_extension FlexGEMM "$EXT_DIR/FlexGEMM" || return 1
  fi

  # o-voxel は TRELLIS.2 に同梱されている（上流 setup.sh も cp してからビルドする）。
  # --no-deps が要る: 上流（microsoft 版）の pyproject は cumesh と flex_gemm を git+URL の実行時依存に持ち、
  # そのままだと uv がコミット未固定の clone を勝手にビルドしてしまう（pixal3d-upstream.md）。
  # visualbruno 版はその行が無いが、同じ扱いにしておく。実行時の依存は lock 側で入っている。
  clone_extension TRELLIS.2 "$TRELLIS_URL" "$TRELLIS_COMMIT" || return 1
  if ! "$VENV_DIR/bin/python" -c "import torch, o_voxel" >/dev/null 2>&1; then
    rm -rf "$EXT_DIR/o-voxel"
    cp -r "$EXT_DIR/TRELLIS.2/o-voxel" "$EXT_DIR/o-voxel"
    EXTRA_PIP_ARGS=(--no-deps)
    install_extension o-voxel "$EXT_DIR/o-voxel" || return 1
  fi

  clone_extension nvdiffrast "$NVDIFFRAST_URL" "$NVDIFFRAST_COMMIT" || return 1
  if ! "$VENV_DIR/bin/python" -c "import torch, nvdiffrast.torch" >/dev/null 2>&1; then
    EXTRA_PIP_ARGS=(--no-deps)
    install_extension nvdiffrast "$EXT_DIR/nvdiffrast" || return 1
  fi
}
echo
echo "[7/12] CUDA 拡張（CuMesh / FlexGEMM / o-voxel / nvdiffrast。ソースからビルド、sm_80）"
build_cuda_extensions
if "$VENV_DIR/bin/python" -c "import torch, cumesh, flex_gemm, o_voxel, nvdiffrast.torch" >/dev/null 2>&1; then
  echo "CUDA 拡張: 確認しました（すべて import できました）"
else
  echo "CUDA 拡張: import できないものがあります。$LOG_DIR/build-*.log を確認してください" >&2
  exit 1
fi

# ---------------------------------------------------------------- [8/12]
echo
echo "[8/12] Quad Reconstruct の install.py と自前パッケージ（cfui）"
# install.py の中身（2026-10-02 に読んだ）:
#   1) python -m pip install -r requirements.txt（pymeshlab>=2023.12。lock で入っているので何もしない）
#   2) cumesh.remeshing.reconstruct_mesh_dc_quad があれば終わり（[7/12] で入れたのでここで終わる）
#   3) 無ければ ComfyUI-Trellis2 の wheels から cumesh を --force-reinstall で入れる
#      （Linux の Torch291 は sm_86 で A30 では動かない。2) で止まるので、ここには来ない）
# torch を入れ替える処理は無い。--build-if-needed は付けない（[7/12] で自前でビルドしている）。
QUAD_INSTALL="$NODES_DIR/ComfyUI-Mesh-Quad-Reconstruct/install.py"
PIP_ADDED=false
if ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" "$PIP_SPEC" >/dev/null
  PIP_ADDED=true
fi
QUAD_RC=0
"$VENV_DIR/bin/python" "$QUAD_INSTALL" > "$LOG_DIR/quad-install.log" 2>&1 || QUAD_RC=$?
if $PIP_ADDED; then
  "$UV_BIN" pip uninstall --python "$VENV_DIR/bin/python" pip >/dev/null
fi
if [ "$QUAD_RC" -ne 0 ]; then
  echo "Quad の install.py が失敗しました（終了コード $QUAD_RC）。$LOG_DIR/quad-install.log を確認してください" >&2
  exit 1
fi
if grep -q "VisualBruno CuMesh backend is already ready" "$LOG_DIR/quad-install.log"; then
  echo "Quad install.py: 完了しました（CuMesh は [7/12] のものをそのまま使う）"
else
  echo "Quad install.py: 想定と違う出力です。$LOG_DIR/quad-install.log を確認してください" >&2
  exit 1
fi

"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -e "$TOOL_DIR" >/dev/null
echo "cfui: 導入しました"

# ---------------------------------------------------------------- [9/12]
echo
echo "[9/12] WTiVo の Linux ビルド（scripts/build-wtivo.sh）"
# 終了コード: 0=ビルド済み、3=apt パッケージが無いので core / vdb を飛ばした、それ以外=失敗。
# 飛ばしても他の工程は続ける（予備案のワークフローで防水化できる）。
WTIVO_RC=0
"$TOOL_DIR/scripts/build-wtivo.sh" || WTIVO_RC=$?
if [ "$WTIVO_RC" -eq 0 ]; then
  echo "WTiVo: 使えます"
elif [ "$WTIVO_RC" -eq 3 ]; then
  echo "WTiVo: apt パッケージが無いため core / vdb のビルドを飛ばしました（上の案内を参照）"
else
  echo "WTiVo: ビルドに失敗しました（終了コード $WTIVO_RC）。他の工程は続けます" >&2
fi

if $BUILD_ONLY; then
  echo
  echo "--build-only が指定されたため、ここで終了します。"
  echo "次にやること:"
  echo "  - 重みの取得: $RUNNER fetch-models"
  echo "  - ワークフローと systemd ユニット: このスクリプトを --build-only 無しで再実行する"
  echo "  - 点検: $RUNNER doctor"
  exit 0
fi

# ---------------------------------------------------------------- [10/12]
echo
echo "[10/12] 重みとサンプル画像"
if $SKIP_MODELS; then
  echo "重み取得: 省略しました（--skip-models）。あとで '$RUNNER fetch-models' を実行してください"
else
  "$RUNNER" fetch-models
  echo "重み取得: 完了しました"
fi

# ---------------------------------------------------------------- [11/12]
echo
echo "[11/12] PixelArtistry のワークフロー（$PIXELARTISTRY_COMMIT）"
fetch_pinned_repo "$PIXELARTISTRY_URL" "$PIXELARTISTRY_COMMIT" \
  "$VENDOR_DIR/PixelArtistry-Watertight-Meshes" "PixelArtistry-Watertight-Meshes"
ADAPT_ARGS=()
if $FALLBACK_WORKFLOWS || [ "$WTIVO_RC" -ne 0 ]; then
  # WTiVo が使えないときは、予備案（WTiVo を外し、LODTailor の Voxel Remesh で防水化する）も置く。
  ADAPT_ARGS=(--fallback)
fi
"$VENV_DIR/bin/python" "$TOOL_DIR/scripts/adapt_workflows.py" "${ADAPT_ARGS[@]}"

# ---------------------------------------------------------------- [12/12]
echo
echo "[12/12] systemd user ユニット・Blender の空の設定・env ファイル（enable はしない）"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/comfyui.service"
if [ -f "$SERVICE_FILE" ]; then
  echo "systemd ユニット: 既にあります（$SERVICE_FILE）"
else
  mkdir -p "$SYSTEMD_USER_DIR"
  # 雛形のリポジトリのパス（@REPO_ROOT@）をこの clone の絶対パスにして置く
  render_unit_file "$TOOL_DIR/systemd/comfyui.service.example" "$SERVICE_FILE"
  echo "systemd ユニット: 作成しました（$SERVICE_FILE）"
fi

# ComfyUI から呼ぶ Blender の利用者設定・スクリプト・拡張の置き場（空）。run-comfyui serve が環境変数で向ける。
BLENDER_CLEAN_DIR="$HOME/.config/comfyui/blender-clean"
mkdir -p "$BLENDER_CLEAN_DIR/config" "$BLENDER_CLEAN_DIR/scripts" "$BLENDER_CLEAN_DIR/extensions"
echo "Blender の空の設定: 用意しました（$BLENDER_CLEAN_DIR）"

ENV_FILE="$HOME/.config/comfyui/comfyui.env"
if [ -f "$ENV_FILE" ]; then
  echo "env ファイル: 既にあります（$ENV_FILE）"
else
  cat > "$ENV_FILE" <<'EOF'
# comfyui.service が読む環境変数（run-comfyui serve に渡る）。
# ComfyUI の main.py に足す引数。例: VRAM が足りないとき
# COMFYUI_EXTRA_ARGS=--lowvram
# torch が cu126 のため comfy_kitchen の CUDA 版は無効になる（README 参照）。triton 版を試すなら（未検証）
# COMFYUI_EXTRA_ARGS=--enable-triton-backend
EOF
  chmod 644 "$ENV_FILE"
  echo "env ファイル: 作成しました（$ENV_FILE、設定は空）"
fi

systemctl --user daemon-reload
echo "自動起動: 設定していません（enable しない方針）"
echo "手で起動する: systemctl --user start comfyui ／ 止める: systemctl --user stop comfyui"

echo
echo "点検"
DOCTOR_RC=0
"$RUNNER" doctor || DOCTOR_RC=$?
if [ "$DOCTOR_RC" -eq 0 ]; then
  echo "点検: 合格しました"
else
  echo "点検: 一部 NG があります（終了コード $DOCTOR_RC）。上の出力を確認してください"
fi

SERVER_HOST="$(detect_server_host)"
echo
echo "次にやること:"
echo "  - 手動起動: $RUNNER serve"
echo "  - systemd 経由: systemctl --user start comfyui"
echo "  - ブラウザ: http://$SERVER_HOST:8188 → Workflows → PixelArtistry"
exit "$DOCTOR_RC"
