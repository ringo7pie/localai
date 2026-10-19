"""H5 min_dfa_size / distinguish の隠しテスト。モデルには見せない（形式は suites/coding/c1/tests.py と同じ）。

期待値は reference.py（Thompson の NFA と部分集合構成）で計算し、oracle.py（Brzozowski の微分と区別の表、
短い順の全列挙）と一致することを確かめた（tests/test_hard.py）。大きい DFA の状態数は 2**(k+1) の公式とも一致する。
"""

FORBIDDEN_CALLS = ("re", "re.compile", "re.search", "re.match", "re.fullmatch", "re.finditer", "re.findall",
                   "sre_parse", "sre_compile", "_sre", "sre_constants")


def _code(value):
    if value == "VE":
        return 7
    if value is None:
        return 11
    if isinstance(value, int):
        return 13 + value * 17
    acc = 19
    for ch in value:
        acc = (acc * 131 + ord(ch)) % ((1 << 61) - 1)
    return acc


def _checksum(values):
    acc = 0
    for index, value in enumerate(values):
        acc = (acc * 1000003 + _code(value) + index) % ((1 << 61) - 1)
    return acc


def _call(fn, *args):
    try:
        return fn(*args)
    except ValueError:
        return "VE"


def case_examples(sol, t):
    t.eq(sol.min_dfa_size("a*", "ab"), 2)
    t.eq(sol.min_dfa_size("(a|b)*", "ab"), 1)
    t.eq(sol.min_dfa_size("", "ab"), 2)
    t.eq(sol.min_dfa_size("[c]", "ab"), 1)
    t.eq(sol.min_dfa_size("(a|b)*a(a|b)", "ab"), 4)
    t.eq(sol.distinguish("(ab)*", "(a|b)*", "ab"), "a")
    t.eq(sol.distinguish("a(b|c)", "ab|ac", "abc"), None)
    t.eq(sol.distinguish("b*", "a*", "ba"), "b")


def case_bad_alphabets(sol, t):
    t.raises(ValueError, sol.min_dfa_size, "a", "")
    t.raises(ValueError, sol.min_dfa_size, "a", "aa")
    t.raises(ValueError, sol.min_dfa_size, "a", "abca")
    t.raises(ValueError, sol.distinguish, "a", "b", "")
    t.raises(ValueError, sol.distinguish, "a", "b", "bab")


def case_bad_patterns(sol, t):
    for bad in ("a**", "a*?", "*a", "(*a)", "a|*", "(a", "a)", "[]", "[^]", "[a", "a\\", "[b-a]", "(|+)", "a(", ")("):
        t.raises(ValueError, sol.min_dfa_size, bad, "ab")
    t.raises(ValueError, sol.distinguish, "a", "a**", "ab")
    t.raises(ValueError, sol.distinguish, "(a", "a", "ab")


def case_empty_language_and_empty_string(sol, t):
    t.eq(sol.min_dfa_size("x", "ab"), 1)
    t.eq(sol.min_dfa_size("()", "ab"), 2)
    t.eq(sol.min_dfa_size("()*", "ab"), 2)
    t.eq(sol.min_dfa_size("x*", "ab"), 2)
    t.eq(sol.min_dfa_size("a|x", "ab"), 3)
    t.eq(sol.min_dfa_size("ax*b", "ab"), 4)
    t.eq(sol.min_dfa_size("axb", "ab"), 1)


def case_dot_and_classes(sol, t):
    t.eq(sol.min_dfa_size(".", "ab"), 3)
    t.eq(sol.min_dfa_size("[^a]", "ab"), 3)
    t.eq(sol.min_dfa_size("[^ab]", "ab"), 1)
    t.eq(sol.min_dfa_size("[a-c]*", "abcd"), 2)
    t.eq(sol.min_dfa_size("[a-z]", "ab"), 3)
    t.eq(sol.min_dfa_size("[b-]*", "ab-"), 2)
    t.eq(sol.min_dfa_size("[-a]b", "ab-"), 4)
    t.eq(sol.min_dfa_size("[\\]a]*", "a]b"), 2)


