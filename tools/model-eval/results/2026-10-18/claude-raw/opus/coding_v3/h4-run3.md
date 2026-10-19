```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    if den < 0:
        num, den = -num, -den
    common = gcd(num, den)
    num //= common
    den //= common

    if den <= max_den:
        return (num, den)

    # 連分数展開で、分母が max_den を超える直前の収束子まで進める
    p0, q0, p1, q1 = 0, 1, 1, 0
    numer, denom = num, den
    while True:
        quotient = numer // denom
        q2 = q0 + quotient * q1
        if q2 > max_den:
            break
        p0, q0, p1, q1 = p1, q1, p0 + quotient * p1, q2
        numer, denom = denom, numer - quotient * denom

    # 中間近似分数（semiconvergent）で分母の上限まで寄せる
    steps = (max_den - q0) // q1
    cand_a = (p0 + steps * p1, q0 + steps * q1)
    cand_b = (p1, q1)

    # 2 つは x を挟む隣接 Farey 分数（どちらも既約）
    if cand_a[0] * cand_b[1] < cand_b[0] * cand_a[1]:
        lower, upper = cand_a, cand_b
    else:
        lower, upper = cand_b, cand_a

    if side == -1:
        return lower
    if side == 1:
        return upper

    low_p, low_q = lower
    up_p, up_q = upper
    # x - lower = (num*low_q - low_p*den) / (den*low_q)
    # upper - x = (up_p*den - num*up_q) / (den*up_q)
    dist_low = (num * low_q - low_p * den) * up_q
    dist_up = (up_p * den - num * up_q) * low_q
    if dist_low < dist_up:
        return lower
    if dist_up < dist_low:
        return upper
    if low_q < up_q:
        return lower
    if up_q < low_q:
        return upper
    return lower
```
