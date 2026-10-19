"""H4 best_rational の参照解（Stern–Brocot 木をまとめて下りる。整数だけ）。"""


def _bounds(num, den, max_den):
    """x = num/den（den > 0）の、分母 max_den 以下の最良の下側 L と上側 U（既約）。x が表せれば L = U = x。"""

    whole = num // den
    rest = num - whole * den  # 0 <= rest < den
    if rest == 0:
        return (whole, 1), (whole, 1)
    # y = rest/den は (0, 1) の中。左の端 0/1、右の端 1/1 から下りる
    lp, lq, rp, rq = 0, 1, 1, 1
    while True:
        mp, mq = lp + rp, lq + rq
        if mq > max_den:
            break
        lhs, rhs = mp * den, rest * mq
        if lhs == rhs:
            return (whole * mq + mp, mq), (whole * mq + mp, mq)
        if lhs < rhs:
            # 中間の分数は y より小さい: 左の端を右へ k 段まとめて動かす（(lp + k rp)/(lq + k rq) < y を保つ最大の k）
            gap_left = rest * lq - lp * den      # > 0
            gap_right = rp * den - rest * rq     # > 0
            k_value = (gap_left - 1) // gap_right
            k_den = (max_den - lq) // rq
            step = min(k_value, k_den)
            lp, lq = lp + step * rp, lq + step * rq
            if step == k_den:
                break
        else:
            gap_left = rest * lq - lp * den
            gap_right = rp * den - rest * rq
            k_value = (gap_right - 1) // gap_left
            k_den = (max_den - rq) // lq
            step = min(k_value, k_den)
            rp, rq = rp + step * lp, rq + step * lq
            if step == k_den:
                break
    return (whole * lq + lp, lq), (whole * rq + rp, rq)


def best_rational(num, den, max_den, side=0):
    if den == 0:
        raise ValueError("den must not be 0")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")
    if den < 0:
        num, den = -num, -den
    lower, upper = _bounds(num, den, max_den)
    if side == -1:
        return lower
    if side == 1:
        return upper
    if lower == upper:
        return lower
    # |x - L| と |U - x| を比べる（通分して整数で）
    dist_lower = (num * lower[1] - lower[0] * den) * upper[1]
    dist_upper = (upper[0] * den - num * upper[1]) * lower[1]
    if dist_lower < dist_upper:
        return lower
    if dist_upper < dist_lower:
        return upper
    return min(lower, upper, key=lambda frac: (frac[1], frac[0]))
