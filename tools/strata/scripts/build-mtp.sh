#!/usr/bin/env bash
# MTP の draft 層（投機デコード用）を models/mtp/rt に作る（冪等。できていれば何もしない）。
#
# RVN の pack は MTP を含まない。上流 setup.py と同じく、元の BF16 チェックポイント（Qwen/Qwen3.8-Flash-Next、
# 固定コミット、tools/mtp_fetch.py の PINNED_REVISION）から mtp.* のテンソル約 5 GB だけを HTTP の範囲取得で取り、
# Q2_0 のエキスパートに詰めて engine が読む形（rt/）にする（setup.py:4744-4760 と同じ 3 段）。
# 取得したテンソルは mtp_fetch.py が固定コミットの sha256 で確かめる。
set -euo pipefail

TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$TOOL_DIR/.venv/bin/python"
STRATA_DIR="$TOOL_DIR/vendor/Strata"
MTP_DIR="$TOOL_DIR/models/mtp"
RT_DIR="$MTP_DIR/rt"
LOG_DIR="$TOOL_DIR/logs"

if [ ! -x "$PYTHON" ] || [ ! -d "$STRATA_DIR/tools" ]; then
  echo "venv か vendor/Strata がありません。先に setup-server.sh を実行してください。" >&2
  exit 1
fi
mkdir -p "$MTP_DIR" "$LOG_DIR"

# 上流の tools/_paths.py が third_party/llama.cpp/gguf-py を見つける（setup-server.sh が取得済み）。
run_step() {
  # $1=表示名 $2=ログ名 以降=コマンド
  local label="$1" log_name="$2"
  shift 2
  local log_file="$LOG_DIR/$log_name"
  echo "  $label（ログ: $log_file）"
  if ! "$@" > "$log_file" 2>&1; then
    echo "  $label に失敗しました。$log_file を確認してください" >&2
    exit 1
  fi
}

if [ -f "$RT_DIR/experts.bin" ] && "$PYTHON" "$STRATA_DIR/tools/mtp_fetch.py" verify --out "$MTP_DIR" > "$LOG_DIR/mtp-verify.log" 2>&1; then
  echo "MTP の draft 層: 既にあります（$RT_DIR、テンソルの sha256 も一致）"
else
  run_step "MTP のテンソルを取得（約 5 GB、範囲取得、途中から再開できる）" mtp-fetch.log \
    "$PYTHON" "$STRATA_DIR/tools/mtp_fetch.py" fetch --out "$MTP_DIR"
  run_step "Q2_0 のエキスパートで GGUF に詰める" mtp-pack.log \
    "$PYTHON" "$STRATA_DIR/tools/mtp_pack.py" --src "$MTP_DIR" --experts q2_0 --out "$MTP_DIR/mtp-q2_0.gguf"
  run_step "engine が読む形（rt/）にする" mtp-rt.log \
    "$PYTHON" "$STRATA_DIR/tools/mtp_rt.py" --gguf "$MTP_DIR/mtp-q2_0.gguf" --out "$RT_DIR"
  echo "MTP の draft 層: 作りました（$RT_DIR）"
fi

# draft が提案できるトークンの部分集合。上流の既定（setup.py の refresh_draft_vocab、"cjk"）と同じく、
# 日本語・中国語・韓国語のトークンを含む data/draft_vocab.bin を置く（手で置いたものは上書きしない）。
if [ ! -f "$RT_DIR/draft_vocab.bin" ]; then
  cp -p "$STRATA_DIR/data/draft_vocab.bin" "$RT_DIR/draft_vocab.bin"
  echo "draft の語彙: data/draft_vocab.bin（CJK 込み）を置きました"
else
  echo "draft の語彙: 既にあります（$RT_DIR/draft_vocab.bin）"
fi
