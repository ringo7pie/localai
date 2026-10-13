#!/usr/bin/env bash
# A30 サーバーで「入口ページ」（tools/portal、既定ポート 8080）を導入する。冪等。再実行は既存物を触らない。
#
# やること（既定）:
#   1. 入口ページのポート（既定 8080、--port で変える）が空いていることを確かめる。
#      他のプロセスが使っていれば、使っているものを表示して終了コード 1 で止める
#   2. そのポートに入口ページ (portal.service) を新規に立てる
# --move-open-webui を付けたときだけ、先に Open WebUI を 8080 から 8081 へ移す
# （現在の設定をバックアップしてから sed で書き換える）。既定では Open WebUI に触らない。
#
# 使い方: setup-server.sh [オプション]
#   --port N           入口ページの待受ポート（既定 8080）。ユニットの ExecStart の --port がこの値になる
#   --move-open-webui  Open WebUI のユニットを 8080 から 8081 へ移してから、入口ページを立てる
#   --revert           入口ページを止める。--move-open-webui も付けると Open WebUI を 8080 に戻す
#   -h, --help         この説明を表示して終了
#
# 注意: systemctl --user を使うため、root では実行できない（root 以外のユーザーで実行すること）。
set -euo pipefail

PORTAL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PORTAL_UNIT_EXAMPLE="$PORTAL_DIR/systemd/portal.service.example"

# 雛形の書き出し（render_unit_file）と、終わりに表示する URL のホスト（detect_server_host）
# shellcheck source=../../scripts/lib/render-unit.sh
source "$PORTAL_DIR/../../scripts/lib/render-unit.sh"
# shellcheck source=../../scripts/lib/server-host.sh
source "$PORTAL_DIR/../../scripts/lib/server-host.sh"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
WEBUI_UNIT="$SYSTEMD_USER_DIR/open-webui.service"
WEBUI_BACKUP="$SYSTEMD_USER_DIR/open-webui.service.bak"
PORTAL_UNIT="$SYSTEMD_USER_DIR/portal.service"

# --------------------------------------------------------------------------
# root 拒否（最優先。systemctl --user は実行ユーザーのユーザーマネージャを指すため、
# root で実行すると利用者のセッションではなく root 自身のセッションを操作してしまう）
# --------------------------------------------------------------------------
if [ "$(id -u)" -eq 0 ]
then
  echo "エラー: root では実行できません。systemctl --user を使うため、root 以外のユーザーで実行してください。" >&2
  exit 2
fi

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --port N           入口ページの待受ポート（既定 8080）
  --move-open-webui  Open WebUI（~/.config/systemd/user/open-webui.service）を 8080 から 8081 へ移してから
                     入口ページを立てる。既定では Open WebUI に触らない
  --revert           入口ページを止める。--move-open-webui も付けると Open WebUI を 8080 に戻す
  -h, --help         この説明を表示して終了
EOF
}

MODE="install"
MOVE_OPEN_WEBUI=false
PORTAL_PORT="8080"
PORT_GIVEN=false
while [ $# -gt 0 ]
do
  case "$1" in
    --revert)
      MODE="revert"
      shift
      ;;
    --move-open-webui)
      MOVE_OPEN_WEBUI=true
      shift
      ;;
    --port)
      if [ $# -lt 2 ]; then
        echo "--port にはポート番号が要ります" >&2
        usage
        exit 2
      fi
      PORTAL_PORT="$2"
      PORT_GIVEN=true
      shift 2
      ;;
    --port=*)
      PORTAL_PORT="${1#--port=}"
      PORT_GIVEN=true
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

# ポートは 1〜65535 の 10 進数だけを受け付ける（ユニットの ExecStart に埋めるため、ほかの文字を通さない）
if [[ ! "$PORTAL_PORT" =~ ^[0-9]{1,5}$ ]] || [ "$((10#$PORTAL_PORT))" -lt 1 ] || [ "$((10#$PORTAL_PORT))" -gt 65535 ]; then
  echo "--port の値が不正です: $PORTAL_PORT（1〜65535 の数）" >&2
  exit 2
fi
PORTAL_PORT="$((10#$PORTAL_PORT))"
if [ "$MODE" = "revert" ] && $PORT_GIVEN; then
  echo "--port は導入のときだけ使えます（--revert とは一緒に使えません）" >&2
  exit 2
