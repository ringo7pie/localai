"""C2 parse_duration の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

誤りの入力はまとめて 1 ケースにしている（どれか 1 つでも ValueError にならなければ不合格）。
"""

FORBIDDEN_CALLS = ()


def case_seconds_only(sol, t):
    t.eq(sol.parse_duration("45s"), 45)


def case_outer_spaces(sol, t):
    t.eq(sol.parse_duration("  10m  "), 600)


def case_all_units(sol, t):
    t.eq(sol.parse_duration("1d 1h 1m 1s"), 90061)


def case_zero(sol, t):
    t.eq(sol.parse_duration("0s"), 0)


def case_no_space(sol, t):
    t.eq(sol.parse_duration("1h30m"), 5400)


def case_large_value(sol, t):
    t.eq(sol.parse_duration("100m"), 6000)
    t.eq(sol.parse_duration("48h"), 172800)


def case_error_empty(sol, t):
    for text in ("", "   "):
        t.raises(ValueError, sol.parse_duration, text)


def case_error_unit(sol, t):
    for text in ("1x", "1H", "h", "5", "10min"):
        t.raises(ValueError, sol.parse_duration, text)


def case_error_order(sol, t):
    for text in ("30m 1h", "1h 2h", "1s1m", "2d 3d"):
        t.raises(ValueError, sol.parse_duration, text)


def case_error_format(sol, t):
    for text in ("1 h", "1.5h", "-1h", "1h,30m", "1h-30m"):
        t.raises(ValueError, sol.parse_duration, text)


CASES = [
    case_seconds_only, case_outer_spaces, case_all_units, case_zero, case_no_space, case_large_value,
    case_error_empty, case_error_unit, case_error_order, case_error_format,
]
