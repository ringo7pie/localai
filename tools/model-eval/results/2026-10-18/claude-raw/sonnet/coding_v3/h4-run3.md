```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be at least 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    if den < 0:
        num = -num
        den = -den
    divisor = gcd(num, den)
    num //= divisor
    den //= divisor

    # x itself is representable.
    if den <= max_den:
        return (num, den)

    # Here den >= 2, so x is not an integer: floor(x) < x < floor(x) + 1.
    floor_value = num // den
    low_p, low_q = floor_value, 1
    high_p, high_q = floor_value + 1, 1

    # Stern-Brocot descent in batches (equivalent to walking the continued
    # fraction with semiconvergents). Invariant: low < x < high and
    # high_p * low_q - low_p * high_q == 1.
    while True:
        # Move the lower bound toward the upper bound as far as it stays < x
        # and its denominator stays within max_den.
        gap_low = num * low_q - den * low_p      # > 0
        gap_high = den * high_p - num * high_q   # > 0
        steps_low = min(gap_low // gap_high, (max_den - low_q) // high_q)
        if steps_low > 0:
            low_p += steps_low * high_p
            low_q += steps_low * high_q

        # Move the upper bound toward the lower bound as far as it stays > x
        # and its denominator stays within max_den.
        gap_low = num * low_q - den * low_p
        gap_high = den * high_p - num * high_q
        steps_high = min((gap_high - 1) // gap_low, (max_den - high_q) // low_q)
        if steps_high > 0:
            high_p += steps_high * low_p
            high_q += steps_high * low_q

        if steps_low == 0 and steps_high == 0:
            break

    if side == -1:
        return (low_p, low_q)
    if side == 1:
        return (high_p, high_q)

    # side == 0: compare x - low with high - x using integers only.
    gap_low = num * low_q - den * low_p
    gap_high = den * high_p - num * high_q
    left = gap_low * high_q    # proportional to x - low
    right = gap_high * low_q   # proportional to high - x
    if left < right:
        return (low_p, low_q)
    if right < left:
        return (high_p, high_q)
    if low_q <= high_q:
        return (low_p, low_q)
    return (high_p, high_q)
```
