```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must be nonzero")
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
    n, d = num, den
    a0 = n // d
    lp, lq = a0, 1
    hp, hq = a0 + 1, 1
    while True:
        moved = False
        # move lo toward x
        gap_hi = hp * d - n * hq  # > 0
        gap_lo = n * lq - lp * d  # > 0
        k = (gap_lo - 1) // gap_hi
        k = min(k, (max_den - lq) // hq)
        if k > 0:
            lp, lq = lp + k * hp, lq + k * hq
            moved = True
        gap_hi = hp * d - n * hq
        gap_lo = n * lq - lp * d
        k = (gap_hi - 1) // gap_lo
        k = min(k, (max_den - hq) // lq)
        if k > 0:
            hp, hq = hp + k * lp, hq + k * lq
            moved = True
        if not moved:
            break
    if side == -1:
        return (lp, lq)
    if side == 1:
        return (hp, hq)
    gap_lo = n * lq - lp * d
    gap_hi = hp * d - n * hq
    left = gap_lo * hq
    right = gap_hi * lq
    if left < right:
        return (lp, lq)
    if right < left:
        return (hp, hq)
    if lq < hq:
        return (lp, lq)
    if hq < lq:
        return (hp, hq)
    return (lp, lq)
```
