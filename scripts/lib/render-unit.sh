# shellcheck shell=bash
# 雛形（systemd ユニット・設定ファイル）の @REPO_ROOT@ を、このリポジトリの絶対パスに置き換えて書き出す。
# 各ツールの setup-server.sh が source して、雛形の cp -p の代わりに使う。
#
# 使い方:
#   source "<リポジトリ>/scripts/lib/render-unit.sh"
#   render_unit_file <雛形> <出力先>     # 出力先へ書く。mode は雛形と同じにする
#   render_unit_text <雛形>              # 置き換えた中身を標準出力へ（既存のファイルとの比較用）
#
# リポジトリの位置はこのファイルの場所から決める（symlink はたどって実体のパスにする）。
# clone した場所がどこでも、ユニットはそのパスを指す。

# このファイルは scripts/lib/ にあるので、2 つ上がリポジトリの根。
# readlink -f でファイル自身の symlink を、cd -P / pwd -P で途中のディレクトリの symlink を実体に直す。
LOCALAI_REPO_ROOT="$(cd -P -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd -P)"

# 雛形の @REPO_ROOT@ を置き換えた中身を標準出力へ書く。
# 置き換えは awk の index/substr で文字どおりに行う。sed の s/// や bash の ${var//} は
# パスに | & \ が入ると区切りや「一致した部分」と解釈されてこわれるため使わない。
# 置き換える値は -v ではなく ENVIRON で渡す（-v は \ をエスケープとして解釈するため）。
render_unit_text() {
  if [ "$#" -ne 1 ]; then
    echo "使い方: render_unit_text <雛形>" >&2
    return 2
  fi
  local template_file="$1"
  if [ ! -f "$template_file" ]; then
    echo "エラー: 雛形が見つかりません: $template_file" >&2
    return 1
  fi
  LOCALAI_RENDER_REPO_ROOT="$LOCALAI_REPO_ROOT" awk '
    BEGIN {
      placeholder = "@REPO_ROOT@"
      replacement = ENVIRON["LOCALAI_RENDER_REPO_ROOT"]
    }
    {
      rest = $0
      rendered = ""
      while ((position = index(rest, placeholder)) > 0) {
        rendered = rendered substr(rest, 1, position - 1) replacement
        rest = substr(rest, position + length(placeholder))
      }
      print rendered rest
    }
  ' "$template_file"
}

# 雛形を置き換えて出力先へ書く。途中で失敗しても半端なファイルを残さないよう、
# 同じディレクトリの一時ファイルに書いてから mv で差し替える。mode は雛形に合わせる（cp -p と同じ）。
# 「既にあれば上書きしない」かどうかは呼び出し側で決める（この関数は常に書く）。
render_unit_file() {
  if [ "$#" -ne 2 ]; then
    echo "使い方: render_unit_file <雛形> <出力先>" >&2
    return 2
  fi
  local template_file="$1"
  local output_file="$2"
  if [ ! -f "$template_file" ]; then
    echo "エラー: 雛形が見つかりません: $template_file" >&2
    return 1
  fi
  # systemd はユニットの中の空白・%・\・引用符を特別に扱う（引数の区切り・指定子・エスケープ）。
  # 置き換え自体はこわれないが、ユニットとして読まれたときに意図と違うパスになりうるので知らせる。
  case "$LOCALAI_REPO_ROOT" in
    *[[:space:]%\\\"\']*)
      echo "警告: リポジトリのパスに空白・%・\\・引用符が含まれます（$LOCALAI_REPO_ROOT）。" >&2
      echo "  systemd のユニットでは正しく読まれないことがあります。$output_file を確かめてください。" >&2
      ;;
  esac
  local temp_file
  temp_file="$(mktemp "$output_file.XXXXXX")" || return 1
  if ! render_unit_text "$template_file" > "$temp_file"; then
    rm -f -- "$temp_file"
    return 1
  fi
  if ! chmod --reference="$template_file" -- "$temp_file"; then
    rm -f -- "$temp_file"
    return 1
  fi
  if ! mv -f -- "$temp_file" "$output_file"; then
    rm -f -- "$temp_file"
    return 1
  fi
}
