#!/usr/bin/env bash
# A30 サーバーで qwen-worker 本体を 1 回の実行で導入する（冪等。再実行は既存ものを触らない）。
set -euo pipefail

WORKER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$WORKER_DIR/.venv"
LINK_TARGET="$HOME/.local/share/qwen-worker"
CONFIG_DIR="$HOME/.config/qwen-worker"
CONFIG_FILE="$CONFIG_DIR/config.toml"
RUNNER="$LINK_TARGET/run-qwen-worker"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --no-mcp    Claude Code / Codex への MCP 登録を省略
  -h, --help  この説明を表示して終了
EOF
}

NO_MCP=false
while [ $# -gt 0 ]
do
  case "$1" in
    --no-mcp)
      NO_MCP=true
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

echo "== qwen-worker 導入（A30 サーバー） =="

# ---------------------------------------------------------------- [1/5]
echo
echo "[1/5] venv"
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
if [ -d "$VENV_DIR" ]; then
  echo "venv: 既にあります（$VENV_DIR）"
else
  (
    cd -- "$WORKER_DIR"
    "$UV_BIN" venv --python 3.12 .venv
    "$UV_BIN" pip install --python .venv/bin/python -r requirements.lock.txt
    "$UV_BIN" pip install --python .venv/bin/python -e .
  )
  echo "venv: 作成しました（$VENV_DIR）"
fi

# ---------------------------------------------------------------- [2/5]
echo
echo "[2/5] シンボリックリンク（$LINK_TARGET）"
if [ -e "$LINK_TARGET" ] || [ -L "$LINK_TARGET" ]; then
  ACTUAL_TARGET="$(readlink -f -- "$LINK_TARGET")"
  if [ "$ACTUAL_TARGET" = "$WORKER_DIR" ]; then
    echo "symlink: 既にあります（$LINK_TARGET -> $ACTUAL_TARGET）"
  else
    if [ -L "$LINK_TARGET" ]; then
      echo "警告: シンボリックリンクの向き先が WORKER_DIR ではありません。" >&2
    else
      echo "警告: $LINK_TARGET はシンボリックリンクではなく、そこに別のファイル・ディレクトリが存在しています。" >&2
    fi
    echo "  現在  : $LINK_TARGET -> $ACTUAL_TARGET" >&2
    echo "  期待値: $WORKER_DIR" >&2
    echo "勝手に張り替えないで終了します。確認して手動で対処してください。" >&2
    exit 1
  fi
else
  mkdir -p "$HOME/.local/share"
  ln -s "$WORKER_DIR" "$LINK_TARGET"
  echo "symlink: 作成しました（$LINK_TARGET -> $WORKER_DIR）"
fi

# ---------------------------------------------------------------- [3/5]
echo
echo "[3/5] 設定（$CONFIG_FILE）"
if [ -f "$CONFIG_FILE" ]; then
  echo "設定: 既にあります（$CONFIG_FILE）"
else
  EXAMPLE_FILE="$WORKER_DIR/config.toml.example"
  if [ ! -f "$EXAMPLE_FILE" ]; then
    echo "設定の雛形が見つかりません: $EXAMPLE_FILE" >&2
    exit 1
  fi
  mkdir -p "$CONFIG_DIR"
  cp -p "$EXAMPLE_FILE" "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"
  echo "設定: 作成しました（$CONFIG_FILE）"
fi

# ---------------------------------------------------------------- [4/5]
echo
echo "[4/5] MCP 登録"
if $NO_MCP; then
  echo "MCP 登録: 既にあります（--no-mcp により新規作成を省略しました。登録そのものは触っていません）"
else
  MCP_CREATED=false
  if command -v claude >/dev/null 2>&1; then
    if claude mcp get qwen-worker >/dev/null 2>&1; then
      echo "claude: 既にあります"
    else
      claude mcp add -s user qwen-worker -- "$RUNNER"
      echo "claude: 作成しました"
      MCP_CREATED=true
    fi
  else
    echo "claude: スキップ（claude コマンドが無い）"
  fi
  CODEX_BIN=""
  if command -v codex >/dev/null 2>&1; then
    CODEX_BIN="$(command -v codex)"
  elif [ -x /usr/lib/chatgpt/resources/codex ]; then
    CODEX_BIN="/usr/lib/chatgpt/resources/codex"
  fi
  if [ -n "$CODEX_BIN" ]; then
    if "$CODEX_BIN" mcp get qwen-worker >/dev/null 2>&1; then
      echo "codex: 既にあります"
    else
      "$CODEX_BIN" mcp add qwen-worker -- "$RUNNER"
      echo "codex: 作成しました"
      MCP_CREATED=true
    fi
  else
    echo "codex: スキップ（codex コマンドも /usr/lib/chatgpt/resources/codex も無い）"
  fi
  if $MCP_CREATED; then
    echo "MCP 登録: 作成しました"
  else
    echo "MCP 登録: 既にあります（新規作成はしていません）"
  fi
fi

# ---------------------------------------------------------------- [5/5]
echo
echo "[5/5] 点検"
TEST_RC=0
"$WORKER_DIR/.venv/bin/python" "$WORKER_DIR/tests/test_sandbox.py" || TEST_RC=$?
if [ "$TEST_RC" -eq 0 ]; then
  echo "点検: 合格しました（作成しました。test_sandbox.py 終了コード 0）"
else
  echo "点検: 不合格（作成しました。test_sandbox.py 終了コード $TEST_RC。修正後再実行してください）"
  echo "→ 点検失敗: [1/5] venv を確認してください（uv pip install が未完了の場合）"
fi
echo
echo "他の PC の鍵を受け入れる・取り消す: $WORKER_DIR/remote/add-remote-key.sh, remove-remote-key.sh（他の PC 側は remote/setup-remote.sh / .ps1 が 1 回で行う）"
echo "次にやること: 新しい会話を開く"
exit "$TEST_RC"
