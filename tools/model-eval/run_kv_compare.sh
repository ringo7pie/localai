#!/usr/bin/env bash
# Strata 3 種で KV キャッシュの型（int8 / fp16）を変えて、コーディング C4・C5 を流す。
#
# 使い方: run_kv_compare.sh [--dry-run]
#   環境変数 RUN_TAG（既定 2026-10-09-kv）: 結果の置き場 results/<RUN_TAG>/
#   環境変数 ONLY_TARGETS（例 "strata-official:IQ3_XXS,strata-flash-next:IQ3_S"）: この key のモデルだけ流す
#   環境変数 ONLY_KV（int8 か fp16）: この型の条件だけ流す
#   環境変数 RETRY_ERRORS=1: status が error の問を流し直す
#   --dry-run: 流す順番と命令を表示するだけ（systemctl も run_eval.py run も実行しない）
#
# 順番: Coder（strata-coder）→ 公式（strata-official）→ RVN（strata）。モデルごとに
#       「int8 で起動 → rep2・rep3 → 停止」→「fp16 で起動 → rep1・rep2・rep3 → 停止」。
# int8 の rep1 は既存の記録（results/2026-10-08/）の写し（results/<RUN_TAG>/int8/rep1/source.json に元を書く）。
# KV の型は STRATA_EXTRA_ARGS="--kv fp16" を systemd の user manager の環境に一時的に置いて切り替える
# （engine は --kv を後ろの指定で上書きする）。終了時（異常終了でも）に必ず外す。
# 起動のたびに engine のログの最後の起動行で --kv を確かめ、違っていたらその条件を止めて kv_mismatch と記録する。
# 起動に失敗したら journal を results/<RUN_TAG>/<kv>/ に残して start_failed と記録し、次へ進む。
# 条件ごとに results/<RUN_TAG>/<kv>/server-<slug>.json（枠・命中率・VRAM・RAM・起動秒）を、止める前に書く。
# 途中で止めても、もう一度実行すれば記録のある問は飛ばして続きから流す（run_eval.py の再開の規則）。
# 終わったら（途中で止まっても）results/<RUN_TAG>/DONE を置く。待つ側は終了の通知か until [ -f DONE ] で待つ
# （pgrep -f で待つと待つ側の bash 自身に一致して終わらない）。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON=/usr/bin/python3
# 試験用の差し替え口（本番では使わない）: RUN_EVAL_CMD（run_eval.py の代わりの実行ファイル）、VRAM_POLICY、
# RESULTS_BASE・SOURCE_RESULTS・STRATA_LOGS・LOG_DIR（置き場）。tests/test_units.py が偽の systemctl と組み合わせて使う
if [ -n "${RUN_EVAL_CMD:-}" ]; then RUN_EVAL=("$RUN_EVAL_CMD"); else RUN_EVAL=("$PYTHON" -B "$TOOL_DIR/run_eval.py"); fi
KV_COMPARE=("$PYTHON" -B "$TOOL_DIR/cond_compare.py")
VRAM_POLICY="${VRAM_POLICY:-$HOME/.claude/scripts/vram-policy.sh}"
RUN_TAG="${RUN_TAG:-2026-10-09-kv}"
RESULTS_ROOT="${RESULTS_BASE:-$TOOL_DIR/results}/$RUN_TAG"
# int8 の rep1 に写す元（Coder の 2026-10-09 の記録も、同じ results/2026-10-08/ の下にある）
SOURCE_RESULTS="${SOURCE_RESULTS:-$TOOL_DIR/results/2026-10-08}"
STRATA_LOGS="${STRATA_LOGS:-$TOOL_DIR/../strata/logs}"
DONE_FILE="$RESULTS_ROOT/DONE"
LOG_DIR="${LOG_DIR:-$TOOL_DIR/work}"
LOG_FILE="$LOG_DIR/run_kv_compare-$RUN_TAG.log"
ITEMS="c4,c5"
TIME_BUDGET_MIN=200

# 「target の key」「systemd の unit」「記録の slug」「engine のログ名（tools/strata/logs/ の下）」。流す順
KV_MODELS=(
  "strata-flash-coder:IQ1_M strata-coder strata-coder-IQ1_M strata-coder-engine.log"
  "strata-official:IQ3_XXS strata-official strata-official-IQ3_XXS strata-official-engine.log"
  "strata-flash-next:IQ3_S strata strata-rvn-IQ3_S strata-engine.log"
)
# 条件ごとに流す回（int8 の rep1 は既存の記録の写しなので流さない）
INT8_REPS=(2 3)
FP16_REPS=(1 2 3)
# GPU を取り合うほかのサービス（入口ページの GPU_EXCLUSIVE_KEYS と同じ顔ぶれ）
GPU_SERVICES=(hunyuan3d pixal3d comfyui)

