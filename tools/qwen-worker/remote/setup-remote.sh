#!/usr/bin/env bash
# 他の PC（macOS / Linux）で実行する。qwen-worker を SSH 越しに Claude Code / Codex へ登録する。
#
# 使い方:  bash setup-remote.sh <ホストIP> [--server-user USER] [--skip-server]
#   例: bash setup-remote.sh 192.168.1.10 --server-user alice
#   ホストIP は必須。環境変数 LOCALAI_SERVER_HOST でも指定できる。
#   SSH ユーザーは --server-user か環境変数 LOCALAI_SERVER_USER。無ければこの PC のユーザー名。
#
# やること:
#   1. 専用鍵 ~/.ssh/qwen-worker を作る（既にあれば再利用）
#   2. ~/.ssh/config に Host qwen-worker 節を足す（既にあれば触らない）
#   3. claude / codex があれば MCP 登録し、タイムアウトを合わせる
#   4. サーバーへ登録: 公開鍵を標準入力で add-remote-key.sh に渡す（ssh がパスワードを 1 回聞く）
#   5. 疎通確認: ssh -n -T qwen-worker と（あれば）claude mcp get qwen-worker
#
#   --skip-server を指定すると 4 と 5 を行わず、公開鍵と手で打つコマンドの表示だけで終わる。
#   パスワード・パスフレーズはこのスクリプトが受け取ったり保存したりしない。
set -euo pipefail

server_ip="${LOCALAI_SERVER_HOST:-}"
server_user="${LOCALAI_SERVER_USER:-$(id -un)}"
skip_server=0
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-server) skip_server=1; shift ;;
    --server-user) server_user="${2:?--server-user にはユーザー名が要る}"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) server_ip="$1"; shift ;;
  esac
done
if [ -z "$server_ip" ]; then
  echo "ホストIP が未指定です。引数か環境変数 LOCALAI_SERVER_HOST で指定してください。" >&2
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi
key_file="$HOME/.ssh/qwen-worker"
pc_name="$(hostname -s 2>/dev/null || hostname)"

mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"

# 1. 鍵
if [ -f "$key_file" ]; then
  echo "[1/5] 鍵は既にあります: $key_file"
else
  ssh-keygen -t ed25519 -N "" -f "$key_file" -C "qwen-worker@$pc_name" >/dev/null
  echo "[1/5] 鍵を作りました: $key_file"
fi

# 2. ssh config
config_file="$HOME/.ssh/config"
touch "$config_file"; chmod 600 "$config_file"
if grep -qE '^Host qwen-worker$' "$config_file"; then
  echo "[2/5] ~/.ssh/config に Host qwen-worker は既にあります。触りません。"
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
  echo "[2/5] ~/.ssh/config に Host qwen-worker を追記しました。"
fi

# 3. MCP 登録
if command -v claude >/dev/null 2>&1; then
  if claude mcp get qwen-worker >/dev/null 2>&1; then
    echo "[3/5] Claude Code: qwen-worker は既に登録済み。"
  else
    claude mcp add -s user qwen-worker -- ssh -T qwen-worker
    echo "[3/5] Claude Code: 登録しました。"
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
  echo "[3/5] claude コマンドが無いので Claude Code の登録は省略。"
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

# 4. サーバーへ登録（公開鍵を stdin で渡す。ssh がパスワードを対話で 1 回聞く）
if [ "$skip_server" -eq 1 ]; then
  echo
  echo "[4/5] --skip-server 指定のためサーバへの登録と疎通確認をスキップします。"
  echo "      手動登録: ssh $server_user@$server_ip 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh $pc_name -' < $key_file.pub"
  echo "      または Samba 共有 \\\\$server_ip\\$server_user からファイルを渡して add-remote-key.sh に食わせる。"
  echo
  cat "$key_file.pub"
  echo
  echo "受け入れ後の疎通確認:  ssh -n -T qwen-worker   （JSON が返らず即終了すれば OK。エラーが出なければ接続は通っている）"
  echo "MCP の確認:            claude mcp get qwen-worker      （Connected になること）"
  exit 0
fi

echo
echo "[4/5] サーバー（$server_ip）へ公開鍵を登録します: add-remote-key.sh $pc_name"
echo "      ssh がパスワードを対話で 1 回聞きます。パスワードはこのスクリプトに渡しません・保存しません。"
ssh_exit=0
# set -e の下で ssh の失敗で即終了しないように if で受ける
if ssh "$server_user@$server_ip" "bash ~/.local/share/qwen-worker/remote/add-remote-key.sh ${pc_name} -" < "$key_file.pub"; then
  echo "      登録コマンドを実行しました。"
else
  ssh_exit=$?
  echo
  echo "      !! サーバーへの登録に失敗しました（ssh 終了コード $ssh_exit）。"
  echo "      手動で打ってください:"
  echo "         ssh $server_user@$server_ip 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh $pc_name -' < $key_file.pub"
  echo "      公開鍵の内容は次の通りです:"
  echo
  cat "$key_file.pub"
  echo
  exit 1
fi

# 5. 疎通確認
echo
echo "[5/5] 疎通確認: ssh -n -T qwen-worker"
probe_ok=0
if ssh -n -T qwen-worker >/dev/null 2>&1; then
  probe_ok=1
fi
if [ "$probe_ok" -eq 1 ]; then
  echo "      接続 OK"
else
  echo "      接続 NG"
  echo "      原因の見方:"
  echo "        - Enter passphrase for key と聞かれる / 鍵を拒否される: 鍵にパスフレーズが付いているか、authorized_keys に未登録。"
  echo "          パスフレーズは ssh-keygen -p -f $key_file （旧を入力、新は Enter 2 回）で外す。"
  echo "        - Permission denied (publickey): authorized_keys にこの PC の鍵が無い。手順 4 を成功させる。"
  echo "        - hostname 解決できない: ~/.ssh/config の HostName が $server_ip か確認。"
fi
if command -v claude >/dev/null 2>&1; then
  echo
  echo "      MCP の確認: claude mcp get qwen-worker"
  claude mcp get qwen-worker
fi
echo
if [ "$probe_ok" -eq 1 ]; then
  echo "設定完了。Claude Code / Codex から qwen-worker を呼べるはずです。"
else
  echo "設定は進んでいますが接続 NG でした。上の原因の見方を確認してください。"
  exit 1
fi
