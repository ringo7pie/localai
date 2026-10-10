#!/usr/bin/env bash
# ローカルの 8 モデルにコーディング 6 問と追加 3 試験（各 3 問）を順に解かせる（計画の P2）。
#
# 使い方: run_local.sh [--retry-errors] [--retry-skipped]
#   環境変数 RUN_DATE（既定 2026-10-08）: 結果の置き場 results/<RUN_DATE>/
#   環境変数 ONLY（例 "gemma4:e4b,strata-official:IQ3_XXS"）: このモデルだけ流す
#
# 順番: Ollama の e4b → 27b → ctx32k → it-qat → IQ4_XS（各モデルの後に keep_alive:0 で降ろす）→
#       VRAM を開放（vram-policy.sh release 22000）→ Strata の strata（RVN、8082）→ strata-official（8084。
#       Conflicts= により RVN は止まる）→ strata-coder（8083）→ 止める → VRAM が空いたことを確かめる。
# Strata の起動に失敗したら journal を results/<日付>/local/<slug>/ に残して飛ばし、最後にもう一度だけ試す。
# 途中で止めても、もう一度実行すれば記録の無い問から続ける（run_eval.py の再開の規則）。
# 終わったら（途中で止まっても）results/<日付>/DONE を置く。待つ側は終了の通知か until [ -f DONE ] で待つ
# （pgrep -f で待つと待つ側の bash 自身に一致して終わらない）。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON=/usr/bin/python3
RUN_EVAL=("$PYTHON" -B "$TOOL_DIR/run_eval.py")
VRAM_POLICY="$HOME/.claude/scripts/vram-policy.sh"
RUN_DATE="${RUN_DATE:-2026-10-08}"
RESULTS_DIR="$TOOL_DIR/results/$RUN_DATE"
DONE_FILE="$RESULTS_DIR/DONE"
LOG_DIR="$TOOL_DIR/work"
LOG_FILE="$LOG_DIR/run_local-$RUN_DATE.log"

OLLAMA_ORDER=(gemma4:e4b qwen3.8:27b gemma4:31b-ctx32k gemma4:31b-it-qat qwen3.8-flash-next:IQ4_XS)
# Strata は「target の key」と「systemd の unit」の組
STRATA_ORDER=("strata-flash-next:IQ3_S strata" "strata-official:IQ3_XXS strata-official" "strata-flash-coder:IQ1_M strata-coder")
# GPU を取り合うほかのサービス（入口ページの GPU_EXCLUSIVE_KEYS と同じ顔ぶれ）
GPU_SERVICES=(hunyuan3d pixal3d comfyui)

retry_args=()
while [ $# -gt 0 ]
do
  case "$1" in
    --retry-errors|--retry-skipped) retry_args+=("$1"); shift ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$RESULTS_DIR" "$LOG_DIR"
rm -f "$DONE_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

started_at="$(date --iso-8601=seconds)"
outcomes=()
failed_strata=()
final_status="aborted"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

wanted() {
  # ONLY が空なら全部。指定があれば、その中にあるものだけ
  local key="$1"
  [ -z "${ONLY:-}" ] && return 0
  case ",$ONLY," in *",$key,"*) return 0 ;; *) return 1 ;; esac
}

vram_line() {
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo "nvidia-smi なし"
}

write_done() {
  # 途中で止まった場合も、待っている側が先へ進めるように必ず置く
  {
    echo "status=$final_status"
    echo "started_at=$started_at"
    echo "finished_at=$(date --iso-8601=seconds)"
    echo "results_dir=$RESULTS_DIR"
    echo "log=$LOG_FILE"
    echo "vram_after=$(vram_line)"
    for line in "${outcomes[@]}"; do echo "outcome $line"; done
    for unit in "${failed_strata[@]}"; do echo "strata_failed $unit"; done
  } > "$DONE_FILE"
  log "DONE を置いた: $DONE_FILE（status=$final_status）"
}
trap write_done EXIT

