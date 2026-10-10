"""C5 regex_search の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

re モジュールの使用は、実行の前に静的な走査で見つけて 0 点にする（FORBIDDEN_CALLS。import と re.compile などの呼び出し）。
期待値は、仕様が Python の re と一致する範囲では re.search と照合した（照合用の script は work の外には残していない）。
"""

FORBIDDEN_CALLS = ("re", "re.compile", "re.search", "re.match", "re.fullmatch", "re.finditer", "re.findall",
                   "sre_parse", "sre_compile", "_sre", "sre_constants")

BS = "\\"


def case_literals(sol, t):
    t.eq(sol.regex_search("abc", "xxabcxx"), True)
    t.eq(sol.regex_search("abc", "abd"), False)
    t.eq(sol.regex_search("abc", "ab"), False)
    t.eq(sol.regex_search("A", "a"), False)
    t.eq(sol.regex_search("b", ""), False)


def case_empty_pattern_matches_everything(sol, t):
    t.eq(sol.regex_search("", ""), True)
    t.eq(sol.regex_search("", "abc"), True)
    t.eq(sol.regex_search("()", "x"), True)
    t.eq(sol.regex_search("a*", "bbb"), True)


def case_dot(sol, t):
    t.eq(sol.regex_search("a.c", "abc"), True)
    t.eq(sol.regex_search("a.c", "ac"), False)
    t.eq(sol.regex_search(".", ""), False)
    t.eq(sol.regex_search(".", "\n"), True)
    t.eq(sol.regex_search("a.b", "a\nb"), True)
    t.eq(sol.regex_search(".", "😀"), True)


def case_quantifiers(sol, t):
    t.eq(sol.regex_search("ab*c", "ac"), True)
    t.eq(sol.regex_search("ab*c", "abbbc"), True)
    t.eq(sol.regex_search("ab+c", "ac"), False)
    t.eq(sol.regex_search("ab+c", "abbbc"), True)
    t.eq(sol.regex_search("ab?c", "ac"), True)
    t.eq(sol.regex_search("ab?c", "abc"), True)
    t.eq(sol.regex_search("ab?c", "abbc"), False)
    t.eq(sol.regex_search("x*y", "aaay"), True)


def case_anchors(sol, t):
    t.eq(sol.regex_search("^abc", "abcd"), True)
    t.eq(sol.regex_search("^abc", "xabc"), False)
    t.eq(sol.regex_search("abc$", "xabc"), True)
    t.eq(sol.regex_search("abc$", "abcx"), False)
    t.eq(sol.regex_search("^$", ""), True)
    t.eq(sol.regex_search("^$", "a"), False)
    t.eq(sol.regex_search("^", "anything"), True)
    t.eq(sol.regex_search("$", ""), True)
    t.eq(sol.regex_search("^a*$", "aab"), False)
    t.eq(sol.regex_search("^a*$", "aaa"), True)


def case_anchors_ignore_newlines(sol, t):
    # Python の re とは違い、$ は末尾の改行の前には一致しない。^ は位置 0 だけ
    t.eq(sol.regex_search("a$", "a\n"), False)
    t.eq(sol.regex_search("^b", "a\nb"), False)
    t.eq(sol.regex_search("a$", "a\nb"), False)
    t.eq(sol.regex_search("b$", "a\nb"), True)
    t.eq(sol.regex_search("^a", "\na"), False)


def case_alternation(sol, t):
    t.eq(sol.regex_search("cat|dog", "hotdog"), True)
    t.eq(sol.regex_search("cat|dog", "cow"), False)
    t.eq(sol.regex_search("ab|cd", "acd"), True)
    t.eq(sol.regex_search("a(b|c)d", "abd"), True)
    t.eq(sol.regex_search("a(b|c)d", "abcd"), False)
    t.eq(sol.regex_search("(cat|dog)s?$", "I like dogs"), True)
    t.eq(sol.regex_search("(cat|dog)s?$", "dogs bark"), False)


def case_empty_alternatives(sol, t):
    t.eq(sol.regex_search("a|", "zzz"), True)
    t.eq(sol.regex_search("|a", ""), True)
    t.eq(sol.regex_search("x(|a)y", "xy"), True)
    t.eq(sol.regex_search("x(|a)y", "xay"), True)
    t.eq(sol.regex_search("x(|a)y", "xby"), False)
    t.eq(sol.regex_search("^(a|)$", "b"), False)


def case_groups_with_quantifiers(sol, t):
    t.eq(sol.regex_search("(ab)+", "abab"), True)
    t.eq(sol.regex_search("^(ab)+$", "ababa"), False)
    t.eq(sol.regex_search("^(ab)+$", "ababab"), True)
    t.eq(sol.regex_search("(a|bc)*d", "abcbcad"), True)
    t.eq(sol.regex_search("^(a|bc)*d$", "abcbcbd"), False)
    t.eq(sol.regex_search("(a)(b)", "ab"), True)
    t.eq(sol.regex_search("^((a|b)c)?d$", "bcd"), True)
    t.eq(sol.regex_search("^((a|b)c)?d$", "abcd"), False)


