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

    # x = num / den is not an integer here (den > max_den >= 1).
    # lo = p0/q0 < x < hi = p1/q1, adjacent in the Stern-Brocot tree.
    p0 = num // den
    q0 = 1
    p1 = p0 + 1
    q1 = 1

    while True:
        moved = False

        # Move lo toward x: (p0 + k*p1) / (q0 + k*q1) <= x, denominator <= max_den.
        gap_lo = num * q0 - p0 * den  # > 0 : x - lo scaled
        gap_hi = p1 * den - num * q1  # > 0 : hi - x scaled
        steps = min(gap_lo // gap_hi, (max_den - q0) // q1)
        if steps > 0:
            p0 += steps * p1
            q0 += steps * q1
            moved = True

        # Move hi toward x: (p1 + k*p0) / (q1 + k*q0) >= x, denominator <= max_den.
        gap_lo = num * q0 - p0 * den
        gap_hi = p1 * den - num * q1
        steps = min(gap_hi // gap_lo, (max_den - q1) // q0)
        if steps > 0:
            p1 += steps * p0
            q1 += steps * q0
            moved = True

        if not moved:
            break

    if side == -1:
        return (p0, q0)
    if side == 1:
        return (p1, q1)

    # side == 0: compare x - lo and hi - x exactly.
    # x - lo = gap_lo / (den * q0), hi - x = gap_hi / (den * q1)
    gap_lo = num * q0 - p0 * den
    gap_hi = p1 * den - num * q1
    left = gap_lo * q1
    right = gap_hi * q0
    if left < right:
        return (p0, q0)
    if left > right:
        return (p1, q1)
    if q0 <= q1:
        return (p0, q0)
    return (p1, q1)
```
