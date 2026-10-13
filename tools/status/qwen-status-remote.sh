#!/usr/bin/env bash
# 他の PC（macOS / Linux / WSL2）から、A30 サーバー上の qwen-status.sh を ssh で呼ぶ。
#
# 使い方:  qwen-status-remote.sh [--server <user>@<server-ip>] [--watch 秒] [--lines N]
#   接続先は --server か環境変数 LOCALAI_SERVER_HOST（<user>@<server-ip> の形）で必ず指定する。
#   例: qwen-status-remote.sh --server alice@192.168.1.10
#   サーバーのログインパスワードを ssh が聞く（qwen-worker 用の鍵は強制コマンド付きで使えない）。
#   毎回聞かれるのが嫌なら、自分の通常の鍵を ssh-copy-id で登録する。
set -euo pipefail
usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }
server="${LOCALAI_SERVER_HOST:-}"
pass_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --server) server="${2:?--server には user@host が要る}"; shift 2 ;;
    --watch|--lines) pass_args+=("$1" "${2:?$1 には値が要る}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$server" ]; then
  echo "接続先が未指定です。--server か環境変数 LOCALAI_SERVER_HOST で指定してください。" >&2
  usage >&2
  exit 2
fi
# -t は --watch の画面更新と Ctrl-C のため。リモート側のパスはサーバー上の絶対パス
exec ssh -t "$server" "bash ~/Proj/localai/tools/status/qwen-status.sh ${pass_args[*]:-}"
