#!/usr/bin/env bash
# ローカルのモデルに問題を順に解かせる（2026-10-08 の評価の P2、2026-10-18 の評価の P1）。
#
# 使い方: run_local.sh [--retry-errors] [--retry-skipped] [--dry-run]
#   環境変数 RUN_DATE（既定 2026-10-08）: 結果の置き場 results/<RUN_DATE>/
#   環境変数 ONLY（例 "gemma4:e4b,strata-official:IQ3_XXS"）: このモデルだけ流す
#   環境変数 ORDER（target の key のカンマ区切り）: この順に流す（既定は下の OLLAMA_ORDER → STRATA_ORDER）
#   環境変数 SUITE（既定 all）: run_eval.py の --suite（hard = 2026-10-18 の難問 9 問）
#   環境変数 BUDGET_MIN（既定 100）: 1 モデルの累計時間の上限（分）
#   環境変数 DEADLINE（ISO、任意）: 全モデルの締切。モデルごとの上限を min(BUDGET_MIN, (締切 - 今 - 残りモデル × 5 分) ÷ 残りモデル)
#     に詰め、run_eval.py にも --deadline で渡す
#   results/<RUN_DATE>/progress.json があれば、run_eval.py に --progress で渡し、モデルの開始・終了も書く（progress.py show で見る）
#
# 既定の順番: Ollama の e4b → 27b → it-qat → IQ4_XS（各モデルの後に keep_alive:0 で降ろす）→ Strata の strata（RVN、8082）→
#       strata-official（8084）→ strata-coder（8083）→ strata-official-iq3s（8085）→ strata-swift（8086）→ 止める。
# Ollama から Strata に移る前に VRAM を開放し（vram-policy.sh release 22000）、Strata から Ollama に移る前に Strata を止める。
# Strata の起動に失敗したら journal を results/<日付>/local/<slug>/ に残して飛ばし、最後にもう一度だけ試す。
# 途中で止めても、もう一度実行すれば記録の無い問から続ける（run_eval.py の再開の規則）。
# 終わったら（途中で止まっても）results/<日付>/DONE を置く。待つ側は終了の通知か until [ -f DONE ] で待つ
# （pgrep -f で待つと待つ側の bash 自身に一致して終わらない）。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON=/usr/bin/python3
RUN_EVAL=("$PYTHON" -B "$TOOL_DIR/run_eval.py")
PROGRESS_PY=("$PYTHON" -B "$TOOL_DIR/progress.py")
VRAM_POLICY="$HOME/.claude/scripts/vram-policy.sh"
RUN_DATE="${RUN_DATE:-2026-10-08}"
RESULTS_DIR="$TOOL_DIR/results/$RUN_DATE"
DONE_FILE="$RESULTS_DIR/DONE"
PROGRESS_FILE="$RESULTS_DIR/progress.json"
LOG_DIR="$TOOL_DIR/work"
LOG_FILE="$LOG_DIR/run_local-$RUN_DATE.log"
SUITE="${SUITE:-all}"
BUDGET_MIN="${BUDGET_MIN:-100}"
DEADLINE="${DEADLINE:-}"
# モデルの切り替え（読み込み・起動・停止）に見込む分（progress.py の SWITCH_MIN と同じ）
SWITCH_MIN=5

OLLAMA_ORDER=(gemma4:e4b qwen3.8:27b gemma4:31b-it-qat qwen3.8-flash-next:IQ4_XS)
STRATA_ORDER=(strata-flash-next:IQ3_S strata-official:IQ3_XXS strata-flash-coder:IQ1_M strata-official:IQ3_S
              strata-swift:IQ3_XXS)
# GPU を取り合うほかのサービス（入口ページの GPU_EXCLUSIVE_KEYS と同じ顔ぶれ）
GPU_SERVICES=(hunyuan3d pixal3d comfyui)

retry_args=()
dry_run=false
while [ $# -gt 0 ]
do
  case "$1" in
    --retry-errors|--retry-skipped) retry_args+=("$1"); shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

wanted() {
  # ONLY が空なら全部。指定があれば、その中にあるものだけ
  local key="$1"
  [ -z "${ONLY:-}" ] && return 0
  case ",$ONLY," in *",$key,"*) return 0 ;; *) return 1 ;; esac
}

target_field() {
  # targets.py の 1 項目（backend / unit / slug）を引く。知らない key なら終了コード 1
  "$PYTHON" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import targets; print(getattr(targets.get(sys.argv[2]), sys.argv[3]))' \
    "$TOOL_DIR" "$1" "$2"
}

