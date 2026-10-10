"""C2 next_run の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

2026-10-08 は木曜。期待値は、1 分ずつ全部を調べる別の実装（work の外には残していない）で照合した。
"""

from datetime import datetime as D

FORBIDDEN_CALLS = ()


def case_every_minute(sol, t):
    t.eq(sol.next_run("* * * * *", D(2026, 10, 8, 12, 30)), D(2026, 10, 8, 12, 31))
    t.eq(sol.next_run("* * * * *", D(2026, 10, 8, 12, 30, 15)), D(2026, 10, 8, 12, 31))
    t.eq(sol.next_run("* * * * *", D(2026, 10, 8, 23, 59, 59, 999999)), D(2026, 10, 9, 0, 0))


def case_same_minute_is_excluded(sol, t):
    t.eq(sol.next_run("30 12 * * *", D(2026, 10, 8, 12, 30)), D(2026, 10, 9, 12, 30))
    t.eq(sol.next_run("30 12 * * *", D(2026, 10, 8, 12, 30, 0, 1)), D(2026, 10, 9, 12, 30))
    t.eq(sol.next_run("30 12 * * *", D(2026, 10, 8, 12, 29, 59)), D(2026, 10, 8, 12, 30))


def case_fixed_minute_wraps_hour(sol, t):
    t.eq(sol.next_run("5 * * * *", D(2026, 10, 8, 12, 6)), D(2026, 10, 8, 13, 5))
    t.eq(sol.next_run("5 * * * *", D(2026, 10, 8, 12, 5)), D(2026, 10, 8, 13, 5))
    t.eq(sol.next_run("5 * * * *", D(2026, 10, 8, 12, 4)), D(2026, 10, 8, 12, 5))


def case_hour_range_wraps_day(sol, t):
    t.eq(sol.next_run("0 9-17 * * *", D(2026, 10, 8, 17, 0)), D(2026, 10, 9, 9, 0))
    t.eq(sol.next_run("0 9-17 * * *", D(2026, 10, 8, 8, 59)), D(2026, 10, 8, 9, 0))
    t.eq(sol.next_run("0 9-17 * * *", D(2026, 10, 8, 16, 59, 30)), D(2026, 10, 8, 17, 0))


def case_step_from_minimum(sol, t):
    t.eq(sol.next_run("*/15 * * * *", D(2026, 10, 8, 12, 0)), D(2026, 10, 8, 12, 15))
    t.eq(sol.next_run("*/20 * * * *", D(2026, 10, 8, 12, 41)), D(2026, 10, 8, 13, 0))
    t.eq(sol.next_run("*/7 * * * *", D(2026, 10, 8, 12, 50)), D(2026, 10, 8, 12, 56))
    t.eq(sol.next_run("*/7 * * * *", D(2026, 10, 8, 12, 56)), D(2026, 10, 8, 13, 0))
    t.eq(sol.next_run("0 */5 * * *", D(2026, 10, 8, 20, 0)), D(2026, 10, 9, 0, 0))


def case_range_with_step(sol, t):
    t.eq(sol.next_run("10-40/15 * * * *", D(2026, 10, 8, 12, 11)), D(2026, 10, 8, 12, 25))
    t.eq(sol.next_run("10-40/15 * * * *", D(2026, 10, 8, 12, 40)), D(2026, 10, 8, 13, 10))
    t.eq(sol.next_run("0-5/10 * * * *", D(2026, 10, 8, 12, 1)), D(2026, 10, 8, 13, 0))
    t.eq(sol.next_run("0 8-20/6 * * *", D(2026, 10, 8, 14, 0)), D(2026, 10, 8, 20, 0))


def case_lists_and_duplicates(sol, t):
    t.eq(sol.next_run("1,15-17,*/30 * * * *", D(2026, 10, 8, 12, 17)), D(2026, 10, 8, 12, 30))
    t.eq(sol.next_run("1,15-17,*/30 * * * *", D(2026, 10, 8, 12, 30)), D(2026, 10, 8, 13, 0))
    t.eq(sol.next_run("0,0,0 12,12 * * *", D(2026, 10, 8, 12, 0)), D(2026, 10, 9, 12, 0))
    t.eq(sol.next_run("*,5 * * * *", D(2026, 10, 8, 12, 30)), D(2026, 10, 8, 12, 31))


def case_month_names(sol, t):
    t.eq(sol.next_run("0 0 1 dec *", D(2026, 10, 8)), D(2026, 12, 1, 0, 0))
    t.eq(sol.next_run("0 0 1 feb-MAR *", D(2026, 10, 8)), D(2027, 2, 1, 0, 0))
    t.eq(sol.next_run("0 12 * JAN,jul Mon", D(2026, 10, 8)), D(2027, 1, 4, 12, 0))


