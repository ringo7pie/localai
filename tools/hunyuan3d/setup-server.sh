#!/usr/bin/env bash
# A30 サーバーで Hunyuan3D-2 を 1 回の実行で導入する（冪等。再実行は既存物を触らない）。
#
# torch（cu132）と重み合計 約23GB をダウンロードする。実行前に空きディスクとネットワークを確認すること。
#
# 上流のコードと重みは Tencent Hunyuan 3D 2.0 Community License で配布されている。取得の前に要約を表示し、
# --accept-tencent-license（または環境変数 HY3D_ACCEPT_LICENSE=1）が無ければ何もせず終了コード 2 で止まる。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$TOOL_DIR/.venv"
VENDOR_DIR="$TOOL_DIR/vendor/Hunyuan3D-2"
RUNNER="$TOOL_DIR/run-hunyuan3d"

# 雛形の書き出し（render_unit_file）と、終わりに表示する URL のホスト（detect_server_host）
# shellcheck source=../../scripts/lib/render-unit.sh
source "$TOOL_DIR/../../scripts/lib/render-unit.sh"
# shellcheck source=../../scripts/lib/server-host.sh
source "$TOOL_DIR/../../scripts/lib/server-host.sh"

# hy3d/config.py の UPSTREAM_URL / UPSTREAM_COMMIT と一致させること
# （venv 構築前に git 操作をするため、ここでは python を経由せず直値で持つ）。
UPSTREAM_URL="https://github.com/Tencent-Hunyuan/Hunyuan3D-2"
UPSTREAM_COMMIT="f8db63096c8282cb27354314d896feba5ba6ff8a"
# 使用許諾の原文。固定コミットのものを指す（取得後は $VENDOR_DIR/LICENSE と同じ）。
LICENSE_URL="$UPSTREAM_URL/blob/$UPSTREAM_COMMIT/LICENSE"

# torch / torchvision は cu132 の index から入れる（requirements.lock.txt には書かない）。
# download.pytorch.org/whl/cu132 を実際に確認し、cp311 + linux_x86_64 wheel がある組み合わせのうち、
# パッチリリースがあって枯れている 2.12 系を選んだ（2.13.0 / 2.14.0 はこの時点でまだ .0 のみ）。
TORCH_INDEX_URL="https://download.pytorch.org/whl/cu132"
TORCH_SPEC="torch==2.12.1+cu132"
TORCHVISION_SPEC="torchvision==0.27.1+cu132"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --accept-tencent-license
                  Tencent Hunyuan 3D 2.0 Community License に同意して進める（必須。
                  環境変数 HY3D_ACCEPT_LICENSE=1 でも同じ）。無いと要約を表示して終了コード 2 で止まる
  --no-texture    ネイティブ拡張のビルドとテクスチャ用の重み取得を省略する（形状生成のみ）
  --skip-models   重みの取得を省略する（あとで run-hunyuan3d fetch-models を手で実行する）
  --no-autostart  PC 起動時の自動起動を有効にしない（使うときだけ手で起動する）
  -h, --help      この説明を表示して終了

使用許諾の原文: $LICENSE_URL
EOF
}

# 使用許諾の要約。正式な条件は原文。要約は 2026-10-13 に固定コミットの LICENSE（1(l)・3(d)・4・5(b)）と照らした。
show_license_summary() {
  cat <<EOF
Hunyuan3D-2 の上流のコードと重みは Tencent Hunyuan 3D 2.0 Community License Agreement で配布されています。
要点（要約です。正式な条件は原文を読んでください）:
  - 欧州連合（EU）・英国（UK）・韓国は使用許諾の対象地域から外れています（これらの地域では使えません）
  - 月間アクティブユーザーが 100 万人を超える製品・サービスで使うには、Tencent への別途の申請が要ります
  - 第三者へ配布するときは、所定の Notice（表示）のテキストファイルを添える必要があります
  - 出力（生成物）を使って他の AI モデルを改善してはいけません（Hunyuan3D 2.0 とその派生物を除く）
原文: $LICENSE_URL
      （取得後は $VENDOR_DIR/LICENSE にもあります）
EOF
}

ACCEPT_LICENSE=false
if [ "${HY3D_ACCEPT_LICENSE:-}" = "1" ]; then
  ACCEPT_LICENSE=true
fi
NO_TEXTURE=false
SKIP_MODELS=false
NO_AUTOSTART=false
while [ $# -gt 0 ]
do
  case "$1" in
    --accept-tencent-license)
      ACCEPT_LICENSE=true
      shift
      ;;
    --no-texture)
      NO_TEXTURE=true
      shift
      ;;
    --skip-models)
      SKIP_MODELS=true
      shift
      ;;
    --no-autostart)
      NO_AUTOSTART=true
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

