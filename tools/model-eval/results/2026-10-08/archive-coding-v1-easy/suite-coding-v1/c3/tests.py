"""C3 merge_intervals の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

戻り値の型（タプルのリスト）は case_returns_tuples だけで見る。ほかのケースは要素をタプルに直してから比べる。
"""

import random

FORBIDDEN_CALLS = ()


def _as_tuples(result):
    return [tuple(pair) for pair in result]


def _reference(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(pair) for pair in merged]


def case_empty(sol, t):
    t.eq(_as_tuples(sol.merge_intervals([])), [])


def case_single_point(sol, t):
    t.eq(_as_tuples(sol.merge_intervals([(5, 5)])), [(5, 5)])


def case_unsorted(sol, t):
    t.eq(_as_tuples(sol.merge_intervals([(8, 10), (1, 3), (2, 6)])), [(1, 6), (8, 10)])


def case_nested(sol, t):
    t.eq(_as_tuples(sol.merge_intervals([(1, 10), (2, 3), (4, 5)])), [(1, 10)])


def case_not_touching(sol, t):
    # 整数で隣り合っていても、端が等しくなければ別の区間（仕様の「接する」の定義）
    t.eq(_as_tuples(sol.merge_intervals([(1, 2), (3, 4)])), [(1, 2), (3, 4)])


def case_negative(sol, t):
    t.eq(_as_tuples(sol.merge_intervals([(-5, -1), (-2, 3)])), [(-5, 3)])


def case_duplicates(sol, t):
    t.eq(_as_tuples(sol.merge_intervals([(1, 3), (1, 3), (1, 3)])), [(1, 3)])


def case_input_unchanged(sol, t):
    data = [(3, 4), (1, 2), (2, 3)]
    snapshot = list(data)
    result = sol.merge_intervals(data)
    t.eq(data, snapshot)
    t.eq(_as_tuples(result), [(1, 4)])


def case_returns_tuples(sol, t):
    result = sol.merge_intervals([(1, 3), (2, 4), (6, 7)])
    t.eq(type(result).__name__, "list")
    t.eq([type(pair).__name__ for pair in result], ["tuple", "tuple"])
    t.eq(result, [(1, 4), (6, 7)])


def case_value_error(sol, t):
    t.raises(ValueError, sol.merge_intervals, [(1, 2), (5, 3)])


def case_large_random(sol, t):
    rng = random.Random(20261008)
    data = []
    for _ in range(100000):
        start = rng.randint(-1000000, 1000000)
        data.append((start, start + rng.randint(0, 40)))
    t.eq(_as_tuples(sol.merge_intervals(data)), _reference(data))


CASES = [
    case_empty, case_single_point, case_unsorted, case_nested, case_not_touching, case_negative,
    case_duplicates, case_input_unchanged, case_returns_tuples, case_value_error, case_large_random,
]