def case_anchors_inside_groups(sol, t):
    t.eq(sol.regex_search("(^a|b$)", "cab"), True)
    t.eq(sol.regex_search("(^a|b$)", "cba"), False)
    t.eq(sol.regex_search("(^a|b$)", "abc"), True)
    t.eq(sol.regex_search("x(^a)", "xa"), False)
    t.eq(sol.regex_search("(^)*a", "a"), True)


def case_character_classes(sol, t):
    t.eq(sol.regex_search("[abc]", "xbx"), True)
    t.eq(sol.regex_search("[abc]", "xyz"), False)
    t.eq(sol.regex_search("[a-c]x", "dx"), False)
    t.eq(sol.regex_search("[a-c]x", "cx"), True)
    t.eq(sol.regex_search("^[a-zA-Z0-9_]+$", "Hello_42"), True)
    t.eq(sol.regex_search("^[a-zA-Z0-9_]+$", "Hello-42"), False)
    t.eq(sol.regex_search("[0-9][0-9]", "a7b"), False)
    t.eq(sol.regex_search("[0-9][0-9]", "a78b"), True)


def case_negated_classes(sol, t):
    t.eq(sol.regex_search("[^a-c]", "abc"), False)
    t.eq(sol.regex_search("[^a-c]", "abcd"), True)
    t.eq(sol.regex_search("^[^0-9]*$", "abc"), True)
    t.eq(sol.regex_search("^[^0-9]*$", "ab3c"), False)
    t.eq(sol.regex_search("[^\n]", "\n"), False)
    t.eq(sol.regex_search("[^\n]", "\na"), True)
    t.eq(sol.regex_search("[^" + BS + "]a]", "x"), True)
    t.eq(sol.regex_search("[^" + BS + "]a]", "]a"), False)


def case_class_edge_syntax(sol, t):
    t.eq(sol.regex_search("[-a]", "-"), True)
    t.eq(sol.regex_search("[a-]", "-"), True)
    t.eq(sol.regex_search("[a-]", "b"), False)
    t.eq(sol.regex_search("[a^]", "^"), True)
    t.eq(sol.regex_search("[" + BS + "]]", "]"), True)
    t.eq(sol.regex_search("[" + BS + "]]", "a"), False)
    t.eq(sol.regex_search("[a" + BS + "-z]", "-"), True)
    t.eq(sol.regex_search("[a" + BS + "-z]", "m"), False)
    t.eq(sol.regex_search("[" + BS + BS + "]", BS), True)
    t.eq(sol.regex_search("[.]", "a"), False)
    t.eq(sol.regex_search("[.]", "."), True)
    t.eq(sol.regex_search("[*+?|()$^]", "+"), True)
    t.eq(sol.regex_search("[a|b]", "|"), True)
    t.eq(sol.regex_search("[+--]", ","), True)
    t.eq(sol.regex_search("[" + BS + "--" + BS + "/]", "."), True)


def case_escapes(sol, t):
    t.eq(sol.regex_search(BS + ".", "a"), False)
    t.eq(sol.regex_search(BS + ".", "."), True)
    t.eq(sol.regex_search(BS + "*", "*"), True)
    t.eq(sol.regex_search("a" + BS + "|b", "a|b"), True)
    t.eq(sol.regex_search("a" + BS + "|b", "a"), False)
    t.eq(sol.regex_search(BS + "(", "("), True)
    t.eq(sol.regex_search(BS + BS, BS), True)
    t.eq(sol.regex_search(BS + "^", "^"), True)
    t.eq(sol.regex_search("x" + BS + "$", "x$"), True)
    t.eq(sol.regex_search(BS + "[", "["), True)


def case_escaped_letters_are_literal(sol, t):
    # \d や \n は特別な意味を持たない（仕様に明記）
    t.eq(sol.regex_search(BS + "d", "5"), False)
    t.eq(sol.regex_search(BS + "d", "d"), True)
    t.eq(sol.regex_search(BS + "n", "\n"), False)
    t.eq(sol.regex_search(BS + "n", "n"), True)
    t.eq(sol.regex_search(BS + "w+", "www"), True)
    t.eq(sol.regex_search("^" + BS + "s$", "s"), True)
    t.eq(sol.regex_search("^" + BS + "s$", " "), False)


def case_invalid_patterns(sol, t):
    for pattern in ("*a", "a**", "a*?", "a+*", "a??", "(*a)", "a|*", "a|*b", "+", "?"):
        t.raises(ValueError, sol.regex_search, pattern, "aaa")


