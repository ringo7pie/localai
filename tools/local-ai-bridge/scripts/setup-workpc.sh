#!/usr/bin/env bash
# 他の PC（macOS / Linux / WSL2）で実行する。local-ai-bridge をその PC に導入し、
# SSH トンネル越しに A30 サーバー（--server-ip か環境変数 LOCALAI_SERVER_HOST で指定）の Ollama を使える状態にする。
#
# 1 回の実行で [1/7]〜[7/7] を全部済ませる。再実行しても既にあるものは触らず
# 「既にあります」と表示する（冪等）。
#
# 注意: このスクリプトは「作業 PC」側で実行するもの。A30 サーバー自身の上では
#       実行しないこと（[2/7] でサーバー側の ~/.ssh/authorized_keys を書き換える）。
set -euo pipefail

# サーバーの IP は --server-ip か環境変数 LOCALAI_SERVER_HOST で必ず指定する（既定値は持たない）。
# SSH ユーザーは --server-user か環境変数 LOCALAI_SERVER_USER。無ければこの PC のユーザー名。
server_ip="${LOCALAI_SERVER_HOST:-}"
server_user="${LOCALAI_SERVER_USER:-$(id -un)}"
install_dir="$HOME/local-ai-bridge"
allowed_roots=()
skip_server=false
no_rules=false

print_usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --server-ip IP        A30 サーバーの IP（必須。環境変数 LOCALAI_SERVER_HOST でも指定できる）
  --server-user USER    A30 サーバーの SSH ユーザー名
                        （既定: 環境変数 LOCALAI_SERVER_USER、無ければこの PC のユーザー名）
  --install-dir DIR     local-ai-bridge の導入先（既定: \$HOME/local-ai-bridge）
  --allowed-root DIR    許可ルート（複数可。既定: \$HOME/Proj）
  --skip-server         サーバーへの鍵登録を行わず、手動コマンドの表示だけにする
  --no-rules            ~/.claude/CLAUDE.md への委譲ルール追記をしない
  -h, --help            この説明を表示して終了

例:
  $(basename -- "$0") --server-ip 192.168.1.10
  $(basename -- "$0") --server-ip 192.168.1.10 --server-user alice --allowed-root \$HOME/Proj --allowed-root \$HOME/work
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --server-ip)
      if [ $# -lt 2 ]; then echo "--server-ip には値が必要です" >&2; exit 2; fi
      server_ip="$2"
      shift 2
      ;;
    --server-user)
      if [ $# -lt 2 ]; then echo "--server-user には値が必要です" >&2; exit 2; fi
      server_user="$2"
      shift 2
      ;;
    --install-dir)
      if [ $# -lt 2 ]; then echo "--install-dir には値が必要です" >&2; exit 2; fi
      install_dir="$2"
      shift 2
      ;;
    --allowed-root)
      if [ $# -lt 2 ]; then echo "--allowed-root には値が必要です" >&2; exit 2; fi
      allowed_roots+=("$2")
      shift 2
      ;;
    --skip-server)
      skip_server=true
      shift
      ;;
    --no-rules)
      no_rules=true
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "未知の引数です: $1" >&2
      print_usage
      exit 2
      ;;
  esac
done

if [ -z "$server_ip" ]; then
  echo "サーバーの IP が未指定です。--server-ip か環境変数 LOCALAI_SERVER_HOST で指定してください。" >&2
  print_usage >&2
  exit 2
fi

if [ "${#allowed_roots[@]}" -eq 0 ]; then
  allowed_roots=("$HOME/Proj")
fi

echo "== local-ai-bridge 導入（作業 PC） =="
echo "サーバー: $server_user@$server_ip / 導入先: $install_dir / 許可ルート: ${allowed_roots[*]}"

key_file="$HOME/.ssh/a30-tunnel"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# ---------------------------------------------------------------- [1/7]
echo
echo "[1/7] SSH 鍵（トンネル専用）"
if [ -f "$key_file" ]; then
  echo "鍵は既にあります: $key_file"
else
  pc_name="$(hostname -s 2>/dev/null || hostname)"
  if ssh-keygen -t ed25519 -N "" -f "$key_file" -C "a30-tunnel@$pc_name" >/dev/null; then
    echo "鍵を作成しました: $key_file"
  else
    echo "鍵の作成に失敗しました" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- [2/7]
echo
echo "[2/7] サーバー側 authorized_keys"
pubkey_line="$(cat "$key_file.pub")"
key_body="$(awk '{print $2}' "$key_file.pub")"
restricted_entry="restrict,port-forwarding,permitopen=\"127.0.0.1:11434\",command=\"echo tunnel-only\" ${pubkey_line}"

