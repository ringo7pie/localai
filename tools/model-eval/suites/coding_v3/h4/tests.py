"""H4 best_rational の隠しテスト。モデルには見せない（形式は suites/coding/c1/tests.py と同じ）。

期待値は reference.py で計算し、小さい入力は oracle.py（分母を 1 つずつ調べる総当たり）と一致することを
tests/test_hard.py で確かめている。乱数の束は種を固定し、答えの列のチェックサムで比べる。
"""

import random

FORBIDDEN_CALLS = ("fractions", "fractions.Fraction", "decimal", "decimal.Decimal")

BIG = 10 ** 40


def _checksum(pairs):
    acc = 0
    for index, (p, q) in enumerate(pairs):
        acc = (acc * 1000003 + (p % (1 << 61)) * 7 + q * 13 + index) % ((1 << 61) - 1)
    return acc


def _small_batch(seed, side):
    rng = random.Random(seed)
    args = []
    for _ in range(300):
        den = rng.choice((1, -1)) * rng.randint(1, 500)
        args.append((rng.randint(-3000, 3000), den, rng.randint(1, 150), side))
    return args


def _big_batch(seed, count):
    rng = random.Random(seed)
    args = []
    for _ in range(count):
        den = rng.choice((1, -1)) * rng.randint(1, BIG)
        args.append((rng.randint(-BIG, BIG), den, rng.randint(1, BIG), rng.choice((-1, 0, 1))))
    return args


def _run(sol, args):
    return [tuple(sol.best_rational(*arg)) for arg in args]


def case_examples(sol, t):
    t.eq(tuple(sol.best_rational(314159, 100000, 100)), (311, 99))
    t.eq(tuple(sol.best_rational(1, 2, 1)), (0, 1))
    t.eq(tuple(sol.best_rational(-1, 2, 1)), (-1, 1))
    t.eq(tuple(sol.best_rational(314159, 100000, 100, side=1)), (22, 7))
    t.eq(tuple(sol.best_rational(6, -4, 10)), (-3, 2))


def case_exact_value_is_returned_reduced(sol, t):
    t.eq(tuple(sol.best_rational(3, 4, 4)), (3, 4))
    t.eq(tuple(sol.best_rational(6, 8, 4)), (3, 4))
    t.eq(tuple(sol.best_rational(6, 8, 100, -1)), (3, 4))
    t.eq(tuple(sol.best_rational(6, 8, 100, 1)), (3, 4))
    t.eq(tuple(sol.best_rational(-14, 21, 3)), (-2, 3))


def case_integers_and_zero(sol, t):
    t.eq(tuple(sol.best_rational(10, 5, 1)), (2, 1))
    t.eq(tuple(sol.best_rational(-7, 1, 3)), (-7, 1))
    t.eq(tuple(sol.best_rational(0, 5, 7)), (0, 1))
    t.eq(tuple(sol.best_rational(0, -3, 1, 1)), (0, 1))
    t.eq(tuple(sol.best_rational(0, -3, 1, -1)), (0, 1))


def case_max_den_one(sol, t):
    t.eq(tuple(sol.best_rational(7, 3, 1)), (2, 1))
    t.eq(tuple(sol.best_rational(7, 3, 1, -1)), (2, 1))
    t.eq(tuple(sol.best_rational(7, 3, 1, 1)), (3, 1))
    t.eq(tuple(sol.best_rational(5, 2, 1)), (2, 1))
    t.eq(tuple(sol.best_rational(-5, 2, 1)), (-3, 1))


def case_negative_values_and_sides(sol, t):
    t.eq(tuple(sol.best_rational(1, -3, 2)), (-1, 2))
    t.eq(tuple(sol.best_rational(-1, 3, 2, -1)), (-1, 2))
    t.eq(tuple(sol.best_rational(-1, 3, 2, 1)), (0, 1))
    t.eq(tuple(sol.best_rational(-314159, 100000, 100)), (-311, 99))
    t.eq(tuple(sol.best_rational(-314159, 100000, 100, -1)), (-22, 7))
    t.eq(tuple(sol.best_rational(314159, -100000, 100, 1)), (-311, 99))


