#!/usr/bin/env bash
# A30 サーバーで local-ai-bridge を 1 回の実行で導入する（冪等。再実行は既存ものを触らない）。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BRIDGE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
OPENCODE_BIN="$HOME/.opencode/bin/opencode"
CONFIG_DIR="$HOME/.config/local-ai-bridge"
CONFIG="$CONFIG_DIR/bridge.toml"
RUNNER="$BRIDGE_DIR/run-local-ai-task"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --allowed-root DIR    許可ルート（複数可。既定: $HOME/Proj）
  --workspace PATH      登録する作業場所のパス（複数可。既定なし）
  --mcp-scope SCOPE     MCP 登録スコープ: local / user（既定: local）
  --no-rules            委譲ルールの追記をしない
  --no-skills           スキルの作成をしない
  -h, --help            この説明を表示して終了
EOF
}

ALLOWED_ROOTS=()
WORKSPACES=()
MCP_SCOPE="local"
NO_RULES=false
NO_SKILLS=false

while [ $# -gt 0 ]
do
  case "$1" in
    --allowed-root)
      if [ $# -lt 2 ]; then echo "--allowed-root には値が必要です" >&2; exit 2; fi
      ALLOWED_ROOTS+=("$2")
      shift 2
      ;;
    --workspace)
      if [ $# -lt 2 ]; then echo "--workspace には値が必要です" >&2; exit 2; fi
      WORKSPACES+=("$2")
      shift 2
      ;;
    --mcp-scope)
      if [ $# -lt 2 ]; then echo "--mcp-scope には値が必要です" >&2; exit 2; fi
      MCP_SCOPE="$2"
      shift 2
      ;;
    --no-rules)
      NO_RULES=true
      shift
      ;;
    --no-skills)
      NO_SKILLS=true
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

case "$MCP_SCOPE" in
  local|user) ;;
  *) echo "--mcp-scope は local / user のいずれかです: $MCP_SCOPE" >&2; exit 2 ;;
esac

if [ "${#ALLOWED_ROOTS[@]}" -eq 0 ]; then
  ALLOWED_ROOTS=("$HOME/Proj")
fi

echo "== local-ai-bridge 導入（A30 サーバー） =="

