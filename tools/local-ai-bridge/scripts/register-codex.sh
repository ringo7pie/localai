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

# Codex のツール呼び出しは既定 60 秒で切れる。wait_for_task は
# bridge.toml の wait_for_task_max_sec（既定 2000 秒）までブロックするので、
# 足さないと必ず時間切れになり、親が wait を呼び直す往復が増える。
if [ -f "$CONFIG" ] && ! grep -A6 "^\[mcp_servers.$NAME\]" "$CONFIG" | grep -q tool_timeout_sec; then
  python3 - "$CONFIG" "$NAME" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1]); name = sys.argv[2]
text = path.read_text(encoding="utf-8")
head, sep, tail = text.partition(f"[mcp_servers.{name}]\n")
if sep:
    body, marker, rest = tail.partition("\n[")
    body = body.rstrip("\n") + "\nstartup_timeout_sec = 30\ntool_timeout_sec = 2100\n"
    path.write_text(head + sep + body + (marker + rest if marker else ""), encoding="utf-8")
    print("config.toml にタイムアウト（startup 30 秒 / tool 2100 秒）を足しました。")
PY
fi
echo
echo "登録しました。確認:"
"$CODEX_BIN" mcp get "$NAME" || true
echo
echo "注意: submit_task は受付だけなので短時間で返ります。"
echo "      長い待ちは get_task_status を繰り返して確認します。"
