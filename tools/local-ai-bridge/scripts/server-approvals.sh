#!/usr/bin/env bash
# A30 サーバーで承認が要る作業（sudo を伴うもの）を
# 人が 1 項目ずつ確認して実行するためのスクリプト。
# 既定（引数無し / --show）は状態表示だけで何も変更しない。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BRIDGE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
RUNNER="$BRIDGE_DIR/run-local-ai-task"
OPENWEBUI_ENV="$HOME/.config/open-webui/open-webui.env"
OLLAMA_OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OLLAMA_OVERRIDE_FILE="$OLLAMA_OVERRIDE_DIR/override.conf"

UNKNOWN="未取得（sudo が要る）"

# ufw-8080 で許可する LAN。環境変数 LOCALAI_LAN_CIDR で指定する（例: 192.168.1.0/24）。
# 未指定のままでは ufw-8080 を適用しない。
LAN_CIDR="${LOCALAI_LAN_CIDR:-<lan-cidr>}"
# linger の対象は、このスクリプトを実行しているユーザー
USER_NAME="$(id -un)"

usage() {
  cat <<'EOF'
使い方: server-approvals.sh [--show] | --apply <項目> | -h

  --show          4 項目の内容と現状を表示して終了（何も変更しない。既定）
  --apply <項目>  項目を詳しく表示し、「実行しますか？ [yes/NO]」で確認して
                  yes のときだけ実行する。yes 以外なら何もしない（終了コード 0）
  -h, --help      この説明を表示して終了

利用可能な項目:
  ufw-8080       LAN <lan-cidr> からだけ 8080 を開ける
                 （<lan-cidr> は環境変数 LOCALAI_LAN_CIDR で指定する。例: 192.168.1.0/24）
  linger         実行したユーザーがログアウト後もユーザーサービスを残す
  ollama-dropin  ollama.service に 4 つの Environment を足して再始動
  close-signup   Open WebUI の新規登録を閉じる（sudo 不要）

sudo のパスワードは sudo 自身が聞く。このスクリプトはパスワードを扱わない。
EOF
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

prompt_yes() {
  local answer=""
  printf '実行しますか？ [yes/NO] '
  IFS= read -r answer || true
  [ "$answer" = "yes" ]
}

# ---------------------------------------------------------------- 現状取得

ufw_current() {
  local state_output=""
  local matching=""
  if ! have_command ufw; then
    echo "（ufw コマンドが無い）"
    return 0
  fi
  state_output="$(ufw status 2>/dev/null)" || state_output=""
  if [ -z "$state_output" ]; then
    echo "$UNKNOWN"
    return 0
  fi
  matching="$(printf '%s\n' "$state_output" | grep '8080' 2>/dev/null)" || matching=""
  if [ -n "$matching" ]; then
    printf '%s\n' "$matching"
  else
    echo "（8080 に関する行: なし）"
  fi
}

linger_current() {
  local state_output=""
  local matching=""
  if ! have_command loginctl; then
    echo "（loginctl コマンドが無い）"
    return 0
  fi
  state_output="$(loginctl show-user "$USER_NAME" 2>/dev/null)" || state_output=""
  if [ -z "$state_output" ]; then
    echo "$UNKNOWN"
    return 0
  fi
  matching="$(printf '%s\n' "$state_output" | grep -E '^(Linger|Unit)=' 2>/dev/null)" || matching=""
  if [ -n "$matching" ]; then
    printf '%s\n' "$matching"
  else
    echo "（Linger の行: なし）"
  fi
}

ollama_override_current() {
  local matching=""
  if [ -f "$OLLAMA_OVERRIDE_FILE" ] && [ -r "$OLLAMA_OVERRIDE_FILE" ]; then
    matching="$(grep -nE '^[[:space:]]*Environment=' "$OLLAMA_OVERRIDE_FILE" 2>/dev/null)" || matching=""
    if [ -n "$matching" ]; then
      printf '%s\n' "$matching"
    else
      echo "（既存の Environment 行: なし）"
    fi
  else
    echo "$UNKNOWN"
  fi
}

openwebui_signup_current() {
  local matching=""
  if [ -f "$OPENWEBUI_ENV" ]; then
    matching="$(grep -nE '^[[:space:]]*ENABLE_SIGNUP=' "$OPENWEBUI_ENV" 2>/dev/null)" || matching=""
    if [ -n "$matching" ]; then
      printf '%s\n' "$matching"
    else
      echo "（ENABLE_SIGNUP 行: なし）"
    fi
  else
    echo "（ファイルが見つからない: $OPENWEBUI_ENV）"
  fi
}

# ---------------------------------------------------------------- 項目の説明

describe_ufw_8080() {
  echo "項目: ufw-8080"
  echo "何を変えるか: LAN ($LAN_CIDR) からだけ 8080 を開ける（ufw のルール追加）"
  echo "コマンド:   sudo ufw allow from $LAN_CIDR to any port 8080 proto tcp comment 'Open WebUI'"
  echo "影響:     Open WebUI が LAN の他の PC から見える"
  echo "戻し方:   sudo ufw delete allow from $LAN_CIDR to any port 8080 proto tcp"
  echo "今の状態: $(ufw_current)"
}

describe_linger() {
  echo "項目: linger"
  echo "何を変えるか: ユーザー $USER_NAME がログアウト後も systemd --user の動作を継続する"
  echo "コマンド:   sudo loginctl enable-linger $USER_NAME"
  echo "影響:     ログアウト後も systemd --user の open-webui が動き続ける"
  echo "戻し方:   sudo loginctl disable-linger $USER_NAME"
  echo "今の状態: $(linger_current)"
}

describe_ollama_dropin() {
  cat <<'BLOCK'
項目: ollama-dropin
何変わるか: /etc/systemd/system/ollama.service.d/override.conf の [Service] 節に
  無い行だけ、以下の 4 行を足す（既存行は消さない、既にある行は足さない）:
    Environment="OLLAMA_NUM_PARALLEL=1"
    Environment="OLLAMA_MAX_LOADED_MODELS=1"
    Environment="OLLAMA_MAX_QUEUE=64"
    Environment="OLLAMA_NO_CLOUD=1"
  適用前に run-local-ai-task list --state running と ollama ps を見て、
  実行中のタスクや読み込み中のモデルがあれば中止（終了コード 3）
コマンド:
  preflight: <bridge>/run-local-ai-task list --state running
  preflight: ollama ps
  適用:   sudo cp override.conf override.conf.bak.<日時>
          sudo tee -a で上の行を足す
          sudo systemctl daemon-reload && sudo systemctl restart ollama
  確認:   journalctl -u ollama --no-pager -n 50 | grep 'server config'
影響:   再起動中は推論が中断する
戻し方: .bak を戻して sudo systemctl daemon-reload && sudo systemctl restart ollama
BLOCK
  echo "今の状態: $(ollama_override_current)"
}

describe_close_signup() {
  cat <<BLOCK
項目: close-signup
何変わるか: $OPENWEBUI_ENV に
  ENABLE_SIGNUP=false
を書く（ENABLE_SIGNUP=true などの既存行は false に置き換える。既に false なら触らない）。その後 systemctl --user restart open-webui
コマンド:
  （sudo 不要）
  適用:   cp open-webui.env open-webui.env.bak.<日時>
          echo 'ENABLE_SIGNUP=false' >> $OPENWEBUI_ENV
          systemctl --user restart open-webui
影響:   新規のアカウント登録ができなくなる
戻し方: ENABLE_SIGNUP 行を消して systemctl --user restart open-webui
BLOCK
  echo "今の状態: $(openwebui_signup_current)"
}

# ---------------------------------------------------------------- 適用処理

# LOCALAI_LAN_CIDR が数字・ドット・スラッシュだけの値でなければ止める
require_lan_cidr() {
  case "$LAN_CIDR" in
    ""|*[!0-9./]*)
      echo "中止: 環境変数 LOCALAI_LAN_CIDR に LAN のネットワークアドレスを指定してください（例: 192.168.1.0/24）" >&2
      exit 2
      ;;
  esac
}

