# shellcheck shell=bash
# 導入の終わりに表示する URL（http://<ホスト>:<ポート>）のホスト部分を決める。
# 各ツールの setup-server.sh が source して使う。
#
# 使い方:
#   source "<リポジトリ>/scripts/lib/server-host.sh"
#   SERVER_HOST="$(detect_server_host)"
#
# 優先順位:
#   1. 環境変数 LOCALAI_SERVER_HOST（ホスト名でも IP でもよい。そのまま使う）
#   2. hostname -I の中で最初の私的 IPv4（10/8・172.16/12・192.168/16）
#   3. localhost
# hostname -I の並びはインターフェースの順。Docker のブリッジ（172.17.0.1 など）も私的 IPv4 なので、
# LAN の IP より先に出る機体では LOCALAI_SERVER_HOST で指定する。

# 引数が私的 IPv4（RFC 1918）なら真。IPv6 や書式の崩れたものは偽。
is_private_ipv4_address() {
  local address="$1"
  if [[ ! "$address" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]]; then
    return 1
  fi
  local first_octet="${BASH_REMATCH[1]}"
  local second_octet="${BASH_REMATCH[2]}"
  local octet
  for octet in "${BASH_REMATCH[@]:1}"
  do
    # 先頭の 0 で 8 進数と解釈されないよう 10# を付ける
    if [ "$((10#$octet))" -gt 255 ]; then
      return 1
    fi
  done
  first_octet="$((10#$first_octet))"
  second_octet="$((10#$second_octet))"
  if [ "$first_octet" -eq 10 ]; then
    return 0
  fi
  if [ "$first_octet" -eq 172 ] && [ "$second_octet" -ge 16 ] && [ "$second_octet" -le 31 ]; then
    return 0
  fi
  if [ "$first_octet" -eq 192 ] && [ "$second_octet" -eq 168 ]; then
    return 0
  fi
  return 1
}

# 表示に使うホストを標準出力へ 1 行で書く。失敗しない（最後は localhost）。
detect_server_host() {
  if [ -n "${LOCALAI_SERVER_HOST:-}" ]; then
    echo "$LOCALAI_SERVER_HOST"
    return 0
  fi
  local host_addresses=""
  if command -v hostname >/dev/null 2>&1; then
    host_addresses="$(hostname -I 2>/dev/null || true)"
  fi
  # 空白区切りの一覧を配列にする（グロブ展開させないよう read で分ける）
  local address_list=()
  read -r -a address_list <<< "$host_addresses" || true
  local address
  for address in "${address_list[@]}"
  do
    if is_private_ipv4_address "$address"; then
      echo "$address"
      return 0
    fi
  done
  echo "localhost"
}