def case_weekday_names(sol, t):
    t.eq(sol.next_run("0 9 * * mon-fri", D(2026, 10, 9, 9, 0)), D(2026, 10, 12, 9, 0))
    t.eq(sol.next_run("0 9 * * MON-FRI", D(2026, 10, 10, 0, 0)), D(2026, 10, 12, 9, 0))
    t.eq(sol.next_run("0 9 * * Fri-Sat", D(2026, 10, 8, 10, 0)), D(2026, 10, 9, 9, 0))


def case_sunday_as_seven(sol, t):
    t.eq(sol.next_run("0 0 * * 7", D(2026, 10, 8)), D(2026, 10, 11, 0, 0))
    t.eq(sol.next_run("0 0 * * 5-7", D(2026, 10, 8)), D(2026, 10, 9, 0, 0))
    t.eq(sol.next_run("0 0 * * 5-7", D(2026, 10, 11, 0, 0)), D(2026, 10, 16, 0, 0))
    t.eq(sol.next_run("0 0 * * 7-7", D(2026, 10, 8)), D(2026, 10, 11, 0, 0))
    t.eq(sol.next_run("0 0 * * 0", D(2026, 10, 11, 0, 0)), D(2026, 10, 18, 0, 0))


def case_day_only_restricted(sol, t):
    t.eq(sol.next_run("0 0 31 * *", D(2026, 9, 1)), D(2026, 10, 31, 0, 0))
    t.eq(sol.next_run("0 0 31 * *", D(2026, 10, 31)), D(2026, 12, 31, 0, 0))
    t.eq(sol.next_run("0 0 31 * *", D(2026, 12, 31)), D(2027, 1, 31, 0, 0))
    t.eq(sol.next_run("0 0 29-31 * *", D(2027, 2, 1)), D(2027, 3, 29, 0, 0))


def case_weekday_only_restricted(sol, t):
    t.eq(sol.next_run("30 6 * * 0", D(2026, 10, 8)), D(2026, 10, 11, 6, 30))
    t.eq(sol.next_run("30 6 * * 4", D(2026, 10, 8, 6, 30)), D(2026, 10, 15, 6, 30))


def case_both_restricted_means_or(sol, t):
    t.eq(sol.next_run("0 0 1 * 1", D(2026, 10, 8)), D(2026, 10, 12, 0, 0))
    t.eq(sol.next_run("0 0 1 * 1", D(2026, 10, 30)), D(2026, 11, 1, 0, 0))
    t.eq(sol.next_run("0 0 1 * 1", D(2026, 11, 1)), D(2026, 11, 2, 0, 0))
    t.eq(sol.next_run("0 0 13 * 5", D(2026, 10, 8)), D(2026, 10, 9, 0, 0))
    t.eq(sol.next_run("0 0 13 * 5", D(2026, 10, 9)), D(2026, 10, 13, 0, 0))


def case_step_in_day_field_is_restricted(sol, t):
    # `*/2` は「無指定」ではないので、曜日との OR になる（Vixie cron とは違う。仕様に明記）
    t.eq(sol.next_run("0 0 */2 * 1", D(2026, 10, 6)), D(2026, 10, 7, 0, 0))
    t.eq(sol.next_run("0 0 * * */2", D(2026, 10, 8)), D(2026, 10, 10, 0, 0))
    t.eq(sol.next_run("0 0 1 * */2", D(2026, 10, 8)), D(2026, 10, 10, 0, 0))
    t.eq(sol.next_run("0 0 1-31/30 * 1", D(2026, 10, 8)), D(2026, 10, 12, 0, 0))


def case_leap_day(sol, t):
    t.eq(sol.next_run("0 0 29 2 *", D(2026, 1, 1)), D(2028, 2, 29, 0, 0))
    t.eq(sol.next_run("0 0 29 2 *", D(2028, 2, 29)), D(2032, 2, 29, 0, 0))
    t.eq(sol.next_run("0 0 29 2 *", D(2096, 3, 1)), D(2104, 2, 29, 0, 0))


def case_impossible_dates_return_none(sol, t):
    t.eq(sol.next_run("30 4 30 2 *", D(2026, 1, 1)), None)
    t.eq(sol.next_run("0 0 31 4,6,9,11 *", D(2026, 1, 1)), None)
    t.eq(sol.next_run("0 0 31 FEB *", D(2026, 1, 1)), None)
    # 曜日との OR なので None にはならない（2026-02-02 は月曜）
    t.eq(sol.next_run("0 0 30 2 1", D(2026, 1, 1)), D(2026, 2, 2, 0, 0))


def case_year_boundary(sol, t):
    t.eq(sol.next_run("0 0 1 1 *", D(2026, 12, 31, 23, 59)), D(2027, 1, 1, 0, 0))
    t.eq(sol.next_run("59 23 31 12 *", D(2026, 12, 31, 23, 59)), D(2027, 12, 31, 23, 59))
    t.eq(sol.next_run("59 23 31 12 *", D(2026, 12, 31, 23, 58)), D(2026, 12, 31, 23, 59))