apply_ufw_8080() {
  sudo ufw allow from "$LAN_CIDR" to any port 8080 proto tcp comment 'Open WebUI'
  echo "適用しました。確認: ufw status"
}

apply_linger() {
  sudo loginctl enable-linger "$USER_NAME"
  echo "適用しました。確認: loginctl show-user $USER_NAME"
}

apply_ollama_dropin() {
  local list_output
  local ps_output
  local ps_body
  local timestamp
  local backup_path
  local env_value
  local new_block
  local log_tail

  # ---- 適用前の確認: 実行中のタスク ----
  if ! list_output="$("$RUNNER" list --state running 2>&1)"; then
    echo "中止: <bridge>/run-local-ai-task list --state running を確認できませんでした（終了コード 3）" >&2
    printf '%s\n' "$list_output" >&2
    exit 3
  fi
  echo "run-local-ai-task list --state running の出力:"
  printf '%s\n' "$list_output"
  echo
  if printf '%s\n' "$list_output" | grep -q '"task_id"'; then
    echo "中止: 実行中のタスクがあります（終了コード 3）" >&2
    exit 3
  fi

  # ---- 適用前の確認: 読み込み中のモデル ----
  if ! have_command ollama; then
    echo "中止: ollama コマンドが見つからず ollama ps を確認できません（終了コード 3）" >&2
    exit 3
  fi
  if ! ps_output="$(ollama ps 2>&1)"; then
    echo "中止: ollama ps を確認できませんでした（終了コード 3）" >&2
    printf '%s\n' "$ps_output" >&2
    exit 3
  fi
  echo "ollama ps の出力:"
  printf '%s\n' "$ps_output"
  echo
  ps_body="$(printf '%s\n' "$ps_output" | tail -n +2)"
  if [ -n "${ps_body//[[:space:]]/}" ]; then
    echo "中止: ollama ps に読み込み中のモデルがあります（終了コード 3）" >&2
    exit 3
  fi

  # ---- バックアップ ----
  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_path="$OLLAMA_OVERRIDE_FILE.bak.$timestamp"
  sudo mkdir -p "$OLLAMA_OVERRIDE_DIR"
  if [ -f "$OLLAMA_OVERRIDE_FILE" ]; then
    sudo cp -p "$OLLAMA_OVERRIDE_FILE" "$backup_path"
  else
    : | sudo tee "$OLLAMA_OVERRIDE_FILE" > /dev/null
  fi
  echo "退避: $backup_path"

  # ---- 無い行だけ足す ----
  local candidates=("OLLAMA_NUM_PARALLEL=1" "OLLAMA_MAX_LOADED_MODELS=1" "OLLAMA_MAX_QUEUE=64" "OLLAMA_NO_CLOUD=1")
  new_block=""
  for env_value in "${candidates[@]}"; do
    if ! grep -qE "^[[:space:]]*Environment=\\\"?${env_value}\\\"?[[:space:]]*$" "$OLLAMA_OVERRIDE_FILE" 2>/dev/null; then
      new_block+="Environment=\"${env_value}\""$'\n'
    fi
  done

  if [ -n "$new_block" ]; then
    if grep -qE '^[[:space:]]*\[Service\][[:space:]]*$' "$OLLAMA_OVERRIDE_FILE" 2>/dev/null; then
      printf '%s' "$new_block" | sudo tee -a "$OLLAMA_OVERRIDE_FILE" > /dev/null
    else
      printf '\n[Service]\n%s' "$new_block" | sudo tee -a "$OLLAMA_OVERRIDE_FILE" > /dev/null
    fi
    echo "Environment 行を追加しました"
  else
    echo "4 行とも既に存在していたため追加しませんでした"
  fi

  sudo systemctl daemon-reload
  sudo systemctl restart ollama
  echo "ollama を再始動しました"

  # ---- 確認 ----
  echo
  echo "確認（'server config' の行が出ていれば設定が反映されています）:"
  if have_command journalctl; then
    log_tail="$(sudo journalctl -u ollama --no-pager -n 50)"
    printf '%s\n' "$log_tail" | grep 'server config' || echo "  （'server config' 行が見つかりません）"
  else
    echo "（journalctl コマンドが無い）"
  fi
}

