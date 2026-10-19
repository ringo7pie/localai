"""H2 shortest_edit_script の隠しテスト。モデルには見せない（形式は suites/coding/c1/tests.py と同じ）。

期待値は reference.py（後ろからの Myers + 先頭からの貪欲）で計算し、oracle.py の O(NM) の表と、
最短スクリプトの全列挙（とても小さい入力）と一致することを確かめた（tests/test_hard.py）。
"""

import itertools
import random

FORBIDDEN_CALLS = ("difflib", "difflib.SequenceMatcher", "difflib.unified_diff", "difflib.ndiff")


def _checksum(scripts):
    acc = 0
    for index, script in enumerate(scripts):
        for op in script:
            code = {"=": 1, "-": 2, "+": 3}.get(op[0], 9)
            for part in op[1:]:
                code = code * 10007 + int(part)
            acc = (acc * 1000003 + code) % ((1 << 61) - 1)
        acc = (acc * 1000003 + index + 7) % ((1 << 61) - 1)
    return acc


def _ses(sol, a, b):
    return [tuple(op) for op in sol.shortest_edit_script(list(a), list(b))]


def _edit(base, rng, count, vocab):
    out = list(base)
    for _ in range(count):
        op = rng.random()
        pos = rng.randrange(len(out) + 1)
        if op < 0.4 and out:
            out.pop(min(pos, len(out) - 1))
        elif op < 0.8:
            out.insert(pos, rng.choice(vocab))
        elif out:
            out[min(pos, len(out) - 1)] = rng.choice(vocab)
    return out


def case_examples(sol, t):
    t.eq(_ses(sol, ["a", "b", "c"], ["a", "c"]), [("=", 0, 0), ("-", 1), ("=", 2, 1)])
    t.eq(_ses(sol, ["x"], ["y"]), [("-", 0), ("+", 0)])
    t.eq(_ses(sol, ["a", "b"], ["b", "a"]), [("-", 0), ("=", 1, 0), ("+", 1)])
    t.eq(_ses(sol, ["a", "x", "a"], ["a"]), [("=", 0, 0), ("-", 1), ("-", 2)])
    t.eq(_ses(sol, [], ["p", "q"]), [("+", 0), ("+", 1)])


def case_empty_sides(sol, t):
    t.eq(_ses(sol, [], []), [])
    t.eq(_ses(sol, ["a", "b"], []), [("-", 0), ("-", 1)])
    t.eq(_ses(sol, [""], [""]), [("=", 0, 0)])


def case_identical(sol, t):
    lines = ["def f():", "    return 1", "", "x = f()"]
    t.eq(_ses(sol, lines, list(lines)), [("=", i, i) for i in range(4)])


def case_completely_different(sol, t):
    t.eq(_ses(sol, ["p", "q"], ["r", "s"]), [("-", 0), ("-", 1), ("+", 0), ("+", 1)])
    t.eq(_ses(sol, ["p"], ["r", "s", "t"]), [("-", 0), ("+", 0), ("+", 1), ("+", 2)])


def case_replaced_line_deletes_first(sol, t):
    t.eq(_ses(sol, ["a", "b", "c"], ["a", "x", "c"]), [("=", 0, 0), ("-", 1), ("+", 1), ("=", 2, 2)])
    t.eq(_ses(sol, ["a", "b", "b", "c"], ["a", "x", "y", "c"]),
         [("=", 0, 0), ("-", 1), ("-", 2), ("+", 1), ("+", 2), ("=", 3, 3)])


def case_repeated_lines_keep_early(sol, t):
    t.eq(_ses(sol, ["x"] * 3, ["x"] * 5), [("=", 0, 0), ("=", 1, 1), ("=", 2, 2), ("+", 3), ("+", 4)])
    t.eq(_ses(sol, ["x"] * 5, ["x"] * 2), [("=", 0, 0), ("=", 1, 1), ("-", 2), ("-", 3), ("-", 4)])
    t.eq(_ses(sol, ["y", "x", "x"], ["x", "x", "y"]), EXPECTED["rotate3"])


def case_greedy_match_must_stay_shortest(sol, t):
    # 先頭の "a" を残すと最短にならない
    t.eq(_ses(sol, ["a", "b", "c", "d"], ["b", "c", "d", "a"]), EXPECTED["move_first"])
    t.eq(_ses(sol, ["a", "x", "b", "x", "c"], ["x", "b", "x", "c", "a"]), EXPECTED["move_first2"])
    t.eq(_ses(sol, ["b", "a", "b", "a"], ["a", "b", "a", "b", "a"]), EXPECTED["alternate"])


def case_block_move(sol, t):
    a = [f"line {i}" for i in range(10)]
    t.eq(_ses(sol, a, a[6:] + a[:6]), EXPECTED["block_move"])


def case_result_is_list_of_tuples(sol, t):
    got = sol.shortest_edit_script(["a", "b"], ["b"])
    t.eq([tuple(op) for op in got], [("-", 0), ("=", 1, 0)])
    t.eq(all(type(op) is tuple for op in sol.shortest_edit_script(["a"], ["a", "b"])), True)


def case_exhaustive_tiny(sol, t):
    pairs = [(a, b) for la in range(5) for lb in range(5)
             for a in itertools.product("xy", repeat=la) for b in itertools.product("xy", repeat=lb)]
    t.eq(_checksum([_ses(sol, a, b) for a, b in pairs]), EXPECTED["exhaustive"])


