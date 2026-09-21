#!/usr/bin/env bash
# Codex へ stdio MCP サーバー local-ai-bridge を登録する。
#
# このマシンの codex は PATH 上に無い。ChatGPT デスクトップ版 deb に同梱された
# /usr/lib/chatgpt/resources/codex が実体。フルパスで呼ぶ。
# 無ければ導入を強制せず、手順だけ出して終わる。
set -euo pipefail

CODEX_BIN="${CODEX_BIN:-/usr/lib/chatgpt/resources/codex}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
LAUNCHER="$HERE/run-local-ai-bridge"
NAME="local-ai-bridge"
CONFIG="${CODEX_HOME:-$HOME/.codex}/config.toml"

if [ ! -x "$CODEX_BIN" ]; then
  cat <<EOF
codex が見つかりません: $CODEX_BIN

導入は強制しません。導入済みの codex がある場合は次を実行してください:

  <codex のパス> mcp add $NAME -- $LAUNCHER

または ~/.codex/config.toml へ次を追記してください（既存内容は消さないこと）:

  [mcp_servers.$NAME]
  command = "$LAUNCHER"
  startup_timeout_sec = 30
  tool_timeout_sec = 120
EOF
  exit 0
fi

if [ -f "$CONFIG" ]; then
  BACKUP="$CONFIG.$(date +%Y%m%d-%H%M%S).bak"
  cp -p "$CONFIG" "$BACKUP"
  echo "退避しました: $BACKUP"
fi

if "$CODEX_BIN" mcp get "$NAME" >/dev/null 2>&1; then
  echo "既存の登録を削除します（重複を避けるため）。"
  "$CODEX_BIN" mcp remove "$NAME" >/dev/null 2>&1 || true
fi

"$CODEX_BIN" mcp add "$NAME" -- "$LAUNCHER"
echo
echo "登録しました。確認:"
"$CODEX_BIN" mcp get "$NAME" || true
echo
echo "注意: submit_task は受付だけなので短時間で返ります。"
echo "      長い待ちは get_task_status を繰り返して確認します。"