# ---------------------------------------------------------------- 流す順番
sequence=()
if [ -n "${ORDER:-}" ]; then
  IFS=',' read -r -a order_keys <<< "$ORDER"
else
  order_keys=("${OLLAMA_ORDER[@]}" "${STRATA_ORDER[@]}")
fi
for key in "${order_keys[@]}"
do
  key="${key// /}"
  [ -z "$key" ] && continue
  wanted "$key" || continue
  backend="$(target_field "$key" backend)" || { echo "知らない target: $key" >&2; exit 2; }
  case "$backend" in
    ollama|strata) sequence+=("$key") ;;
    *) echo "ローカルのモデルではない: $key（$backend）" >&2; exit 2 ;;
  esac
done
[ "${#sequence[@]}" -gt 0 ] || { echo "流すモデルが無い" >&2; exit 2; }

budget_for() {
  # 残りモデル数（いまのモデルを含む）から、このモデルの累計時間の上限（分）を決める
  local remaining="$1"
  if [ -z "$DEADLINE" ]; then
    echo "$BUDGET_MIN"
    return
  fi
  "$PYTHON" -B - "$DEADLINE" "$remaining" "$BUDGET_MIN" "$SWITCH_MIN" <<'PY'
import datetime, sys
deadline = datetime.datetime.fromisoformat(sys.argv[1])
remaining, base, switch = int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
left = (deadline - datetime.datetime.now().astimezone()).total_seconds() / 60 - remaining * switch
print(f"{max(5.0, min(base, left / remaining)):.1f}")
PY
}

if $dry_run; then
  echo "結果 $RESULTS_DIR、試験 $SUITE、上限 $BUDGET_MIN 分、締切 ${DEADLINE:-なし}"
  echo "進捗の状態ファイル: $([ -f "$PROGRESS_FILE" ] && echo "$PROGRESS_FILE" || echo "無い（書かない）")"
  total="${#sequence[@]}"
  index=0
  for key in "${sequence[@]}"
  do
    index=$((index + 1))
    backend="$(target_field "$key" backend)"
    unit=""
    [ "$backend" = "strata" ] && unit=" unit $(target_field "$key" unit)"
    echo "  $index/$total $key（$backend$unit）上限 $(budget_for $((total - index + 1))) 分（いま計算した場合）"
  done
  echo "命令の例: ${RUN_EVAL[*]} run --target ${sequence[0]} --suite $SUITE --results-dir $RESULTS_DIR --time-budget-min <上限>${DEADLINE:+ --deadline $DEADLINE}"
  exit 0
fi

mkdir -p "$RESULTS_DIR" "$LOG_DIR"
rm -f "$DONE_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

started_at="$(date --iso-8601=seconds)"
outcomes=()
failed_strata=()
final_status="aborted"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

vram_line() {
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo "nvidia-smi なし"
}

progress() {
  # progress.json があるときだけ書く（失敗しても計測は止めない）
  [ -f "$PROGRESS_FILE" ] || return 0
  "${PROGRESS_PY[@]}" --state "$PROGRESS_FILE" lane local --set "$@" || log "progress.json に書けなかった"
}

write_done() {
  # 途中で止まった場合も、待っている側が先へ進めるように必ず置く
  {
    echo "status=$final_status"
    echo "started_at=$started_at"
    echo "finished_at=$(date --iso-8601=seconds)"
    echo "results_dir=$RESULTS_DIR"
    echo "suite=$SUITE"
    echo "log=$LOG_FILE"
    echo "vram_after=$(vram_line)"
    for line in "${outcomes[@]}"; do echo "outcome $line"; done
    for key in "${failed_strata[@]}"; do echo "strata_failed $key"; done
  } > "$DONE_FILE"
  if [ "$final_status" = "finished" ]; then
    progress status=finished item= target=
  fi
  log "DONE を置いた: $DONE_FILE（status=$final_status）"
}
trap write_done EXIT

stop_all_strata() {
  local unit
  for unit in strata strata-coder strata-official strata-official-iq3s strata-swift
  do
    if systemctl --user is-active --quiet "$unit"; then
      log "$unit を止める"
      systemctl --user stop "$unit" || log "$unit の停止に失敗"
    fi
  done
}

