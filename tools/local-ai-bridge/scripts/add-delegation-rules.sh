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

**呼び方は 1 つだけ**: `run_task`（MCP）を **1 回**呼ぶ。
MCP が見えない会話では Bash から
`run-local-ai-task run ... --max-wait 540` を **1 回**だけ呼ぶ
（Bash ツールの 600 秒上限の内側に収める）。
どちらも 委譲 → 完了待ち → 判定 → 適用 → 再検証 → 要約 を 1 回で行う。
`submit` / `status` / `wait` / `get_artifact` を親が個別に叩かない。
分けて叩くと親のターンが積み上がり、長い会話では単独で直すより高くつく。

**委譲してよい仕事**（**両方**を満たすときだけ）

- **親の文脈が大きい**（会話が長く、1 ターンの読み直しが高い）
- **クラウド単独でやると 4 ターン以上**かかると見込める

新しい短い会話や、1 行〜1 ファイルの極小の修正は、**親が直すほうが安い**。
実測で B/A は 0.8〜1.15（委譲が高いこともある）だった。
効くのは「親のターン数を 2 に固定できる」ときだけで、「委譲＝常に安い」ではない。
委譲しない判断も書き残す。

**渡すもの**: workspace、目的、変更可能範囲、変更禁止事項、合格条件、検証プロファイル。
親の会話全体は渡さない。全ソースを読んでから渡すのではなく、先に条件を決めて渡す。

**差分の適用**: 判定に合格したときだけ one-shot が作業ツリーへ適用し、再検証まで行う。
**commit / push / stash / reset はしない。** 返ってきた要約を鵜呑みにせず、
最後は人が `git diff` を自分の目で見る。

**qwen-worker との使い分け**: qwen-worker（`qwen_research` / `qwen_implement`）は
サーバー上のコードを読み取り専用で調べる・その場で実装させる用、
local-ai-bridge は手元の作業ツリーで実装しテストまで回す用。

**Claude Code からは**: 実装の委譲は `/qwen <依頼>`、大きなソースの調査は `/qwen-read <調べること>`
というスキルを使う。**Codex には Claude Code のスキル機構が無いので**、
上の `run_task`（MCP）を直接 **1 回**呼ぶ。

このルールを書いただけで自動的に委譲される保証はない。判断は都度行う。
推論はローカルだが、返ってくる要約と差分はクラウドへ送られる。
詳細は `~/Proj/localai/tools/local-ai-bridge/README.ja.md`。
EOF
)

if $SHORT; then
BLOCK=$(cat <<'EOF'
## ローカル実装の委譲（local-ai-bridge MCP。管理対象: このブロックのみ）

- 委譲は `run_task`（MCP）か `local-ai-task run ... --max-wait 540`（Bash）を **1 回**呼ぶ。委譲→待ち→判定→適用→再検証まで 1 回で終わる
- `submit` / `status` / `wait` を親が個別に叩かない。ターンが積み上がって高くつく
- 委譲するのは **親の文脈が大きく（会話が長く）かつ単独で 4 ターン以上**の仕事だけ
- 新しい短い会話や極小の修正は親が直すほうが安い（実測 B/A 0.8〜1.15）。「委譲＝常に安い」ではない
- 実装の委譲は `/qwen <依頼>`（Claude Code）。大きなソースの調査は `/qwen-read`。Codex は MCP `run_task` を直接 1 回
- 渡すのは workspace・目的・変更可能範囲・変更禁止事項・合格条件だけ。親の会話全体は渡さない
- 適用は判定に合格したときだけ one-shot が行う。commit / push はしない。最後は人が `git diff` を見る
- qwen-worker（`qwen_research` / `qwen_implement`）はサーバー上を読み取り専用で調べる・その場で実装させる用、local-ai-bridge は手元の作業ツリーで実装しテストまで回す用
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
