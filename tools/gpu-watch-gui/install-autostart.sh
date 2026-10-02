#!/usr/bin/env bash
# gpu-watch-gui をログイン時に自動起動する（GNOME の自動ログイン → ロック解除後に見える想定）。
# .desktop の本体はこのリポジトリの中に置き、~/.config/autostart/ にはこのスクリプトが生成した
# 登録ファイル 1 個だけを置く（GNOME の仕様で autostart はここにしか置けないため）。
#
# 使い方: install-autostart.sh [--uninstall]
#   （引数無し）  ~/.config/autostart/gpu-watch-gui.desktop を作る・更新する
#   --uninstall   ~/.config/autostart/gpu-watch-gui.desktop を削除する
#
# 冪等: 何度実行しても結果は同じ（既にあれば作り直すだけ、無ければ何もしない）。
set -euo pipefail

GUI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TEMPLATE="$GUI_DIR/gpu-watch-gui.desktop.in"
AUTOSTART_DIR="$HOME/.config/autostart"
TARGET="$AUTOSTART_DIR/gpu-watch-gui.desktop"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [--uninstall]

  （引数無し）  ~/.config/autostart/gpu-watch-gui.desktop を作る・更新する
  --uninstall   ~/.config/autostart/gpu-watch-gui.desktop を削除する
  -h, --help    この説明を表示して終了
EOF
}

mode="install"
case "${1:-}" in
  --uninstall) mode="uninstall" ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "install-autostart.sh: 不明な引数です: $1" >&2; usage >&2; exit 2 ;;
esac

if [ "$mode" = uninstall ]; then
  if [ -e "$TARGET" ]; then
    rm -f -- "$TARGET"
    echo "削除しました: $TARGET"
  else
    echo "もともと登録されていません: $TARGET"
  fi
  exit 0
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "install-autostart.sh: テンプレートが見つかりません: $TEMPLATE" >&2
  exit 1
fi
if [ ! -x "$GUI_DIR/run-gpu-watch-gui" ]; then
  echo "install-autostart.sh: run-gpu-watch-gui が実行可能ではありません: $GUI_DIR/run-gpu-watch-gui" >&2
  exit 1
fi

mkdir -p -- "$AUTOSTART_DIR"
sed "s#@ROOT@#$GUI_DIR#g" "$TEMPLATE" > "$TARGET"
echo "作成しました: $TARGET"

if command -v desktop-file-validate >/dev/null 2>&1; then
  if desktop-file-validate "$TARGET"; then
    echo "desktop-file-validate: 問題なし"
  else
    echo "警告: desktop-file-validate がエラーを報告しました（上記）。内容を確認してください。" >&2
  fi
else
  echo "desktop-file-validate が無いため検査を省略しました。"
fi

echo
echo "有効にするには再ログイン（または再起動）してください。"
echo "外すには: $0 --uninstall"
