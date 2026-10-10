#!/usr/bin/env bash
# Strata 3 種のコーディング性能が低い原因の調査（実験 A と B）。コーディング C4・C5 を、思考の上限なし・生成 65,536 で流す。
#
# 使い方: run_fix_compare.sh [--dry-run]
#   環境変数 RUN_TAG（既定 2026-10-09-fix）: 結果の置き場 results/<RUN_TAG>/
#   環境変数 ONLY_TARGETS（例 "strata-official:IQ3_XXS,strata-flash-next:IQ3_S"）: この key のモデルだけ流す
#   環境変数 ONLY_ARMS（nobudget-ja か nobudget-en。カンマ区切りで両方も可）: この条件だけ流す
#   環境変数 RETRY_ERRORS=1: status が error の問を流し直す
#   環境変数 ARM_SPEC（例 "low-ja=1,2,3"）: 各モデルの条件の並びを、この並びに差し替える（追加の実験用）。
#     条件の名前が low- / medium- で始まれば思考の強さ（--reasoning-effort）を、-en で終われば英語の問題文を付ける
#   環境変数 MAX_TOKENS（既定 65536）: 生成の上限
#   --dry-run: 基準の写し元と、流す順番・命令を表示するだけ（systemctl も run_eval.py run も実行せず、結果の置き場も作らない）
#
# 条件（腕）: budget24k-ja = 基準（思考の上限 24,576・生成 32,768・日本語。既存の記録の写しで、流さない）、
#            nobudget-ja = A（思考の上限なし・生成 65,536・日本語）、nobudget-en = B（A と同じ条件で英語の問題文）。
# 順番: Coder（A rep1〜3 → B rep1〜3）→ 公式（A rep1〜3 → B rep1〜2）→ RVN（A rep1〜3）。
#       モデルごとに unit を起動し、そのモデルの全部の条件を流してから止める（起動は 3 回）。
# 最初に基準を写す（既にある記録は写さない）。写し元: rep1 は results/2026-10-08/、rep2・rep3 は results/2026-10-09-kv/int8/rep<N>/。
#   写し元のパスと「思考の上限 24,576・生成 32,768・日本語」は results/<RUN_TAG>/budget24k-ja/source.json に書く。
# KV キャッシュの型は切り替えない（int8 のまま。systemctl --user set-environment / unset-environment は使わない）。
#   STRATA_EXTRA_ARGS が user manager の環境に残っていたら、型が変わってしまうので実行を止める。
# 起動に失敗したら journal を results/<RUN_TAG>/ に残して start_failed と記録し、次のモデルへ進む。
# 条件 × モデルごとに results/<RUN_TAG>/<条件>/server-<slug>.json（起動行・枠・命中率・VRAM・RAM・起動秒・status）を、
# その条件を流し終えたあと（止める前）に書く。さらに、モデルの unit の journal（起動から停止まで）から
# 「repeated reasoning detected」「thinking budget reached」「the reply reached max tokens」の行数を数えて
# results/<RUN_TAG>/journal-counts-<slug>.json に書く（条件ごとの分も）。
# 途中で止めても、もう一度実行すれば記録のある問は飛ばして続きから流す（run_eval.py の再開の規則）。
# 終わったら（途中で止まっても）results/<RUN_TAG>/DONE を置く。待つ側は終了の通知か until [ -f DONE ] で待つ
# （pgrep -f で待つと待つ側の bash 自身に一致して終わらない）。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON=/usr/bin/python3
# 試験用の差し替え口（本番では使わない）: RUN_EVAL_CMD（run_eval.py の代わりの実行ファイル）、VRAM_POLICY、
# RESULTS_BASE・SOURCE_RESULTS・SOURCE_KV_RESULTS・STRATA_LOGS・LOG_DIR（置き場）。tests/test_units.py が偽の systemctl と組み合わせて使う
if [ -n "${RUN_EVAL_CMD:-}" ]; then RUN_EVAL=("$RUN_EVAL_CMD"); else RUN_EVAL=("$PYTHON" -B "$TOOL_DIR/run_eval.py"); fi
COND_COMPARE=("$PYTHON" -B "$TOOL_DIR/cond_compare.py")
VRAM_POLICY="${VRAM_POLICY:-$HOME/.claude/scripts/vram-policy.sh}"
RUN_TAG="${RUN_TAG:-2026-10-09-fix}"
RESULTS_ROOT="${RESULTS_BASE:-$TOOL_DIR/results}/$RUN_TAG"
# 基準に写す元（rep1 は 2026-10-08 の記録、rep2・rep3 は KV の比べで流した int8 の記録）
SOURCE_RESULTS="${SOURCE_RESULTS:-$TOOL_DIR/results/2026-10-08}"
SOURCE_KV_RESULTS="${SOURCE_KV_RESULTS:-$TOOL_DIR/results/2026-10-09-kv/int8}"
STRATA_LOGS="${STRATA_LOGS:-$TOOL_DIR/../strata/logs}"
DONE_FILE="$RESULTS_ROOT/DONE"
LOG_DIR="${LOG_DIR:-$TOOL_DIR/work}"
LOG_FILE="$LOG_DIR/run_fix_compare-$RUN_TAG.log"
ITEMS="c4,c5"
# 1 つの結果の置き場（条件 × 回）・1 モデルあたりの累計時間の上限（分）。run_eval.py の既定 100 分では足りない
TIME_BUDGET_MIN=400
MAX_TOKENS="${MAX_TOKENS:-65536}"
BASELINE_ARM="budget24k-ja"