echo "== Hunyuan3D-2 導入（A30 サーバー） =="

# 使用許諾の確認。上流の取得・重みのダウンロードより前（何も作らないうち）に止める。
echo
echo "[使用許諾] Tencent Hunyuan 3D 2.0 Community License"
show_license_summary
if ! $ACCEPT_LICENSE; then
  echo >&2
  echo "使用許諾に同意していないので止めます（何も取得・作成していません）。" >&2
  echo "原文を読んで同意する場合は、次のどちらかで再実行してください:" >&2
  echo "  $0 --accept-tencent-license [ほかのオプション]" >&2
  echo "  HY3D_ACCEPT_LICENSE=1 $0 [ほかのオプション]" >&2
  exit 2
fi
echo "使用許諾: 同意を確認しました"

# ---------------------------------------------------------------- [1/9]
echo
echo "[1/9] uv と venv（Python 3.11）"
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
  "$UV_BIN" venv --python 3.11 "$VENV_DIR"
  echo "venv: 作成しました（$VENV_DIR）"
fi

# uv venv は .venv/include を作らない。ヘッダは uv 管理 Python の本体側にあり、
# 拡張をビルドするときに setuptools が参照するのは sysconfig の INCLUDEPY。そこを見る。
PYTHON_INCLUDE_DIR="$("$VENV_DIR/bin/python" -c 'import sysconfig; print(sysconfig.get_config_var("INCLUDEPY"))')"
if [ ! -f "$PYTHON_INCLUDE_DIR/Python.h" ]; then
  echo "Python.h が見つかりません（$PYTHON_INCLUDE_DIR）。" >&2
  echo "uv 管理の CPython 3.11 にヘッダが同梱されていないようです。ネイティブ拡張のビルドができません。" >&2
  exit 1
fi
echo "Python.h: 確認しました（$PYTHON_INCLUDE_DIR/Python.h）"

# ---------------------------------------------------------------- [2/9]
echo
echo "[2/9] 上流の取得（$UPSTREAM_COMMIT）"
if [ -d "$VENDOR_DIR/.git" ]; then
  CURRENT_HEAD="$(git -C "$VENDOR_DIR" rev-parse HEAD 2>/dev/null || echo "")"
  if [ "$CURRENT_HEAD" = "$UPSTREAM_COMMIT" ]; then
    echo "上流: 既にあります（$VENDOR_DIR, HEAD=$CURRENT_HEAD）"
  else
    echo "上流は既にありますが、指定コミットではありません（HEAD=$CURRENT_HEAD）。" >&2
    echo "勝手に張り替えないで終了します。確認して手動で対処してください: $VENDOR_DIR" >&2
    exit 1
  fi
else
  mkdir -p "$(dirname -- "$VENDOR_DIR")"
  git init "$VENDOR_DIR"
  git -C "$VENDOR_DIR" remote add origin "$UPSTREAM_URL"
  git -C "$VENDOR_DIR" fetch --depth 1 origin "$UPSTREAM_COMMIT"
  git -C "$VENDOR_DIR" checkout FETCH_HEAD
  echo "上流: 取得しました（$VENDOR_DIR）"
fi

