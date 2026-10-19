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

    if den <= max_den:
        return (num, den)

    # Continued fraction expansion; stop before the convergent denominator exceeds max_den.
    p_prev, q_prev, p_cur, q_cur = 0, 1, 1, 0
    numer, denom = num, den
    while True:
        term = numer // denom
        q_next = q_prev + term * q_cur
        if q_next > max_den:
            break
        p_prev, q_prev, p_cur, q_cur = p_cur, q_cur, p_prev + term * p_cur, q_next
        numer, denom = denom, numer - term * denom

    steps = (max_den - q_prev) // q_cur
    semi_p = p_prev + steps * p_cur
    semi_q = q_prev + steps * q_cur
    conv_p, conv_q = p_cur, q_cur

    # The two candidates are the Farey neighbours of x of order max_den.
    if semi_p * conv_q < conv_p * semi_q:
        low_p, low_q, high_p, high_q = semi_p, semi_q, conv_p, conv_q
    else:
        low_p, low_q, high_p, high_q = conv_p, conv_q, semi_p, semi_q

    if side == -1:
        return (low_p, low_q)
    if side == 1:
        return (high_p, high_q)

    # Compare x - low and high - x using integers only.
    diff_low = (num * low_q - low_p * den) * high_q
    diff_high = (high_p * den - num * high_q) * low_q
    if diff_low < diff_high:
        return (low_p, low_q)
    if diff_high < diff_low:
        return (high_p, high_q)
    if low_q < high_q:
        return (low_p, low_q)
    if high_q < low_q:
        return (high_p, high_q)
    if low_p <= high_p:
        return (low_p, low_q)
    return (high_p, high_q)
```
