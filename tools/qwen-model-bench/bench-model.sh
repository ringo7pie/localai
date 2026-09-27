#!/usr/bin/env bash
# Ollama の 1 モデルを載せて、この機体で実用になるかを数字で出す。
#
# 使い方: bench-model.sh <モデル名> [オプション]
#   --num-predict N    生成するトークン数（既定 128）
#   --prompt-file PATH プロンプトをファイルから読む（既定は内蔵の短い日本語の問い）
#   --keep             計測後もモデルを VRAM に残す（既定は降ろす）
#   -h, --help         この説明を表示して終了
#
# 測るもの: GPU 配置率 / 生成速度 tok/s / ロード時間 / VRAM・RAM・swap のピーク /
#          メモリ待ちの割合（/proc/pressure/memory の full）。
# 読み取りと、対象モデルのロード・解放だけを行う。サービスは止めない。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RESULTS_DIR="$TOOL_DIR/results"
OLLAMA_URL="http://127.0.0.1:11434"

# 実用かどうかの目安。README にも同じ値を書いてある。
MIN_USABLE_TOKENS_PER_SEC=5
MAX_USABLE_MEMORY_PRESSURE=50

num_predict=128
prompt_file=""
keep_loaded=false
model_name=""

while [ $# -gt 0 ]
do
  case "$1" in
    --num-predict) num_predict="${2:?--num-predict には数が要る}"; shift 2 ;;
    --prompt-file) prompt_file="${2:?--prompt-file にはパスが要る}"; shift 2 ;;
    --keep) keep_loaded=true; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "不明な引数: $1" >&2; exit 2 ;;
    *)
      if [ -n "$model_name" ]; then echo "モデル名が 2 つ指定されています: $model_name と $1" >&2; exit 2; fi
      model_name="$1"; shift ;;
  esac
done

if [ -z "$model_name" ]; then
  echo "モデル名を指定してください（例: $(basename -- "$0") qwen3.8:27b）" >&2
  exit 2
fi

# ---------------------------------------------------------------- 前提の確認
echo "== $model_name の計測 =="
echo
echo "[1/5] 前提の確認"

if ! curl -s -m 5 -o /dev/null "$OLLAMA_URL/api/tags"; then
  echo "Ollama に接続できません（$OLLAMA_URL）。" >&2
  exit 1
fi

if ! curl -s -m 10 "$OLLAMA_URL/api/tags" | /usr/bin/python3 -c "
import json, sys
target = sys.argv[1]
names = [m.get('name') for m in json.load(sys.stdin).get('models', [])]
sys.exit(0 if target in names else 1)
" "$model_name"; then
  echo "そのモデルは入っていません: $model_name" >&2
  echo "先に取得してください: ollama pull $model_name" >&2
  exit 1
fi
echo "モデル: あります（$model_name）"

# Hunyuan3D / Pixal3D は VRAM を食い合う。動いていたら測る意味が無いので止めてもらう。
busy_services=""
for unit in hunyuan3d pixal3d
do
  if systemctl --user is-active "$unit" >/dev/null 2>&1; then busy_services="$busy_services $unit"; fi
done
if [ -n "$busy_services" ]; then
  echo "次のサービスが動いています:$busy_services" >&2
  echo "VRAM を食い合うので、止めてから測ってください:" >&2
  for unit in $busy_services; do echo "  systemctl --user stop $unit" >&2; done
  exit 1
fi
echo "GPU を使う他のサービス: 動いていません"

# ---------------------------------------------------------------- VRAM を空ける
echo
echo "[2/5] VRAM を空ける"
loaded_before="$(curl -s -m 10 "$OLLAMA_URL/api/ps" | /usr/bin/python3 -c "
import json, sys
print(' '.join(m.get('name','') for m in json.load(sys.stdin).get('models', [])))
")"
for name in $loaded_before
do
  echo "  降ろします: $name"
  curl -s -m 60 "$OLLAMA_URL/api/generate" \
    -d "$(/usr/bin/python3 -c "import json,sys; print(json.dumps({'model': sys.argv[1], 'prompt': '', 'keep_alive': 0, 'stream': False}))" "$name")" \
    > /dev/null