if $skip_server; then
  echo "--skip-server が指定されたため、サーバーへの登録は行いません。"
  echo "手動で次を行ってください:"
  echo "  1. ssh $server_user@$server_ip"
  echo "  2. ~/.ssh/authorized_keys に次の 1 行を追記して chmod 600 ~/.ssh/authorized_keys:"
  echo "     $restricted_entry"
else
  if remote_output="$(ssh "$server_user@$server_ip" bash -s -- "$key_body" "$restricted_entry" <<'REMOTE'
set -euo pipefail
key_body="$1"
full_entry="$2"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
if grep -qF -- "$key_body" "$HOME/.ssh/authorized_keys"; then
  echo "ALREADY_EXISTS"
else
  printf '%s\n' "$full_entry" >> "$HOME/.ssh/authorized_keys"
  chmod 600 "$HOME/.ssh/authorized_keys"
  echo "ADDED"
fi
REMOTE
)"; then
    case "$remote_output" in
      *ALREADY_EXISTS*)
        echo "サーバー側 authorized_keys: 既にあります"
        ;;
      *ADDED*)
        echo "サーバー側 authorized_keys: 作成しました"
        ;;
      *)
        echo "サーバーからの応答を判別できませんでした: $remote_output" >&2
        echo "手動で次の 1 行を ~/.ssh/authorized_keys に追記してください:" >&2
        echo "  $restricted_entry" >&2
        exit 1
        ;;
    esac
  else
    ssh_exit=$?
    echo "サーバーへの鍵登録に失敗しました（ssh 終了コード $ssh_exit）。" >&2
    echo "手動で次を行ってください:" >&2
    echo "  1. ssh $server_user@$server_ip" >&2
    echo "  2. ~/.ssh/authorized_keys に次の 1 行を追記して chmod 600 ~/.ssh/authorized_keys:" >&2
    echo "     $restricted_entry" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- [3/7]
echo
echo "[3/7] ~/.ssh/config"
ssh_config="$HOME/.ssh/config"
touch "$ssh_config"
chmod 600 "$ssh_config"
if grep -qE '^Host a30-ollama$' "$ssh_config"; then
  echo "Host a30-ollama は既にあります（触りません）"
else
  cat >> "$ssh_config" <<CFG

Host a30-ollama
  HostName $server_ip
  User $server_user
  IdentityFile $key_file
  IdentitiesOnly yes
  LocalForward 127.0.0.1:11434 127.0.0.1:11434
  ExitOnForwardFailure yes
  ServerAliveInterval 30
  RequestTTY no
CFG
  echo "Host a30-ollama を作成しました"
fi

# ---------------------------------------------------------------- [4/7]
echo
echo "[4/7] トンネル起動ヘルパ"
bin_dir="$HOME/.local/bin"
state_dir="$HOME/.local/state"
mkdir -p "$bin_dir"
mkdir -p "$state_dir"
tunnel_script="$bin_dir/a30-tunnel"

if [ -f "$tunnel_script" ]; then
  echo "ヘルパは既にあります: $tunnel_script"
else
  cat > "$tunnel_script" <<'HELPER'
#!/usr/bin/env bash
# a30-tunnel: A30 サーバーへの SSH トンネル（Host a30-ollama）の起動・停止・状態確認。
set -euo pipefail

pid_file="$HOME/.local/state/a30-tunnel.pid"

is_alive() {
  if [ -f "$pid_file" ]; then
    existing_pid="$(cat "$pid_file")"
    if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

case "${1:-}" in
  start)
    if is_alive; then
      echo "既に起動しています（pid $(cat "$pid_file")）"
    else
      mkdir -p "$(dirname "$pid_file")"
      ssh -N -f a30-ollama
      found_pid="$(pgrep -f 'ssh -N -f a30-ollama' | head -n 1)"
      if [ -n "$found_pid" ]; then
        echo "$found_pid" > "$pid_file"
        echo "起動しました（pid $found_pid）"
      else
        echo "起動コマンドは実行しましたが pid を確認できませんでした" >&2
        exit 1
      fi
    fi
    ;;
  stop)
    if is_alive; then
      existing_pid="$(cat "$pid_file")"
      kill "$existing_pid"
      rm -f "$pid_file"
      echo "止めました（pid $existing_pid）"
    else
      rm -f "$pid_file"
      echo "起動していません"
    fi
    ;;
  status)
    status_ok=true
    if is_alive; then
      echo "トンネル: 起動中（pid $(cat "$pid_file")）"
    else
      echo "トンネル: 停止中"
      status_ok=false
    fi
    if command -v curl >/dev/null 2>&1; then
      if curl -s --max-time 5 http://127.0.0.1:11434/api/version; then
        echo
      else
        echo "Ollama への疎通確認に失敗しました" >&2
        status_ok=false
      fi
    else
      echo "curl が無いため疎通確認をスキップしました" >&2
      status_ok=false
    fi
    if ! $status_ok; then
      exit 1
    fi
    ;;
  *)
    echo "使い方: a30-tunnel {start|stop|status}" >&2
    exit 2
    ;;