def case_ties_prefer_smaller_denominator(sol, t):
    # 5/12 は 1/3 と 1/2 のちょうど中間。分母の小さい 1/2
    t.eq(tuple(sol.best_rational(5, 12, 3)), (1, 2))
    t.eq(tuple(sol.best_rational(-5, 12, 3)), (-1, 2))
    # 7/12 は 1/2 と 2/3 の中間
    t.eq(tuple(sol.best_rational(7, 12, 3)), (1, 2))
    # 11/20 は 1/2 と 3/5 の中間（分母 5 以下で隣り合う）
    t.eq(tuple(sol.best_rational(11, 20, 5)), (1, 2))
    t.eq(tuple(sol.best_rational(-11, 20, 5)), (-1, 2))


def case_ties_same_denominator_smaller_numerator(sol, t):
    t.eq(tuple(sol.best_rational(3, 2, 1)), (1, 1))
    t.eq(tuple(sol.best_rational(-3, 2, 1)), (-2, 1))
    t.eq(tuple(sol.best_rational(1, 4, 2)), (0, 1))
    # -1/4 は -1/2 と 0/1 の中間。分母の小さい 0/1
    t.eq(tuple(sol.best_rational(-1, 4, 2)), (0, 1))


def case_semiconvergents_are_needed(sol, t):
    # 3.14159265358979 の分母 57 以下の最良は半収束分数 179/57（収束分数 22/7 ではない）
    t.eq(tuple(sol.best_rational(314159265358979, 100000000000000, 57)), (179, 57))
    t.eq(tuple(sol.best_rational(314159265358979, 100000000000000, 60)), (179, 57))
    t.eq(tuple(sol.best_rational(314159265358979, 100000000000000, 112)), (333, 106))
    t.eq(tuple(sol.best_rational(314159265358979, 100000000000000, 113)), (355, 113))
    t.eq(tuple(sol.best_rational(314159265358979, 100000000000000, 16603)), (355, 113))


def case_one_sided_semiconvergents(sol, t):
    x = (314159265358979, 100000000000000)
    t.eq(tuple(sol.best_rational(*x, 57, -1)), (179, 57))
    t.eq(tuple(sol.best_rational(*x, 57, 1)), (22, 7))
    t.eq(tuple(sol.best_rational(*x, 112, 1)), (22, 7))
    t.eq(tuple(sol.best_rational(*x, 113, 1)), (355, 113))
    t.eq(tuple(sol.best_rational(*x, 113, -1)), (333, 106))


def case_value_errors(sol, t):
    t.raises(ValueError, sol.best_rational, 1, 0, 5)
    t.raises(ValueError, sol.best_rational, 1, 3, 0)
    t.raises(ValueError, sol.best_rational, 1, 3, -4)
    t.raises(ValueError, sol.best_rational, 1, 3, 5, 2)
    t.raises(ValueError, sol.best_rational, 1, 3, 5, -2)


def case_result_is_reduced_int_tuple(sol, t):
    for arg in ((10, 4, 9), (-10, 4, 9), (99, 100, 50, -1), (99, 100, 50, 1), (2, 6, 1000)):
        p, q = sol.best_rational(*arg)
        t.eq(type(p) is int and type(q) is int, True)
        t.eq(q >= 1, True)
        a, b = abs(p), q
        while b:
            a, b = b, a % b
        t.eq(a, 1)


def case_small_random_nearest(sol, t):
    t.eq(_checksum(_run(sol, _small_batch(11, 0))), EXPECTED["small_nearest"])


def case_small_random_lower(sol, t):
    t.eq(_checksum(_run(sol, _small_batch(12, -1))), EXPECTED["small_lower"])


def case_small_random_upper(sol, t):
    t.eq(_checksum(_run(sol, _small_batch(13, 1))), EXPECTED["small_upper"])


