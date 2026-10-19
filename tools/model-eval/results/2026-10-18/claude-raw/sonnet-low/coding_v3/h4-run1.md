```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0 or max_den < 1 or side not in (-1, 0, 1):
        raise ValueError("invalid argument")
    if den < 0:
        num, den = -num, -den
    g = gcd(num, den)
    num //= g
    den //= g
    if den <= max_den:
        return (num, den)

    n, d = num, den
    h0, k0 = 0, 1
    h1, k1 = 1, 0
    cand = None
    while d != 0:
        a = n // d
        n, d = d, n - a * d
        h2 = a * h1 + h0
        k2 = a * k1 + k0
        if k2 > max_den:
            t = (max_den - k0) // k1
            cand = [(h1, k1), (h0 + t * h1, k0 + t * k1)]
            break
        h0, k0, h1, k1 = h1, k1, h2, k2
    # cand は必ず設定される（既約の分母が max_den を超えるため）
    (p1, q1), (p2, q2) = cand
    if p1 * q2 <= p2 * q1:
        low, high = (p1, q1), (p2, q2)
    else:
        low, high = (p2, q2), (p1, q1)
    if side == -1:
        return low
    if side == 1:
        return high
    dist_low = (num * low[1] - low[0] * den) * high[1]
    dist_high = (high[0] * den - num * high[1]) * low[1]
    if dist_low < dist_high:
        return low
    if dist_high < dist_low:
        return high
    return min(low, high, key=lambda frac: (frac[1], frac[0]))
```