run_target() {
  # 1 モデルを全問。失敗（エラーの問がある）でも次へ進む
  local key="$1" budget="$2"
  local code=0
  local extra=()
  [ -f "$PROGRESS_FILE" ] && extra+=(--progress "$PROGRESS_FILE")
  [ -n "$DEADLINE" ] && extra+=(--deadline "$DEADLINE")
  "${RUN_EVAL[@]}" run --target "$key" --suite "$SUITE" --results-dir "$RESULTS_DIR" --time-budget-min "$budget" \
    "${extra[@]}" "${retry_args[@]}" || code=$?
  outcomes+=("$key run_exit=$code budget_min=$budget")
  log "$key: run の終了コード $code"
}

save_journal() {
  local key="$1" unit="$2" slug
  slug="$(target_field "$key" slug)"
  mkdir -p "$RESULTS_DIR/local/$slug"
  journalctl --user -u "$unit" -n 300 --no-pager > "$RESULTS_DIR/local/$slug/journal-$(date +%Y%m%d-%H%M%S).txt" 2>&1 || true
}

pending_count() {
  "${RUN_EVAL[@]}" pending --target "$1" --suite "$SUITE" --results-dir "$RESULTS_DIR" "${retry_args[@]}"
}

run_strata() {
  # 起動に成功して流し終えたら 0、起動に失敗したら 1
  local key="$1" budget="$2" unit
  unit="$(target_field "$key" unit)"
  log "$unit を起動する（/health が返るまで待つ。20〜100 秒）"
  progress phase_note="$unit を起動中" item=
  if ! systemctl --user start "$unit"; then
    log "$unit の起動に失敗。journal を残して飛ばす"
    save_journal "$key" "$unit"
    systemctl --user stop "$unit" || true
    return 1
  fi
  log "$unit が起動した。VRAM $(vram_line)"
  run_target "$key" "$budget"
  systemctl --user stop "$unit" || log "$unit の停止に失敗"
  return 0
}

# ---------------------------------------------------------------- 前提の確認
log "== ローカル評価（結果 $RESULTS_DIR、試験 $SUITE、上限 $BUDGET_MIN 分、締切 ${DEADLINE:-なし}、ログ $LOG_FILE）=="
log "順番: ${sequence[*]}"
"$VRAM_POLICY" status || true
for unit in "${GPU_SERVICES[@]}"
do
  if systemctl --user is-active --quiet "$unit"; then
    log "$unit が動いている。GPU を取り合うので止めてから実行する（systemctl --user stop $unit）"
    exit 1
  fi
done
stop_all_strata

# ---------------------------------------------------------------- 本体
total="${#sequence[@]}"
# モデルごとの流す問の数。後のモデルの合計を items_after として進捗に書く（上限なしのとき progress.py が残り時間を出すのに使う）
pending_counts=()
for key in "${sequence[@]}"
do
  pending_counts+=("$(pending_count "$key")")
done
index=0
previous_backend=""
for key in "${sequence[@]}"
do
  index=$((index + 1))
  backend="$(target_field "$key" backend)"
  budget="$(budget_for $((total - index + 1)))"
  items_after=0
  for ((later = index; later < total; later++))
  do
    items_after=$((items_after + pending_counts[later]))
  done
  log "---- $index/$total $key（$backend、上限 $budget 分）----"
  progress target="$key" model_index="$index" model_count="$total" budget_min="$budget" base_budget_min="$BUDGET_MIN" \
    deadline="$DEADLINE" status=running spent_min=0 done=0 item= phase_note= items_after="$items_after"
  if [ "$(pending_count "$key")" = "0" ]; then
    log "$key: 流す問が無い（記録済み）"
    outcomes+=("$key run_exit=0 (記録済み)")
    continue
  fi
  if [ "$backend" = "ollama" ]; then
    [ "$previous_backend" = "strata" ] && stop_all_strata
    run_target "$key" "$budget"
    "${RUN_EVAL[@]}" unload --target "$key" || log "$key を降ろせなかった"
  else
    if [ "$previous_backend" != "strata" ]; then
      log "VRAM を開放する（Strata のエキスパートのキャッシュは起動時の空き VRAM で決まる）"
      "$VRAM_POLICY" release 22000 || log "release に失敗（policy=use か）。そのまま続ける"
    fi
    run_strata "$key" "$budget" || failed_strata+=("$key")
  fi
  previous_backend="$backend"
done

if [ "${#failed_strata[@]}" -gt 0 ]; then
  retry_list=("${failed_strata[@]}")
  failed_strata=()
  "$VRAM_POLICY" release 22000 || true
  for key in "${retry_list[@]}"
  do
    log "---- $key をもう一度試す ----"
    run_strata "$key" "$(budget_for 1)" || failed_strata+=("$key")
  done
fi
stop_all_strata

log "VRAM $(vram_line)"
"$VRAM_POLICY" status || true
final_status="finished"