esac
HELPER
  chmod +x "$tunnel_script"
  echo "ヘルパを作成しました: $tunnel_script"
fi

echo "a30-tunnel start を実行します"
tunnel_ok=true
if ! "$tunnel_script" start; then
  echo "a30-tunnel start が失敗しました（続行します）" >&2
  tunnel_ok=false
fi

echo "a30-tunnel status を実行します"
if ! "$tunnel_script" status; then
  echo "a30-tunnel status が疎通 NG を報告しました（続行します）" >&2
  tunnel_ok=false
fi

if $tunnel_ok; then
  echo "疎通確認: OK"
else
  echo "疎通確認: NG（[2/7] のサーバー登録と [3/7] の ~/.ssh/config を確認してください）"
fi

# ---------------------------------------------------------------- [5/7]
echo
echo "[5/7] uv と OpenCode"
uv_bin=""
if command -v uv >/dev/null 2>&1; then
  uv_bin="$(command -v uv)"
  echo "uv は既にあります（$uv_bin）"
elif [ -x "$HOME/.local/bin/uv" ]; then
  uv_bin="$HOME/.local/bin/uv"
  echo "uv は既にあります（$uv_bin）"
else
  echo "uv が無いため導入します"
  if curl -LsSf https://astral.sh/uv/install.sh | sh; then
    echo "uv を作成しました"
  else
    echo "uv の導入に失敗しました" >&2
    exit 1
  fi
  if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
  elif [ -x "$HOME/.local/bin/uv" ]; then
    uv_bin="$HOME/.local/bin/uv"
  else
    echo "uv を導入しましたが実行ファイルが見つかりません" >&2
    exit 1
  fi
fi

opencode_bin="$HOME/.opencode/bin/opencode"
if [ -x "$opencode_bin" ]; then
  echo "OpenCode は既にあります（$opencode_bin）"
else
  echo "OpenCode が無いため導入します（v1.19.2）"
  if curl -fsSL https://opencode.ai/install | bash -s -- --version 1.19.2 --no-modify-path; then
    echo "OpenCode を作成しました"
  else
    echo "OpenCode の導入に失敗しました" >&2
    exit 1
  fi
  if [ ! -x "$opencode_bin" ]; then
    echo "OpenCode を導入しましたが実行ファイルが見つかりません: $opencode_bin" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- [6/7]
echo
echo "[6/7] bridge 本体"
remote_src="${server_user}@${server_ip}:Proj/localai/tools/local-ai-bridge/"

if [ -d "$install_dir" ]; then
  echo "更新します。ローカルの変更は上書きされます: $install_dir"
else
  mkdir -p "$install_dir"
  echo "新規に取得します: $install_dir"
fi

if command -v rsync >/dev/null 2>&1; then
  if rsync -a --exclude .venv --exclude fixtures --exclude bench/ab-benchmark --exclude __pycache__ \
      "$remote_src" "$install_dir/"; then
    echo "bridge 本体を取得しました（rsync）"
  else
    echo "rsync での取得に失敗しました" >&2
    exit 1
  fi
else
  echo "rsync が無いため scp -r で代替します"
  if scp -r "${server_user}@${server_ip}:Proj/localai/tools/local-ai-bridge/." "$install_dir/"; then
    echo "bridge 本体を取得しました（scp）"
  else
    echo "scp での取得に失敗しました" >&2
    exit 1
  fi
fi

if [ -d "$install_dir/.venv" ]; then
  echo "venv は既にあります（$install_dir/.venv）"
else
  (
    cd -- "$install_dir"
    "$uv_bin" venv --python 3.12 .venv
    "$uv_bin" pip install --python .venv/bin/python -r requirements.lock.txt
    "$uv_bin" pip install --python .venv/bin/python -e .
  )
  echo "venv を作成しました"
fi

config_dir="$HOME/.config/local-ai-bridge"
config_file="$config_dir/bridge.toml"
if [ -f "$config_file" ]; then
  echo "設定ファイルは既にあります（触りません）: $config_file"
else
  example_file="$install_dir/config/bridge.toml.example"
  if [ ! -f "$example_file" ]; then
    echo "設定の雛形が見つかりません: $example_file" >&2
    exit 1
  fi
  mkdir -p "$config_dir"
  cp -p "$example_file" "$config_file"
  chmod 600 "$config_file"
  backup_file="$config_file.bak.$(date +%Y%m%d-%H%M%S)"
  cp -p "$config_file" "$backup_file"

  state_root="$HOME/.local/state/local-ai-bridge"
  opencode_config_source="$install_dir/opencode-profile/opencode.json"

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$config_file" "$opencode_bin" "$opencode_config_source" "$state_root" "${allowed_roots[@]}" <<'PY'
import json
import pathlib
import re
import sys