def case_specials_are_ordinary_characters(sol, t):
    t.eq(sol.min_dfa_size("^a$", "^a$"), 5)
    t.eq(sol.min_dfa_size("a$", "a"), 1)
    t.eq(sol.min_dfa_size("[.]*", ".a"), 2)
    t.eq(sol.min_dfa_size("\\.\\*", ".*"), 4)
    t.eq(sol.min_dfa_size("\\n", "n"), 3)
    t.eq(sol.min_dfa_size("[a^]*", "a^b"), 2)


def case_quantifiers_and_groups(sol, t):
    t.eq(sol.min_dfa_size("a+", "ab"), 3)
    t.eq(sol.min_dfa_size("a?", "ab"), 3)
    t.eq(sol.min_dfa_size("(ab)*", "ab"), 3)
    t.eq(sol.min_dfa_size("(ab)+", "ab"), 4)
    t.eq(sol.min_dfa_size("(a*b*)*", "ab"), 1)
    t.eq(sol.min_dfa_size("(a|)(b|)", "ab"), EXPECTED["optional_pair"])


def case_alternation_with_empty_branches(sol, t):
    t.eq(sol.min_dfa_size("a|", "ab"), 3)
    t.eq(sol.min_dfa_size("|a", "ab"), 3)
    t.eq(sol.min_dfa_size("(|a)b", "ab"), 4)
    t.eq(sol.min_dfa_size("||", "ab"), 2)


def case_counting_languages(sol, t):
    t.eq(sol.min_dfa_size("(a|b)*a(a|b)(a|b)", "ab"), 8)
    t.eq(sol.min_dfa_size("((a|b)(a|b))*", "ab"), 2)
    t.eq(sol.min_dfa_size("(aaa)*", "a"), 3)
    t.eq(sol.min_dfa_size("(aaa)*", "ab"), 4)
    t.eq(sol.min_dfa_size("(b*ab*ab*a)*b*", "ab"), 3)


def case_random_patterns(sol, t):
    values = [_call(sol.min_dfa_size, p, a) for p, a in zip(PATTERNS, ALPHABETS)]
    t.eq(_checksum(values), EXPECTED["random_sizes"])


def case_equal_languages(sol, t):
    t.eq(sol.distinguish("(a|b)*", "(a*b*)*", "ab"), None)
    t.eq(sol.distinguish("(ab)*a", "a(ba)*", "ab"), None)
    t.eq(sol.distinguish("a*", "a*a*", "ab"), None)
    t.eq(sol.distinguish("x", "[c]", "ab"), None)
    t.eq(sol.distinguish(".", "a|b", "ab"), None)


def case_empty_string_can_distinguish(sol, t):
    t.eq(sol.distinguish("a*", "a+", "ab"), "")
    t.eq(sol.distinguish("", "x", "ab"), "")
    t.eq(sol.distinguish("()", "()", "ab"), None)


def case_shortest_first(sol, t):
    t.eq(sol.distinguish("aaa|b", "aaa", "ab"), "b")
    t.eq(sol.distinguish("(a|b)*bb(a|b)*", "(a|b)*b(a|b)*", "ab"), "b")
    t.eq(sol.distinguish("(aa)*", "a*", "ab"), "a")
    t.eq(sol.distinguish("(aa)*", "(aa)*|aaaaaaa", "ab"), "aaaaaaa")


def case_ties_follow_alphabet_order(sol, t):
    t.eq(sol.distinguish("b*", "a*", "ab"), "a")
    t.eq(sol.distinguish("..", "aa|ba|cb", "abc"), "ab")
    t.eq(sol.distinguish("..", "aa|ba|cb", "cba"), "cc")
    t.eq(sol.distinguish("(a|b|c)c", "bc|cc", "cba"), "ac")


