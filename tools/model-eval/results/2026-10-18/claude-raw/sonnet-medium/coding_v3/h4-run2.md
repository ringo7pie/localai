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

    floor_value = num // den
    lo_n, lo_d = floor_value, 1
    hi_n, hi_d = floor_value + 1, 1

    while True:
        # lo を hi 方向へ動かす: lo + k*hi <= x かつ分母が上限以内の最大の k
        a_gap = num * lo_d - lo_n * den   # x - lo (スケール済み, > 0)
        b_gap = hi_n * den - num * hi_d   # hi - x (スケール済み, > 0)
        k_lo = min(a_gap // b_gap, (max_den - lo_d) // hi_d)
        if k_lo > 0:
            lo_n += k_lo * hi_n
            lo_d += k_lo * hi_d
            a_gap = num * lo_d - lo_n * den
        # hi を lo 方向へ動かす: hi + k*lo >= x かつ分母が上限以内の最大の k
        k_hi = min(b_gap // a_gap, (max_den - hi_d) // lo_d)
        if k_hi > 0:
            hi_n += k_hi * lo_n
            hi_d += k_hi * lo_d
        if k_lo == 0 and k_hi == 0:
            break

    if side == -1:
        return (lo_n, lo_d)
    if side == 1:
        return (hi_n, hi_d)

    a_gap = num * lo_d - lo_n * den
    b_gap = hi_n * den - num * hi_d
    left = a_gap * hi_d
    right = b_gap * lo_d
    if left < right:
        return (lo_n, lo_d)
    if left > right:
        return (hi_n, hi_d)
    if lo_d <= hi_d:
        return (lo_n, lo_d)
    return (hi_n, hi_d)
```
