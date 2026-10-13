#!/usr/bin/env bash
# GitHub Pages に載せるサイトを 1 つのディレクトリに組み立てる。
#
#   docs/site/       → <出力先>/            （サイトの本体。index.html はここから）
#   Documents/*.html → <出力先>/reports/    （評価レポート・調査書。相対リンクを保つため同じ階層に置く）
#   docs/images/     → <出力先>/images/
#   .nojekyll        → <出力先>/            （Jekyll に処理させない）
#
# 元のディレクトリが無ければ飛ばす（docs/site/ はあとから足す）。docs/site/index.html が無いときは、
# reports/ の一覧だけの簡単な index.html を作る（Pages のルートが 404 にならないように）。
#
# 使い方: scripts/build-site.sh <出力先>
#   出力先は無いか空のディレクトリであること（既存の中身は消さない）。
#   GitHub Actions（.github/workflows/pages.yml）も、手元の確認もこれを使う。
set -euo pipefail

SCRIPT_DIR="$(cd -P -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd -P)"
REPO_ROOT="$(cd -P -- "$SCRIPT_DIR/.." && pwd -P)"

usage() {
  cat <<EOF
使い方: $(basename -- "$0") <出力先>

  docs/site/ を出力先のルートに、Documents/*.html を reports/ に、docs/images/ を images/ に集めて
  GitHub Pages 用のサイトを作る。出力先は無いか、空のディレクトリであること。
  -h, --help  この説明を表示して終了
EOF
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi
case "$1" in
  -h | --help)
    usage
    exit 0
    ;;
esac

OUTPUT_DIR="$1"
if [ -z "$OUTPUT_DIR" ]; then
  echo "エラー: 出力先が空です。" >&2
  exit 2
fi

# 出力先の中身は消さない。空でないディレクトリは、取り違えて上書きしないよう断る。
if [ -e "$OUTPUT_DIR" ] && [ ! -d "$OUTPUT_DIR" ]; then
  echo "エラー: 出力先がディレクトリではありません: $OUTPUT_DIR" >&2
  exit 2
fi
if [ -d "$OUTPUT_DIR" ] && [ -n "$(ls -A -- "$OUTPUT_DIR")" ]; then
  echo "エラー: 出力先が空ではありません: $OUTPUT_DIR（消してから再実行してください）" >&2
  exit 2
fi
# 作る前に絶対パスへ直し（readlink -m は存在しないパスも扱える）、元のファイルを巻き込む場所への出力を断る。
OUTPUT_DIR="$(readlink -m -- "$OUTPUT_DIR")"

SITE_DIR="$REPO_ROOT/docs/site"
IMAGES_DIR="$REPO_ROOT/docs/images"
REPORTS_SRC_DIR="$REPO_ROOT/Documents"

# リポジトリ自身（や、その外側のディレクトリ）への出力は、元のファイルを巻き込むので断る。
case "$REPO_ROOT/" in
  "$OUTPUT_DIR"/*)
    echo "エラー: 出力先がリポジトリを含んでいます: $OUTPUT_DIR" >&2
    exit 2
    ;;
esac
# 元のディレクトリの中への出力は、コピーが自分自身を巻き込むので断る。
case "$OUTPUT_DIR/" in
  "$SITE_DIR"/* | "$IMAGES_DIR"/* | "$REPORTS_SRC_DIR"/*)
    echo "エラー: 出力先が元のディレクトリの中です: $OUTPUT_DIR" >&2
    exit 2
    ;;
esac
mkdir -p -- "$OUTPUT_DIR"

echo "== サイトを組み立てる =="
echo "出力先: $OUTPUT_DIR"

# 1. サイト本体（隠しファイルも含めてルートへ）
if [ -d "$SITE_DIR" ]; then
  cp -R -- "$SITE_DIR"/. "$OUTPUT_DIR"/
  echo "docs/site/ → /"
else
  echo "docs/site/ が無いので飛ばします"
fi

# 2. レポート（Documents 直下の *.html だけ。入れ子のディレクトリ・Markdown は載せない）
REPORT_COUNT=0
if [ -d "$REPORTS_SRC_DIR" ]; then
  mkdir -p -- "$OUTPUT_DIR/reports"
  for report_file in "$REPORTS_SRC_DIR"/*.html
  do
    if [ ! -f "$report_file" ]; then
      continue
    fi
    cp -- "$report_file" "$OUTPUT_DIR/reports/"
    REPORT_COUNT=$((REPORT_COUNT + 1))
  done
  echo "Documents/*.html → /reports/（$REPORT_COUNT 件）"
else
  echo "Documents/ が無いので飛ばします"
fi

# 3. 画像
if [ -d "$IMAGES_DIR" ]; then
  mkdir -p -- "$OUTPUT_DIR/images"
  cp -R -- "$IMAGES_DIR"/. "$OUTPUT_DIR/images"/
  echo "docs/images/ → /images/"
else
  echo "docs/images/ が無いので飛ばします"
fi

# 4. Jekyll を通さない（_ で始まるファイル名や、日本語のファイル名をそのまま配るため）
: > "$OUTPUT_DIR/.nojekyll"

# 5. index.html が無ければ、reports/ の一覧だけのページを作る。タイトルは各 HTML の <title> から取る。
if [ ! -f "$OUTPUT_DIR/index.html" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "エラー: index.html が無く、python3 も無いので一覧ページを作れません。" >&2
    exit 1
  fi
  python3 -I - "$OUTPUT_DIR" <<'PY'
import html
import re
import sys
import urllib.parse
from pathlib import Path

output_dir = Path(sys.argv[1])
items = []
reports_dir = output_dir / "reports"
if reports_dir.is_dir():
    for report_path in sorted(reports_dir.glob("*.html")):
        head = report_path.read_text(encoding="utf-8", errors="replace")[:20000]
        match = re.search(r"<title>(.*?)</title>", head, re.IGNORECASE | re.DOTALL)
        title = html.unescape(match.group(1)).strip() if match else report_path.stem
        link = "reports/" + urllib.parse.quote(report_path.name)
        items.append(f'<li><a href="{link}">{html.escape(title)}</a></li>')

body = "\n".join(items) if items else "<li>公開しているレポートはありません。</li>"
page = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>localai</title>
<style>body{{font-family:system-ui,sans-serif;max-width:48rem;margin:2rem auto;padding:0 1rem;line-height:1.7}}</style>
</head>
<body>
<h1>localai</h1>
<p>NVIDIA A30 1 枚でローカル LLM を動かす環境の、評価レポートと調査書。</p>
<ul>
{body}
</ul>
</body>
</html>
"""
(output_dir / "index.html").write_text(page, encoding="utf-8")
PY
  echo "index.html: docs/site/index.html が無いので、reports/ の一覧を作りました"
fi

FILE_COUNT="$(find "$OUTPUT_DIR" -type f | wc -l)"
echo "完了: $FILE_COUNT ファイル"