done
sleep 3
echo "  いまの VRAM: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

# ---------------------------------------------------------------- 計測
echo
echo "[3/5] 生成して測る（トークン数 $num_predict）"

if [ -n "$prompt_file" ]; then
  prompt_text="$(cat -- "$prompt_file")"
else
  prompt_text="日本の四季について、それぞれの特徴を 1 文ずつで説明してください。"
fi

sampler_pid=""
sample_file="$(mktemp /tmp/bench-samples-XXXXXX.tsv)"
cleanup() {
  [ -n "$sampler_pid" ] && kill "$sampler_pid" 2>/dev/null || true
  rm -f "$sample_file"
}
trap cleanup EXIT

# 1 秒ごとに VRAM・RAM・swap・メモリ待ちを記録する。GPU 使用率が 0% でも詰まっている場合を拾うため。
(
  while true
  do
    vram="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null || echo 0)"
    read -r ram_used swap_used <<< "$(free -m | awk '/^Mem:/{m=$3} /^Swap:/{s=$3} END{print m, s}')"
    pressure="$(awk '/^full/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){sub("avg10=","",$i); print $i}}' /proc/pressure/memory 2>/dev/null || echo 0)"
    printf '%s\t%s\t%s\t%s\n' "$vram" "$ram_used" "$swap_used" "$pressure" >> "$sample_file"
    sleep 1
  done
) &
sampler_pid=$!

request_body="$(/usr/bin/python3 -c "
import json, sys
print(json.dumps({
    'model': sys.argv[1],
    'prompt': sys.argv[2],
    'stream': False,
    'options': {'num_predict': int(sys.argv[3])},
}))" "$model_name" "$prompt_text" "$num_predict")"

response_file="$(mktemp /tmp/bench-response-XXXXXX.json)"
start_epoch="$(date +%s)"
http_code="$(curl -s -m 3600 -o "$response_file" -w "%{http_code}" "$OLLAMA_URL/api/generate" -d "$request_body")"
elapsed_sec=$(( $(date +%s) - start_epoch ))

kill "$sampler_pid" 2>/dev/null || true
sampler_pid=""

if [ "$http_code" != "200" ]; then
  echo "生成に失敗しました（HTTP $http_code）:" >&2
  head -c 500 "$response_file" >&2; echo >&2
  rm -f "$response_file"
  exit 1
fi

# ---------------------------------------------------------------- GPU 配置率
echo
echo "[4/5] GPU 配置率"
ps_file="$(mktemp /tmp/bench-ps-XXXXXX.json)"
curl -s -m 10 "$OLLAMA_URL/api/ps" -o "$ps_file"

# ---------------------------------------------------------------- まとめ
echo
echo "[5/5] 結果"
timestamp="$(date +%Y%m%d_%H%M%S)"
safe_name="$(printf '%s' "$model_name" | tr '/:' '__')"
result_path="$RESULTS_DIR/${safe_name}-${timestamp}.json"
mkdir -p "$RESULTS_DIR"

/usr/bin/python3 - "$model_name" "$response_file" "$ps_file" "$sample_file" "$result_path" \
  "$elapsed_sec" "$MIN_USABLE_TOKENS_PER_SEC" "$MAX_USABLE_MEMORY_PRESSURE" <<'PYEOF'
import json, sys
from pathlib import Path

(model_name, response_path, ps_path, sample_path, result_path,
 elapsed_sec, min_tokens_per_sec, max_pressure) = sys.argv[1:9]
min_tokens_per_sec = float(min_tokens_per_sec)
max_pressure = float(max_pressure)

response = json.loads(Path(response_path).read_text(encoding="utf-8"))
eval_count = response.get("eval_count") or 0
eval_duration_sec = (response.get("eval_duration") or 0) / 1e9
load_duration_sec = (response.get("load_duration") or 0) / 1e9
tokens_per_sec = eval_count / eval_duration_sec if eval_duration_sec > 0 else 0.0

