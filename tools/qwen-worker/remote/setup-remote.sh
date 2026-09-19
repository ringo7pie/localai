#!/usr/bin/env bash
# 他の PC（macOS / Linux）で実行する。qwen-worker を SSH 越しに Claude Code / Codex へ登録する。
#
# 使い方:  bash setup-remote.sh [ホストIP]   （省略時 <server-ip>）
#
# やること:
#   1. 専用鍵 ~/.ssh/qwen-worker を作る（既にあれば再利用）
#   2. ~/.ssh/config に Host qwen-worker 節を足す（既にあれば触らない）
#   3. claude / codex があれば MCP 登録し、タイムアウトを合わせる
#   4. 公開鍵を表示する → これをサーバ側の add-remote-key.sh に渡す
set -euo pipefail

server_ip="${1:-<server-ip>}"
server_user="mt"
key_file="$HOME/.ssh/qwen-worker"
pc_name="$(hostname -s 2>/dev/null || hostname)"

mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"

# 1. 鍵
if [ -f "$key_file" ]; then
  echo "[1/4] 鍵は既にあります: $key_file"
else
  ssh-keygen -t ed25519 -N "" -f "$key_file" -C "qwen-worker@$pc_name" >/dev/null
  echo "[1/4] 鍵を作りました: $key_file"
fi

# 2. ssh config
config_file="$HOME/.ssh/config"
touch "$config_file"; chmod 600 "$config_file"
if grep -qE '^Host qwen-worker$' "$config_file"; then
  echo "[2/4] ~/.ssh/config に Host qwen-worker は既にあります。触りません。"
else
  cat >> "$config_file" <<CFG

Host qwen-worker
  HostName $server_ip
  User $server_user
  IdentityFile $key_file
  IdentitiesOnly yes
  ServerAliveInterval 30
  RequestTTY no
CFG
  echo "[2/4] ~/.ssh/config に Host qwen-worker を追記しました。"
fi

# 3. MCP 登録
if command -v claude >/dev/null 2>&1; then
  if claude mcp get qwen-worker >/dev/null 2>&1; then
    echo "[3/4] Claude Code: qwen-worker は既に登録済み。"
  else
    claude mcp add -s user qwen-worker -- ssh -T qwen-worker
    echo "[3/4] Claude Code: 登録しました。"
  fi
  settings="$HOME/.claude/settings.json"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$settings" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True)
data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
env = data.setdefault("env", {})
changed = False
for key, value in (("MCP_TOOL_TIMEOUT", "2100000"), ("MCP_TIMEOUT", "30000")):
    if env.get(key) != value:
        env[key] = value; changed = True
if changed:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("      settings.json の env に MCP_TOOL_TIMEOUT / MCP_TIMEOUT を足しました（他の設定は無傷）。")
else:
    print("      settings.json のタイムアウトは既に設定済み。")
PY
  else
    echo "      python3 が無いため settings.json は手で編集: env に MCP_TOOL_TIMEOUT=2100000, MCP_TIMEOUT=30000"
  fi
else
  echo "[3/4] claude コマンドが無いので Claude Code の登録は省略。"
fi

if command -v codex >/dev/null 2>&1; then
  if codex mcp get qwen-worker >/dev/null 2>&1; then
    echo "      Codex: qwen-worker は既に登録済み。"
  else
    codex mcp add qwen-worker -- ssh -T qwen-worker
    echo "      Codex: 登録しました。"
  fi
  codex_cfg="${CODEX_HOME:-$HOME/.codex}/config.toml"
  if [ -f "$codex_cfg" ] && ! grep -A6 '^\[mcp_servers.qwen-worker\]' "$codex_cfg" | grep -q tool_timeout_sec; then
    python3 - "$codex_cfg" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1]); text = path.read_text(encoding="utf-8")
head, sep, tail = text.partition("[mcp_servers.qwen-worker]\n")
if sep:
    body, marker, rest = tail.partition("\n[")
    body = body.rstrip("\n") + "\ntool_timeout_sec = 2100\nstartup_timeout_sec = 30\n"
    path.write_text(head + sep + body + (marker + rest if marker else ""), encoding="utf-8")
    print("      config.toml にタイムアウトを足しました。")
PY
  fi
else
  echo "      codex コマンドが無いので Codex の登録は省略。"
fi

# 4. 公開鍵を表示
echo
echo "[4/4] この公開鍵をサーバ（$server_ip）側で受け入れてください:"
echo "      ssh $server_user@$server_ip 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh $pc_name -' < $key_file.pub"
echo "      または Samba 共有 \\\\$server_ip\\mt からファイルを渡して add-remote-key.sh に食わせる。"
echo
cat "$key_file.pub"
echo
echo "受け入れ後の疎通確認:  ssh -T qwen-worker </dev/null   （JSON が返らず即終了すれば OK。エラーが出なければ接続は通っている）"
echo "MCP の確認:            claude mcp get qwen-worker      （Connected になること）"
