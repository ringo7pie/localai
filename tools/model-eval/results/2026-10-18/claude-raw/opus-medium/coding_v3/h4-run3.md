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
    if num == 0:
        return (0, 1)
    if den <= max_den:
        return (num, den)

    # Continued fraction expansion to find the two Farey neighbours of x.
    p0, q0, p1, q1 = 0, 1, 1, 0
    n, d = num, den
    while True:
        term = n // d
        q2 = q0 + term * q1
        if q2 > max_den:
            break
        p0, q0, p1, q1 = p1, q1, p0 + term * p1, q2
        n, d = d, n - term * d

    k = (max_den - q0) // q1
    cand_a = (p0 + k * p1, q0 + k * q1)
    cand_b = (p1, q1)

    # Determine which candidate lies below x.
    if cand_a[0] * den < num * cand_a[1]:
        lower, upper = cand_a, cand_b
    else:
        lower, upper = cand_b, cand_a

    if side == -1:
        return lower
    if side == 1:
        return upper

    lp, lq = lower
    up, uq = upper
    # Distances scaled: dist_lower = dl / (den*lq), dist_upper = du / (den*uq)
    dl = num * lq - lp * den
    du = up * den - num * uq
    left = dl * uq
    right = du * lq
    if left < right:
        return lower
    if right < left:
        return upper
    # Tie: smaller q, then smaller p.
    if lq != uq:
        return lower if lq < uq else upper
    return lower if lp <= up else upper
```
