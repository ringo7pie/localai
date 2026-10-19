```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if not isinstance(num, int) or not isinstance(den, int) or not isinstance(max_den, int):
        raise ValueError("integers required")
    if den == 0 or max_den < 1 or side not in (-1, 0, 1):
        raise ValueError("invalid argument")
    if den < 0:
        num, den = -num, -den
    g = gcd(num, den)
    num //= g
    den //= g
    if den <= max_den:
        return (num, den)
    n, d, N = num, den, max_den
    lp, lq = n // d, 1
    rp, rq = lp + 1, 1
    while True:
        mp, mq = lp + rp, lq + rq
        if mq > N:
            break
        if mp * d < n * mq:
            k = (n * lq - lp * d - 1) // (rp * d - n * rq)
            k = min(k, (N - lq) // rq)
            if k < 1:
                k = 1
            lp, lq = lp + k * rp, lq + k * rq
        else:
            k = (rp * d - n * rq - 1) // (n * lq - lp * d)
            k = min(k, (N - rq) // lq)
            if k < 1:
                k = 1
            rp, rq = rp + k * lp, rq + k * lq
    if side == -1:
        return (lp, lq)
    if side == 1:
        return (rp, rq)
    dl = (n * lq - lp * d) * rq
    du = (rp * d - n * rq) * lq
    if dl < du:
        return (lp, lq)
    if du < dl:
        return (rp, rq)
    if lq != rq:
        return (lp, lq) if lq < rq else (rp, rq)
    return (lp, lq) if lp < rp else (rp, rq)
```