apply_close_signup() {
  local dir
  local existing_line=""
  local timestamp
  dir="$(dirname -- "$OPENWEBUI_ENV")"
  mkdir -p "$dir"

  if [ -f "$OPENWEBUI_ENV" ]; then
    existing_line="$(grep -m 1 -E '^[[:space:]]*ENABLE_SIGNUP=' "$OPENWEBUI_ENV" 2>/dev/null)" || existing_line=""
    if printf '%s' "$existing_line" | grep -qE '^[[:space:]]*ENABLE_SIGNUP=false[[:space:]]*$'; then
      echo "既に ENABLE_SIGNUP=false です。触りません（既にあります）"
      return 0
    fi
    timestamp="$(date +%Y%m%d-%H%M%S)"
    cp -p "$OPENWEBUI_ENV" "$OPENWEBUI_ENV.bak.$timestamp"
    echo "退避: $OPENWEBUI_ENV.bak.$timestamp"
    if [ -n "$existing_line" ]; then
      # 既存の行（例: ENABLE_SIGNUP=true）を false に置き換える。他の行は触らない
      sed -i -E 's/^[[:space:]]*ENABLE_SIGNUP=.*$/ENABLE_SIGNUP=false/' "$OPENWEBUI_ENV"
      echo "ENABLE_SIGNUP を false に置き換えました（元: $existing_line）"
    else
      echo "ENABLE_SIGNUP=false" >> "$OPENWEBUI_ENV"
      echo "ENABLE_SIGNUP=false を追加しました"
    fi
  else
    : > "$OPENWEBUI_ENV"
    echo "ENABLE_SIGNUP=false" >> "$OPENWEBUI_ENV"
    echo "ファイルを作成して ENABLE_SIGNUP=false を書きました"
  fi

  systemctl --user restart open-webui
  echo "open-webui を再始動しました"
}

