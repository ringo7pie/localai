```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0 or max_den < 1 or side not in (-1, 0, 1):
        raise ValueError("invalid argument")
    if den < 0:
        num, den = -num, -den
    common = gcd(num, den)
    num //= common
    den //= common
    if den <= max_den:
        return (num, den)

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
    cand_a = (p0 + k * p1, q0 + k * q1)
    cand_b = (p1, q1)

    # determine lower / upper
    if cand_a[0] * cand_b[1] < cand_b[0] * cand_a[1]:
        lower, upper = cand_a, cand_b
    else:
        lower, upper = cand_b, cand_a

    if side == -1:
        return lower
    if side == 1:
        return upper

    dist_low = abs(num * lower[1] - lower[0] * den)  # / (den * lower_q)
    dist_up = abs(num * upper[1] - upper[0] * den)
    left = dist_low * upper[1]
    right = dist_up * lower[1]
    if left < right:
        return lower
    if right < left:
        return upper
    if lower[1] != upper[1]:
        return lower if lower[1] < upper[1] else upper
    return lower if lower[0] < upper[0] else upper
```
