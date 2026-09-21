#!/usr/bin/env bash
# 今回追加したものだけを戻す。既存の設定には触らない。
# 実際には削除せず、何を消せばよいかを表示する（誤削除を避けるため）。
# --apply を付けたときだけ、登録の解除と隔離プロファイルの削除を行う。
set -euo pipefail

APPLY=false
[ "${1:-}" = "--apply" ] && APPLY=true

CLAUDE_BIN="${CLAUDE_BIN:-/home/mt/.local/bin/claude}"
CODEX_BIN="${CODEX_BIN:-/usr/lib/chatgpt/resources/codex}"
STATE="${LOCAL_AI_BRIDGE_STATE:-$HOME/.local/state/local-ai-bridge}"
CONFIG="${LOCAL_AI_BRIDGE_CONFIG:-$HOME/.config/local-ai-bridge/bridge.toml}"

cat <<EOF
今回追加したもの（これ以外は触っていない）:

  1. MCP 登録         Claude Code: local-ai-bridge / Codex: local-ai-bridge
  2. 設定             $CONFIG
  3. 状態と台帳        $STATE
  4. OpenCode 本体     \$HOME/.opencode/bin/opencode（公式インストーラで導入）
  5. 連携層のソース     このリポジトリの tools/local-ai-bridge/

変更していないもの:
  - ~/.config/opencode（利用者の通常の OpenCode 設定。隔離プロファイルとは別）
  - Ollama のサービス設定、モデル、ドライバー、CUDA
  - Claude Code / Codex の既存ログインとモデル設定
  - 各リポジトリの作業ツリー（worktree の外へは書いていない）
EOF

if ! $APPLY; then
  echo
  echo "実際に戻すには --apply を付けて実行してください。"
  exit 0
fi

echo
echo "=== MCP 登録を解除 ==="
[ -x "$CLAUDE_BIN" ] && "$CLAUDE_BIN" mcp remove -s local local-ai-bridge 2>/dev/null || true
[ -x "$CODEX_BIN" ] && "$CODEX_BIN" mcp remove local-ai-bridge 2>/dev/null || true

echo "=== 残っている worktree を外す ==="
if [ -d "$STATE/worktrees" ]; then
  for dir in "$STATE/worktrees"/*; do
    [ -d "$dir" ] || continue
    repo=$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
    if [ -n "$repo" ]; then
      git -C "$(dirname "$repo")" worktree remove --force "$dir" 2>/dev/null || true
    fi
  done
fi

echo "=== 隔離プロファイルを外す（台帳とログは残す） ==="
echo "削除対象: $STATE/opencode-profile"
echo "台帳とタスクログは証拠なので残します。不要なら手で削除してください:"
echo "  $STATE/ledger.db  $STATE/tasks/"
rm -rf "$STATE/opencode-profile"
echo "完了。"
