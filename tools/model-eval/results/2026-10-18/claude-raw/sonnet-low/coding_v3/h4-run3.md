```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be 0")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")
    if den < 0:
        num, den = -num, -den
    g = gcd(num, den)
    num //= g
    den //= g
    if den <= max_den:
        return (num, den)
    floor_value = num // den
    a, b = floor_value, 1
    c, d = floor_value + 1, 1
    while True:
        moved = False
        # lo (a/b) を x に近づける
        denom = c * den - num * d
        k = (num * b - a * den) // denom
        k = min(k, (max_den - b) // d)
        if k > 0:
            a += k * c
            b += k * d
            moved = True
        # hi (c/d) を x に近づける
        denom = num * b - a * den
        k = (c * den - num * d) // denom
        k = min(k, (max_den - d) // b)
        if k > 0:
            c += k * a
            d += k * b
            moved = True
        if not moved:
            break
    if side == -1:
        return (a, b)
    if side == 1:
        return (c, d)
    dist_lo = (num * b - a * den) * d
    dist_hi = (c * den - num * d) * b
    if dist_lo < dist_hi:
        return (a, b)
    if dist_lo > dist_hi:
        return (c, d)
    if b <= d:
        return (a, b)
    return (c, d)
```
