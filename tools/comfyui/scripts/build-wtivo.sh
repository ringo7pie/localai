#!/usr/bin/env bash
# WTiVo（防水化ノード）のネイティブ部を Linux 向けにビルドし、ノードが読む場所に置く（冪等）。
# setup-server.sh の [9/12] から呼ばれる。単独でも実行できる。
#
# ノード repo（WTiVo-WatertightVoxel-ComfyuiNode, v1.1）は Windows 用の .pyd しか持たない。
# ソースは姉妹 repo（WTiVo-WatertightVoxel, v1.0）にあるので、そこから 3 本を作る:
#   wtivo_core  … native/core/wtivo_core.cpp（CGAL + TBB + Eigen）を cmake + pybind11 で
#   wtivo_vdb   … native/vdb/wtivo_vdb.cpp（OpenVDB + TBB）を cmake + pybind11 で
#   wtivo_gpupr … native/gpupr/*.cu / *.cpp を torch.utils.cpp_extension で（CUDA 12.6、sm_80）
# ノードの wtivo.py は ROOT と ROOT/build を sys.path に足し、wtivo_core / wtivo_gpupr / wtivo_vdb を
# 優先して import する（無ければ同梱の Windows 用 cppmodules に落ちる）。できた .so は ROOT/build に置く。
#
# 終了コード: 0=3 本とも import できる、3=apt パッケージが無いので飛ばした、それ以外=失敗。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_PYTHON="$TOOL_DIR/.venv/bin/python"
LOG_DIR="$TOOL_DIR/logs"
SRC_DIR="$TOOL_DIR/vendor/WTiVo-WatertightVoxel"
NODE_DIR="$TOOL_DIR/vendor/ComfyUI/custom_nodes/WTiVo-WatertightVoxel-ComfyuiNode"
NATIVE_DIR="$NODE_DIR/build"
PATCH_DIR="$TOOL_DIR/patches"

# cfui/config.py の WTIVO_SRC_URL / WTIVO_SRC_COMMIT / WTIVO_APT_PACKAGES と一致させること。
SRC_URL="https://github.com/Mstafa-awad/WTiVo-WatertightVoxel.git"
# タグは無い。VERSION が 1.0.0 の main の HEAD（2026-09-11）。
SRC_COMMIT="7a0ac7cb24fd0588f2f7a78c787779d760d36f48"
APT_PACKAGES="libcgal-dev libopenvdb-dev libtbb-dev libeigen3-dev"

CUDA_HOME_DIR="/usr/local/cuda-12.6"
# Ubuntu の libopenvdb-dev は config パッケージを持たず FindOpenVDB.cmake だけを置くが、それは
# libboost-iostreams-dev（未導入）の cmake 設定を必須にする。代わりに、システムの OpenVDB 10 を指す
# 最小の OpenVDBConfig.cmake を渡す（理由は cmake/openvdb-config/OpenVDBConfig.cmake の冒頭）。
OPENVDB_CONFIG_DIR="$TOOL_DIR/cmake/openvdb-config"

mkdir -p "$LOG_DIR"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "venv の python がありません: $VENV_PYTHON（先に setup-server.sh を実行してください）" >&2
  exit 1
fi

# ---------------------------------------------------------------- apt パッケージ
missing_packages=()
for package_name in $APT_PACKAGES
do
  if ! dpkg -s "$package_name" >/dev/null 2>&1; then
    missing_packages+=("$package_name")
  fi
done
if [ "${#missing_packages[@]}" -gt 0 ]; then
  echo "  WTiVo のビルドに要る apt パッケージがありません: ${missing_packages[*]}"
  echo "  利用者が sudo で入れてから、このスクリプトを再実行してください:"
  echo "    sudo apt install $APT_PACKAGES"
  exit 3
fi
echo "  apt パッケージ: 確認しました（$APT_PACKAGES）"