DRY_RUN=false
while [ $# -gt 0 ]
do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

retry_args=()
if [ "${RETRY_ERRORS:-0}" = "1" ]; then retry_args+=(--retry-errors); fi

case "${ONLY_KV:-}" in
  ""|int8|fp16) ;;
  *) echo "ONLY_KV は int8 か fp16: ${ONLY_KV}" >&2; exit 2 ;;
esac

started_at="$(date --iso-8601=seconds)"
outcomes=()
final_status="aborted"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

wanted_target() {
  # ONLY_TARGETS が空なら全部。指定があれば、その key だけ
  local key="$1"
  [ -z "${ONLY_TARGETS:-}" ] && return 0
  case ",$ONLY_TARGETS," in *",$key,"*) return 0 ;; *) return 1 ;; esac
}

wanted_kv() {
  [ -z "${ONLY_KV:-}" ] && return 0
  [ "$ONLY_KV" = "$1" ]
}

vram_line() {
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo "nvidia-smi なし"
}

vram_used_mib() {
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 || true
}

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

set_kv_env() {
  # 起動の前に必ず呼ぶ。fp16 は STRATA_EXTRA_ARGS を足し、int8 は外す
  if [ "$1" = "fp16" ]; then
    systemctl --user set-environment STRATA_EXTRA_ARGS="--kv fp16"
  else
    systemctl --user unset-environment STRATA_EXTRA_ARGS
  fi
}

extra_args_line() {
  # user manager の環境にある STRATA_EXTRA_ARGS の行。無ければ「STRATA_EXTRA_ARGS なし」
  # （パイプで grep -q を使うと、早く閉じて systemctl が SIGPIPE になり pipefail で誤判定するので、いったん変数に取る）
  local dump line
  dump="$(systemctl --user show-environment 2>/dev/null)" || { echo "show-environment を読めない"; return 0; }
  while IFS= read -r line
  do
    case "$line" in STRATA_EXTRA_ARGS=*) echo "$line"; return 0 ;; esac
  done <<< "$dump"
  echo "STRATA_EXTRA_ARGS なし"
}

write_done() {
  # 途中で止まった場合も、待っている側が先へ進めるように必ず置く
  local env_check line
  env_check="$(extra_args_line)"
  {
    echo "status=$final_status"
    echo "started_at=$started_at"
    echo "finished_at=$(date --iso-8601=seconds)"
    echo "results_root=$RESULTS_ROOT"
    echo "log=$LOG_FILE"
    echo "vram_after=$(vram_line)"
    echo "environment=$env_check"
    for line in "${outcomes[@]}"; do echo "outcome $line"; done
  } > "$DONE_FILE"
  log "DONE を置いた: $DONE_FILE（status=$final_status）"
}

finish() {
  # 終了時（正常でも異常でも）の後始末。途中で失敗しても残りを続ける
  set +e
  log "---- 終了の後始末 ----"
  stop_all_strata
  systemctl --user unset-environment STRATA_EXTRA_ARGS
  log "確認: user manager の環境 → $(extra_args_line)（「なし」以外なら外し忘れ）"
  log "VRAM $(vram_line)"
  "$VRAM_POLICY" status
  write_done
}

save_journal() {
  local unit="$1" kv="$2" slug="$3"
  mkdir -p "$RESULTS_ROOT/$kv"
  journalctl --user -u "$unit" -n 300 --no-pager > "$RESULTS_ROOT/$kv/journal-$slug-$(date +%Y%m%d-%H%M%S).txt" 2>&1 || true
}

write_server_info() {
  # 引数: kv key unit slug engine_log log_offset start_s status vram_before "reps"。止める前に呼ぶ
  local vram_args=()
  if [ -n "${9:-}" ]; then vram_args=(--vram-before "$9"); fi
  "${KV_COMPARE[@]}" server-info --root "$RESULTS_ROOT" --kv "$1" --target "$2" --unit "$3" --slug "$4" \
    --engine-log "$5" --after-line "$6" --start-s "$7" --status "$8" --reps "${10}" "${vram_args[@]}" \
    || log "server-info の書き出しに失敗（$4 $1）"
}

pending_count() {
  # 引数: kv slug rep。この回でまだ流していない問の数
  "${KV_COMPARE[@]}" pending --root "$RESULTS_ROOT" --kv "$1" --slug "$2" --rep "$3" "${retry_args[@]}"
}

