# 英語版の問題文の対応表

`run_eval.py run --prompt-lang en` が送る英語版（`PREAMBLE.en.md`、`c4/prompt.en.md`、`c5/prompt.en.md`）は、日本語版
（`PREAMBLE.md`、`c4/prompt.md`、`c5/prompt.md`）の**忠実な英訳**。隠しテスト（`tests.py`）と採点は日本語版と同じで、変えていない。

訳し方の約束:

- 関数名・引数名・型注釈・数値・コードの例・例外の名前と条件・禁止事項（C4 は `json`、C5 は `re` など）は 1 字も変えない。
- 箇条書きの数・順番・入れ子は日本語版と同じ。見出し（`##`・`###`）も 1 対 1 で対応させた。
- 日本語版にある具体例の文字列（JSON の例、正規表現の例、Unicode のエスケープ、`"あ😀"`）はそのまま写した。
- 解説の言い回しを足したり、ヒントを増やしたり、条件を削ったりしていない。

## 確かめ方（機械でできる部分）

バッククォートで囲んだコード片（関数名・引数・数値・例・例外名）の集合が、日本語版と英語版で一致することを確かめる。
違うのは `float(その文字列)` → `float(that string)` の 1 か所だけ（コード片の中の日本語の仮名を訳した）。
並びが前後する所は語順の違いだけ（`True`・`^`・`ValueError` の位置）。