# ---------------------------------------------------------------- 姉妹 repo の取得
if [ -d "$SRC_DIR/.git" ]; then
  current_head="$(git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || echo "")"
  if [ "$current_head" != "$SRC_COMMIT" ]; then
    echo "  $SRC_DIR が指定コミットではありません（HEAD=$current_head）。勝手に張り替えないで終了します" >&2
    exit 1
  fi
  echo "  WTiVo-WatertightVoxel: 既にあります（HEAD=$current_head）"
else
  mkdir -p "$(dirname -- "$SRC_DIR")"
  git init -q "$SRC_DIR"
  git -C "$SRC_DIR" remote add origin "$SRC_URL"
  git -C "$SRC_DIR" fetch -q --depth 1 origin "$SRC_COMMIT"
  git -C "$SRC_DIR" checkout -q FETCH_HEAD
  echo "  WTiVo-WatertightVoxel: 取得しました（$SRC_COMMIT）"
fi

# ---------------------------------------------------------------- パッチ
# 上流の作業ツリーには手で書かず、patches/ の差分を git apply で当てる。当たっていれば何もしない。
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
    exit 1
  fi
}
# 姉妹 repo:
#   wtivo-src-linux-build.patch           CMakeLists.txt と scripts/build_gpupr.py の Windows 限定を外す
#   wtivo-src-core-vertices-lifetime.patch wtivo_core が解放済みの一時配列を返す不具合を直す（Linux で SIGSEGV）
SRC_PATCHES=(
  "$PATCH_DIR/wtivo-src-linux-build.patch"
  "$PATCH_DIR/wtivo-src-core-vertices-lifetime.patch"
)
for patch_file in "${SRC_PATCHES[@]}"
do
  apply_patch "$SRC_DIR" "$patch_file"
done
# ノード: wtivo.py の main() にある `os.name != "nt"` の終了を外す。
apply_patch "$NODE_DIR" "$PATCH_DIR/wtivo-node-allow-linux.patch"

# ---------------------------------------------------------------- パッチが変わったら作り直す
# できた .so がどのパッチの組で作られたかを記録しておき、違えば消してビルドし直す
# （ソースを直すパッチを足したのに、古い .so が「既にある」で使われ続けないように）。
EXT_SUFFIX="$("$VENV_PYTHON" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
PATCH_STAMP="$SRC_DIR/build/.localai-patches.sha256"
current_stamp="$(cat "${SRC_PATCHES[@]}" | sha256sum | cut -d' ' -f1)"
if [ ! -f "$PATCH_STAMP" ] || [ "$(cat "$PATCH_STAMP")" != "$current_stamp" ]; then
  for module_name in wtivo_core wtivo_vdb wtivo_gpupr
  do
    rm -f "$SRC_DIR/build/$module_name$EXT_SUFFIX" "$NATIVE_DIR/$module_name$EXT_SUFFIX"
  done
  # gpupr は torch.utils.cpp_extension の作業場所に古い .so が残ると、それを読み込んで終わるため消す。
  rm -rf "$SRC_DIR/.build/gpupr"
fi

# ---------------------------------------------------------------- 3 本が import できるか
native_ready() {
  # wtivo_gpupr は torch の libc10.so にリンクしているので、torch を先に import する（wtivo.py と同じ順）。
  "$VENV_PYTHON" -c "
import sys
sys.path.insert(0, sys.argv[1])
import torch
import wtivo_core, wtivo_vdb, wtivo_gpupr
for module in (wtivo_core, wtivo_vdb, wtivo_gpupr):
    assert module.__file__.startswith(sys.argv[1]), module.__file__
" "$NATIVE_DIR" >/dev/null 2>&1
}

if native_ready; then
  echo "  wtivo_core / wtivo_vdb / wtivo_gpupr: 既に入っています（$NATIVE_DIR）"
  exit 0
fi

# ---------------------------------------------------------------- core / vdb（cmake + pybind11）
CMAKE_BUILD_DIR="$SRC_DIR/.build/cmake"
CMAKE_LOG="$LOG_DIR/build-wtivo-cmake.log"
if [ -f "$SRC_DIR/build/wtivo_core$EXT_SUFFIX" ] && [ -f "$SRC_DIR/build/wtivo_vdb$EXT_SUFFIX" ]; then
  echo "  wtivo_core / wtivo_vdb: 既にビルド済みです（$SRC_DIR/build）"
