"""H4 の総当たりのオラクル（分母を 1 つずつ調べる。小さい max_den だけ）。参照解とは別の作り。"""

from fractions import Fraction


def best_rational_brute(num, den, max_den, side=0):
    if den == 0 or max_den < 1 or side not in (-1, 0, 1):
        raise ValueError
    x = Fraction(num, den)
    candidates = set()
    for q in range(1, max_den + 1):
        p = (x * q).numerator // (x * q).denominator  # floor
        for pp in (p - 1, p, p + 1, p + 2):
            candidates.add(Fraction(pp, q))
    if side == -1:
        best = max(c for c in candidates if c <= x)
    elif side == 1:
        best = min(c for c in candidates if c >= x)
    else:
        best = min(candidates, key=lambda c: (abs(c - x), c.denominator, c.numerator))
    return best.numerator, best.denominator