placement = {"size_bytes": 0, "size_vram_bytes": 0, "gpu_percent": None}
for entry in json.loads(Path(ps_path).read_text(encoding="utf-8")).get("models", []):
    if entry.get("name") == model_name:
        total = entry.get("size") or 0
        vram = entry.get("size_vram") or 0
        placement = {
            "size_bytes": total,
            "size_vram_bytes": vram,
            "gpu_percent": round(100 * vram / total) if total else None,
        }

peaks = {"vram_mib": 0, "ram_mib": 0, "swap_mib": 0, "memory_pressure_full_max": 0.0,
         "memory_pressure_full_mean": 0.0, "samples": 0}
pressures = []
for line in Path(sample_path).read_text(encoding="utf-8").splitlines():
    fields = line.split("\t")
    if len(fields) != 4:
        continue
    try:
        vram, ram, swap, pressure = int(fields[0]), int(fields[1]), int(fields[2]), float(fields[3])
    except ValueError:
        continue
    peaks["vram_mib"] = max(peaks["vram_mib"], vram)
    peaks["ram_mib"] = max(peaks["ram_mib"], ram)
    peaks["swap_mib"] = max(peaks["swap_mib"], swap)
    pressures.append(pressure)
if pressures:
    peaks["memory_pressure_full_max"] = round(max(pressures), 2)
    peaks["memory_pressure_full_mean"] = round(sum(pressures) / len(pressures), 2)
    peaks["samples"] = len(pressures)

reasons = []
if tokens_per_sec < min_tokens_per_sec:
    reasons.append(f"生成が {tokens_per_sec:.1f} tok/s で、目安の {min_tokens_per_sec:.0f} tok/s を下回る")
if peaks["memory_pressure_full_mean"] > max_pressure:
    reasons.append(
        f"メモリ待ちの割合が平均 {peaks['memory_pressure_full_mean']:.0f}% で、"
        f"目安の {max_pressure:.0f}% を超える"
    )
usable = not reasons

result = {
    "model": model_name,
    "tokens_per_sec": round(tokens_per_sec, 1),
    "eval_count": eval_count,
    "load_duration_sec": round(load_duration_sec, 1),
    "total_elapsed_sec": int(elapsed_sec),
    "placement": placement,
    "peaks": peaks,
    "usable": usable,
    "reasons": reasons,
}
Path(result_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

gpu_percent = placement["gpu_percent"]
size_gib = placement["size_bytes"] / 2**30
vram_gib = placement["size_vram_bytes"] / 2**30
print(f"  生成速度         {tokens_per_sec:.1f} tok/s（{eval_count} トークン）")
print(f"  ロード時間       {load_duration_sec:.1f} 秒")
print(f"  全体の所要時間   {elapsed_sec} 秒")
if gpu_percent is not None:
    print(f"  GPU 配置         {gpu_percent}%（{vram_gib:.1f} / {size_gib:.1f} GiB）")
else:
    print("  GPU 配置         取得できず（計測後に降りた可能性）")
print(f"  VRAM ピーク      {peaks['vram_mib']} MiB")
print(f"  RAM ピーク       {peaks['ram_mib']} MiB")
print(f"  swap ピーク      {peaks['swap_mib']} MiB")
print(f"  メモリ待ち       平均 {peaks['memory_pressure_full_mean']:.0f}% / 最大 "
      f"{peaks['memory_pressure_full_max']:.0f}%（{peaks['samples']} 秒ぶん）")
print()
if usable:
    print("  判定: 実用になる")
else:
    print("  判定: 実用外")
    for reason in reasons:
        print(f"    - {reason}")
print()
print(f"  記録: {result_path}")
PYEOF

rm -f "$response_file" "$ps_file"

if ! $keep_loaded; then
  echo
  echo "計測したモデルを降ろします（残すには --keep）"
  curl -s -m 60 "$OLLAMA_URL/api/generate" \
    -d "$(/usr/bin/python3 -c "import json,sys; print(json.dumps({'model': sys.argv[1], 'prompt': '', 'keep_alive': 0, 'stream': False}))" "$model_name")" \
    > /dev/null
fi
