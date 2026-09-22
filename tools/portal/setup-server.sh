#!/usr/bin/env bash
# A30 サーバーで「入口ページ」(8080) を導入する。冪等。再実行は既存物を触らない。
#
# やること:
#   1. Open WebUI を 8080 から 8081 へ移す（現在の設定をバックアップしてから sed で書き換える）
#   2. 8080 番に入口ページ (portal.service) を新規に立てる
#
# 使い方: setup-server.sh [オプション]
#   --revert    Open WebUI を 8080 に戻し、入口ページを止める
#   -h, --help  この説明を表示して終了
#
# 注意: systemctl --user を使うため、root では実行できない（mt ユーザーで実行すること）。
set -euo pipefail

PORTAL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PORTAL_PY="$PORTAL_DIR/portal.py"
PORTAL_UNIT_EXAMPLE="$PORTAL_DIR/systemd/portal.service.example"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
WEBUI_UNIT="$SYSTEMD_USER_DIR/open-webui.service"
WEBUI_BACKUP="$SYSTEMD_USER_DIR/open-webui.service.bak"
PORTAL_UNIT="$SYSTEMD_USER_DIR/portal.service"

# --------------------------------------------------------------------------
# root 拒否（最優先。systemctl --user は実行ユーザーのユーザーマネージャを指すため、
# root で実行すると mt のセッションではなく root 自身のセッションを操作してしまう）
# --------------------------------------------------------------------------
if [ "$(id -u)" -eq 0 ]
then
  echo "エラー: root では実行できません。mt ユーザーで実行してください（例: su - mt、または sudo -u mt -i）。" >&2
  exit 2
fi

usage() {
  cat <<EOF
使い方: $(basename -- "$0") [オプション]

  --revert    Open WebUI を 8080 に戻し、入口ページを止める
  -h, --help  この説明を表示して終了
EOF
}

MODE="install"
while [ $# -gt 0 ]
do
  case "$1" in
    --revert)
      MODE="revert"
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

# port_is_listening が偽になるまで最大 timeout_sec 秒待つ
wait_for_port_closed() {
  local target_port="$1"
  local timeout_sec="$2"
  local waited_sec=0
  while [ "$waited_sec" -lt "$timeout_sec" ]
  do
    if ! port_is_listening "$target_port"
    then
      return 0
    fi
    sleep 1
    waited_sec=$((waited_sec + 1))
  done
  return 1
}

