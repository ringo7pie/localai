"""C5 evaluate の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

eval / exec / compile の呼び出しは、実行の前に静的な走査で見つけて 0 点にする（FORBIDDEN_CALLS）。
"""

FORBIDDEN_CALLS = ("eval", "exec", "compile")


def case_precedence(sol, t):
    t.close(sol.evaluate("1 + 2 * 3"), 7)
    t.close(sol.evaluate("2 + 3 * 4 - 6 / 2"), 11)


def case_parentheses(sol, t):
    t.close(sol.evaluate("(1 + 2) * 3"), 9)


def case_true_division(sol, t):
    t.close(sol.evaluate("10 / 4"), 2.5)
    t.close(sol.evaluate("7 / 2"), 3.5)


def case_left_associative(sol, t):
    t.close(sol.evaluate("8 - 3 - 2"), 3)
    t.close(sol.evaluate("16 / 4 / 2"), 2)


def case_unary_minus(sol, t):
    t.close(sol.evaluate("2 * -3"), -6)
    t.close(sol.evaluate("-(2 + 3) * 2"), -10)


def case_repeated_unary(sol, t):
    t.close(sol.evaluate("--3"), 3)
    t.close(sol.evaluate("3 - -3"), 6)


def case_decimals(sol, t):
    t.close(sol.evaluate("0.5 * 4"), 2)
    t.close(sol.evaluate("1.25 + 0.75"), 2)


def case_spaces_and_nesting(sol, t):
    t.close(sol.evaluate("  7  "), 7)
    t.close(sol.evaluate("((((1))))"), 1)
    t.close(sol.evaluate("(1+2)*(3-(4/(2)))"), 3)


def case_zero_division(sol, t):
    t.raises(ZeroDivisionError, sol.evaluate, "1 / 0")
    t.raises(ZeroDivisionError, sol.evaluate, "5 / (2 - 2)")


def case_error_structure(sol, t):
    for text in ("", "   ", "(1 + 2", "1 + 2)", "1 +", "* 2", "()"):
        t.raises(ValueError, sol.evaluate, text)


def case_error_tokens(sol, t):
    for text in ("1 2", "2 * * 3", "2 ** 3", "abc", "1 + x", "+3", "2 ^ 3"):
        t.raises(ValueError, sol.evaluate, text)


def case_error_decimal_format(sol, t):
    for text in ("3.", ".5", "1.2.3"):
        t.raises(ValueError, sol.evaluate, text)


def case_long_expression(sol, t):
    t.close(sol.evaluate("1 + " * 999 + "1"), 1000)
    t.close(sol.evaluate("(" * 150 + "2" + ")" * 150), 2)


CASES = [
    case_precedence, case_parentheses, case_true_division, case_left_associative, case_unary_minus,
    case_repeated_unary, case_decimals, case_spaces_and_nesting, case_zero_division, case_error_structure,
    case_error_tokens, case_error_decimal_format, case_long_expression,
]
