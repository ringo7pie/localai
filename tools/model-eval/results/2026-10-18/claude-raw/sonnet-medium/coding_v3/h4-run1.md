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

    # x is not representable; den > 1 so x is not an integer.
    floor_value = num // den
    lo_p, lo_q = floor_value, 1
    hi_p, hi_q = floor_value + 1, 1

    while True:
        moved = False

        # move lower bound toward x
        a_val = den * hi_p - num * hi_q  # > 0
        b_val = num * lo_q - den * lo_p  # > 0
        step = min(b_val // a_val, (max_den - lo_q) // hi_q)
        if step > 0:
            lo_p += step * hi_p
            lo_q += step * hi_q
            moved = True

        # move upper bound toward x
        a_val = den * hi_p - num * hi_q
        b_val = num * lo_q - den * lo_p
        step = min(a_val // b_val, (max_den - hi_q) // lo_q)
        if step > 0:
            hi_p += step * lo_p
            hi_q += step * lo_q
            moved = True

        if not moved:
            break

    if side == -1:
        return (lo_p, lo_q)
    if side == 1:
        return (hi_p, hi_q)

    a_val = den * hi_p - num * hi_q
    b_val = num * lo_q - den * lo_p
    left = b_val * hi_q   # proportional to x - lo
    right = a_val * lo_q  # proportional to hi - x
    if left < right:
        return (lo_p, lo_q)
    if left > right:
        return (hi_p, hi_q)
    if lo_q <= hi_q:
        return (lo_p, lo_q)
    return (hi_p, hi_q)
```
