```python
import math


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    # 正規化: 分母を正にし、既約にする
    if den < 0:
        num, den = -num, -den
    divisor = math.gcd(num, den)
    num //= divisor
    den //= divisor

    if den <= max_den:
        return (num, den)

    # 連分数展開で、分母が max_den 以下の最後の近似分数を求める
    prev_p, prev_q, cur_p, cur_q = 0, 1, 1, 0
    rem_n, rem_d = num, den
    while True:
        quotient = rem_n // rem_d
        next_q = prev_q + quotient * cur_q
        if next_q > max_den:
            break
        prev_p, prev_q, cur_p, cur_q = cur_p, cur_q, prev_p + quotient * cur_p, next_q
        rem_n, rem_d = rem_d, rem_n - quotient * rem_d

    # 中間近似分数（semiconvergent）
    steps = (max_den - prev_q) // cur_q
    semi_p = prev_p + steps * cur_p
    semi_q = prev_q + steps * cur_q

    # 2 つの候補は x を挟む Farey 隣接分数。どちらが下側かを整数で比べる
    if semi_p * cur_q < cur_p * semi_q:
        low_p, low_q = semi_p, semi_q
        high_p, high_q = cur_p, cur_q
    else:
        low_p, low_q = cur_p, cur_q
        high_p, high_q = semi_p, semi_q

    if side == -1:
        return (low_p, low_q)
    if side == 1:
        return (high_p, high_q)

    # x - low = (num*low_q - low_p*den) / (den*low_q)
    # high - x = (high_p*den - num*high_q) / (den*high_q)
    dist_low = (num * low_q - low_p * den) * high_q
    dist_high = (high_p * den - num * high_q) * low_q
    if dist_low < dist_high:
        return (low_p, low_q)
    if dist_high < dist_low:
        return (high_p, high_q)

    # 同じ距離: 分母の小さい方、同じなら分子の小さい方
    if low_q < high_q:
        return (low_p, low_q)
    if high_q < low_q:
        return (high_p, high_q)
    if low_p <= high_p:
        return (low_p, low_q)
    return (high_p, high_q)
```