def case_random_pairs(sol, t):
    values = []
    for i in range(len(PATTERNS) // 2):
        values.append(_call(sol.distinguish, PATTERNS[2 * i], PATTERNS[2 * i + 1] if i % 3 else
                            PATTERNS[2 * i] + "|" + PATTERNS[2 * i + 1], ALPHABETS[i]))
    t.eq(_checksum(values), EXPECTED["random_pairs"])


def case_performance_large_minimal_dfa(sol, t):
    t.eq(sol.min_dfa_size(".*a" + "." * 12, "ab"), 8192)


def case_performance_larger_alphabet(sol, t):
    t.eq(sol.min_dfa_size(".*a" + "." * 7, "abcd"), 256)
    t.eq(sol.min_dfa_size("(.*a.*b.*c|.*d.*e)*(f|g)+h?" + "." * 5, "abcdefgh"), EXPECTED["alpha8"])


def case_performance_long_shortest_difference(sol, t):
    t.eq(sol.distinguish(".*a.........", ".*a.........|dddddddddddd", "abcd"), "dddddddddddd")
    t.eq(sol.distinguish(".*a.........", ".*a.........|dddddddddddd", "dcba"), "dddddddddddd")


def case_performance_equal_large_languages(sol, t):
    k = 11
    t.eq(sol.distinguish(".*a" + "." * k, "(a|b)*a" + "(a|b)" * k, "ab"), None)
    t.eq(sol.distinguish(".*a" + "." * k, "(a|b)*a" + "(a|b)" * (k - 1) + "a", "ab"), "a" * k + "b")


EXPECTED = {'random_sizes': 1358341198244754261, 'random_pairs': 514699418255375818, 'optional_pair': 4, 'alpha8': 492}
PATTERNS = [
    '[\\]a]',
    '$',
    '(a|x)',
    'a)[^a]+|(\\.)**',
    '[\\]a]a|(d)+',
    '((\\a)+[^a]\\a]+)?',
    'b|[\\]a](',
    '((c[b*-])?d*x)+',
    '((x)?+?)',
    '(.)*|(d)+[\\]a][b-][^a]?',
    '([ab]+)+[b-]c[a-c]\\.?',
    '(\\aa)|?.[^a]',
    '($)',
    '($|b($)\\+|[\\]a])?',
    '[\\-]a]',
    '[a-c]|([^a])+*|bb?',
    '(([b-]))',
    'a|[a-c](\\a\\.)',
    '(c)',
    '(-((.)+))(\\.d+)',
    '[^a]',
    '((-\\.)?(a)?)?',
    '[a-c]',
    '(([a-c])?)*|d^',
    '[a-c]|[a-c]',
    'cc\\a?d*([a-c])*',
    '\\a|',
    '[ab]-',
    '\\.[b-]|b*',
    'a[a-c]',
    '(b)+[',
    '($|[^a])*-',
    '(\\.)',
    '.|.+*\\.c?',
    '\\a',
    'x|',
    '[^a]',
    '(\\a|[a--c]*|[a-c]*)+',
    '\\ad.|$+',
    'c[\\]a]c[b-]|$[ab]?d',
    '[\\]a]|[\\]a]|.^|xd(c)+[a-c]+',
    'x|(c.)*$',
    'x',
    '[\\]a]+',
    '[b-]|[ab]([ab])+[b-]|(cc*)?',
    'ca',
    '[^a-](b)+',
    '^',
    '[a-c](^?)?+',
    '(x)*+[',
    '(.[a-c]|\\.)+d|a\\a?((\\.)+)*',
    'x[^a]',
    'd',
    '(d)?c?+([b-])*\\a$\\aa',
    '.',
    '(b)|*',
    '(c[^a]|a^*)+',
    '(\\a)(.)?]\\a[b-]+',
    '\\.',
    'b^',
    '(\\.($)+)?.\\.\\a(x)*',
    '[ab]?(c)*[\\]a]?',
    '(.)+[ab]*[a-c]|$^xx|x',
    '[^a]|[ab]++$',
    '[a-c]((x)?|c)+',
    '$(x)*|([^a])+\\a[\\]a]+|((c))+',
    '\\a',
    '([\\]a])',
    '\\.+',
    '[b-]|x',
    '\\.',
    'a$?\\a\\a+c^\\a|(d)+',
    '(^[\\]a]|^x)?[^a]',
    '(((\\a)+)*)?.',
    'x*|(.)??|.*',
    '(.$)+*',
    '^*|[a-c]|\\a|^*$',
    '[\\]a]',
    '\\ab|(^])++',
    '[a(b]',
    'x',
    '(((.)*)?[a-c]xa)?',
    '[a-c]',
    '[\\]a]?-',
    '([*b-]\\.)+^|([^a]*)',
    '$',
    '(x)+',
    'c|\\.',
    '($?)*?|([a-c])[a-c][a-c]a',
    '($[^a]|b[^a])|x|d',
    '\\.?|[b-][^a]|[a-c]((xc))?',
    '(^|\\.)?[^a]|([b-])*',
    '(([b-][a-c][b-]))+',
    'a',
    '([b-]$|a((.)*)?)+',
    '(da|x)[b-]|(x)*|d[ab]',
    'x[\\]a].\\.\\a\\.',
    'c',
    '((^))?b)?',
    'd',
    '\\a|a|[^a].[a-c][b-]|^+',
    '((d)*()*[b-]',
    '((.)|[\\]a]c+*)+',
    '(^)+',
    'c(a|^)*|\\.|c|[^a][?a-c]',
    '\\.',
    '[b-]',
    '.+x\\a[\\]a]|(x)|[^a].',
    '(d|dc',
    '(([b-])+|[a-c]*)+',
    '\\.[\\]a]',
    '^|^[^a]|\\a|[ab]+[a-c]',
    '([a-c])+(d|x[a-c])',
    '((x)?+($)**(d)?)*',
    '([ab])|([a-c])*c|[a-c]|\\a|(\\a)+(.)*',
    '$(d)',
    '(c?\\a)+[b-][b-]',
    '[^)a]',
    '[\\]a]|(\\a)+',
    '\\a.c+(c)|([b-]*|[a-c])',
    '(b)?*-',
    '(*^|c)?',
    '([a-c])+*((x\\a))?',
    ')a',
    '(([ab])?\\a[a-c])+$?||c|d?',
    'd',
    '((b)*d)|[b-]',
    '([b-])[a-c](c)^$',
    '($.?)+|\\.|d[\\]a]|([a-c]?',
    '^[',
    'c|((^)*)\\a',
    '((^|[\\]a])c|d)?',
    '((.[*))+*',
    '(*[ab][a-c]+.)?',
    'c*',
    '[b-]|^',
    '\\..c|d($))+',
    'c|.+',
    '([ab].|cc[b-]|)[\\]a]|\\a?)+',
    '\\.((x)*)*.[^a]',
    '-[^a]',
    '($)?',
    '[ab]',
    'c',
    '(.|$)|\\.++$^|(\\a)?|$',
    '(d|^*+)+',
    '[a-c]*',
    '(b|\\ada|[a*b])',
    '[b-]b[ab]|[\\]a]($)+',
    'a[a-c]|(^-)?*',
    '[^a]|c|b.|[ab-]',
    'b?[^a][a-c\\]?(d)*',
    '\\.*|d+|[b-]^^|$',
    '.',
    '(*a)|d',
    '(d)-',
    '(x^a[^a]*)',
    '[^a]?',
    'b\\',
    '.',
    '[ab]|x',
    '(^?)',
    '\\.**',
    '([ab]*)+*',
    '(\\a)\\?',
    '(.)',
    '(\\.$[^a]?)*(a+)*[^a]',
    '(a|xc[\\]a])+?',
    '(xd)+?',
    ')$',
    '(.x+([^a])*)?',
    '(c)?x([a-c])|[\\]a]b',
    '-b+',
    'c+\\.*|[a-c]|[^a]|bb|c',
    '^(\\a)*+(a)*($)',
    '([\\]a])?-',
    '(c)*',
    '[\\]a]|[^a]([ab])*\\.d',
    '[b-]',
    '[b-]?',
    '([ab]|[\\]a]|a)+|d+|dx',
    '^[ab]|a|d[^a]|(^)*|\\^?',
    '$?|($)++?',
    'x|^',
    'x',
    '([ab)](^[a-c]))+',
    '\\a',
    '((b)*+)^|(b)+a*',
    '\\.',
    '$|(d)+|(x)[ab]^\\.',
    '[^a](^)+a',
    '(d(b)?|\\.|([\\]a]|\\a+)?',
    '(a)?\\aa]d.',
    '[a-c]',
    '(([\\]a]d)|$)+',
    '?\\a',
    'a',
    '([\\]a]*)*',
    '(([ab])?[ab]|.|[ab[]\\.)',
    '(x',
    '\\.',
    '(\\|a)',
    '((b?\\a*|^)?)*',
    'b',
    '[ab]',
    '((c)*)?',
    'xc',
    'x[^a]$|[b-]?((c?)*)',
    'x',
    '[b-]',
    '[\\]a]|d[ab]*',
    '((.)+)(',
    '[ab]+(a)*\\.+',
    '((a)*|ac+)*',
    '(((d.)*)+)*',
    '.b([a-c])[a-c]+[^a]+|[b-][\\]a]|d.',
    '\\a|[a-c]^($|x)|([\\]a]|[b-])*|cd',
    '[^a]',
    '\\a',
    '([\\|]a])*',
    '([a-c])-|c|cx(x)$$+a',
    '(^)*b^(a)+[\\]a]^|x([^a])*x',
    '[\\a',
    'x(',
    'b',
    '(x|[^a][^a]\\.+)',
    '(\\a[ab](.))[^a)]',
    '*[ab]|[ab]',
    'd',
    '[b-]',
    '[^a]',
    '(.)++',
    '(([^a])?|b\\.)?',
    '[\\]a]xa|(\\.)|([\\]a])?|[ab]+',
    '(\\.)?',
    '(((b|a))+)*',
    '((\\a)+|[b-])?[b-]*((^))+',
    '((([b-])?*)?|[^a]',
    '\\.[^a]\\a$?',
    '^',
    '((b?)?)*[|([b-]|$)*',
    '\\a',
    '\\.b|dc?',
    '(($)*)?',
    '((.[a-c].[^a])?)?',
    '^?',
    '($\\a|x|[^a]\\.)?',
    '^',
    '*$?',
    '.',
    '^|(($)*\\a^)*',
    '((a)?)+|(ab)?|((\\.)*)?.',
    '[ab]\\a*[\\]a]|^|[b-]|(((^)+)+)',
    '^\\',
    '(.)\\a(\\aa)*',
    '$\\.',
    '|b',
    'c|[ab]|c**[)\\]a]^+^',
    '\\?a([ab])?|[b-]|[\\]a]|[a-c]*|($^)',
    '\\.(\\a|\\a\\a+)?',
    '(([^a]+)|([\\]a]))?',
    '(x)+[',
    'x(^)+(x)[^a]$',
    '(^?*.)*',
    '^abc[\\]a](b)*|d*',
    '\\.|a|x??',
    '(([\\]a])?)?',
    'a[ab]+|([ab])*',
    '^.',
    'x(x^|b.)*',
    '.',
    '$?|[b-]|\\.|x|d\\a|a[\\]a].a',
    '(x|^d^)+',
    '(d-)+',
    '([b-]x|c*[a-c])*',
    'c[\\]a]x\\a|b^[b-]^|(.)?(.[\\]a])',
    '((\\a)*)*',
    '[a-c]?|[b-]b|$([b-])?',
    '$|[a-c][\\]a](a|\\.)x([b-]|[a-c])?',
    '(([^a][b-]|^))*',
    '.',
    '[a-c]]',
    '[b-]]',
    '$',
    '([ab][-ab](\\a)+([b-]x))+',
    '((\\.)+a^[a]b])',
    '[ab]',
    'd',
    'a\\.]',
    'ab$+*',
    '[a-c]da+|b*|x[b-]|^',
    '([^a](^$)*)?\\',
    'x',
    'a',
    'd(x)*',
    '(d)?|$$([ab])*.',
    'b',
    'x',
    '(\\a)?b|c[ab]*$',
    'bxd|[\\]a]|[^a].',
]
ALPHABETS = ['abc', 'abc', 'ab', 'abcd', 'cab', 'abc', 'a', 'ab', 'a', 'a', 'ba', 'dcba', 'ab', 'abc', 'ba', 'ab', 'ba', 'abcd', 'abc', 'abcd', 'a', 'a', 'cab', 'a', 'ab', 'abcd', 'ab', 'abcd', 'ba', 'ba', 'cab', 'abc', 'abc', 'dcba', 'ab', 'abcd', 'abcd', 'a', 'dcba', 'abcd', 'ab', 'a', 'ba', 'abcd', 'ba', 'ba', 'abc', 'cab', 'ba', 'dcba', 'dcba', 'a', 'abcd', 'abc', 'ba', 'dcba', 'ba', 'a', 'a', 'abc', 'cab', 'ab', 'ba', 'abcd', 'ab', 'cab', 'ba', 'abcd', 'ba', 'abcd', 'cab', 'cab', 'a', 'abc', 'ba', 'abcd', 'ba', 'cab', 'abcd', 'ab', 'ba', 'abcd', 'abcd', 'abcd', 'abcd', 'abcd', 'cab', 'dcba', 'a', 'abcd', 'cab', 'ab', 'ab', 'cab', 'ba', 'ab', 'cab', 'dcba', 'cab', 'ab', 'dcba', 'abc', 'abcd', 'abc', 'cab', 'ab', 'ab', 'cab', 'abc', 'abc', 'ab', 'abcd', 'cab', 'ba', 'abc', 'ba', 'ba', 'a', 'abc', 'cab', 'ab', 'ab', 'abcd', 'abc', 'dcba', 'dcba', 'a', 'a', 'abc', 'a', 'a', 'ab', 'ab', 'abc', 'cab', 'ab', 'dcba', 'abc', 'abcd', 'cab', 'ab', 'dcba', 'ab', 'cab', 'a', 'abcd', 'abc', 'abcd', 'ba', 'a', 'a', 'dcba', 'cab', 'cab', 'a', 'ab', 'a', 'a', 'ba', 'dcba', 'ab', 'dcba', 'dcba', 'abcd', 'ba', 'ab', 'ab', 'abc', 'abcd', 'ba', 'a', 'ab', 'ba', 'ab', 'abc', 'a', 'a', 'abcd', 'cab', 'a', 'ba', 'abc', 'ab', 'ab', 'abc', 'ba', 'a', 'ab', 'abc', 'abcd', 'ba', 'cab', 'dcba', 'ab', 'abc', 'ab', 'ba', 'dcba', 'ab', 'abcd', 'cab', 'abcd', 'abc', 'cab', 'ba', 'ab', 'a', 'abcd', 'dcba', 'abc', 'ab', 'abc', 'cab', 'dcba', 'dcba', 'abcd', 'ab', 'abc', 'abc', 'dcba', 'cab', 'a', 'cab', 'ab', 'dcba', 'a', 'a', 'cab', 'cab', 'ba', 'abc', 'abc', 'ab', 'ba', 'ab', 'a', 'abcd', 'abc', 'abc', 'a', 'ba', 'ab', 'ab', 'cab', 'abc', 'abcd', 'ba', 'ab', 'dcba', 'cab', 'a', 'ab', 'ba', 'dcba', 'dcba', 'ab', 'abc', 'a', 'dcba', 'cab', 'dcba', 'a', 'abc', 'cab', 'abcd', 'cab', 'abc', 'ba', 'ba', 'ba', 'dcba', 'dcba', 'a', 'ab', 'a', 'cab', 'abcd', 'a', 'ab', 'abc', 'dcba', 'dcba', 'abcd', 'abcd', 'a', 'ba', 'ba', 'dcba', 'dcba', 'abcd', 'ba', 'abc', 'ba', 'ba', 'abcd', 'abc', 'ba', 'dcba', 'dcba', 'abcd']

CASES = [
    case_examples, case_bad_alphabets, case_bad_patterns, case_empty_language_and_empty_string, case_dot_and_classes,
    case_specials_are_ordinary_characters, case_quantifiers_and_groups, case_alternation_with_empty_branches,
    case_counting_languages, case_random_patterns, case_equal_languages, case_empty_string_can_distinguish,
    case_shortest_first, case_ties_follow_alphabet_order, case_random_pairs, case_performance_large_minimal_dfa,
    case_performance_larger_alphabet, case_performance_long_shortest_difference, case_performance_equal_large_languages,
]
