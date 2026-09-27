#!/usr/bin/env bash
# HuggingFace の分割 GGUF を落として結合し、Ollama に取り込む（Open WebUI で選べるようにする）。
#
# 使い方: import-hf-gguf.sh <HF リポジトリ> <量子化のフォルダ名> <Ollama での名前> [オプション]
#   --template-from 名前  RENDERER / PARSER / TEMPLATE / PARAMETER / LICENSE を写す元の Ollama モデル
#   -h, --help            この説明を表示して終了
#
# 例: import-hf-gguf.sh bartowski/Qwen3.8-Flash-Next-GGUF Qwen3.8-Flash-Next-IQ1_M \
#       qwen3.8-flash-next:125b-a6b-IQ1_M --template-from qwen3.8-flash-next:125b-a6b-q4_K_M
#
# Ollama は HuggingFace の分割 GGUF を直接 pull できない（HF が「分割ファイルを落として手元で結合し、
# ollama create で取り込め」と返す）。そのため 落とす → 結合 → 取り込む → 作業ファイルを消す を行う。
# ディスクは一時的に「モデルの大きさ × 2」要る（結合後のファイルと、Ollama が複製する実体）。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
LLAMA_DIR="$TOOL_DIR/bin/llama-b11146"
GGUF_SPLIT="$LLAMA_DIR/llama-gguf-split"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

template_from=""
positional=()
while [ $# -gt 0 ]
do
  case "$1" in
    --template-from) template_from="${2:?--template-from にはモデル名が要る}"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "不明な引数: $1" >&2; exit 2 ;;
    *) positional+=("$1"); shift ;;
  esac
done
if [ "${#positional[@]}" -ne 3 ]; then
  echo "引数は 3 つ要ります: <HF リポジトリ> <量子化のフォルダ名> <Ollama での名前>" >&2
  exit 2
fi
hf_repo="${positional[0]}"
quant_folder="${positional[1]}"
ollama_name="${positional[2]}"

safe_name="$(printf '%s' "$ollama_name" | tr '/:' '__')"
work_dir="$TOOL_DIR/work/$safe_name"

echo "== $ollama_name を取り込む（$hf_repo / $quant_folder） =="

# ---------------------------------------------------------------- [1/6]
echo
echo "[1/6] 前提の確認"
if ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qxF "$ollama_name"; then
  echo "既にあります: $ollama_name（何もしません）"
  exit 0
fi
if [ ! -x "$GGUF_SPLIT" ]; then
  echo "結合ツールがありません: $GGUF_SPLIT" >&2
  echo "README.md の「結合ツールの入れ方」を見てください。" >&2
  exit 1
fi
if [ -n "$template_from" ] && ! ollama show "$template_from" >/dev/null 2>&1; then
  echo "写し元のモデルがありません: $template_from" >&2
  exit 1
fi

size_bytes="$(curl -s -m 30 "https://huggingface.co/api/models/$hf_repo?blobs=true" | /usr/bin/python3 -c "
import json, sys
folder = sys.argv[1]
data = json.load(sys.stdin)
print(sum((s.get('size') or 0) for s in data.get('siblings', [])
          if s['rfilename'].startswith(folder + '/') and s['rfilename'].endswith('.gguf')))
" "$quant_folder")"
if [ "$size_bytes" -le 0 ]; then
  echo "そのフォルダに GGUF がありません: $hf_repo / $quant_folder" >&2
  exit 1
fi
need_bytes=$(( size_bytes * 2 + 10 * 1024 * 1024 * 1024 ))
free_bytes="$(df -B1 --output=avail "$TOOL_DIR" | tail -1)"
printf '大きさ: %.1f GiB / 必要な空き: %.1f GiB / いまの空き: %.1f GiB\n' \
  "$(echo "$size_bytes / 1073741824" | bc -l)" "$(echo "$need_bytes / 1073741824" | bc -l)" \
  "$(echo "$free_bytes / 1073741824" | bc -l)"
if [ "$free_bytes" -lt "$need_bytes" ]; then
  echo "ディスクの空きが足りません。" >&2
  exit 1
fi

# ---------------------------------------------------------------- [2/6]
echo
echo "[2/6] 分割ファイルを落とす（$work_dir）"
mkdir -p "$work_dir"
"$UV_BIN" run --quiet --no-project --with huggingface_hub python - "$hf_repo" "$quant_folder" "$work_dir" <<'PYEOF'
import sys
from huggingface_hub import snapshot_download
repo, folder, target = sys.argv[1:4]
snapshot_download(repo_id=repo, allow_patterns=[f"{folder}/*.gguf"], local_dir=target)
PYEOF
mapfile -t shards < <(find "$work_dir/$quant_folder" -name '*.gguf' | sort)
echo "分割ファイル: ${#shards[@]} 個"
if [ "${#shards[@]}" -eq 0 ]; then echo "GGUF を落とせませんでした" >&2; exit 1; fi

# ---------------------------------------------------------------- [3/6]
echo
echo "[3/6] 結合する"
merged="$work_dir/merged.gguf"
if [ "${#shards[@]}" -eq 1 ]; then
  mv -- "${shards[0]}" "$merged"
else
  LD_LIBRARY_PATH="$LLAMA_DIR" "$GGUF_SPLIT" --merge "${shards[0]}" "$merged"
fi
rm -rf -- "${work_dir:?}/$quant_folder" "$work_dir/.cache"
printf '結合後: %.1f GiB\n' "$(echo "$(stat -c %s "$merged") / 1073741824" | bc -l)"

# ---------------------------------------------------------------- [4/6]
echo
echo "[4/6] Modelfile を作る"
modelfile="$work_dir/Modelfile"
printf 'FROM %s\n' "$merged" > "$modelfile"
if [ -n "$template_from" ]; then
  # 写すのは会話の扱い（RENDERER / PARSER / TEMPLATE）と既定のパラメータとライセンス。FROM は写さない。
  ollama show --modelfile "$template_from" | /usr/bin/python3 -c "
import sys
lines = sys.stdin.read().splitlines()
keep, inside_block = [], False
for line in lines:
    if inside_block:
        keep.append(line)
        if line.rstrip().endswith('\"\"\"'): inside_block = False
        continue
    head = line.split(' ', 1)[0]
    if head in ('RENDERER', 'PARSER', 'TEMPLATE', 'PARAMETER', 'LICENSE', 'SYSTEM'):
        keep.append(line)
        if line.count('\"\"\"') == 1: inside_block = True
print('\n'.join(keep))
" >> "$modelfile"
  echo "会話の扱いと既定値を写しました（写し元: $template_from）"
fi
grep -vE '^(LICENSE|Copyright|Permission|THE |1\.|2\.|"|“|For any|$)' "$modelfile" | sed 's/^/  /' | head -12

# ---------------------------------------------------------------- [5/6]
echo
echo "[5/6] Ollama に取り込む（Ollama が実体を複製する。時間がかかる）"
ollama create "$ollama_name" -f "$modelfile"

# ---------------------------------------------------------------- [6/6]
echo
echo "[6/6] 作業ファイルを消す"
rm -rf -- "${work_dir:?}"
echo "取り込みました: $ollama_name"
echo "Open WebUI の画面上部のモデル選択に出ます（出なければ再読み込み）。"
echo "この機体で実用になるかは: $TOOL_DIR/bench-model.sh $ollama_name --num-predict 300"
