#!/usr/bin/env bash
# ~/.claude/skills/{qwen,qwen-read} を tools/local-ai-bridge/skills/<name> への
# シンボリックリンクとして作る。実体はこのリポジトリの中にだけ置く。
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
SKILLS_SRC="$HERE/skills"
SKILLS_DST="$HOME/.claude/skills"
NAMES=(qwen qwen-read)

usage() {
  cat <<EOF
使い方: $0 [--uninstall]

  --uninstall  張ったシンボリックリンクだけを外す（実体ディレクトリは触らない）

対象: $SKILLS_DST/{qwen,qwen-read} <- $SKILLS_SRC/{qwen,qwen-read}
EOF
}

UNINSTALL=false
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) UNINSTALL=true; shift ;;
    --help) usage; exit 0 ;;
    *) echo "不明な指定: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$SKILLS_DST"

status=0
for name in "${NAMES[@]}"; do
  src="$SKILLS_SRC/$name"
  dst="$SKILLS_DST/$name"

  if $UNINSTALL; then
    if [ -L "$dst" ]; then
      rm -f "$dst"
      echo "外した: $dst"
    elif [ -e "$dst" ]; then
      echo "スキップ（シンボリックリンクではない。実体は触らない）: $dst" >&2
      status=1
    else
      echo "変更なし（元から無い）: $dst"
    fi
    continue
  fi

  if [ ! -d "$src" ]; then
    echo "実体が見つかりません: $src" >&2
    status=1
    continue
  fi

  if [ -L "$dst" ]; then
    current="$(readlink -f -- "$dst")"
    wanted="$(readlink -f -- "$src")"
    if [ "$current" = "$wanted" ]; then
      echo "変更なし: $dst -> $src"
    else
      echo "既に別の先を指すリンクがあります。上書きしません: $dst -> $current（期待: $src）" >&2
      status=1
    fi
    continue
  fi

  if [ -e "$dst" ]; then
    echo "既にファイル／ディレクトリがあります。上書きしません: $dst" >&2
    status=1
    continue
  fi

  ln -s "$src" "$dst"
  echo "リンクしました: $dst -> $src"
done

exit "$status"
