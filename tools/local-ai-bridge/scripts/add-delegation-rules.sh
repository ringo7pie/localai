#!/usr/bin/env bash
# CLAUDE.md / AGENTS.md へ委譲ルールを「管理ブロック」として追記する。
# 既存内容は書き換えない。再実行しても重複しない（ブロックを差し替える）。
set -euo pipefail

BEGIN='<!-- local-ai-bridge:begin 管理対象: このブロックのみ -->'
END='<!-- local-ai-bridge:end -->'

SHORT=false

usage() {
  cat <<EOF
使い方: $0 [--short] <対象ファイル> [<対象ファイル> ...]

  --short  行数に予算があるファイル向けの短い版を入れる（詳細は README.ja.md を指す）

例:
  $0 --short ~/.claude/CLAUDE.md
  $0 ~/.codex/AGENTS.md
EOF
}

while [ $# -gt 0 ] && [ "${1#--}" != "$1" ]; do
  case "$1" in
    --short) SHORT=true; shift ;;
    --help)  usage; exit 0 ;;
    *) echo "不明な指定: $1" >&2; usage; exit 2 ;;
  esac
done

[ $# -ge 1 ] || { usage; exit 2; }

BLOCK=$(cat <<'EOF'
## ローカル実装の委譲（local-ai-bridge MCP）

作業 PC の OpenCode 経由で、A30 サーバーのローカル Qwen へ実装を委譲できる。
ツールは `submit_task`（受付。task_id を返す）、`get_task_status`、`get_task_result`、
`get_artifact`、`cancel_task`、`resume_task`、`bridge_doctor`。

- 実装、局所修正、テスト追加はローカルへの委譲を優先する
- 委譲する前に、目的・変更可能範囲・変更禁止事項・合格条件を渡す。
  全ソースを読んでから渡すのではなく、先に条件を決めて渡す
- 結果確認では `get_task_result` の要約を見て、必要な差分だけ `get_artifact` で取る
- ローカルの失敗を無限に再投入しない。`failed` が 2 回続いたら引き取る
- 細かい進捗確認を繰り返さない。`get_task_status` の間隔は 30 秒以上を目安にする
- 小さすぎる仕事（1 行の typo など）や、難しくて引き取る仕事は、その理由を書く
- 差分の適用・commit・push は親が行う。ワーカーは適用しない

このルールを書いただけで自動的に委譲される保証はない。判断は都度行う。
推論はローカルだが、返ってくる要約と差分はクラウドへ送られる。
EOF
)

if $SHORT; then
BLOCK=$(cat <<'EOF'
## ローカル実装の委譲（local-ai-bridge MCP。管理対象: このブロックのみ）

- 実装・局所修正・テスト追加は `submit_task` で作業 PC の OpenCode 経由ローカル Qwen へ委譲する
- 委譲時に目的・変更可能範囲・変更禁止事項・合格条件を渡す。親の会話全体は渡さない
- `submit_task` は受付だけ。`get_task_status` の間隔は 30 秒以上。細かい進捗確認を繰り返さない
- 結果は `get_task_result` の要約を見て、必要な差分だけ `get_artifact` で取る
- `failed` が 2 回続いたら親が引き取り、その理由を書く。無限に再投入しない
- 差分の適用・commit・push は親が行う。ワーカーは適用しない
- 詳細は `~/Proj/localai/tools/local-ai-bridge/README.ja.md`
EOF
)
fi

for target in "$@"; do
  mkdir -p "$(dirname "$target")"
  if [ -f "$target" ]; then
    backup="$target.$(date +%Y%m%d-%H%M%S).bak"
    cp -p "$target" "$backup"
    echo "退避: $backup"
    if grep -qF "$BEGIN" "$target"; then
      # 既存ブロックを差し替える（重複させない）
      python3 - "$target" "$BEGIN" "$END" "$BLOCK" <<'PY'
import sys, pathlib
target, begin, end, block = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = pathlib.Path(target).read_text(encoding="utf-8")
head, _, rest = text.partition(begin)
_, _, tail = rest.partition(end)
pathlib.Path(target).write_text(f"{head}{begin}\n{block}\n{end}{tail}", encoding="utf-8")
print("既存ブロックを差し替えました")
PY
      continue
    fi
    printf '\n%s\n%s\n%s\n' "$BEGIN" "$BLOCK" "$END" >> "$target"
    echo "追記しました: $target"
  else
    printf '%s\n%s\n%s\n' "$BEGIN" "$BLOCK" "$END" > "$target"
    echo "新規作成しました: $target"
  fi
done
