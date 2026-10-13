#!/usr/bin/env bash
# 他の PC の公開鍵を、qwen-worker しか起動できない鍵として受け入れる。
# 使い方:
#   add-remote-key.sh <PC名> <公開鍵ファイル>
#   cat id.pub | add-remote-key.sh <PC名> -
set -euo pipefail

pc_name="${1:?PC名を指定してください}"
key_source="${2:?公開鍵ファイル（または -）を指定してください}"

worker="$HOME/.local/share/qwen-worker/run-qwen-worker"
auth_dir="$HOME/.ssh"
auth_file="$auth_dir/authorized_keys"

if [ "$key_source" = "-" ]; then
  public_key="$(cat)"
else
  public_key="$(cat "$key_source")"
fi
public_key="$(printf '%s\n' "$public_key" | grep -E '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+|sk-ssh-ed25519@openssh.com) ' | head -1)"
if [ -z "$public_key" ]; then
  echo "公開鍵の形式が読めません（ssh-ed25519 / ssh-rsa / ecdsa で始まる 1 行が必要）" >&2
  exit 1
fi

# 鍵本体（種別 + base64）だけで重複を判定する。コメント部分は無視する。
key_body="$(printf '%s' "$public_key" | awk '{print $1" "$2}')"

mkdir -p "$auth_dir"; chmod 700 "$auth_dir"
touch "$auth_file"; chmod 600 "$auth_file"

if grep -qF "$key_body" "$auth_file"; then
  echo "この鍵は既に authorized_keys にあります。追記しません。"
else
  options="command=\"$worker\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding"
  printf '%s %s qwen-worker@%s\n' "$options" "$key_body" "$pc_name" >> "$auth_file"
  echo "追記しました: $auth_file"
fi

echo
echo "指紋（他の PC 側で ssh-keygen -lf ~/.ssh/qwen-worker.pub と突合すること）:"
printf '%s\n' "$key_body" | ssh-keygen -lf -