fi
if $MOVE_OPEN_WEBUI && [ "$PORTAL_PORT" -eq 8081 ]; then
  echo "--move-open-webui は Open WebUI を 8081 へ移すので、入口ページを --port 8081 には置けません" >&2
  exit 2
fi

# --------------------------------------------------------------------------
# 共通のヘルパー
# --------------------------------------------------------------------------

# 指定ポートが 127.0.0.1 で待受中かどうか（bash 標準機能 /dev/tcp のみで確認。curl 等に依存しない）
port_is_listening() {
  local target_port="$1"
  timeout 1 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/$target_port" 2>/dev/null
}

# port_is_listening が真になるまで最大 timeout_sec 秒待つ
wait_for_port_open() {
  local target_port="$1"
  local timeout_sec="$2"
  local waited_sec=0
  while [ "$waited_sec" -lt "$timeout_sec" ]
  do
    if port_is_listening "$target_port"
    then
      return 0
    fi
    sleep 1
    waited_sec=$((waited_sec + 1))
  done
  return 1
}

# 指定ポートを何かが待ち受けているか。ss があれば全アドレスの待受を見る
# （127.0.0.1 以外のアドレスだけで待ち受けるものも、0.0.0.0 で待ち受ける入口ページとはぶつかるため）。
port_in_use() {
  local target_port="$1"
  local listing
  if command -v ss >/dev/null 2>&1 && listing="$(ss -H -ltn "sport = :$target_port" 2>/dev/null)"; then
    [ -n "$listing" ]
    return
  fi
  port_is_listening "$target_port"
}

# port_in_use が偽になるまで最大 timeout_sec 秒待つ（0 なら 1 回だけ見る）
wait_for_port_free() {
  local target_port="$1"
  local timeout_sec="$2"
  local waited_sec=0
  while port_in_use "$target_port"
  do
    if [ "$waited_sec" -ge "$timeout_sec" ]; then
      return 1
    fi
    sleep 1
    waited_sec=$((waited_sec + 1))
  done
  return 0
}

# 指定ポートを待ち受けているものを標準エラーへ表示する。
# ss -p は別ユーザー（root など）のプロセスの名前を出さないので、そのときは sudo で見る方法を添える。
show_port_user() {
  local target_port="$1"
  local listing=""
  if command -v ss >/dev/null 2>&1; then
    listing="$(ss -H -ltnp "sport = :$target_port" 2>/dev/null || true)"
  fi
  if [ -z "$listing" ]; then
    echo "  使っているものを特定できませんでした（ss が無いか、待受が見えません）。" >&2
    return 0
  fi
  echo "  使っているもの（ss -ltnp）:" >&2
  printf '%s\n' "$listing" | sed 's/^/    /' >&2
  if ! printf '%s\n' "$listing" | grep -q 'users:'; then
    echo "  （プロセス名が出ないのは別ユーザーのプロセスのため。sudo ss -ltnp 'sport = :$target_port' で確かめてください）" >&2
  fi
}

# 置いてある portal.service の ExecStart から --port の値を取り出す（無ければ空）
installed_portal_port() {
  if [ ! -f "$PORTAL_UNIT" ]; then
    return 0
  fi
  sed -n -E 's/^ExecStart=.*--port[ =]([0-9]+).*$/\1/p' "$PORTAL_UNIT" | head -n 1
}

# 雛形から portal.service を作る。@REPO_ROOT@ をリポジトリの絶対パスに、ExecStart の --port を指定のポートにする。
# ポートは数字だけと確かめてあるので、sed の置き換え文字列に入れても崩れない。
render_portal_unit() {
  local target_port="$1"
  render_unit_file "$PORTAL_UNIT_EXAMPLE" "$PORTAL_UNIT"
  sed -i -E "/^ExecStart=/ s/--port[ =][0-9]+/--port $target_port/" "$PORTAL_UNIT"
}

