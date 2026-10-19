```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if not isinstance(num, int) or not isinstance(den, int) or not isinstance(max_den, int):
        raise ValueError("arguments must be integers")
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
    if den <= max_den:
        return (num, den)

    whole = num // den
    target_n = num - whole * den  # 0 < target_n < den
    target_d = den
    limit = max_den

    lo_p, lo_q = 0, 1
    hi_p, hi_q = 1, 1
    while lo_q + hi_q <= limit:
        # gap_hi = hi - x (scaled), gap_lo = x - lo (scaled)
        gap_hi = hi_p * target_d - target_n * hi_q
        gap_lo = target_n * lo_q - lo_p * target_d
        steps_left = (gap_hi - 1) // gap_lo
        if steps_left >= 1:
            cap = (limit - hi_q) // lo_q
            steps = min(steps_left, cap)
            hi_p += steps * lo_p
            hi_q += steps * lo_q
            if steps < steps_left:
                break
            continue
        steps_right = (gap_lo - 1) // gap_hi
        if steps_right >= 1:
            cap = (limit - lo_q) // hi_q
            steps = min(steps_right, cap)
            lo_p += steps * hi_p
            lo_q += steps * hi_q
            if steps < steps_right:
                break
            continue
        break

    lower = (lo_p + whole * lo_q, lo_q)
    upper = (hi_p + whole * hi_q, hi_q)

    if side == -1:
        return lower
    if side == 1:
        return upper

    gap_lo = target_n * lo_q - lo_p * target_d  # distance lo: gap_lo / (d*lo_q)
    gap_hi = hi_p * target_d - target_n * hi_q  # distance hi: gap_hi / (d*hi_q)
    left_side = gap_lo * hi_q
    right_side = gap_hi * lo_q
    if left_side < right_side:
        return lower
    if right_side < left_side:
        return upper
    if lo_q < hi_q:
        return lower
    if hi_q < lo_q:
        return upper
    return lower if lower[0] <= upper[0] else upper
```
