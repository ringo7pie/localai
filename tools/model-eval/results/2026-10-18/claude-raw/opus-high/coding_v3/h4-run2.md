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
    common = math.gcd(num, den)
    num //= common
    den //= common
    if den <= max_den:
        return (num, den)

    # Here den >= 2, so x is not an integer: floor(x) < x < floor(x) + 1.
    low_p, low_q = num // den, 1
    high_p, high_q = low_p + 1, 1

    # Invariant: low_p/low_q < x < high_p/high_q, high_p*low_q - low_p*high_q == 1,
    # and both denominators <= max_den.
    while low_q + high_q <= max_den:
        gap_low = num * low_q - low_p * den      # > 0  (x - low) * den * low_q
        gap_high = high_p * den - num * high_q   # > 0  (high - x) * den * high_q
        if (low_p + high_p) * den < num * (low_q + high_q):
            # Mediant lies below x: advance the lower bound as far as possible.
            steps = min((gap_low - 1) // gap_high, (max_den - low_q) // high_q)
            low_p += steps * high_p
            low_q += steps * high_q
        else:
            # Mediant lies above x (cannot equal x since its denominator <= max_den < den).
            steps = min((gap_high - 1) // gap_low, (max_den - high_q) // low_q)
            high_p += steps * low_p
            high_q += steps * low_q

    if side == -1:
        return (low_p, low_q)
    if side == 1:
        return (high_p, high_q)

    gap_low = num * low_q - low_p * den
    gap_high = high_p * den - num * high_q
    # Compare gap_low / low_q with gap_high / high_q.
    left = gap_low * high_q
    right = gap_high * low_q
    if left < right:
        return (low_p, low_q)
    if right < left:
        return (high_p, high_q)
    if low_q < high_q:
        return (low_p, low_q)
    if high_q < low_q:
        return (high_p, high_q)
    return (low_p, low_q) if low_p <= high_p else (high_p, high_q)
```