```bash
cd ~/Proj/localai/tools/model-eval/suites/coding
python3 - <<'PY'
import re
from collections import Counter
for ja, en in (("c4/prompt.md", "c4/prompt.en.md"), ("c5/prompt.md", "c5/prompt.en.md")):
    spans_ja = [s.replace("その文字列", "that string") for s in re.findall(r"`([^`]+)`", open(ja, encoding="utf-8").read())]
    spans_en = re.findall(r"`([^`]+)`", open(en, encoding="utf-8").read())
    print(ja, len(spans_ja), len(spans_en), Counter(spans_ja) == Counter(spans_en))
PY
```

## PREAMBLE（共通の指示）

| 日本語版 | 英語版 |
|---|---|
| 1 行目「次の仕様を満たす Python 3.12 のコードを書いてください。」 | "Write Python 3.12 code that satisfies the following specification." |
| 「守ること:」 | "Rules:" |
| 箇条書き 1「標準ライブラリだけを使う。外部のパッケージは使わない。」 | "Use only the standard library. Do not use any external packages." |
| 箇条書き 2「ファイルの読み書き、ネットワーク、サブプロセス、標準入力からの読み込みをしない。」 | "Do not read or write files, use the network, use subprocesses, or read from standard input." |
| 箇条書き 3「仕様にある関数名・クラス名・引数の名前をそのまま使う。」 | "Use the function names, class names, and argument names given in the specification exactly as they are." |
| 箇条書き 4「答えは ```python で始まるコードブロック 1 つだけにする。…ブロックの外の説明は要らない。」 | "Your answer must be exactly one code block that starts with ```python. … No explanation outside the block is needed." |

箇条書きは 4 つで同数。

## C4（厳密な JSON パーサ）

| 日本語版 | 英語版 |
|---|---|
| 見出し「問題 C4: 厳密な JSON パーサ」 | "Problem C4: Strict JSON parser" |
| 導入の段落（`parse_json(text: str) -> object`、RFC 8259、`json` 禁止で使うと 0 点） | 導入の段落（同じ関数名・型注釈、RFC 8259、`json` 禁止で "scores 0"） |
| 小見出し「文法」 | "Grammar" |
| 1「`text` 全体が『空白（0 個以上）、値 1 つ、空白（0 個以上）』でなければならない。…は `ValueError`」 | 1 "The whole of `text` must be "whitespace (zero or more), one value, whitespace (zero or more)". … is a `ValueError`." |
| 2「空白は半角スペース、`\t`、`\n`、`\r` の 4 種類だけ。`\f`、`\v`、ノーブレークスペース、先頭の BOM（U+FEFF）は…`ValueError`」 | 2 "Whitespace is only these 4 kinds: the ASCII space, `\t`, `\n`, and `\r`. `\f`, `\v`, the no-break space, and a leading BOM (U+FEFF) are not whitespace and are a `ValueError`." |
| 3「値は、オブジェクト、配列、文字列、数、`true`、`false`、`null` のいずれか。トップレベル…（`"abc"` や `42` だけでも正しい）」 | 3 "A value is one of: an object, an array, a string, a number, `true`, `false`, or `null`. The top-level value need not be … (`"abc"` or `42` alone is also valid)." |
| 4「リテラルは `true`、`false`、`null` の小文字だけ。`True`、`NULL`、`nul` は `ValueError`。`NaN`、`Infinity`、`-Infinity` も `ValueError`」 | 4 "The literals are only lowercase `true`, `false`, and `null`. `True`, `NULL`, and `nul` are a `ValueError`. `NaN`, `Infinity`, and `-Infinity` are also a `ValueError`." |
| 5「オブジェクト…`dict`。キーは必ず文字列。…末尾の余計な `,`（`{"a":1,}`）や空のメンバー（`{,}`）は `ValueError`。**同じキーが 2 回出てきたら `ValueError`**（エスケープを解いたあとの文字列として同じなら同じキー。…）」 | 5 "An object … becomes a Python `dict`. Keys must always be strings. … **If the same key appears twice, it is a `ValueError`** (keys are the same if they are the same string after escapes are decoded; …)" |
| 6「配列…`list`。末尾の余計な `,` や空の要素（`[1,,2]`、`[,1]`）は `ValueError`」 | 6 "An array … becomes a Python `list`. A trailing extra `,` or an empty element (`[1,,2]`, `[,1]`) is a `ValueError`." |
| 7「文字列は `"` で囲む（`'` は不可）。中で使えるエスケープは…だけ。それ以外のエスケープ（…桁の足りない…）は `ValueError`」 | 7 "A string is enclosed in `"` (`'` is not allowed). The only escapes allowed inside are … Any other escape (… with too few digits) is a `ValueError`." |
| 7 の入れ子 1「エスケープされていない制御文字（U+0000〜U+001F）があれば `ValueError`。U+007F 以降の文字（日本語や絵文字）はそのまま書いてよい」 | 7 の入れ子 1 "An unescaped control character (U+0000 to U+001F) inside a string is a `ValueError`. Characters from U+007F onward (such as Japanese text or emoji) may be written as they are." |
| 7 の入れ子 2「上位サロゲート…の直後に下位サロゲート…の `\u` エスケープが続くときは、合わせて 1 文字（U+1F600）。下位サロゲートだけ、…続かない、という場合は `ValueError`。`\u0000` は許される」 | 7 の入れ子 2 "When a high surrogate … is immediately followed by a `\u` escape of a low surrogate …, combine them into a single character (U+1F600 in this example). A low surrogate on its own, or a high surrogate that is not immediately followed by a low-surrogate escape, is a `ValueError`. `\u0000` is allowed (…)" |
| 8「数は `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?` の形だけ。…は `ValueError`。小数部か指数部があれば…`float(その文字列)`…、どちらも無ければ `int`（…`-0` は `int` の `0`）」 | 8 "A number must have exactly the form `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?`. … are a `ValueError`. If there is a fractional part or an exponent part, … `float(that string)` …; if there is neither, it is an `int` (… `-0` is the `int` `0`)." |
| 9「入れ子の深さは最大 50,000（…）。`text` の長さは最大 1,000,000 文字で、…（…`text = text[1:]`…では間に合わない）」 | 9 "The nesting depth is at most 50,000 (…). The length of `text` is at most 1,000,000 characters, and … (… `text = text[1:]` … will not be fast enough)." |
| 「例:」の 3 項目（`parse_json(' {"a": …} ')`、`parse_json('"…"')` → `"あ😀"`、`parse_json('[1, 2,]')` → `ValueError` を送出） | "Examples:" の 3 項目（式と結果は同じ文字列。3 つ目は "raises `ValueError`"） |

箇条書きは文法の 9 項（7 に入れ子 2 つ）と例の 3 項で、日本語版と同数・同順。

## C5（正規表現の部分集合のマッチャ）

| 日本語版 | 英語版 |
|---|---|
| 見出し「問題 C5: 正規表現の部分集合のマッチャ」 | "Problem C5: Matcher for a subset of regular expressions" |
| 導入の段落（`regex_search(pattern: str, text: str) -> bool`、空の部分文字列も含む、`re`・`sre_parse`・`sre_compile`・`_sre` 禁止で使うと 0 点） | 導入の段落（同じ関数名・型注釈、"including the empty substring"、同じ 4 つのモジュール名、"scores 0"） |
| 小見出し「パターンの文法」 | "Pattern grammar" |
| 1「文字: 普通の文字はその文字そのものに一致する。大文字と小文字は区別する」 | 1 "Characters: An ordinary character matches that character itself. Upper case and lower case are distinguished." |
| 2「`.`: 改行を含む任意の 1 文字に一致する」 | 2 "`.`: Matches any single character, including a newline." |
| 3「`\` の直後の 1 文字: その文字そのものに一致する（`\.` は `.`、`\\` は `\`、`\n` は改行ではなく `n`、`\d` は `d`）。パターンの末尾に単独の `\` があれば `ValueError`」 | 3 "A single character immediately after `\`: Matches that character itself (`\.` is `.`, `\\` is `\`, `\n` is `n` and not a newline, and `\d` is `d`). A lone `\` at the end of the pattern is a `ValueError`." |
| 4「文字クラス `[...]`: 否定、項目の読み方、範囲 `x-y`（`x > y` は `ValueError`）、`]` は常に閉じる、`-` の扱い、クラス内の特殊文字、`[]`・`[^]`・閉じていない `[` は `ValueError`」 | 4 "Character class `[...]`: negation, how an item is read, range `x-y` (`x > y` is a `ValueError`), `]` always closes, how `-` is treated, special characters inside a class, `[]`, `[^]` and an unclosed `[` are a `ValueError`"（全文を 1 文ずつ対応させた） |
| 5「`^`: `text` の先頭（位置 0）にだけ…、`$`: 末尾にだけ…（末尾の改行の前には一致しない）。パターンのどこに置いてもよい」 | 5 "`^`: A zero-width assertion that matches only at the start of `text` (position 0). `$`: … (it does not match before a trailing newline). They may be placed anywhere in the pattern." |
| 6「量指定子 `*`（0 回以上）、`+`（1 回以上）、`?`（0 回か 1 回）: …`ValueError`」 | 6 "Quantifiers `*` (zero or more times), `+` (one or more times), and `?` (zero or one time): … It is a `ValueError` when …" |
| 7「グループ `( ... )`: …空のグループ `()` は空文字列に一致する。対応の取れていない `(` や `)` は `ValueError`」 | 7 "Group `( ... )`: … The empty group `()` matches the empty string. An unmatched `(` or `)` is a `ValueError`." |
| 8「選択 `|`: 優先順位は最も低く、…空の選択肢（`a|`、`|a`、`(|a)`）は空文字列に一致する」 | 8 "Alternation `|`: It has the lowest precedence, … An empty alternative (`a|`, `|a`, `(|a)`) matches the empty string." |
| 9「空のパターン `""` はどの `text` にも一致する（`True`）」 | 9 "The empty pattern `""` matches any `text` (`True`)." |
| 小見出し「性能」の 2 項（`pattern` は最大 100 文字・`text` は最大 10,000 文字／バックトラックで指数時間は不可。`(a|aa)*b`・`(a*)*b`・`a*b` と 5,000 文字） | "Performance" の 2 項（同じ数値・同じ式・同じ 5,000 文字） |
| 「例:」の 3 項目 | "Examples:" の 3 項目（式と結果は同じ文字列） |

箇条書きは文法の 9 項、性能の 2 項、例の 3 項で、日本語版と同数・同順。

## 訳で判断に迷った所

- 「半角スペース」（C4 の空白）は "the ASCII space" とした。全角スペース（U+3000）と区別する日本語の言い方なので、英語では ASCII の空白（U+0020）を指す。
  コード（U+0020）は書き足していない。
- 「大文字小文字どちらも可」（`\uXXXX` の 16 進）は "upper case and lower case are both accepted"、C5 の「大文字と小文字は区別する」は
  "Upper case and lower case are distinguished"（大文字小文字を区別する、の意）とした。
- 「送出」は "raises"、「使った答えは 0 点」は "an answer that uses it scores 0"。
- `float(その文字列)` は、コード片の中の日本語（仮名）を訳して `float(that string)` にした。コードの意味は同じ。
- 「項目」"item"、「要素」"element"、「選択肢」"alternative"、「アサーション」"assertion"、「量指定子」"quantifier"、「否定」"negation"。
- 例の `"あ😀"` は英語版でもそのまま。日本語の文字を含む例を英語の問題文に入れることになるが、隠しテストの入力がこの種の文字を含むので、写した。
- 「日本語や絵文字」は "Japanese text or emoji" とした（「日本語」という語は残る。U+007F 以降の文字の例として）。