# portal.service の ExecStart 行を、実際の配置に合わせて作る。
# $HOME 配下ならユニットの可搬性のため %h を使い、そうでなければ絶対パスをそのまま使う。
build_portal_exec_start() {
  case "$PORTAL_DIR" in
    "$HOME"/*)
      local relative_dir="${PORTAL_DIR#"$HOME"/}"
      echo "ExecStart=/usr/bin/python3 %h/$relative_dir/portal.py --host 0.0.0.0 --port 8080"
      ;;
    *)
      echo "ExecStart=/usr/bin/python3 $PORTAL_PY --host 0.0.0.0 --port 8080"
      ;;
  esac
}

# --------------------------------------------------------------------------
# インストール
# --------------------------------------------------------------------------
run_install() {
  echo "== 入口ページ導入（A30 サーバー） =="

  # ---------------------------------------------------------------- [1/6]
  echo
  echo "[1/6] 前提の確認"
  if [ ! -x /usr/bin/python3 ]; then
    echo "エラー: /usr/bin/python3 がありません。" >&2
    exit 1
  fi
  echo "python3: あります（/usr/bin/python3）"

  if [ ! -f "$WEBUI_UNIT" ]; then
    echo "エラー: Open WebUI のユニットがありません: $WEBUI_UNIT" >&2
    exit 1
  fi
  echo "Open WebUI のユニット: あります（$WEBUI_UNIT）"

  WEBUI_ALREADY_MOVED=false
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

  # ---------------------------------------------------------------- [2/6]
  echo
  echo "[2/6] バックアップ"
  if [ -f "$WEBUI_BACKUP" ]; then
    echo "バックアップ: 既にあります（$WEBUI_BACKUP。上書きしません）"
  else
    cp -p "$WEBUI_UNIT" "$WEBUI_BACKUP"
    echo "バックアップ: 作成しました（$WEBUI_BACKUP）"
  fi

  # ---------------------------------------------------------------- [3/6]
  echo
  echo "[3/6] Open WebUI を 8081 へ"
  if $WEBUI_ALREADY_MOVED; then
    echo "スキップ（既に 8081 です）"
  else
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

  # ---------------------------------------------------------------- [4/6]
  echo
  echo "[4/6] 8080 が空いたことを確認"
  if systemctl --user is-active portal >/dev/null 2>&1; then
    # 2 回目以降の実行。8080 は自分が立てた入口ページが使っているので空いていなくてよい。
    echo "8080: 入口ページが既に使っています（スキップ）"
  elif wait_for_port_closed 8080 30; then
    echo "8080: 空いています"
  else
    echo "エラー: 8080 がまだ何かに使われています。入口ページを立てられません。" >&2
    echo "  何が使っているか確認してください: ss -ltnp | grep :8080" >&2
    exit 1
  fi

  # ---------------------------------------------------------------- [5/6]
  echo
  echo "[5/6] 入口のユニットを作る"
  if [ -f "$PORTAL_UNIT" ]; then
    echo "portal.service: 既にあります（$PORTAL_UNIT。変更しません）"
  else
    if [ ! -f "$PORTAL_UNIT_EXAMPLE" ]; then
      echo "エラー: ユニットの雛形が見つかりません: $PORTAL_UNIT_EXAMPLE" >&2
      exit 1
    fi
    mkdir -p "$SYSTEMD_USER_DIR"
    EXEC_START_LINE="$(build_portal_exec_start)"
    awk -v exec_start_line="$EXEC_START_LINE" '
      /^ExecStart=/ { print exec_start_line; next }
      { print }
    ' "$PORTAL_UNIT_EXAMPLE" > "$PORTAL_UNIT"
    echo "portal.service: 作成しました（$PORTAL_UNIT）"
    echo "  $EXEC_START_LINE"
  fi
  systemctl --user daemon-reload
  systemctl --user enable --now portal

  # ---------------------------------------------------------------- [6/6]
  echo
  echo "[6/6] 点検"
  CHECK_RC=0

  if wait_for_port_open 8080 15; then
    echo "8080: 待受しています（入口ページ）"
  else
    echo "8080: 待受していません" >&2
    CHECK_RC=1
  fi

  if wait_for_port_open 8081 5; then
    echo "8081: 待受しています（Open WebUI）"
  else
    echo "8081: 待受していません" >&2
    CHECK_RC=1
  fi

  STATUS_BODY="$(curl -s --max-time 5 http://127.0.0.1:8080/api/status || true)"
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
  echo
  echo "次にやること:"
  echo "  - ブラウザのブックマークを http://<server-ip>:8080 から http://<server-ip>:8081 （Open WebUI）へ更新する"
  echo "  - http://<server-ip>:8080 を開いて入口ページを確認する"
  echo "  - 元に戻す場合: $(basename -- "$0") --revert"
  exit "$CHECK_RC"
}

# --------------------------------------------------------------------------
# 元に戻す
# --------------------------------------------------------------------------
run_revert() {
  echo "== 入口ページを戻す（Open WebUI を 8080 へ） =="
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
  echo "[2/3] Open WebUI を 8080 へ"
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

  # ---------------------------------------------------------------- [3/3]
  echo
  echo "[3/3] 点検"
  if wait_for_port_open 8080 5; then
    echo "8080: 待受しています（Open WebUI）"
  else
    echo "8080: 待受していません" >&2
    REVERT_RC=1
  fi

  echo
  if [ "$REVERT_RC" -eq 0 ]; then
    echo "点検: 合格しました"
  else
    echo "点検: 不合格（上記のエラーを確認してください）"
  fi
  echo
  echo "次にやること:"
  echo "  - ブラウザのブックマークを http://<server-ip>:8081 から http://<server-ip>:8080 （Open WebUI）へ戻す"
  echo "  - portal.service を完全に消したい場合は手動で削除する: $PORTAL_UNIT"
  exit "$REVERT_RC"
}

if [ "$MODE" = "revert" ]; then
  run_revert
else
  run_install
fi