def case_floats_are_not_precise_enough(sol, t):
    # 10**30 + 1 を 10**30 で割った値は float では 1.0。分母の上限 10**30 なら厳密な値そのもの
    t.eq(tuple(sol.best_rational(10 ** 30 + 1, 10 ** 30, 10 ** 30)), (10 ** 30 + 1, 10 ** 30))
    t.eq(tuple(sol.best_rational(10 ** 30 + 1, 10 ** 30, 10 ** 29)), (1, 1))
    t.eq(tuple(sol.best_rational(10 ** 30 + 1, 10 ** 30, 10 ** 29, 1)), (10 ** 29 + 1, 10 ** 29))
    t.eq(tuple(sol.best_rational(10 ** 30 - 1, 10 ** 30, 10 ** 29, -1)), (10 ** 29 - 1, 10 ** 29))


def case_tiny_and_huge_values(sol, t):
    t.eq(tuple(sol.best_rational(1, BIG, BIG // 10)), (0, 1))
    t.eq(tuple(sol.best_rational(1, BIG, BIG // 10, 1)), (1, BIG // 10))
    t.eq(tuple(sol.best_rational(BIG, 1, 7)), (BIG, 1))
    t.eq(tuple(sol.best_rational(BIG * 3 + 1, 3, 2)), (2 * BIG + 1, 2))
    t.eq(tuple(sol.best_rational(BIG * 3 + 1, 3, 2, -1)), (BIG, 1))
    t.eq(tuple(sol.best_rational(-1, BIG, BIG // 10, -1)), (-1, BIG // 10))


def case_fibonacci_ratios(sol, t):
    fib = [1, 1]
    while len(fib) < 200:
        fib.append(fib[-1] + fib[-2])
    # 黄金比に近い F(199)/F(198) の、分母 F(k) 以下の最良は F(k+1)/F(k)
    for k in (5, 20, 60, 120, 190):
        t.eq(tuple(sol.best_rational(fib[199], fib[198], fib[k])), (fib[k + 1], fib[k]))


def case_sqrt2_approximations(sol, t):
    num, den = EXPECTED["sqrt2_x"]
    got = [tuple(sol.best_rational(num, den, 10 ** k, side)) for k in (3, 9, 18, 30) for side in (-1, 0, 1)]
    t.eq(_checksum(got), EXPECTED["sqrt2"])


def case_performance_far_from_simple_fractions(sol, t):
    # 1 段ずつ下りると 10**39 段かかる入力
    t.eq(tuple(sol.best_rational(1, BIG, BIG - 1, 1)), (1, BIG - 1))
    t.eq(tuple(sol.best_rational(BIG - 1, BIG, BIG // 3, -1)), (BIG // 3 - 1, BIG // 3))
    t.eq(tuple(sol.best_rational(2 * BIG + 1, BIG, BIG - 1)), (2 * BIG - 1, BIG - 1))
    t.eq(tuple(sol.best_rational(2 * BIG + 1, BIG, BIG - 1, -1)), (2, 1))
    t.eq(tuple(sol.best_rational(2 * BIG + 1, BIG, BIG - 1, 1)), (2 * BIG - 1, BIG - 1))


def case_performance_big_random_batch(sol, t):
    t.eq(_checksum(_run(sol, _big_batch(21, 1500))), EXPECTED["big_a"])


def case_performance_big_random_batch_negative_dens(sol, t):
    t.eq(_checksum(_run(sol, _big_batch(22, 1500))), EXPECTED["big_b"])


EXPECTED = {
    "small_nearest": 1711314544632677354, "small_lower": 1462374690503983648, "small_upper": 56162887021734051,
    "sqrt2_x": (14142135623730950488016887242096980785696, 10000000000000000000000000000000000000000),
    "sqrt2": 1684979878832231977, "big_a": 229010097546217820, "big_b": 1134393567835406225,
}

CASES = [
    case_examples, case_exact_value_is_returned_reduced, case_integers_and_zero, case_max_den_one,
    case_negative_values_and_sides, case_ties_prefer_smaller_denominator, case_ties_same_denominator_smaller_numerator,
    case_semiconvergents_are_needed, case_one_sided_semiconvergents, case_value_errors, case_result_is_reduced_int_tuple,
    case_small_random_nearest, case_small_random_lower, case_small_random_upper, case_floats_are_not_precise_enough,
    case_tiny_and_huge_values, case_fibonacci_ratios, case_sqrt2_approximations,
    case_performance_far_from_simple_fractions, case_performance_big_random_batch,
    case_performance_big_random_batch_negative_dens,
]
