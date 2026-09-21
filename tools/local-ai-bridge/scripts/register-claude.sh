#!/usr/bin/env bash
# Claude Code へ stdio MCP サーバー local-ai-bridge を登録する。
# 既定は local スコープ（このプロジェクトだけ・この利用者だけ）。
# 再実行しても重複しない。既存の登録があれば入れ替える。
set -euo pipefail

CLAUDE_BIN="${CLAUDE_BIN:-/home/mt/.local/bin/claude}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
LAUNCHER="$HERE/run-local-ai-bridge"
NAME="local-ai-bridge"
SCOPE="${1:-local}"

case "$SCOPE" in
  local|user|project) ;;
  *) echo "スコープは local / user / project のいずれか: $SCOPE" >&2; exit 2 ;;
esac

if [ ! -x "$CLAUDE_BIN" ]; then
  echo "claude が見つかりません: $CLAUDE_BIN" >&2
  exit 1
fi
if [ ! -x "$LAUNCHER" ]; then
  echo "起動スクリプトがありません: $LAUNCHER" >&2
  exit 1
fi

if "$CLAUDE_BIN" mcp get "$NAME" >/dev/null 2>&1; then
  echo "既存の登録を削除します（重複を避けるため）。"
  "$CLAUDE_BIN" mcp remove -s "$SCOPE" "$NAME" >/dev/null 2>&1 || true
fi

"$CLAUDE_BIN" mcp add -s "$SCOPE" "$NAME" -- "$LAUNCHER"
echo
echo "登録しました。確認:"
"$CLAUDE_BIN" mcp get "$NAME" || true
echo
echo "注意: 現在の会話には即時反映されません。"
echo "      新しい Claude Code の会話を開いてから使ってください。"