# ---------------------------------------------------------------- 1 条件（モデル × KV の型）
run_condition() {
  # 引数: key unit slug engine_log_name kv rep...
  local key="$1" unit="$2" slug="$3" engine_log="$STRATA_LOGS/$4" kv="$5"
  shift 5
  local reps=("$@") todo_reps=() rep pending log_offset vram_before start_s start_began status code dir
  for rep in "${reps[@]}"
  do
    pending="$(pending_count "$kv" "$slug" "$rep")"
    if [ "$pending" != "0" ]; then todo_reps+=("$rep"); fi
  done
  if [ "${#todo_reps[@]}" -eq 0 ]; then
    log "$slug $kv: 流す問が無い（記録済み）。起動しない"
    outcomes+=("$slug $kv status=skipped (記録済み)")
    return 0
  fi
  log "==== $key（$unit）KV=$kv、流す回: ${todo_reps[*]} ===="
  stop_all_strata
  set_kv_env "$kv"
  log "user manager の環境: $(extra_args_line)"
  # 起動の前の engine ログの行数（新しい起動行だけを見るため）と VRAM
  if [ -f "$engine_log" ]; then log_offset="$(wc -l < "$engine_log")"; else log_offset=0; fi
  vram_before="$(vram_used_mib)"
  log "$unit を起動する（/health が返るまで待つ。50〜90 秒）。起動前の VRAM $(vram_line)"
  start_began=$SECONDS
  if ! systemctl --user start "$unit"; then
    start_s=$((SECONDS - start_began))
    log "$unit の起動に失敗（${start_s} 秒）。journal を残して飛ばす"
    save_journal "$unit" "$kv" "$slug"
    write_server_info "$kv" "$key" "$unit" "$slug" "$engine_log" "$log_offset" "$start_s" start_failed "$vram_before" "${todo_reps[*]}"
    systemctl --user stop "$unit" || true
    outcomes+=("$slug $kv status=start_failed start_s=$start_s")
    return 0
  fi
  start_s=$((SECONDS - start_began))
  log "$unit が起動した（${start_s} 秒）。VRAM $(vram_line)"

  # 起動行の --kv を確かめる。違っていたら、この条件は流さない
  if ! "${KV_COMPARE[@]}" check-kv --log "$engine_log" --after-line "$log_offset" --kv "$kv"; then
    log "$slug $kv: 起動行の --kv が期待と違う。この条件を止める"
    write_server_info "$kv" "$key" "$unit" "$slug" "$engine_log" "$log_offset" "$start_s" kv_mismatch "$vram_before" "${todo_reps[*]}"
    systemctl --user stop "$unit" || true
    outcomes+=("$slug $kv status=kv_mismatch start_s=$start_s")
    return 0
  fi

  status=ok
  for rep in "${todo_reps[@]}"
  do
    if ! systemctl --user is-active --quiet "$unit"; then
      log "$unit が止まっている。この条件の残りの回を打ち切る"
      status=server_died
      break
    fi
    dir="$RESULTS_ROOT/$kv/rep$rep"
    code=0
    log "---- $slug $kv rep$rep（結果 $dir）----"
    "${RUN_EVAL[@]}" run --target "$key" --suite coding --items "$ITEMS" --results-dir "$dir" \
      --time-budget-min "$TIME_BUDGET_MIN" "${retry_args[@]}" || code=$?
    outcomes+=("$slug $kv rep$rep run_exit=$code")
    log "$slug $kv rep$rep: run の終了コード $code"
  done
  if [ "$status" = "ok" ] && ! systemctl --user is-active --quiet "$unit"; then status=server_died; fi

  # 止める前に、起動の記録（枠・命中率・VRAM・RAM）を書く
  write_server_info "$kv" "$key" "$unit" "$slug" "$engine_log" "$log_offset" "$start_s" "$status" "$vram_before" "${todo_reps[*]}"
  systemctl --user stop "$unit" || log "$unit の停止に失敗"
  outcomes+=("$slug $kv status=$status start_s=$start_s")
}

# ---------------------------------------------------------------- --dry-run（命令を表示するだけ）
plan_condition() {
  # 引数: key unit slug engine_log_name kv rep...
  local key="$1" unit="$2" slug="$3" engine_log="$4" kv="$5"
  shift 5
  local rep pending
  echo "[dry-run]   条件 $kv（流す回: $*）"
  if [ "$kv" = "fp16" ]; then
    echo "[dry-run]     systemctl --user set-environment STRATA_EXTRA_ARGS=\"--kv fp16\""
  else
    echo "[dry-run]     systemctl --user unset-environment STRATA_EXTRA_ARGS"
  fi
  echo "[dry-run]     systemctl --user start $unit"
  echo "[dry-run]     cond_compare.py check-kv --log tools/strata/logs/$engine_log --kv $kv   # 最後の起動行の --kv を確かめる"
  for rep in "$@"
  do
    pending="$(pending_count "$kv" "$slug" "$rep")"
    if [ "$pending" = "0" ]; then
      echo "[dry-run]     rep$rep: 記録済み（流さない）"
    else
      echo "[dry-run]     rep$rep: ${RUN_EVAL[*]} run --target $key --suite coding --items $ITEMS --results-dir $RESULTS_ROOT/$kv/rep$rep --time-budget-min $TIME_BUDGET_MIN ${retry_args[*]:-}   # 未記録 $pending 問"
    fi
  done
  echo "[dry-run]     cond_compare.py server-info --root $RESULTS_ROOT --kv $kv --target $key --unit $unit --slug $slug --status ok ...   # 止める前に書く"
  echo "[dry-run]     systemctl --user stop $unit"
}

