#!/usr/bin/env bash
# 受け入れ済みの qwen-worker 用鍵を取り消す。
# 使い方:
#   remove-remote-key.sh --list            受け入れ済みの qwen-worker 鍵を一覧する
#   remove-remote-key.sh <PC名>            qwen-worker@<PC名> の行を消す
#   remove-remote-key.sh --pubkey <file>   その公開鍵の行を消す
set -euo pipefail

auth_file="$HOME/.ssh/authorized_keys"
[ -f "$auth_file" ] || { echo "authorized_keys がありません"; exit 0; }

redact() { sed -E 's/(AAAA[A-Za-z0-9+/=]{12})[A-Za-z0-9+/=]*/\1…/g'; }

case "${1:-}" in
  --list|"")
    echo "受け入れ済みの qwen-worker 鍵:"
    grep -n 'qwen-worker@' "$auth_file" | redact || echo "（無し）"
    echo
    echo "全体の行数: $(wc -l < "$auth_file")"
    exit 0
    ;;
  --pubkey)
    pubfile="${2:?公開鍵ファイルを指定してください}"
    match="$(awk '{print $2}' "$pubfile")"
    label="公開鍵 $pubfile"
    ;;
  *)
    match="qwen-worker@$1"
    label="PC名 $1"
    ;;
esac

before=$(wc -l < "$auth_file")
tmp="$(mktemp)"
grep -vF "$match" "$auth_file" > "$tmp" || true
after=$(wc -l < "$tmp")

if [ "$before" -eq "$after" ]; then
  rm -f "$tmp"
  echo "$label に一致する行はありませんでした。変更なし。"
  exit 0
fi

cp -a "$auth_file" "$auth_file.bak-$(date +%Y%m%d-%H%M%S)"
cat "$tmp" > "$auth_file"
rm -f "$tmp"
chmod 600 "$auth_file"
echo "$label の行を $((before - after)) 件削除しました（$before → $after 行）。"
echo "退避: $auth_file.bak-*"
