```python
from math import gcd


def _normalize(p: int, q: int) -> tuple[int, int]:
    if q < 0:
        p, q = -p, -q
    g = gcd(p, q)
    if g == 0:
        return (0, 1)
    p //= g
    q //= g
    if p == 0:
        return (0, 1)
    return (p, q)


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    num, den = _normalize(num, den)
    if den <= max_den:
        return (num, den)

    # Continued fraction expansion with the denominator limit.
    p0, q0, p1, q1 = 0, 1, 1, 0
    n, d = num, den
    while True:
        a = n // d
        q2 = q0 + a * q1
        if q2 > max_den:
            break
        p0, q0, p1, q1 = p1, q1, p0 + a * p1, q2
        n, d = d, n - a * d

    k = (max_den - q0) // q1
    bound1 = (p0 + k * p1, q0 + k * q1)
    bound2 = (p1, q1)

    # Determine which bound is below x and which is above.
    if bound1[0] * den < num * bound1[1]:
        lower, upper = bound1, bound2
    else:
        lower, upper = bound2, bound1

    lower = _normalize(*lower)
    upper = _normalize(*upper)

    if side == -1:
        return lower
    if side == 1:
        return upper

    pl, ql = lower
    pu, qu = upper
    # distances: (num*ql - pl*den)/(den*ql) and (pu*den - num*qu)/(den*qu)
    dist_low = num * ql - pl * den
    dist_up = pu * den - num * qu
    lhs = dist_low * qu
    rhs = dist_up * ql
    if lhs < rhs:
        return lower
    if rhs < lhs:
        return upper
    # Tie: smaller q, then smaller p.
    if ql != qu:
        return lower if ql < qu else upper
    return lower if pl < pu else upper
```
