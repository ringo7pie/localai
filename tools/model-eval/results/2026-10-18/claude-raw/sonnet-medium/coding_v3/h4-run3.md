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

    # continued fraction expansion with semiconvergents
    p0, q0, p1, q1 = 0, 1, 1, 0
    n, d = num, den
    while d:
        a = n // d
        q2 = q0 + a * q1
        if q2 > max_den:
            break
        p0, q0, p1, q1 = p1, q1, p0 + a * p1, q2
        n, d = d, n - a * d

    k = (max_den - q0) // q1
    cand_a = (p0 + k * p1, q0 + k * q1)
    cand_b = (p1, q1)

    # decide which is below x and which is above x (neither equals x)
    if cand_a[0] * cand_b[1] < cand_b[0] * cand_a[1]:
        low, high = cand_a, cand_b
    else:
        low, high = cand_b, cand_a

    if side == -1:
        return low
    if side == 1:
        return high

    pl, ql = low
    ph, qh = high
    dist_low = num * ql - pl * den      # over den * ql
    dist_high = ph * den - num * qh     # over den * qh
    left = dist_low * qh
    right = dist_high * ql
    if left < right:
        return low
    if right < left:
        return high
    return low if (ql, pl) < (qh, ph) else high
```