def case_random_small(sol, t):
    rng = random.Random(81)
    scripts = []
    for _ in range(300):
        alpha = rng.choice(("ab", "abc", "abcdef"))
        a = [rng.choice(alpha) for _ in range(rng.randint(0, 20))]
        b = [rng.choice(alpha) for _ in range(rng.randint(0, 20))]
        scripts.append(_ses(sol, a, b))
    t.eq(_checksum(scripts), EXPECTED["random_small"])


def case_random_many_edits(sol, t):
    rng = random.Random(82)
    scripts = []
    for _ in range(12):
        a = [rng.choice("abcd") for _ in range(rng.randint(150, 300))]
        b = [rng.choice("abcd") for _ in range(rng.randint(150, 300))]
        scripts.append(_ses(sol, a, b))
    t.eq(_checksum(scripts), EXPECTED["random_many"])


def case_edits_near_both_ends(sol, t):
    a = [str(i) for i in range(40)]
    b = ["new"] + a[1:20] + ["mid"] + a[20:39] + ["end"]
    t.eq(_ses(sol, a, b), EXPECTED["ends"])


def case_performance_large_random_vocabulary(sol, t):
    rng = random.Random(91)
    vocab = [f"line {i}" for i in range(5000)]
    a = [rng.choice(vocab) for _ in range(5000)]
    b = _edit(a, rng, 30, vocab)
    t.eq(_checksum([_ses(sol, a, b)]), EXPECTED["perf_vocab"])


def case_performance_small_vocabulary(sol, t):
    rng = random.Random(92)
    a = [rng.choice("xyz") for _ in range(5000)]
    b = _edit(a, rng, 30, "xyz")
    t.eq(_checksum([_ses(sol, a, b)]), EXPECTED["perf_xyz"])


def case_performance_same_lines(sol, t):
    script = _ses(sol, ["same"] * 5000, ["same"] * 4950)
    t.eq(script, [("=", i, i) for i in range(4950)] + [("-", i) for i in range(4950, 5000)])


def case_performance_block_move(sol, t):
    a = [f"row {i}" for i in range(5000)]
    t.eq(_checksum([_ses(sol, a, a[50:] + a[:50])]), EXPECTED["perf_block"])


def case_performance_scattered_edits(sol, t):
    rng = random.Random(93)
    a = [rng.choice("abcdefgh") for _ in range(4800)]
    b = _edit(a, rng, 45, "abcdefgh")
    t.eq(_checksum([_ses(sol, a, b)]), EXPECTED["perf_scattered"])


EXPECTED = {
    'rotate3': [('-', 0), ('=', 1, 0), ('=', 2, 1), ('+', 2)],
    'move_first': [('-', 0), ('=', 1, 0), ('=', 2, 1), ('=', 3, 2), ('+', 3)],
    'move_first2': [('-', 0), ('=', 1, 0), ('=', 2, 1), ('=', 3, 2), ('=', 4, 3), ('+', 4)],
    'alternate': [('+', 0), ('=', 0, 1), ('=', 1, 2), ('=', 2, 3), ('=', 3, 4)],
    'block_move': [('+', 0), ('+', 1), ('+', 2), ('+', 3), ('=', 0, 4), ('=', 1, 5), ('=', 2, 6), ('=', 3, 7), ('=', 4, 8), ('=', 5, 9), ('-', 6), ('-', 7), ('-', 8), ('-', 9)],
    'exhaustive': 557166201308170701,
    'random_small': 463685689175005909,
    'random_many': 532847102243853764,
    'ends': [('-', 0), ('+', 0), ('=', 1, 1), ('=', 2, 2), ('=', 3, 3), ('=', 4, 4), ('=', 5, 5), ('=', 6, 6), ('=', 7, 7), ('=', 8, 8), ('=', 9, 9), ('=', 10, 10), ('=', 11, 11), ('=', 12, 12), ('=', 13, 13), ('=', 14, 14), ('=', 15, 15), ('=', 16, 16), ('=', 17, 17), ('=', 18, 18), ('=', 19, 19), ('+', 20), ('=', 20, 21), ('=', 21, 22), ('=', 22, 23), ('=', 23, 24), ('=', 24, 25), ('=', 25, 26), ('=', 26, 27), ('=', 27, 28), ('=', 28, 29), ('=', 29, 30), ('=', 30, 31), ('=', 31, 32), ('=', 32, 33), ('=', 33, 34), ('=', 34, 35), ('=', 35, 36), ('=', 36, 37), ('=', 37, 38), ('=', 38, 39), ('-', 39), ('+', 40)],
    'perf_vocab': 11689505232537131,
    'perf_xyz': 1872539836686804491,
    'perf_block': 1504179271719406417,
    'perf_scattered': 2287877057153705575,
}

CASES = [
    case_examples, case_empty_sides, case_identical, case_completely_different, case_replaced_line_deletes_first,
    case_repeated_lines_keep_early, case_greedy_match_must_stay_shortest, case_block_move, case_result_is_list_of_tuples,
    case_exhaustive_tiny, case_random_small, case_random_many_edits, case_edits_near_both_ends,
    case_performance_large_random_vocabulary, case_performance_small_vocabulary, case_performance_same_lines,
    case_performance_block_move, case_performance_scattered_edits,
]
