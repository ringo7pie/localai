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
    divisor = gcd(num, den)
    num //= divisor
    den //= divisor

    if den <= max_den:
        return (num, den)

    # ここでは x は整数ではなく、既約分数の分母 den は max_den より大きい。
    # lo < x < hi を保ったまま、Stern-Brocot 木を一度に k 段ずつ進める。
    floor_value = num // den
    lo_p, lo_q = floor_value, 1
    hi_p, hi_q = floor_value + 1, 1

    while True:
        moved = False

        # lo を hi 方向へ: (lo_p + k*hi_p) / (lo_q + k*hi_q) <= x となる最大の k
        gap_lo = num * lo_q - lo_p * den   # > 0
        gap_hi = hi_p * den - num * hi_q   # > 0
        k_value = gap_lo // gap_hi
        k_den = (max_den - lo_q) // hi_q
        k_step = min(k_value, k_den)
        if k_step > 0:
            lo_p += k_step * hi_p
            lo_q += k_step * hi_q
            moved = True

        # hi を lo 方向へ: (hi_p + k*lo_p) / (hi_q + k*lo_q) >= x となる最大の k
        gap_lo = num * lo_q - lo_p * den
        gap_hi = hi_p * den - num * hi_q
        k_value = gap_hi // gap_lo
        k_den = (max_den - hi_q) // lo_q
        k_step = min(k_value, k_den)
        if k_step > 0:
            hi_p += k_step * lo_p
            hi_q += k_step * lo_q
            moved = True

        if not moved:
            break

    if side == -1:
        return (lo_p, lo_q)
    if side == 1:
        return (hi_p, hi_q)

    gap_lo = num * lo_q - lo_p * den   # x - lo = gap_lo / (den * lo_q)
    gap_hi = hi_p * den - num * hi_q   # hi - x = gap_hi / (den * hi_q)
    left = gap_lo * hi_q
    right = gap_hi * lo_q
    if left < right:
        return (lo_p, lo_q)
    if right < left:
        return (hi_p, hi_q)
    # 同じ距離: q が小さい方、同じなら p が小さい方（lo）
    if hi_q < lo_q:
        return (hi_p, hi_q)
    return (lo_p, lo_q)
```
