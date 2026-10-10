"""C1 is_balanced の隠しテスト。モデルには見せない。

harness.py がサンドボックスの中で読み、CASES を順に `case(sol, t)` で呼ぶ。sol は答えのモジュール、
t は判定の補助（t.eq / t.raises / t.close）。1 ケース = 1 点で、合格したケースの割合が点数になる。
"""

FORBIDDEN_CALLS = ()


def case_empty(sol, t):
    t.eq(sol.is_balanced(""), True)


def case_single_open(sol, t):
    t.eq(sol.is_balanced("("), False)


def case_single_close(sol, t):
    t.eq(sol.is_balanced(")"), False)


def case_unclosed(sol, t):
    t.eq(sol.is_balanced("(()"), False)


def case_nested_ok(sol, t):
    t.eq(sol.is_balanced("{[()()]}"), True)


def case_no_brackets(sol, t):
    t.eq(sol.is_balanced("abc"), True)


def case_wrong_kind(sol, t):
    t.eq(sol.is_balanced("(]"), False)


def case_crossing(sol, t):
    t.eq(sol.is_balanced("({)}"), False)


def case_close_before_open(sol, t):
    t.eq(sol.is_balanced("x)("), False)


def case_angle_ignored(sol, t):
    # < と > は括弧として扱わない（仕様に明記）
    t.eq(sol.is_balanced("<(>)"), True)


def case_deep_ok(sol, t):
    # 再帰で書くと深さ 50,000 で落ちる。仕様の上限 100,000 文字に収まる
    t.eq(sol.is_balanced("(" * 50000 + ")" * 50000), True)


def case_deep_bad(sol, t):
    t.eq(sol.is_balanced("[" * 50000 + "]" * 49999 + ")"), False)


CASES = [
    case_empty, case_single_open, case_single_close, case_unclosed, case_nested_ok, case_no_brackets,
    case_wrong_kind, case_crossing, case_close_before_open, case_angle_ignored, case_deep_ok, case_deep_bad,
]