stop_all_strata() {
  local unit
  for unit in strata strata-coder strata-official
  do
    if systemctl --user is-active --quiet "$unit"; then
      log "$unit を止める"
      systemctl --user stop "$unit" || log "$unit の停止に失敗"
    fi
  done
}

run_target() {
  # 1 モデルを全問。失敗（エラーの問がある）でも次へ進む
  local key="$1"
  local code=0
  "${RUN_EVAL[@]}" run --target "$key" --suite all --results-dir "$RESULTS_DIR" "${retry_args[@]}" || code=$?
  outcomes+=("$key run_exit=$code")
  log "$key: run の終了コード $code"
}

save_journal() {
  local key="$1" unit="$2" slug
  slug="$("$PYTHON" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import targets; print(targets.get(sys.argv[2]).slug)' "$TOOL_DIR" "$key")"
  mkdir -p "$RESULTS_DIR/local/$slug"
  journalctl --user -u "$unit" -n 300 --no-pager > "$RESULTS_DIR/local/$slug/journal-$(date +%Y%m%d-%H%M%S).txt" 2>&1 || true
}

run_strata() {
  # 起動に成功して流し終えたら 0、起動に失敗したら 1
  local key="$1" unit="$2" pending
  pending="$("${RUN_EVAL[@]}" pending --target "$key" --suite all --results-dir "$RESULTS_DIR" "${retry_args[@]}")"
  if [ "$pending" = "0" ]; then
    log "$key: 流す問が無い（記録済み）。起動しない"
    outcomes+=("$key run_exit=0 (記録済み)")
    return 0
  fi
  log "$unit を起動する（/health が返るまで待つ。50〜90 秒）"
  if ! systemctl --user start "$unit"; then
    log "$unit の起動に失敗。journal を残して飛ばす"
    save_journal "$key" "$unit"
    systemctl --user stop "$unit" || true
    return 1
  fi
  log "$unit が起動した。VRAM $(vram_line)"
  run_target "$key"
  return 0
}

# ---------------------------------------------------------------- 前提の確認
log "== ローカル評価（結果 $RESULTS_DIR、ログ $LOG_FILE）=="
"$VRAM_POLICY" status || true
for unit in "${GPU_SERVICES[@]}"
do
  if systemctl --user is-active --quiet "$unit"; then
    log "$unit が動いている。GPU を取り合うので止めてから実行する（systemctl --user stop $unit）"
    exit 1
  fi
done
stop_all_strata

# ---------------------------------------------------------------- Ollama
for key in "${OLLAMA_ORDER[@]}"
do
  wanted "$key" || continue
  log "---- $key ----"
  run_target "$key"
  "${RUN_EVAL[@]}" unload --target "$key" || log "$key を降ろせなかった"
done

# ---------------------------------------------------------------- Strata
need_strata=false
for pair in "${STRATA_ORDER[@]}"
do
  read -r key _unit <<< "$pair"
  if wanted "$key"; then need_strata=true; fi
done
if $need_strata; then
  log "VRAM を開放する（Strata のエキスパートのキャッシュは起動時の空き VRAM で決まる）"
  "$VRAM_POLICY" release 22000 || log "release に失敗（policy=use か）。そのまま続ける"
  for pair in "${STRATA_ORDER[@]}"
  do
    read -r key unit <<< "$pair"
    wanted "$key" || continue
    log "---- $key（$unit）----"
    run_strata "$key" "$unit" || failed_strata+=("$pair")
  done
  if [ "${#failed_strata[@]}" -gt 0 ]; then
    retry_list=("${failed_strata[@]}")
    failed_strata=()
    for pair in "${retry_list[@]}"
    do
      read -r key unit <<< "$pair"
      log "---- $key（$unit）をもう一度試す ----"
      run_strata "$key" "$unit" || failed_strata+=("$pair")
    done
  fi
  stop_all_strata
fi

log "VRAM $(vram_line)"
"$VRAM_POLICY" status || true
final_status="finished"
