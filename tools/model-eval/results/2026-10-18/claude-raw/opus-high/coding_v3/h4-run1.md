```python
import math


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    if den < 0:
        num, den = -num, -den
    divisor = math.gcd(num, den)
    num //= divisor
    den //= divisor

    if den <= max_den:
        return (num, den)

    # x is not an integer here (den >= 2). Start with the integer neighbours.
    base = num // den
    lo_p, lo_q = base, 1
    hi_p, hi_q = base + 1, 1

    while True:
        med_q = lo_q + hi_q
        if med_q > max_den:
            break
        med_p = lo_p + hi_p
        # A = (x - lo) * den * lo_q > 0, B = (hi - x) * den * hi_q > 0
        dist_lo = num * lo_q - lo_p * den
        dist_hi = hi_p * den - num * hi_q
        if med_p * den < num * med_q:
            # mediant below x: move lo toward hi by k steps (lo + k*hi)
            steps = min((dist_lo - 1) // dist_hi, (max_den - lo_q) // hi_q)
            lo_p += steps * hi_p
            lo_q += steps * hi_q
        else:
            # mediant above x (equality impossible since den > max_den)
            steps = min((dist_hi - 1) // dist_lo, (max_den - hi_q) // lo_q)
            hi_p += steps * lo_p
            hi_q += steps * lo_q

    if side == -1:
        return (lo_p, lo_q)
    if side == 1:
        return (hi_p, hi_q)

    dist_lo = num * lo_q - lo_p * den  # (x - lo) = dist_lo / (den * lo_q)
    dist_hi = hi_p * den - num * hi_q  # (hi - x) = dist_hi / (den * hi_q)
    left = dist_lo * hi_q
    right = dist_hi * lo_q
    if left < right:
        return (lo_p, lo_q)
    if right < left:
        return (hi_p, hi_q)
    if lo_q < hi_q:
        return (lo_p, lo_q)
    if hi_q < lo_q:
        return (hi_p, hi_q)
    return (lo_p, lo_q)
```
