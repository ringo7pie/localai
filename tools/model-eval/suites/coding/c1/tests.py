"""C1 split_words の隠しテスト。モデルには見せない。

harness.py がサンドボックスの中で読み、CASES を順に `case(sol, t)` で呼ぶ。sol は答えのモジュール、
t は判定の補助（t.eq / t.raises / t.close）。1 ケース = 1 点で、合格したケースの割合が点数になる。
ケースは易しいものから難しいものへ並べ、性能のケースを最後に置く（途中で落とされても手前の分は数えられる）。
"""

FORBIDDEN_CALLS = ()


def case_empty_and_separators_only(sol, t):
    t.eq(sol.split_words(""), [])
    t.eq(sol.split_words("   \t\n \n\t"), [])


def case_plain_words(sol, t):
    t.eq(sol.split_words("ls -l /tmp"), ["ls", "-l", "/tmp"])
    t.eq(sol.split_words("  a\t\tb \n c  "), ["a", "b", "c"])


def case_single_quotes_keep_everything(sol, t):
    t.eq(sol.split_words("a 'b c'  d"), ["a", "b c", "d"])
    t.eq(sol.split_words("'a\\nb'"), ["a\\nb"])
    t.eq(sol.split_words("'\"'"), ['"'])
    t.eq(sol.split_words("'#x $y'"), ["#x $y"])


def case_double_quotes_keep_dollar_and_single_quote(sol, t):
    t.eq(sol.split_words('"$HOME dir"'), ["$HOME dir"])
    t.eq(sol.split_words('"it\'s"'), ["it's"])


def case_double_quote_escapes(sol, t):
    t.eq(sol.split_words('"\\""'), ['"'])
    t.eq(sol.split_words('"\\\\"'), ["\\"])
    t.eq(sol.split_words('"\\$"'), ["$"])
    t.eq(sol.split_words('"\\`"'), ["`"])


def case_double_quote_non_escapes_keep_backslash(sol, t):
    # \n や \a は特別ではない。バックスラッシュが残る
    t.eq(sol.split_words('"\\n"'), ["\\n"])
    t.eq(sol.split_words('"a\\tb"'), ["a\\tb"])
    t.eq(sol.split_words('"\\\'"'), ["\\'"])


def case_outside_backslash_escapes_anything(sol, t):
    t.eq(sol.split_words("a\\ b"), ["a b"])
    t.eq(sol.split_words("\\'"), ["'"])
    t.eq(sol.split_words('\\"'), ['"'])
    t.eq(sol.split_words("\\\\"), ["\\"])
    t.eq(sol.split_words("\\n"), ["n"])
    t.eq(sol.split_words("a\\\tb"), ["a\tb"])


def case_adjacent_parts_join(sol, t):
    t.eq(sol.split_words("a\"b c\"d'e f'g"), ["ab cde fg"])
    t.eq(sol.split_words("\"a\"'b'\\c\"d\\\"e\""), ['abcd"e'])


def case_empty_quotes_make_empty_words(sol, t):
    t.eq(sol.split_words("'' \"\" a''b"), ["", "", "ab"])
    t.eq(sol.split_words("''"), [""])
    t.eq(sol.split_words("x \"\"\n"), ["x", ""])


def case_comment_at_line_start(sol, t):
    t.eq(sol.split_words("# hi\nfoo"), ["foo"])
    t.eq(sol.split_words("#"), [])
    t.eq(sol.split_words("  # only a comment"), [])


def case_comment_after_separator(sol, t):
    t.eq(sol.split_words("foo # bar baz\nqux"), ["foo", "qux"])
    t.eq(sol.split_words("foo\t#bar\n#baz\nqux # x"), ["foo", "qux"])
    t.eq(sol.split_words("a #b"), ["a"])


def case_hash_inside_word_is_literal(sol, t):
    t.eq(sol.split_words("a#b"), ["a#b"])
    t.eq(sol.split_words("a#b c"), ["a#b", "c"])
    t.eq(sol.split_words("x y#z"), ["x", "y#z"])


def case_hash_after_empty_quotes_is_literal(sol, t):
    t.eq(sol.split_words("''#x"), ["#x"])
    t.eq(sol.split_words('""#x y'), ["#x", "y"])


def case_hash_quoted_or_escaped_is_literal(sol, t):
    t.eq(sol.split_words('"#x" \'#y\''), ["#x", "#y"])
    t.eq(sol.split_words("\\#x"), ["#x"])
    t.eq(sol.split_words("a \\# b"), ["a", "#", "b"])