# 上流への当て物。固定コミットに対して当てるので、順番も結果も決まる。
# 既に当たっていれば触らない（--reverse --check が通る＝適用済み）。
# 当て物は「固定コミットまで戻してから番号順に当て直す」。1 枚ずつ apply --reverse --check で
# 「既に当たっているか」を見る方式は使えない。後の当て物が前の当て物の文脈行に重なると、
# 前の当て物が前向きにも後ろ向きにも当たらなくなり、再実行が失敗するため（0003 と 0004 で実際に起きた）。
# 戻してから当て直せば、何度実行しても結果が同じになる。
PATCH_DIR="$TOOL_DIR/patches"
if [ -d "$PATCH_DIR" ] && [ -n "$(ls -A "$PATCH_DIR"/*.patch 2>/dev/null)" ]; then
  # 当て物に取り込んでいない手作業の変更があれば、戻す前に知らせる（消えてしまうため）。
  if ! git -C "$VENDOR_DIR" diff --quiet; then
    echo "上流に変更があります。固定コミットへ戻してから当て物を当て直します:"
    git -C "$VENDOR_DIR" diff --stat | sed 's/^/  /'
  fi
  git -C "$VENDOR_DIR" checkout -- .
  for patch_file in "$PATCH_DIR"/*.patch
  do
    patch_name="$(basename -- "$patch_file")"
    if git -C "$VENDOR_DIR" apply "$patch_file"; then
      echo "パッチ $patch_name: 当てました"
    else
      echo "パッチ $patch_name を当てられません。上流の内容と当て物の順序を確認してください。" >&2
      exit 1
    fi
  done
else
  # 当て物は上流の派生物なので公開版には含めない。無ければ上流をそのまま使う（固定コミットへ戻す処理もしない）。
  echo "パッチ: $PATCH_DIR/*.patch が無いので飛ばします（このリポジトリの公開版にはパッチを含めない。UI の説明・設定の保存・失敗パラメータの表示は使えない）"
fi

# ---------------------------------------------------------------- [3/9]
echo
echo "[3/9] torch（$TORCH_INDEX_URL）"
if "$VENV_DIR/bin/python" -c "import torch" >/dev/null 2>&1; then
  echo "torch: 既にあります"
else
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" \
    --index-url "$TORCH_INDEX_URL" \
    "$TORCH_SPEC" "$TORCHVISION_SPEC"
  echo "torch: 導入しました（$TORCH_SPEC, $TORCHVISION_SPEC）"
fi

# ---------------------------------------------------------------- [4/9]
echo
echo "[4/9] 依存（requirements.lock.txt）"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -r "$TOOL_DIR/requirements.lock.txt"
echo "依存: 導入しました"

# ---------------------------------------------------------------- [5/9]
echo
echo "[5/9] 自前パッケージ（hy3d）"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" -e "$TOOL_DIR"
echo "hy3d: 導入しました"

# ---------------------------------------------------------------- [6/9]
echo
echo "[6/9] ネイティブ拡張（texgen 配下）"
if $NO_TEXTURE; then
  echo "拡張ビルド: 省略しました（--no-texture）"
else
  if "$VENV_DIR/bin/python" -c "import custom_rasterizer_kernel, mesh_processor" >/dev/null 2>&1; then
    echo "拡張ビルド: 既にあります（import できました）"
  else
    if [ ! -d /usr/local/cuda ]; then
      echo "CUDA_HOME 候補 /usr/local/cuda がありません。拡張ビルドをスキップできません。" >&2
      exit 1
    fi
    export CUDA_HOME=/usr/local/cuda
    export TORCH_CUDA_ARCH_LIST=8.0
    (
      cd "$VENDOR_DIR/hy3dgen/texgen/custom_rasterizer"
      "$UV_BIN" pip install --python "$VENV_DIR/bin/python" --no-build-isolation .
    )
    (
      cd "$VENDOR_DIR/hy3dgen/texgen/differentiable_renderer"
      "$UV_BIN" pip install --python "$VENV_DIR/bin/python" --no-build-isolation .
    )
    echo "拡張ビルド: 完了しました"
  fi
fi

# ---------------------------------------------------------------- [7/9]
echo
echo "[7/9] 重みの取得"
if $SKIP_MODELS; then
  echo "重み取得: 省略しました（--skip-models）。あとで '$RUNNER fetch-models' を実行してください"
else
  FETCH_ARGS=()
  if $NO_TEXTURE; then
    FETCH_ARGS+=(--no-texture)
  fi
  HY3D_ACCEPT_LICENSE=1 "$RUNNER" fetch-models "${FETCH_ARGS[@]}"
  echo "重み取得: 完了しました"
fi

# ---------------------------------------------------------------- [8/9]
echo
echo "[8/9] systemd user ユニット"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/hunyuan3d.service"
if [ -f "$SERVICE_FILE" ]; then
  echo "systemd ユニット: 既にあります（$SERVICE_FILE）"
else
  mkdir -p "$SYSTEMD_USER_DIR"
  # 雛形のリポジトリのパス（@REPO_ROOT@）をこの clone の絶対パスにして置く
  render_unit_file "$TOOL_DIR/systemd/hunyuan3d.service.example" "$SERVICE_FILE"
  echo "systemd ユニット: 作成しました（$SERVICE_FILE）"
fi
systemctl --user daemon-reload
if $NO_AUTOSTART; then
  echo "自動起動: 設定しませんでした（--no-autostart）"
  echo "手で起動する: systemctl --user start hunyuan3d"
else
  systemctl --user enable --now hunyuan3d
  echo "自動起動: 有効にしました（PC 起動時に立ち上がります）"
  echo "止める: systemctl --user stop hunyuan3d ／ 自動起動をやめる: systemctl --user disable hunyuan3d"
fi

# ---------------------------------------------------------------- [9/9]
echo
echo "[9/9] 点検"
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
echo "  - systemd 経由: systemctl --user start hunyuan3d"
echo "  - ブラウザ: http://$SERVER_HOST:7860"
exit "$DOCTOR_RC"