# --------------------------------------------------------------------------
# インストール
# --------------------------------------------------------------------------
run_install() {
  echo "== 入口ページ導入（A30 サーバー） =="

  # ---------------------------------------------------------------- [1/5]
  echo
  echo "[1/5] 前提の確認"
  if [ ! -x /usr/bin/python3 ]; then
    echo "エラー: /usr/bin/python3 がありません。" >&2
    exit 1
  fi
  echo "python3: あります（/usr/bin/python3）"

  # 既にユニットがあれば作り直さないので、そのポートが実際の待受ポートになる
  EFFECTIVE_PORT="$PORTAL_PORT"
  INSTALLED_PORT="$(installed_portal_port)"
  if [ -f "$PORTAL_UNIT" ]; then
    if [ -z "$INSTALLED_PORT" ]; then
      echo "注意: $PORTAL_UNIT の ExecStart に --port が見つかりません。ポート $PORTAL_PORT として点検します。" >&2
    elif [ "$INSTALLED_PORT" != "$PORTAL_PORT" ]; then
      echo "注意: 既存の portal.service はポート $INSTALLED_PORT です（変更しません）。" >&2
      echo "  ポート $PORTAL_PORT に変えるなら、$PORTAL_UNIT を消してから再実行してください。" >&2
      EFFECTIVE_PORT="$INSTALLED_PORT"
    fi
  fi
  echo "入口ページのポート: $EFFECTIVE_PORT"

  WEBUI_ALREADY_MOVED=false
  if $MOVE_OPEN_WEBUI; then
    if [ ! -f "$WEBUI_UNIT" ]; then
      echo "エラー: Open WebUI のユニットがありません: $WEBUI_UNIT" >&2
      echo "  --move-open-webui は Open WebUI を systemd user unit で動かしているときだけ使えます。" >&2
      exit 1
    fi
    echo "Open WebUI のユニット: あります（$WEBUI_UNIT）"
    if grep -q -- "--port 8081" "$WEBUI_UNIT"; then
      WEBUI_ALREADY_MOVED=true
      echo "Open WebUI: 既に 8081 です（移動済みとして扱います）"
    elif grep -q -- "--port 8080" "$WEBUI_UNIT"; then
      echo "Open WebUI: 8080 で動いています（8081 へ移します）"
    else
      echo "エラー: $WEBUI_UNIT の ExecStart に --port 8080 も --port 8081 も見つかりません。" >&2
      echo "  手動で確認してください。想定外の書式の可能性があります。" >&2
      exit 1
    fi
  fi

  # ---------------------------------------------------------------- [2/5]
  echo
  echo "[2/5] Open WebUI を 8081 へ（--move-open-webui のときだけ）"
  if ! $MOVE_OPEN_WEBUI; then
    echo "スキップ（--move-open-webui が無いので Open WebUI には触りません）"
  elif $WEBUI_ALREADY_MOVED; then
    echo "スキップ（既に 8081 です）"
  else
    if [ -f "$WEBUI_BACKUP" ]; then
      echo "バックアップ: 既にあります（$WEBUI_BACKUP。上書きしません）"
    else
      cp -p "$WEBUI_UNIT" "$WEBUI_BACKUP"
      echo "バックアップ: 作成しました（$WEBUI_BACKUP）"
    fi
    sed -i 's/--port 8080/--port 8081/' "$WEBUI_UNIT"
    systemctl --user daemon-reload
    systemctl --user restart open-webui
    echo "8081 が待受になるまで待ちます（最大 60 秒）..."
    if wait_for_port_open 8081 60; then
      echo "Open WebUI: 8081 で待受を確認しました"
    else
      echo "エラー: 8081 が 60 秒待っても待受になりませんでした。設定を元に戻します。" >&2
      cp -p "$WEBUI_BACKUP" "$WEBUI_UNIT"
      systemctl --user daemon-reload
      systemctl --user restart open-webui || true
      echo "  ロールバック: $WEBUI_BACKUP から $WEBUI_UNIT へ復元し、再起動しました。" >&2
      echo "  Open WebUI のログを確認してください: journalctl --user -u open-webui -n 50" >&2
      exit 1
    fi
  fi

  # ---------------------------------------------------------------- [3/5]
  echo
  echo "[3/5] ポート $EFFECTIVE_PORT が空いていることを確認"
  # Open WebUI を移した直後は、古いプロセスが 8080 を手放すまで少し待つ
  FREE_WAIT_SEC=0
  if $MOVE_OPEN_WEBUI; then
    FREE_WAIT_SEC=30
  fi
  if systemctl --user is-active portal >/dev/null 2>&1 && [ "$INSTALLED_PORT" = "$EFFECTIVE_PORT" ]; then
    # 2 回目以降の実行。ポートは自分が立てた入口ページが使っているので空いていなくてよい。
    echo "$EFFECTIVE_PORT: 入口ページが既に使っています（スキップ）"
  elif wait_for_port_free "$EFFECTIVE_PORT" "$FREE_WAIT_SEC"; then
    echo "$EFFECTIVE_PORT: 空いています"
  else
    echo "エラー: ポート $EFFECTIVE_PORT は他のプロセスが使っています。入口ページを立てられません。" >&2
    show_port_user "$EFFECTIVE_PORT"
    if [ -f "$PORTAL_UNIT" ]; then
      echo "  別のポートに置くなら、$PORTAL_UNIT を消してから --port N を付けて再実行してください。" >&2
    else
      echo "  別のポートに置くなら: $(basename -- "$0") --port N（例 --port 8090）" >&2
    fi
    if ! $MOVE_OPEN_WEBUI && [ "$EFFECTIVE_PORT" -eq 8080 ] && [ -f "$WEBUI_UNIT" ] && grep -q -- "--port 8080" "$WEBUI_UNIT"; then
      echo "  使っているのが Open WebUI なら、--move-open-webui で Open WebUI を 8081 へ移せます。" >&2
    fi
    exit 1
  fi

  # ---------------------------------------------------------------- [4/5]
  echo
  echo "[4/5] 入口のユニットを作る"
  if [ -f "$PORTAL_UNIT" ]; then
    echo "portal.service: 既にあります（$PORTAL_UNIT。変更しません）"
  else
    if [ ! -f "$PORTAL_UNIT_EXAMPLE" ]; then
      echo "エラー: ユニットの雛形が見つかりません: $PORTAL_UNIT_EXAMPLE" >&2
      exit 1
    fi
    mkdir -p "$SYSTEMD_USER_DIR"
    render_portal_unit "$EFFECTIVE_PORT"
    echo "portal.service: 作成しました（$PORTAL_UNIT）"
    grep '^ExecStart=' "$PORTAL_UNIT" | sed 's/^/  /'
  fi
  systemctl --user daemon-reload
  systemctl --user enable --now portal

  # ---------------------------------------------------------------- [5/5]
  echo
  echo "[5/5] 点検"
  CHECK_RC=0

  if wait_for_port_open "$EFFECTIVE_PORT" 15; then
    echo "$EFFECTIVE_PORT: 待受しています（入口ページ）"
  else
    echo "$EFFECTIVE_PORT: 待受していません" >&2
    CHECK_RC=1
  fi

  if $MOVE_OPEN_WEBUI; then
    if wait_for_port_open 8081 5; then
      echo "8081: 待受しています（Open WebUI）"
    else
      echo "8081: 待受していません" >&2
      CHECK_RC=1
    fi
  fi

  STATUS_BODY="$(curl -s --max-time 5 "http://127.0.0.1:$EFFECTIVE_PORT/api/status" || true)"
  if [ -n "$STATUS_BODY" ] && /usr/bin/python3 -c 'import json,sys; json.loads(sys.argv[1])' "$STATUS_BODY" 2>/dev/null; then
    echo "/api/status: JSON を返しました"
  else
    echo "/api/status: JSON を返しませんでした（応答: ${STATUS_BODY:0:200}）" >&2
    CHECK_RC=1
  fi

  echo
  if [ "$CHECK_RC" -eq 0 ]; then
    echo "点検: 合格しました"
  else
    echo "点検: 不合格（上記のエラーを確認してください）"
  fi
  SERVER_HOST="$(detect_server_host)"
  echo
  echo "次にやること:"
  echo "  - http://$SERVER_HOST:$EFFECTIVE_PORT を開いて入口ページを確認する"
  if $MOVE_OPEN_WEBUI; then
    echo "  - ブラウザのブックマークを http://$SERVER_HOST:8080 から http://$SERVER_HOST:8081 （Open WebUI）へ更新する"
    echo "  - 元に戻す場合: $(basename -- "$0") --revert --move-open-webui"
  else
    # portal.py の SERVICES は Open WebUI を 8081 として見る（状態の表示とリンク）
    echo "  - 入口ページの Open WebUI のカードはポート 8081 を見ます。Open WebUI を別のポートで動かしているときは停止中に見えます"
    echo "  - 元に戻す場合: $(basename -- "$0") --revert"
  fi
  exit "$CHECK_RC"
}