def case_comment_text_may_contain_quotes(sol, t):
    # コメントの中の引用符は数えない
    t.eq(sol.split_words("# it's \"open\nx"), ["x"])
    t.eq(sol.split_words("a # don't\nb"), ["a", "b"])


def case_line_continuation_outside_quotes(sol, t):
    t.eq(sol.split_words("ab\\\ncd ef"), ["abcd", "ef"])
    t.eq(sol.split_words("ab \\\n cd"), ["ab", "cd"])
    t.eq(sol.split_words("\\\n"), [])
    t.eq(sol.split_words("a\\\n#b"), ["a#b"])


def case_line_continuation_then_comment(sol, t):
    # 継続は単語を始めないので、次の # はコメント
    t.eq(sol.split_words("\\\n#c\nd"), ["d"])
    t.eq(sol.split_words("x \\\n# c\ny"), ["x", "y"])


def case_line_continuation_inside_quotes(sol, t):
    t.eq(sol.split_words('"ab\\\ncd"'), ["abcd"])
    t.eq(sol.split_words("'ab\\\ncd'"), ["ab\\\ncd"])
    t.eq(sol.split_words('"a\\\n\\\nb"'), ["ab"])


def case_other_whitespace_is_not_separator(sol, t):
    t.eq(sol.split_words("a\rb"), ["a\rb"])
    t.eq(sol.split_words("あ\u3000い う"), ["あ\u3000い", "う"])
    t.eq(sol.split_words("a\x0bb\x0cc"), ["a\x0bb\x0cc"])


def case_unterminated_quotes_raise(sol, t):
    t.raises(ValueError, sol.split_words, "it's")
    t.raises(ValueError, sol.split_words, 'say "hi')
    t.raises(ValueError, sol.split_words, "a 'b\nc")
    t.raises(ValueError, sol.split_words, '"abc\\"')
    t.raises(ValueError, sol.split_words, '"abc\\')


def case_trailing_backslash_raises(sol, t):
    t.raises(ValueError, sol.split_words, "abc\\")
    t.raises(ValueError, sol.split_words, "\\")
    t.raises(ValueError, sol.split_words, "a b \\")


def case_errors_are_not_masked_by_comments(sol, t):
    # 単語の途中の # はコメントにならないので、そのあとの引用符は数える
    t.eq(sol.split_words("a#'b c'"), ["a#b c"])
    t.raises(ValueError, sol.split_words, "a#'b")
    # 引用の中の改行はコメントを終わらせない（コメントではないため）
    t.eq(sol.split_words("'#\n' x"), ["#\n", "x"])


def case_mixed_long_line(sol, t):
    text = "cmd --opt=\"a b\" 'c d'\"e\"f \\#g \\\n  # tail comment\n next\\ word  \"$x\\$y\"\n"
    t.eq(sol.split_words(text), ["cmd", "--opt=a b", "c def", "#g", "next word", "$x$y"])


def case_large_input_many_words(sol, t):
    text = "ab \"c d\" 'e' \\x # comment\n" * 5000
    expected = ["ab", "c d", "e", "x"] * 5000
    t.eq(sol.split_words(text), expected)


def case_large_single_quoted_words(sol, t):
    body = "x\\y" * 15000
    text = "\"" + body + "\" '" + body + "' " + body.replace("\\", "\\\\")
    result = sol.split_words(text)
    t.eq(len(result), 3)
    t.eq(result[0], body)
    t.eq(result[1], body)
    t.eq(result[2], body)


CASES = [
    case_empty_and_separators_only, case_plain_words, case_single_quotes_keep_everything,
    case_double_quotes_keep_dollar_and_single_quote, case_double_quote_escapes,
    case_double_quote_non_escapes_keep_backslash, case_outside_backslash_escapes_anything,
    case_adjacent_parts_join, case_empty_quotes_make_empty_words, case_comment_at_line_start,
    case_comment_after_separator, case_hash_inside_word_is_literal, case_hash_after_empty_quotes_is_literal,
    case_hash_quoted_or_escaped_is_literal, case_comment_text_may_contain_quotes,
    case_line_continuation_outside_quotes, case_line_continuation_then_comment,
    case_line_continuation_inside_quotes, case_other_whitespace_is_not_separator,
    case_unterminated_quotes_raise, case_trailing_backslash_raises, case_errors_are_not_masked_by_comments,
    case_mixed_long_line, case_large_input_many_words, case_large_single_quoted_words,
]
