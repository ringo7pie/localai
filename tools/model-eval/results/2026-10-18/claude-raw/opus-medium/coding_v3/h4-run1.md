```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    numer, denom = int(num), int(den)
    if denom < 0:
        numer, denom = -numer, -denom
    common = gcd(numer, denom)
    numer //= common
    denom //= common
    if numer == 0:
        return (0, 1)
    if denom <= max_den:
        return (numer, denom)

    # Continued fraction expansion with convergents.
    p_prev, q_prev = 0, 1
    p_cur, q_cur = 1, 0
    rem_n, rem_d = numer, denom
    while rem_d != 0:
        term = rem_n // rem_d
        p_next = term * p_cur + p_prev
        q_next = term * q_cur + q_prev
        if q_next > max_den:
            break
        p_prev, q_prev, p_cur, q_cur = p_cur, q_cur, p_next, q_next
        rem_n, rem_d = rem_d, rem_n - term * rem_d

    # Best semiconvergent within the bound.
    steps = (max_den - q_prev) // q_cur
    p_semi = p_prev + steps * p_cur
    q_semi = q_prev + steps * q_cur

    cand_a = (p_cur, q_cur)
    cand_b = (p_semi, q_semi)

    def is_below(frac: tuple[int, int]) -> bool:
        # frac < x  <=>  p * denom < numer * q
        return frac[0] * denom < numer * frac[1]

    if is_below(cand_a):
        lower, upper = cand_a, cand_b
    else:
        lower, upper = cand_b, cand_a

    if side == -1:
        return lower
    if side == 1:
        return upper

    dist_low = abs(numer * lower[1] - lower[0] * denom)
    dist_up = abs(numer * upper[1] - upper[0] * denom)
    lhs = dist_low * upper[1]
    rhs = dist_up * lower[1]
    if lhs < rhs:
        return lower
    if rhs < lhs:
        return upper
    if lower[1] != upper[1]:
        return lower if lower[1] < upper[1] else upper
    return lower if lower[0] < upper[0] else upper
```