def case_leading_zeros_tabs_and_outer_spaces(sol, t):
    t.eq(sol.next_run("05\t09 * *\t*", D(2026, 10, 8)), D(2026, 10, 8, 9, 5))
    t.eq(sol.next_run(" 0 0 01 01 * ", D(2026, 10, 8)), D(2027, 1, 1, 0, 0))
    t.eq(sol.next_run("00 00 * * 007", D(2026, 10, 8)), D(2026, 10, 11, 0, 0))


def case_exact_match_time_boundaries(sol, t):
    t.eq(sol.next_run("0 12 * * *", D(2026, 10, 8, 12, 0, 0)), D(2026, 10, 9, 12, 0))
    t.eq(sol.next_run("0 12 * * *", D(2026, 10, 8, 11, 59, 59, 999999)), D(2026, 10, 8, 12, 0))
    t.eq(sol.next_run("0 0 1 1 *", D(2026, 1, 1, 0, 0)), D(2027, 1, 1, 0, 0))


def case_invalid_field_count(sol, t):
    for expression in ("* * * *", "* * * * * *", "", "   ", "0 0 1 1", "0 0 1 1 * extra"):
        t.raises(ValueError, sol.next_run, expression, D(2026, 10, 8))


def case_invalid_values(sol, t):
    for expression in ("60 * * * *", "* 24 * * *", "* * 0 * *", "* * 32 * *", "* * * 13 *", "* * * 0 *",
                       "* * * * 8", "-1 * * * *", "1.5 * * * *", "1e1 * * * *", "* * * * -1"):
        t.raises(ValueError, sol.next_run, expression, D(2026, 10, 8))


def case_invalid_syntax(sol, t):
    for expression in ("*/0 * * * *", "5/15 * * * *", "10-5 * * * *", "1,,2 * * * *", ",1 * * * *",
                       "1, * * * *", "*/ * * * *", "1-2-3 * * * *", "1- * * * *", "-5 * * * *",
                       "* * * * *,", "*/5/2 * * * *", "1-5/0 * * * *", "** * * * *", "* * * * MON-SUN"):
        t.raises(ValueError, sol.next_run, expression, D(2026, 10, 8))


def case_invalid_names_and_extensions(sol, t):
    for expression in ("* * * JANUARY *", "* * * * MONDAY", "JAN * * * *", "* * MON * *", "* MON * * *",
                       "* * * * FOO", "? * * * *", "* * L * *", "* * 15W * *", "@daily", "* * * * 1#2",
                       "0 0 * JAN-DEC/MON *"):
        t.raises(ValueError, sol.next_run, expression, D(2026, 10, 8))


def case_result_is_naive_datetime(sol, t):
    result = sol.next_run("0 0 * * *", D(2026, 10, 8, 1, 2, 3))
    t.eq(result, D(2026, 10, 9, 0, 0))
    t.eq(result.tzinfo, None)
    t.eq((result.second, result.microsecond), (0, 0))


def case_far_answers_are_fast(sol, t):
    # 答えが数年先。1 分ずつ全部を調べると、まとめて数百万回の判定になる
    for year in range(2025, 2037):
        expected_year = year + 1
        while not (expected_year % 4 == 0 and (expected_year % 100 != 0 or expected_year % 400 == 0)):
            expected_year += 1
        t.eq(sol.next_run("0 0 29 2 *", D(year, 3, 1)), D(expected_year, 2, 29, 0, 0))
    t.eq(sol.next_run("30 10 31 12 *", D(2026, 1, 1)), D(2026, 12, 31, 10, 30))
    t.eq(sol.next_run("0 0 1 1 *", D(2026, 1, 1, 0, 0)), D(2027, 1, 1, 0, 0))


def case_none_is_fast(sol, t):
    # 10 年ぶんを 1 分ずつ調べると 500 万回を超える
    t.eq(sol.next_run("0 0 30 2 *", D(2026, 1, 1)), None)
    t.eq(sol.next_run("0 0 31 2,4,6,9,11 *", D(2027, 6, 15, 12, 34, 56)), None)
    t.eq(sol.next_run("*/5 * 31 2 *", D(2030, 1, 1)), None)


CASES = [
    case_every_minute, case_same_minute_is_excluded, case_fixed_minute_wraps_hour, case_hour_range_wraps_day,
    case_step_from_minimum, case_range_with_step, case_lists_and_duplicates, case_month_names,
    case_weekday_names, case_sunday_as_seven, case_day_only_restricted, case_weekday_only_restricted,
    case_both_restricted_means_or, case_step_in_day_field_is_restricted, case_leap_day,
    case_impossible_dates_return_none, case_year_boundary, case_leading_zeros_tabs_and_outer_spaces,
    case_exact_match_time_boundaries, case_invalid_field_count, case_invalid_values, case_invalid_syntax,
    case_invalid_names_and_extensions, case_result_is_naive_datetime, case_far_answers_are_fast,
    case_none_is_fast,
]