# 「target の key」「systemd の unit」「記録の slug」「engine のログ名（tools/strata/logs/ の下）」「流す条件=回」。流す順
FIX_MODELS=(
  "strata-flash-coder:IQ1_M strata-coder strata-coder-IQ1_M strata-coder-engine.log nobudget-ja=1,2,3 nobudget-en=1,2,3"
  "strata-official:IQ3_XXS strata-official strata-official-IQ3_XXS strata-official-engine.log nobudget-ja=1,2,3 nobudget-en=1,2"
  "strata-flash-next:IQ3_S strata strata-rvn-IQ3_S strata-engine.log nobudget-ja=1,2,3"
)
# GPU を取り合うほかのサービス（入口ページの GPU_EXCLUSIVE_KEYS と同じ顔ぶれ）
GPU_SERVICES=(hunyuan3d pixal3d comfyui)

DRY_RUN=false
while [ $# -gt 0 ]
do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

retry_args=()
if [ "${RETRY_ERRORS:-0}" = "1" ]; then retry_args+=(--retry-errors); fi

if [ -n "${ONLY_ARMS:-}" ]; then
  IFS=',' read -ra only_arm_list <<< "$ONLY_ARMS"
  for only_arm in "${only_arm_list[@]}"
  do
    case "$only_arm" in
      nobudget-ja|nobudget-en|low-*|medium-*) ;;
      *) echo "ONLY_ARMS は nobudget-ja か nobudget-en（カンマ区切り）: ${ONLY_ARMS}" >&2; exit 2 ;;
    esac
  done
fi

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

wanted_arm() {
  [ -z "${ONLY_ARMS:-}" ] && return 0
  case ",$ONLY_ARMS," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

arm_lang_args() {
  # 条件の名前から run_eval.py に足す引数を決める: -en で終われば英語の問題文、low- / medium- で始まれば思考の強さ
  local extra=""
  case "$1" in *-en) extra="--prompt-lang en" ;; esac
  case "$1" in
    low-*) extra="${extra:+$extra }--reasoning-effort low" ;;
    medium-*) extra="${extra:+$extra }--reasoning-effort medium" ;;
  esac
  echo "$extra"
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

extra_args_line() {
  # user manager の環境にある STRATA_EXTRA_ARGS の行（読むだけ）。無ければ「STRATA_EXTRA_ARGS なし」
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
  local line
  {
    echo "status=$final_status"
    echo "started_at=$started_at"
    echo "finished_at=$(date --iso-8601=seconds)"
    echo "results_root=$RESULTS_ROOT"
    echo "log=$LOG_FILE"
    echo "vram_after=$(vram_line)"
    echo "environment=$(extra_args_line)"
    for line in "${outcomes[@]}"; do echo "outcome $line"; done
  } > "$DONE_FILE"
  log "DONE を置いた: $DONE_FILE（status=$final_status）"
}

finish() {
  # 終了時（正常でも異常でも）の後始末。途中で失敗しても残りを続ける
  set +e
  log "---- 終了の後始末 ----"
  stop_all_strata
  log "VRAM $(vram_line)"
  "$VRAM_POLICY" status
  write_done
}

