#!/usr/bin/env bash
# 他の PC（macOS / Linux / WSL2）から、A30 サーバー上の qwen-status.sh を ssh で呼ぶ。
#
# 使い方:  qwen-status-remote.sh [--server mt@<server-ip>] [--watch 秒] [--lines N]
#   サーバーのログインパスワードを ssh が聞く（qwen-worker 用の鍵は強制コマンド付きで使えない）。
#   毎回聞かれるのが嫌なら、自分の通常の鍵を ssh-copy-id で登録する。
set -euo pipefail
server="mt@<server-ip>"
pass_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --server) server="${2:?--server には user@host が要る}"; shift 2 ;;
    --watch|--lines) pass_args+=("$1" "${2:?$1 には値が要る}"); shift 2 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done
# -t は --watch の画面更新と Ctrl-C のため。リモート側のパスはサーバー上の絶対パス
exec ssh -t "$server" "bash ~/Proj/localai/tools/status/qwen-status.sh ${pass_args[*]:-}"