# ---------------------------------------------------------------- 主処理

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  --show)
    shift
    ;;
esac

if [ $# -gt 0 ]; then
  case "$1" in
    --apply)
      if [ $# -lt 2 ]; then
        echo "--apply には項目名が必要です（ufw-8080 | linger | ollama-dropin | close-signup）" >&2
        exit 2
      fi
      apply_item="$2"
      case "$apply_item" in
        ufw-8080)
          require_lan_cidr
          describe_ufw_8080
          echo
          if prompt_yes; then
            apply_ufw_8080
          fi
          ;;
        linger)
          describe_linger
          echo
          if prompt_yes; then
            apply_linger
          fi
          ;;
        ollama-dropin)
          describe_ollama_dropin
          echo
          if prompt_yes; then
            apply_ollama_dropin
          fi
          ;;
        close-signup)
          describe_close_signup
          echo
          if prompt_yes; then
            apply_close_signup
          fi
          ;;
        *)
          echo "不明な項目: $apply_item" >&2
          echo "利用可能な項目: ufw-8080 / linger / ollama-dropin / close-signup" >&2
          exit 2
          ;;
      esac
      exit 0
      ;;
    --*)
      echo "未知の引数: $1" >&2
      usage
      exit 2
      ;;
    *)
      echo "無効な項目: $1（引数無しで表示します）" >&2
      ;;
  esac
fi

# 既定: --show
describe_ufw_8080
echo
describe_linger
echo
describe_ollama_dropin
echo
describe_close_signup