save_journal() {
  local unit="$1" slug="$2"
  mkdir -p "$RESULTS_ROOT"
  journalctl --user -u "$unit" -n 300 --no-pager > "$RESULTS_ROOT/journal-start-failed-$slug-$(date +%Y%m%d-%H%M%S).txt" 2>&1 || true
}

write_server_info() {
  # 引数: arm key unit slug engine_log log_offset hits_offset start_s status vram_before "reps"。止める前に呼ぶ
  local vram_args=()
  if [ -n "${10:-}" ]; then vram_args=(--vram-before "${10}"); fi
  "${COND_COMPARE[@]}" server-info --root "$RESULTS_ROOT" --cond "$1" --target "$2" --unit "$3" --slug "$4" \
    --engine-log "$5" --after-line "$6" --hits-after-line "$7" --start-s "$8" --status "$9" --reps "${11}" "${vram_args[@]}" \
    || log "server-info の書き出しに失敗（$4 $1）"
}

write_journal_counts() {
  # 引数: slug unit since until [arm]。arm が無ければ起動からの全部の欄に書く
  local arm_args=()
  if [ -n "${5:-}" ]; then arm_args=(--arm "$5"); fi
  "${COND_COMPARE[@]}" journal-counts --root "$RESULTS_ROOT" --slug "$1" --unit "$2" --since "$3" --until "$4" "${arm_args[@]}" \
    || log "journal-counts の書き出しに失敗（$1 ${5:-total}）"
}

pending_count() {
  # 引数: arm slug rep。この回でまだ流していない問の数
  "${COND_COMPARE[@]}" pending --root "$RESULTS_ROOT" --cond "$1" --slug "$2" --rep "$3" "${retry_args[@]}"
}

log_lines() {
  # engine のログの今の行数（無ければ 0）
  if [ -f "$1" ]; then wc -l < "$1"; else echo 0; fi
}