# --------------------------------------------------------------------------
# 元に戻す
# --------------------------------------------------------------------------
run_revert() {
  if $MOVE_OPEN_WEBUI; then
    echo "== 入口ページを戻す（入口ページを止め、Open WebUI を 8080 へ） =="
  else
    echo "== 入口ページを戻す（入口ページを止める。Open WebUI には触らない） =="
  fi
  REVERT_RC=0

  # ---------------------------------------------------------------- [1/3]
  echo
  echo "[1/3] 入口ページを止める"
  if systemctl --user is-enabled portal >/dev/null 2>&1 || systemctl --user is-active portal >/dev/null 2>&1; then
    systemctl --user disable --now portal
    echo "portal: 停止しました（ユニットファイルは残しています: $PORTAL_UNIT）"
  else
    echo "portal: 元々動いていません"
  fi

  # ---------------------------------------------------------------- [2/3]
  echo
  echo "[2/3] Open WebUI を 8080 へ（--move-open-webui のときだけ）"
  if ! $MOVE_OPEN_WEBUI; then
    echo "スキップ（--move-open-webui が無いので Open WebUI には触りません）"
    if [ -f "$WEBUI_UNIT" ] && grep -q -- "--port 8081" "$WEBUI_UNIT"; then
      echo "  Open WebUI は 8081 のままです。8080 に戻すなら: $(basename -- "$0") --revert --move-open-webui"
    fi
  else
    if [ ! -f "$WEBUI_UNIT" ]; then
      echo "エラー: Open WebUI のユニットがありません: $WEBUI_UNIT" >&2
      exit 1
    fi

    if grep -q -- "--port 8080" "$WEBUI_UNIT"; then
      echo "Open WebUI: 既に 8080 です（変更しません）"
    else
      if [ -f "$WEBUI_BACKUP" ]; then
        cp -p "$WEBUI_BACKUP" "$WEBUI_UNIT"
        echo "Open WebUI のユニット: バックアップから復元しました（$WEBUI_BACKUP）"
      elif grep -q -- "--port 8081" "$WEBUI_UNIT"; then
        sed -i 's/--port 8081/--port 8080/' "$WEBUI_UNIT"
        echo "Open WebUI のユニット: バックアップが無いため sed で 8080 に書き換えました"
      else
        echo "エラー: $WEBUI_UNIT に --port 8080 も --port 8081 も見つからず、バックアップもありません。" >&2
        echo "  手動で確認してください。" >&2
        exit 1
      fi
      systemctl --user daemon-reload
      systemctl --user restart open-webui
      echo "8080 が待受になるまで待ちます（最大 60 秒）..."
      if wait_for_port_open 8080 60; then
        echo "Open WebUI: 8080 で待受を確認しました"
      else
        echo "エラー: 8080 が 60 秒待っても待受になりませんでした。" >&2
        echo "  ログを確認してください: journalctl --user -u open-webui -n 50" >&2
        REVERT_RC=1
      fi
    fi
  fi

  # ---------------------------------------------------------------- [3/3]
  echo
  echo "[3/3] 点検"
  if systemctl --user is-active portal >/dev/null 2>&1; then
    echo "portal: まだ動いています" >&2
    REVERT_RC=1
  else
    echo "portal: 止まっています"
  fi
  if $MOVE_OPEN_WEBUI; then
    if wait_for_port_open 8080 5; then
      echo "8080: 待受しています（Open WebUI）"
    else
      echo "8080: 待受していません" >&2
      REVERT_RC=1
    fi
  fi

  echo
  if [ "$REVERT_RC" -eq 0 ]; then
    echo "点検: 合格しました"
  else
    echo "点検: 不合格（上記のエラーを確認してください）"
  fi
  echo
  echo "次にやること:"
  if $MOVE_OPEN_WEBUI; then
    SERVER_HOST="$(detect_server_host)"
    echo "  - ブラウザのブックマークを http://$SERVER_HOST:8081 から http://$SERVER_HOST:8080 （Open WebUI）へ戻す"
  fi
  echo "  - portal.service を完全に消したい場合は手動で削除する: $PORTAL_UNIT"
  exit "$REVERT_RC"
}

if [ "$MODE" = "revert" ]; then
  run_revert
else
  run_install
fi
