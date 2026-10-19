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

    # x itself is representable.
    if den <= max_den:
        return (num, den)

    # x is not an integer here (den > max_den >= 1 and the fraction is reduced).
    # Walk the Stern-Brocot tree using batched steps (continued-fraction style).
    # Invariant: lo_p/lo_q < x < hi_p/hi_q, and they are Farey neighbours.
    lo_p = num // den
    lo_q = 1
    hi_p = lo_p + 1
    hi_q = 1

    while lo_q + hi_q <= max_den:
        mid_p = lo_p + hi_p
        mid_q = lo_q + hi_q
        gap_lo = num * lo_q - den * lo_p  # x - lo, scaled by den * lo_q (> 0)
        gap_hi = den * hi_p - num * hi_q  # hi - x, scaled by den * hi_q (> 0)
        if mid_p * den <= num * mid_q:
            # mediant is <= x: move lo toward hi as far as possible.
            steps = min(gap_lo // gap_hi, (max_den - lo_q) // hi_q)
            lo_p += steps * hi_p
            lo_q += steps * hi_q
        else:
            # mediant is > x: move hi toward lo as far as possible.
            steps = min(gap_hi // gap_lo, (max_den - hi_q) // lo_q)
            hi_p += steps * lo_p
            hi_q += steps * lo_q

    if side == -1:
        return (lo_p, lo_q)
    if side == 1:
        return (hi_p, hi_q)

    # Compare x - lo and hi - x exactly:
    #   x - lo = (num*lo_q - den*lo_p) / (den*lo_q)
    #   hi - x = (den*hi_p - num*hi_q) / (den*hi_q)
    dist_lo = (num * lo_q - den * lo_p) * hi_q
    dist_hi = (den * hi_p - num * hi_q) * lo_q
    if dist_lo < dist_hi:
        return (lo_p, lo_q)
    if dist_lo > dist_hi:
        return (hi_p, hi_q)
    # Tie: smaller denominator first, then smaller numerator (lo < hi).
    if lo_q <= hi_q:
        return (lo_p, lo_q)
    return (hi_p, hi_q)
```