# 流す条件の一覧（ONLY_TARGETS・ONLY_KV で絞る）。モデルごとに int8 → fp16
for_each_condition() {
  # 引数: 呼ぶ関数名（key unit slug engine_log_name kv rep... を渡す）
  local handler="$1" pair key unit slug engine_log
  for pair in "${KV_MODELS[@]}"
  do
    read -r key unit slug engine_log <<< "$pair"
    wanted_target "$key" || continue
    if wanted_kv int8; then "$handler" "$key" "$unit" "$slug" "$engine_log" int8 "${INT8_REPS[@]}"; fi
    if wanted_kv fp16; then "$handler" "$key" "$unit" "$slug" "$engine_log" fp16 "${FP16_REPS[@]}"; fi
  done
}

selected_slugs() {
  local pair key unit slug engine_log
  for pair in "${KV_MODELS[@]}"
  do
    read -r key unit slug engine_log <<< "$pair"
    if wanted_target "$key"; then echo "$slug"; fi
  done
}

slug_args=()
while read -r slug_name
do
  slug_args+=(--slug "$slug_name")
done < <(selected_slugs)
if [ "${#slug_args[@]}" -eq 0 ]; then
  echo "ONLY_TARGETS に合うモデルが無い: ${ONLY_TARGETS:-}" >&2
  exit 2
fi

if $DRY_RUN; then
  echo "[dry-run] 結果の置き場: $RESULTS_ROOT（RUN_TAG=$RUN_TAG、ONLY_TARGETS=${ONLY_TARGETS:-全部}、ONLY_KV=${ONLY_KV:-両方}）"
  if wanted_kv int8; then
    echo "[dry-run] 最初に int8 の rep1 を既存の記録から写す:"
    "${KV_COMPARE[@]}" copy-int8-rep1 --root "$RESULTS_ROOT" --source-dir "$SOURCE_RESULTS" "${slug_args[@]}" --dry-run
  fi
  for pair in "${KV_MODELS[@]}"
  do
    read -r key unit slug engine_log <<< "$pair"
    wanted_target "$key" || continue
    echo "[dry-run] == $key（unit $unit、slug $slug）=="
    if wanted_kv int8; then plan_condition "$key" "$unit" "$slug" "$engine_log" int8 "${INT8_REPS[@]}"; fi
    if wanted_kv fp16; then plan_condition "$key" "$unit" "$slug" "$engine_log" fp16 "${FP16_REPS[@]}"; fi
  done
  echo "[dry-run] 終わり: 全 Strata を止める → systemctl --user unset-environment STRATA_EXTRA_ARGS → show-environment で確認 → vram-policy.sh status → $DONE_FILE を置く"
  exit 0
fi

# ---------------------------------------------------------------- 前提の確認
mkdir -p "$RESULTS_ROOT" "$LOG_DIR"
rm -f "$DONE_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'final_status=interrupted; exit 130' INT TERM HUP
trap finish EXIT

log "== KV キャッシュの比べ（結果 $RESULTS_ROOT、ログ $LOG_FILE）=="
"$VRAM_POLICY" status || true
for unit in "${GPU_SERVICES[@]}"
do
  if systemctl --user is-active --quiet "$unit"; then
    log "$unit が動いている。GPU を取り合うので止めてから実行する（systemctl --user stop $unit）"
    exit 1
  fi
done
stop_all_strata
# 前の実行の設定が残っていても、int8 の条件が fp16 で起動しないように外しておく
systemctl --user unset-environment STRATA_EXTRA_ARGS

if wanted_kv int8; then
  log "int8 の rep1 を既存の記録から写す"
  "${KV_COMPARE[@]}" copy-int8-rep1 --root "$RESULTS_ROOT" --source-dir "$SOURCE_RESULTS" "${slug_args[@]}"
fi

log "VRAM を開放する（Strata のエキスパートのキャッシュは起動時の空き VRAM で決まる）"
"$VRAM_POLICY" release 22000 || log "release に失敗（policy=use か）。そのまま続ける"

# ---------------------------------------------------------------- 条件を順に流す
for_each_condition run_condition

final_status="finished"
