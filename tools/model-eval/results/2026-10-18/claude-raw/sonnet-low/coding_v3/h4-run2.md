```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0 or max_den < 1 or side not in (-1, 0, 1):
        raise ValueError("invalid argument")
    if den < 0:
        num, den = -num, -den
    divisor = gcd(num, den)
    num //= divisor
    den //= divisor
    if den <= max_den:
        return (num, den)

    floor_value = num // den
    lo_p, lo_q = floor_value, 1
    hi_p, hi_q = floor_value + 1, 1

    while True:
        moved = False
        # hi を lo に近づける
        gap_hi = hi_p * den - num * hi_q
        gap_lo = num * lo_q - lo_p * den
        step = min((gap_hi - 1) // gap_lo, (max_den - hi_q) // lo_q)
        if step > 0:
            hi_p += step * lo_p
            hi_q += step * lo_q
            moved = True
        # lo を hi に近づける
        gap_hi = hi_p * den - num * hi_q
        gap_lo = num * lo_q - lo_p * den
        step = min((gap_lo - 1) // gap_hi, (max_den - lo_q) // hi_q)
        if step > 0:
            lo_p += step * hi_p
            lo_q += step * hi_q
            moved = True
        if not moved:
            break

    if side == -1:
        return (lo_p, lo_q)
    if side == 1:
        return (hi_p, hi_q)

    gap_hi = hi_p * den - num * hi_q
    gap_lo = num * lo_q - lo_p * den
    # 距離: lo は gap_lo / (den*lo_q)、hi は gap_hi / (den*hi_q)
    left = gap_lo * hi_q
    right = gap_hi * lo_q
    if left < right:
        return (lo_p, lo_q)
    if left > right:
        return (hi_p, hi_q)
    if hi_q < lo_q:
        return (hi_p, hi_q)
    return (lo_p, lo_q)
```