# ---------------------------------------------------------------- 1 モデル（起動 1 回で、全部の条件を流す）
run_model() {
  # 引数: key unit slug engine_log_name arm=reps...
  local key="$1" unit="$2" slug="$3" engine_log="$STRATA_LOGS/$4"
  shift 4
  local spec arm reps_text rep pending
  local todo_arms=() todo_reps=()
  for spec in "$@"
  do
    arm="${spec%%=*}"
    reps_text="${spec#*=}"
    wanted_arm "$arm" || continue
    local arm_todo=()
    for rep in ${reps_text//,/ }
    do
      pending="$(pending_count "$arm" "$slug" "$rep")"
      if [ "$pending" != "0" ]; then arm_todo+=("$rep"); fi
    done
    if [ "${#arm_todo[@]}" -gt 0 ]; then
      todo_arms+=("$arm")
      todo_reps+=("${arm_todo[*]}")
    fi
  done
  if [ "${#todo_arms[@]}" -eq 0 ]; then
    log "$slug: 流す問が無い（記録済み、または ONLY_ARMS に合う条件が無い）。起動しない"
    outcomes+=("$slug status=skipped (記録済み)")
    return 0
  fi
  log "==== $key（$unit）流す条件: ${todo_arms[*]} ===="
  stop_all_strata
  local log_offset vram_before start_s start_began model_since index code status dir lang_args arm_since hits_offset arm_status
  log_offset="$(log_lines "$engine_log")"
  vram_before="$(vram_used_mib)"
  model_since="$(date '+%Y-%m-%d %H:%M:%S')"
  log "$unit を起動する（/health が返るまで待つ。50〜90 秒）。起動前の VRAM $(vram_line)"
  start_began=$SECONDS
  if ! systemctl --user start "$unit"; then
    start_s=$((SECONDS - start_began))
    log "$unit の起動に失敗（${start_s} 秒）。journal を残して飛ばす"
    save_journal "$unit" "$slug"
    for index in "${!todo_arms[@]}"
    do
      write_server_info "${todo_arms[$index]}" "$key" "$unit" "$slug" "$engine_log" "$log_offset" 0 "$start_s" start_failed "$vram_before" "${todo_reps[$index]}"
    done
    systemctl --user stop "$unit" || true
    outcomes+=("$slug status=start_failed start_s=$start_s")
    return 0
  fi
  start_s=$((SECONDS - start_began))
  log "$unit が起動した（${start_s} 秒）。VRAM $(vram_line)"

  local server_died=false
  for index in "${!todo_arms[@]}"
  do
    arm="${todo_arms[$index]}"
    arm_status=ok
    if $server_died || ! systemctl --user is-active --quiet "$unit"; then
      log "$unit が止まっている。条件 $arm を飛ばす"
      server_died=true
      arm_status=server_died
    else
      lang_args="$(arm_lang_args "$arm")"
      arm_since="$(date '+%Y-%m-%d %H:%M:%S')"
      hits_offset="$(log_lines "$engine_log")"
      for rep in ${todo_reps[$index]}
      do
        if ! systemctl --user is-active --quiet "$unit"; then
          log "$unit が止まっている。この条件の残りの回を打ち切る"
          server_died=true
          arm_status=server_died
          break
        fi
        dir="$RESULTS_ROOT/$arm/rep$rep"
        code=0
        log "---- $slug $arm rep$rep（結果 $dir）----"
        # shellcheck disable=SC2086  # lang_args は空か「--prompt-lang en」。語として分けて渡す
        "${RUN_EVAL[@]}" run --target "$key" --suite coding --items "$ITEMS" --reasoning-budget 0 --max-tokens "$MAX_TOKENS" \
          --time-budget-min "$TIME_BUDGET_MIN" --results-dir "$dir" $lang_args "${retry_args[@]}" || code=$?
        outcomes+=("$slug $arm rep$rep run_exit=$code")
        log "$slug $arm rep$rep: run の終了コード $code"
      done
      if [ "$arm_status" = "ok" ] && ! systemctl --user is-active --quiet "$unit"; then
        server_died=true
        arm_status=server_died
      fi
      write_journal_counts "$slug" "$unit" "$arm_since" "$(date '+%Y-%m-%d %H:%M:%S')" "$arm"
    fi
    # 条件を流し終えたあと（止める前）に、起動の記録（枠・命中率・VRAM・RAM）を書く
    write_server_info "$arm" "$key" "$unit" "$slug" "$engine_log" "$log_offset" "$hits_offset" "$start_s" "$arm_status" "$vram_before" "${todo_reps[$index]}"
    outcomes+=("$slug $arm status=$arm_status start_s=$start_s")
  done
  # 起動から停止までの journal の行数（ループの回復・思考の予算・生成の上限）
  write_journal_counts "$slug" "$unit" "$model_since" "$(date '+%Y-%m-%d %H:%M:%S')"
  systemctl --user stop "$unit" || log "$unit の停止に失敗"
}

# ---------------------------------------------------------------- --dry-run（命令を表示するだけ）
plan_model() {
  # 引数: key unit slug engine_log_name arm=reps...
  local key="$1" unit="$2" slug="$3" engine_log="$4"
  shift 4
  local spec arm reps_text rep pending lang_args
  echo "[dry-run]   systemctl --user start $unit   # 起動 1 回で、下の条件を続けて流す"
  for spec in "$@"
  do
    arm="${spec%%=*}"
    reps_text="${spec#*=}"
    wanted_arm "$arm" || continue
    lang_args="$(arm_lang_args "$arm")"
    echo "[dry-run]   条件 $arm（流す回: ${reps_text//,/ }）"
    for rep in ${reps_text//,/ }
    do
      pending="$(pending_count "$arm" "$slug" "$rep")"
      if [ "$pending" = "0" ]; then
        echo "[dry-run]     rep$rep: 記録済み（流さない）"
      else
        echo "[dry-run]     rep$rep: ${RUN_EVAL[*]} run --target $key --suite coding --items $ITEMS --reasoning-budget 0 --max-tokens $MAX_TOKENS --time-budget-min $TIME_BUDGET_MIN --results-dir $RESULTS_ROOT/$arm/rep$rep ${lang_args} ${retry_args[*]:-}   # 未記録 $pending 問"
      fi
    done
    echo "[dry-run]     cond_compare.py server-info --root $RESULTS_ROOT --cond $arm --target $key --unit $unit --slug $slug --status ok ...   # 条件を流し終えたあと、止める前に書く"
    echo "[dry-run]     cond_compare.py journal-counts --root $RESULTS_ROOT --slug $slug --unit $unit --since <条件の開始> --arm $arm"
  done
  echo "[dry-run]   cond_compare.py journal-counts --root $RESULTS_ROOT --slug $slug --unit $unit --since <起動時刻>   # 起動から停止までの全部"
  echo "[dry-run]   systemctl --user stop $unit"
}

# 流すモデルの一覧（ONLY_TARGETS で絞る）
for_each_model() {
  # 引数: 呼ぶ関数名（key unit slug engine_log_name arm=reps... を渡す）
  local handler="$1" pair key unit slug engine_log arm_specs
  for pair in "${FIX_MODELS[@]}"
  do
    read -r key unit slug engine_log arm_specs <<< "$pair"
    if [ -n "${ARM_SPEC:-}" ]; then arm_specs="$ARM_SPEC"; fi
    wanted_target "$key" || continue
    read -ra arm_array <<< "$arm_specs"
    "$handler" "$key" "$unit" "$slug" "$engine_log" "${arm_array[@]}"
  done
}

selected_slugs() {
  local pair key unit slug engine_log arm_specs
  for pair in "${FIX_MODELS[@]}"
  do
    read -r key unit slug engine_log arm_specs <<< "$pair"
    if [ -n "${ARM_SPEC:-}" ]; then arm_specs="$ARM_SPEC"; fi
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
  echo "[dry-run] 結果の置き場: $RESULTS_ROOT（RUN_TAG=$RUN_TAG、ONLY_TARGETS=${ONLY_TARGETS:-全部}、ONLY_ARMS=${ONLY_ARMS:-全部}）"
  echo "[dry-run] 最初に基準 $BASELINE_ARM（思考の上限 24,576・生成 32,768・日本語）を既存の記録から写す（rep1: $SOURCE_RESULTS、rep2・rep3: $SOURCE_KV_RESULTS/rep<N>）:"
  "${COND_COMPARE[@]}" copy-baseline --root "$RESULTS_ROOT" --arm "$BASELINE_ARM" --rep1-source "$SOURCE_RESULTS" \
    --reps-source "$SOURCE_KV_RESULTS" "${slug_args[@]}" --dry-run
  for pair in "${FIX_MODELS[@]}"
  do
    read -r key unit slug engine_log arm_specs <<< "$pair"
    if [ -n "${ARM_SPEC:-}" ]; then arm_specs="$ARM_SPEC"; fi
    wanted_target "$key" || continue
    echo "[dry-run] == $key（unit $unit、slug $slug）=="
    read -ra arm_array <<< "$arm_specs"
    plan_model "$key" "$unit" "$slug" "$engine_log" "${arm_array[@]}"
  done
  echo "[dry-run] 終わり: 全 Strata を止める → vram-policy.sh status → $DONE_FILE を置く（KV の型は切り替えない。set-environment は使わない）"
  exit 0
fi

# ---------------------------------------------------------------- 前提の確認
mkdir -p "$RESULTS_ROOT" "$LOG_DIR"
rm -f "$DONE_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'final_status=interrupted; exit 130' INT TERM HUP
trap finish EXIT

log "== Strata のコーディング性能の調査（結果 $RESULTS_ROOT、ログ $LOG_FILE）=="
"$VRAM_POLICY" status || true
for unit in "${GPU_SERVICES[@]}"
do
  if systemctl --user is-active --quiet "$unit"; then
    log "$unit が動いている。GPU を取り合うので止めてから実行する（systemctl --user stop $unit）"
    exit 1
  fi
done
stop_all_strata
# KV の型は切り替えない（int8 のまま）。前の作業の STRATA_EXTRA_ARGS が残っていると型が変わるので、あれば止める
extra_args="$(extra_args_line)"
log "user manager の環境: $extra_args"
case "$extra_args" in
  STRATA_EXTRA_ARGS=*)
    log "STRATA_EXTRA_ARGS が残っている。KV の型が int8 でなくなるので止める（systemctl --user unset-environment STRATA_EXTRA_ARGS を手で実行してから）"
    exit 1 ;;
esac

log "基準 $BASELINE_ARM を既存の記録から写す"
"${COND_COMPARE[@]}" copy-baseline --root "$RESULTS_ROOT" --arm "$BASELINE_ARM" --rep1-source "$SOURCE_RESULTS" \
  --reps-source "$SOURCE_KV_RESULTS" "${slug_args[@]}"

log "VRAM を開放する（Strata のエキスパートのキャッシュは起動時の空き VRAM で決まる）"
"$VRAM_POLICY" release 22000 || log "release に失敗（policy=use か）。そのまま続ける"

# ---------------------------------------------------------------- モデルを順に流す
for_each_model run_model

final_status="finished"