config_path, opencode_binary, config_source, state_root, *allowed_roots = sys.argv[1:]
text = pathlib.Path(config_path).read_text(encoding="utf-8")


def replace_line(source_text, key, value_literal):
    pattern = re.compile(r"(?m)^" + re.escape(key) + r"\s*=.*$")
    if not pattern.search(source_text):
        raise SystemExit("key not found: " + key)
    return pattern.sub(key + " = " + value_literal, source_text, count=1)


text = replace_line(text, "binary", json.dumps(opencode_binary))
text = replace_line(text, "config_source", json.dumps(config_source))
text = replace_line(text, "root", json.dumps(state_root))
roots_literal = "[" + ", ".join(json.dumps(root) for root in allowed_roots) + "]"
text = replace_line(text, "allowed_roots", roots_literal)

pathlib.Path(config_path).write_text(text, encoding="utf-8")
PY
  else
    echo "python3 が無いため sed で書き換えます"
    escaped_opencode_bin=$(printf '%s\n' "$opencode_bin" | sed 's/[&/\]/\\&/g')
    escaped_config_source=$(printf '%s\n' "$opencode_config_source" | sed 's/[&/\]/\\&/g')
    escaped_state_root=$(printf '%s\n' "$state_root" | sed 's/[&/\]/\\&/g')
    roots_value="[$(printf '"%s", ' "${allowed_roots[@]}" | sed 's/, $//')]"
    escaped_roots_value=$(printf '%s\n' "$roots_value" | sed 's/[&/\]/\\&/g')
    sed \
      -e "s#^binary = .*#binary = \"$escaped_opencode_bin\"#" \
      -e "s#^config_source = .*#config_source = \"$escaped_config_source\"#" \
      -e "s#^root = .*#root = \"$escaped_state_root\"#" \
      -e "s#^allowed_roots = .*#allowed_roots = $escaped_roots_value#" \
      "$config_file" > "$config_file.tmp"
    mv "$config_file.tmp" "$config_file"
  fi
  echo "設定ファイルを作成しました（$config_file。退避: $backup_file）"
fi

# ---------------------------------------------------------------- [7/7]
echo
echo "[7/7] 登録（claude / codex / スキル / ルール）"

if command -v claude >/dev/null 2>&1; then
  if claude mcp get local-ai-bridge >/dev/null 2>&1; then
    claude_already=true
  else
    claude_already=false
  fi
  "$install_dir/scripts/register-claude.sh" user
  if $claude_already; then
    echo "Claude Code への MCP 登録: 既にあります（再登録して最新化しました）"
  else
    echo "Claude Code への MCP 登録: 作成しました"
  fi
else
  echo "claude コマンドが無いため Claude Code への登録は省略しました"
fi

if command -v codex >/dev/null 2>&1; then
  if codex mcp get local-ai-bridge >/dev/null 2>&1; then
    codex_already=true
  else
    codex_already=false
  fi
  "$install_dir/scripts/register-codex.sh"
  if $codex_already; then
    echo "Codex への MCP 登録: 既にあります（再登録して最新化しました）"
  else
    echo "Codex への MCP 登録: 作成しました"
  fi
else
  echo "codex コマンドが無いため Codex への登録は省略しました"
fi

skills_already=true
for skill_name in qwen qwen-read; do
  if [ ! -L "$HOME/.claude/skills/$skill_name" ]; then
    skills_already=false
  fi
done
"$install_dir/scripts/install-skills.sh"
if $skills_already; then
  echo "スキル: 既にあります"
else
  echo "スキル: 作成しました"
fi

if $no_rules; then
  echo "ルール: スキップしました（--no-rules）"
else
  rule_target="$HOME/.claude/CLAUDE.md"
  if [ -f "$rule_target" ] && grep -qF 'local-ai-bridge:begin' "$rule_target"; then
    rules_already=true
  else
    rules_already=false
  fi
  "$install_dir/scripts/add-delegation-rules.sh" --short "$rule_target"
  if $rules_already; then
    echo "ルール: 既にあります（差し替えました）"
  else
    echo "ルール: 作成しました"
  fi
fi

echo
echo "点検: run-local-ai-task doctor"
doctor_exit=0
"$install_dir/run-local-ai-task" doctor || doctor_exit=$?

echo
echo "使うたび: a30-tunnel start でトンネルを張ってから Claude Code / Codex を使う。新しい会話を開くと MCP のツールが見える"

exit "$doctor_exit"
