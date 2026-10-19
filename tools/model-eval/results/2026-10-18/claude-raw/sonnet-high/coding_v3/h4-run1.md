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

    # 連分数展開で、分母が max_den 以下の最後の収束分数と半収束分数を求める
    p0, q0, p1, q1 = 0, 1, 1, 0
    rest_n, rest_d = num, den
    while rest_d != 0:
        quotient = rest_n // rest_d
        q2 = q0 + quotient * q1
        if q2 > max_den:
            break
        p0, q0, p1, q1 = p1, q1, p0 + quotient * p1, q2
        rest_n, rest_d = rest_d, rest_n - quotient * rest_d

    k = (max_den - q0) // q1
    semi_p = p0 + k * p1
    semi_q = q0 + k * q1
    conv_p, conv_q = p1, q1

    # x は max_den 以下の分母では表せないので、2 つは x の両側にある
    if semi_p * den < num * semi_q:
        low_p, low_q, up_p, up_q = semi_p, semi_q, conv_p, conv_q
    else:
        low_p, low_q, up_p, up_q = conv_p, conv_q, semi_p, semi_q

    if side == -1:
        return (low_p, low_q)
    if side == 1:
        return (up_p, up_q)

    # 距離を通分せずに交差乗算で比べる
    low_dist = (num * low_q - low_p * den) * -1  # 符号を正にするため後で調整
    low_dist = (num - low_p * den // low_q) if False else None
    left = (num * low_q - low_p * den) * up_q * 1
    # x - low = (num*low_q - low_p*den) / (den*low_q)
    # up - x  = (up_p*den - num*up_q) / (den*up_q)
    left = (num * low_q - low_p * den) * up_q
    right = (up_p * den - num * up_q) * low_q
    if left < right:
        return (low_p, low_q)
    if right < left:
        return (up_p, up_q)
    if low_q <= up_q:
        return (low_p, low_q)
    return (up_p, up_q)
```