def case_invalid_groups_and_anchors(sol, t):
    for pattern in ("(", ")", "a)", "(a", "(()", "())", "^*", "$+", "a^?", "(a|b))", "((a|b)"):
        t.raises(ValueError, sol.regex_search, pattern, "aaa")


def case_invalid_classes_and_escapes(sol, t):
    for pattern in ("[", "[a", "[]", "[^]", "[z-a]", "[b-a]x", "a" + BS, "[a-" + BS, "[" + BS, "ab" + BS, "[]a]", "[^-]]x["):
        t.raises(ValueError, sol.regex_search, pattern, "aaa")


def case_realistic_patterns(sol, t):
    email = "^[a-z]+@[a-z]+" + BS + ".[a-z]+$"
    t.eq(sol.regex_search(email, "foo@bar.com"), True)
    t.eq(sol.regex_search(email, "foo@bar"), False)
    t.eq(sol.regex_search(email, "foo@bar.com "), False)
    t.eq(sol.regex_search("^-?[0-9]+(" + BS + ".[0-9]+)?$", "-12.5"), True)
    t.eq(sol.regex_search("^-?[0-9]+(" + BS + ".[0-9]+)?$", "12."), False)
    t.eq(sol.regex_search("^(0|[1-9][0-9]*)$", "007"), False)
    t.eq(sol.regex_search("^(0|[1-9][0-9]*)$", "0"), True)
    t.eq(sol.regex_search("^#[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]$", "#fA0"), True)


def case_unicode_text(sol, t):
    t.eq(sol.regex_search("日本", "こんにちは日本"), True)
    t.eq(sol.regex_search("[あ-ん]+", "カタカナ"), False)
    t.eq(sol.regex_search("^[あ-ん]+$", "ひらがな"), True)
    t.eq(sol.regex_search("^.$", "😀"), True)
    t.eq(sol.regex_search("^..$", "😀"), False)


def case_nested_quantifiers_with_empty_loops(sol, t):
    t.eq(sol.regex_search("(a*)*b", "aaab"), True)
    t.eq(sol.regex_search("(a*)*b", "aaa"), False)
    t.eq(sol.regex_search("^(a*)+$", "aaa"), True)
    t.eq(sol.regex_search("(|a)*b", "b"), True)
    t.eq(sol.regex_search("^(a?)*$", "aaaa"), True)
    t.eq(sol.regex_search("^(a*b*)*$", "abba"), True)
    t.eq(sol.regex_search("^(a*b*)*c$", "abbaa"), False)


def case_catastrophic_for_backtracking(sol, t):
    t.eq(sol.regex_search("(a|aa)*b", "a" * 40), False)
    t.eq(sol.regex_search("(a|aa)*b", "a" * 40 + "b"), True)
    t.eq(sol.regex_search("(x+x+)+y", "x" * 30), False)
    t.eq(sol.regex_search("^(a?)*$", "a" * 60), True)
    t.eq(sol.regex_search("^" + "a?" * 25 + "a" * 25 + "$", "a" * 25), True)
    t.eq(sol.regex_search("^" + "a?" * 25 + "a" * 25 + "$", "a" * 24), False)


def case_long_text_search(sol, t):
    # 位置ごとに最初からやり直す作り（O(n^2)）では遅すぎる
    t.eq(sol.regex_search("a*b", "a" * 5000), False)
    t.eq(sol.regex_search("a*b", "a" * 5000 + "b"), True)
    t.eq(sol.regex_search("[a-z]+@[a-z]+" + BS + ".[a-z]+", "x" * 9000 + " foo@bar.com"), True)
    t.eq(sol.regex_search(".*.*.*.*.*=.*", "a" * 2000), False)
    t.eq(sol.regex_search("(ab|cd|ef)*gh$", "ab" * 4000 + "gh"), True)


def case_long_alternation_in_long_text(sol, t):
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
    pattern = "(" + "|".join(words) + ")" + BS + "."
    text = ("xyz " * 2400) + "lima."
    t.eq(sol.regex_search(pattern, text), True)
    t.eq(sol.regex_search(pattern, text[:-1]), False)
    t.eq(sol.regex_search("^(" + "|".join(words) + "|xyz| )*$", text[:-5]), True)


CASES = [
    case_literals, case_empty_pattern_matches_everything, case_dot, case_quantifiers, case_anchors,
    case_anchors_ignore_newlines, case_alternation, case_empty_alternatives, case_groups_with_quantifiers,
    case_anchors_inside_groups, case_character_classes, case_negated_classes, case_class_edge_syntax, case_escapes,
    case_escaped_letters_are_literal, case_invalid_patterns, case_invalid_groups_and_anchors,
    case_invalid_classes_and_escapes, case_realistic_patterns, case_unicode_text,
    case_nested_quantifiers_with_empty_loops, case_catastrophic_for_backtracking, case_long_text_search,
    case_long_alternation_in_long_text,
]
