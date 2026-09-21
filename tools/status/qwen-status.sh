#!/usr/bin/env bash
# A30 サーバー上で「いま Qwen が何を処理しているか」を 1 画面で表示する。
#
# 使い方:  qwen-status.sh [--watch 秒] [--lines N]
#   --watch 秒   その間隔で画面を更新し続ける（Ctrl-C で止める）
#   --lines N    タスクの直近イベントを N 行まで表示（既定 3）
#
# 見るもの: GPU / Ollama に載っているモデル / local-ai-bridge の実行中タスク（段階・ツール呼び出し回数・直近の操作）
#          / qwen-worker の実行中タスク / Open WebUI。読み取りだけで何も変更しない。
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bridge_cli="$repo_root/tools/local-ai-bridge/run-local-ai-task"
bridge_tasks="${XDG_STATE_HOME:-$HOME/.local/state}/local-ai-bridge/tasks"
worker_state="${XDG_STATE_HOME:-$HOME/.local/state}/qwen-worker"
watch_sec=0
event_lines=3

while [ $# -gt 0 ]; do
  case "$1" in
    --watch) watch_sec="${2:?--watch には秒数が要る}"; shift 2 ;;
    --lines) event_lines="${2:?--lines には行数が要る}"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

section() { printf '\n== %s ==\n' "$1"; }

show_gpu() {
  section "GPU"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader \
      | awk -F', ' '{printf "使用率 %s / VRAM %s / %s\n", $1, $2, $3}'
  else
    echo "nvidia-smi 無し"
  fi
}

show_ollama() {
  section "Ollama に載っているモデル"
  local body
  if ! body="$(curl -s --max-time 3 http://127.0.0.1:11434/api/ps)"; then
    echo "Ollama に接続できない（127.0.0.1:11434）"; return
  fi
  printf '%s' "$body" | python3 -c '
import sys, json, datetime
models = json.load(sys.stdin).get("models", [])
if not models:
    print("無し（生成していない。次の呼び出しで約 60 秒のロードが入る）")
for m in models:
    size = m.get("size") or 0; vram = m.get("size_vram") or 0
    gpu = round(100 * vram / size) if size else 0
    exp_raw = m.get("expires_at", "")
    exp = exp_raw[:19].replace("T", " ")
    note = ""
    try:
        exp_dt = datetime.datetime.fromisoformat(exp_raw[:26] + exp_raw[-6:]) if exp_raw else None
        if exp_dt and exp_dt < datetime.datetime.now(exp_dt.tzinfo):
            note = "（過ぎているが生成中のため据え置き。5 分以上の生成が続いている）"
    except ValueError:
        pass
    name = m.get("name", "?")
    print(f"{name}  GPU 配置 {gpu}%（CPU に溢れていなければ 100）  VRAM {vram/2**30:.1f} GiB  降りる予定 {exp}{note}")
'
}

show_bridge() {
  section "local-ai-bridge（OpenCode 経由の委譲）"
  if [ ! -x "$bridge_cli" ]; then echo "run-local-ai-task が無い: $bridge_cli"; return; fi
  local listing
  listing="$("$bridge_cli" list --state running 2>/dev/null || echo '[]')"
  local queued
  queued="$("$bridge_cli" list --state queued 2>/dev/null || echo '[]')"
  BRIDGE_TASKS="$bridge_tasks" EVENT_LINES="$event_lines" python3 - "$listing" "$queued" <<'PY'
import sys, json, os, time, glob, datetime
running = json.loads(sys.argv[1]); queued = json.loads(sys.argv[2])
tasks_dir = os.environ["BRIDGE_TASKS"]; event_lines = int(os.environ["EVENT_LINES"])
if not running and not queued:
    print("実行中なし")
def age(ts):
    return f"{int(time.time() - ts)} 秒前"
for task in running:
    started = datetime.datetime.fromtimestamp(task["created_at"]).strftime("%H:%M:%S")
    print(f"{task['task_id']}  段階 {task['stage']}  workspace {task['workspace_id']}  mode {task['mode']}  開始 {started}  依頼元 {task['client_id']} / {task['request_id']}")
    tdir = os.path.join(tasks_dir, task["task_id"])
    events = sorted(glob.glob(os.path.join(tdir, "events-*.jsonl")), key=os.path.getmtime)
    if not events:
        print("   （イベントはまだ無い。OpenCode の起動待ちかモデルのロード中）"); continue
    latest = events[-1]
    tool_calls = []; last_ts = None
    with open(latest, encoding="utf-8") as fh:
        for line in fh:
            try: ev = json.loads(line)
            except Exception: continue
            last_ts = ev.get("timestamp") or last_ts
            if ev.get("type") == "tool_use":
                part = ev.get("part", {}); inp = part.get("state", {}).get("input", {})
                target = inp.get("filePath") or inp.get("pattern") or inp.get("path") or ""
                tool_calls.append(f"{part.get('tool')} {target}")
    phase = os.path.basename(latest).replace("events-", "").replace(".jsonl", "")
    last_age = age(last_ts / 1000) if last_ts else "不明"
    print(f"   いま {phase}  ツール呼び出し {len(tool_calls)} 回  最後のイベント {last_age}（長く止まっていれば生成中か混雑）")
    for call in tool_calls[-event_lines:]:
        print(f"   - {call}")
for task in queued:
    print(f"{task['task_id']}  待ち行列（前のジョブが終わるまで待つ）  workspace {task['workspace_id']}  依頼元 {task['client_id']} / {task['request_id']}")
PY
}

show_worker() {
  section "qwen-worker（Claude Code / Codex から直接）"
  local lock="$worker_state/inference.lock"
  if [ -f "$lock" ]; then
    if flock -n "$lock" true 2>/dev/null; then echo "推論ロック: 空き"; else echo "推論ロック: 使用中（推論が走っている）"; fi
  fi
  if [ -d "$worker_state/inflight" ] && [ -n "$(ls -A "$worker_state/inflight" 2>/dev/null)" ]; then
    echo "実行中タスク:"; ls -1 "$worker_state/inflight" | sed 's/^/   /'
  else
    echo "実行中タスクなし"
  fi
  local latest
  latest="$(ls -t "$worker_state/tasks" 2>/dev/null | head -1 || true)"
  if [ -n "$latest" ]; then
    local tdir="$worker_state/tasks/$latest"
    local done_mark="完了"; [ -f "$tdir/metrics.json" ] || done_mark="未完了"
    echo "直近のタスク: $latest（$done_mark、更新 $(( $(date +%s) - $(stat -c %Y "$tdir") )) 秒前）"
  fi
}

show_webui() {
  section "Open WebUI（ブラウザチャット）"
  if systemctl --user is-active open-webui >/dev/null 2>&1; then echo "動作中（http://<server-ip>:8080。LAN からの到達はサーバー側の許可次第）"
  else echo "停止中か、この端末からは確認できない（systemctl --user が使えない ssh セッションなど）"; fi
}

show_all() {
  echo "Qwen の状態  $(date '+%Y-%m-%d %H:%M:%S')  $(hostname)"
  show_gpu; show_ollama; show_bridge; show_worker; show_webui
}

if [ "$watch_sec" -gt 0 ]; then
  while true; do clear; show_all; sleep "$watch_sec"; done
else
  show_all
fi