# ---------------------------------------------------------------- [1/7]
echo
echo "[1/7] 前提"
if [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
elif command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
else
  echo "uv がありません。導入方法:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "導入後にこのスクリプトを再実行してください。"
  exit 2
fi
echo "uv: 既にあります（$UV_BIN）"
if command -v python3 >/dev/null 2>&1; then
  echo "python3: 既にあります（$(command -v python3)）"
else
  echo "python3 がありません。python3 を入れた後にこのスクリプトを再実行してください。"
  exit 2
fi

# ---------------------------------------------------------------- [2/7]
echo
echo "[2/7] OpenCode"
if [ -x "$OPENCODE_BIN" ]; then
  "$OPENCODE_BIN" --version
  echo "OpenCode: 既にあります"
else
  echo "OpenCode が見つからないため導入します（v1.18.31）"
  curl -fsSL https://opencode.ai/install | bash -s -- --version 1.18.31 --no-modify-path
  echo "OpenCode: 作成しました"
fi

# ---------------------------------------------------------------- [3/7]
echo
echo "[3/7] 仮想環境（venv）"
if [ -d "$BRIDGE_DIR/.venv" ]; then
  echo "venv: 既にあります（$BRIDGE_DIR/.venv）"
else
  (
    cd -- "$BRIDGE_DIR"
    "$UV_BIN" venv --python 3.12 .venv
    "$UV_BIN" pip install --python .venv/bin/python -r requirements.lock.txt
    "$UV_BIN" pip install --python .venv/bin/python -e .
  )
  echo "venv: 作成しました"
fi

# ---------------------------------------------------------------- [4/7]
echo
echo "[4/7] 設定（$CONFIG）"
if [ -f "$CONFIG" ]; then
  if grep -q '^\[registration\]' "$CONFIG" && grep -q '^allowed_roots' "$CONFIG"; then
    echo "設定: 既にあります（[registration] と allowed_roots があります）"
  else
    echo "設定: 既にあります（[registration] または allowed_roots が無いようです。中身は触りません）"
  fi
else
  EXAMPLE="$BRIDGE_DIR/config/bridge.toml.example"
  if [ ! -f "$EXAMPLE" ]; then
    echo "設定の雛形が見つかりません: $EXAMPLE" >&2
    exit 1
  fi
  mkdir -p "$CONFIG_DIR"
  cp -p "$EXAMPLE" "$CONFIG"
  chmod 600 "$CONFIG"
  BACKUP="$CONFIG.bak.$(date +%Y%m%d-%H%M%S)"
  cp -p "$CONFIG" "$BACKUP"
  python3 - "$CONFIG" "${ALLOWED_ROOTS[@]}" <<'PY'
import json
import pathlib
import re
import sys

path, *roots = sys.argv[1:]
line = "allowed_roots = [" + ", ".join(json.dumps(root) for root in roots) + "]"
text = pathlib.Path(path).read_text(encoding="utf-8")
if re.search(r"(?m)^[ \t]*\[registration\]", text):
    if re.search(r"(?m)^[ \t]*allowed_roots[ \t]*=", text):
        text = re.sub(r"(?m)^[ \t]*allowed_roots[ \t]*=.*$", lambda _: line, text, count=1)
    else:
        text = re.sub(
            r"(?m)^(?P<header>[ \t]*\[registration\][ \t]*)$",
            lambda matched: matched.group("header") + "\n" + line,
            text,
            count=1,
        )
else:
    text = text.rstrip("\n") + "\n\n[registration]\n" + line + "\n"
pathlib.Path(path).write_text(text, encoding="utf-8")
PY
  echo "設定: 作成しました（allowed_roots: ${ALLOWED_ROOTS[*]}。退避: $BACKUP）"
fi

# ---------------------------------------------------------------- [5/7]
echo
echo "[5/7] MCP 登録"
MCP_REGISTERED=false
if command -v claude >/dev/null 2>&1; then
  "$BRIDGE_DIR/scripts/register-claude.sh" "$MCP_SCOPE"
  MCP_REGISTERED=true
else
  echo "claude コマンドが無いので、claude への MCP 登録を省略しました"
fi
if command -v codex >/dev/null 2>&1 || [ -x /usr/lib/chatgpt/resources/codex ]; then
  "$BRIDGE_DIR/scripts/register-codex.sh"
  MCP_REGISTERED=true
else
  echo "codex が見つからないので、codex への MCP 登録を省略しました"
fi
if $MCP_REGISTERED; then
  echo "MCP 登録: 作成しました"
else
  echo "MCP 登録: 既にあります（登録対象のコマンドが無いため何も作成せず省略しました）"
fi

# ---------------------------------------------------------------- [6/7]
echo
echo "[6/7] スキルとルール"
if $NO_SKILLS && $NO_RULES; then
  echo "スキル・ルール: 既にあります（--no-skills --no-rules によりスキップ）"
else
  if $NO_SKILLS; then
    echo "スキル: スキップ（--no-skills）"
  else
    "$BRIDGE_DIR/scripts/install-skills.sh"
  fi
  if $NO_RULES; then
    echo "ルール: スキップ（--no-rules）"
  else
    RULE_TARGETS=("$HOME/.claude/CLAUDE.md")
    if [ -d "$HOME/.codex" ]; then
      RULE_TARGETS+=("$HOME/.codex/AGENTS.md")
    fi
    "$BRIDGE_DIR/scripts/add-delegation-rules.sh" --short "${RULE_TARGETS[@]}"
  fi
  echo "スキル・ルール: 作成しました"
fi

# ---------------------------------------------------------------- [7/7]
echo
echo "[7/7] 作業場所"
if [ "${#WORKSPACES[@]}" -eq 0 ]; then
  echo "作業場所: 既にあります（--workspace が無いためスキップ）"
else
  for workspace_path in "${WORKSPACES[@]}"; do
    if "$RUNNER" workspace which "$workspace_path"; then
      echo "$workspace_path: 登録済み（既にあります）"
    else
      "$RUNNER" workspace add "$workspace_path"
      echo "$workspace_path: 作成しました（workspace 登録）"
      echo "検証プロファイルは付けません。--verify/--cmd は後で人が足す"
    fi
  done
fi

doctor_rc=0
"$RUNNER" doctor || doctor_rc=$?

echo
echo "次にやること: 新しい会話を開く（MCP の新しいツールは再接続後にしか見えない）。/qwen と /qwen-read が候補に出る"
exit "$doctor_rc"