else
  PYBIND11_CMAKE_DIR="$("$VENV_PYTHON" -m pybind11 --cmakedir)"
  # 失敗した前回の CMakeCache（見つからなかったパッケージの記録）を引き継がないよう、毎回作り直す。
  rm -rf "$CMAKE_BUILD_DIR"
  echo "  wtivo_core / wtivo_vdb をビルドしています（ログ: $CMAKE_LOG）"
  # Python3_EXECUTABLE は venv の python（uv 管理の 3.12）。拡張子と include はここから決まる。
  # CMAKE_BUILD_TYPE=Release でも CMakeLists.txt 側が -O3 を足す。-ffast-math は使わない（上流の方針）。
  if ! {
      cmake -S "$SRC_DIR" -B "$CMAKE_BUILD_DIR" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DPython3_EXECUTABLE="$VENV_PYTHON" \
        -Dpybind11_DIR="$PYBIND11_CMAKE_DIR" \
        -DOpenVDB_DIR="$OPENVDB_CONFIG_DIR" \
        -DWTIVO_OUTPUT_DIR="$SRC_DIR/build" \
      && cmake --build "$CMAKE_BUILD_DIR" -j 4
    } > "$CMAKE_LOG" 2>&1; then
    echo "  wtivo_core / wtivo_vdb のビルドに失敗しました。$CMAKE_LOG を確認してください" >&2
    exit 1
  fi
  echo "  wtivo_core / wtivo_vdb: ビルドしました"
fi

# ---------------------------------------------------------------- gpupr（CUDA 12.6、sm_80）
GPUPR_LOG="$LOG_DIR/build-wtivo-gpupr.log"
if [ -f "$SRC_DIR/build/wtivo_gpupr$EXT_SUFFIX" ]; then
  echo "  wtivo_gpupr: 既にビルド済みです（$SRC_DIR/build）"
else
  echo "  wtivo_gpupr をビルドしています（ログ: $GPUPR_LOG）"
  # build_gpupr.py は WTIVO_CUDA_ARCH を TORCH_CUDA_ARCH_LIST に写し、WTIVO_CUDA_HOME の nvcc を使う。
  if ! env \
      CUDA_HOME="$CUDA_HOME_DIR" \
      CUDACXX="$CUDA_HOME_DIR/bin/nvcc" \
      WTIVO_CUDA_HOME="$CUDA_HOME_DIR" \
      WTIVO_CUDA_ARCH=8.0 \
      PATH="$CUDA_HOME_DIR/bin:$(dirname -- "$VENV_PYTHON"):$PATH" \
      MAX_JOBS=4 \
      "$VENV_PYTHON" "$SRC_DIR/scripts/build_gpupr.py" > "$GPUPR_LOG" 2>&1; then
    echo "  wtivo_gpupr のビルドに失敗しました。$GPUPR_LOG を確認してください" >&2
    exit 1
  fi
  echo "  wtivo_gpupr: ビルドしました"
fi

# ---------------------------------------------------------------- ノードが読む場所へ置く
mkdir -p "$NATIVE_DIR"
for module_name in wtivo_core wtivo_vdb wtivo_gpupr
do
  cp -p "$SRC_DIR/build/$module_name$EXT_SUFFIX" "$NATIVE_DIR/"
done
echo "  .so を置きました（$NATIVE_DIR）"
mkdir -p "$SRC_DIR/build"
printf '%s\n' "$current_stamp" > "$PATCH_STAMP"

if native_ready; then
  echo "  wtivo_core / wtivo_vdb / wtivo_gpupr: import できました"
  exit 0
fi
echo "  .so を置きましたが import できません。次で原因を確かめてください:" >&2
echo "    $VENV_PYTHON -c 'import sys; sys.path.insert(0, \"$NATIVE_DIR\"); import torch, wtivo_core, wtivo_vdb, wtivo_gpupr'" >&2
exit 1
