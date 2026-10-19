```python
from math import gcd


def best_rational(num: int, den: int, max_den: int, side: int = 0) -> tuple[int, int]:
    if den == 0:
        raise ValueError("den must not be zero")
    if max_den < 1:
        raise ValueError("max_den must be >= 1")
    if side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or 1")

    # den > 0 に正規化し、既約にする
    if den < 0:
        num, den = -num, -den
    divisor = gcd(num, den)
    num //= divisor
    den //= divisor

    # x 自身が上限以内で表せるなら、その既約分数を返す
    if den <= max_den:
        return (num, den)

    # ここでは x は整数ではなく、分母 max_den 以下では表せない。
    # 連分数展開で、最後の収束分数と最後の準収束分数
    # (x を挟む Farey 数列の隣り合う 2 項) を求める。
    prev_p, prev_q, cur_p, cur_q = 0, 1, 1, 0
    numerator, denominator = num, den
    while True:
        quotient = numerator // denominator
        next_q = prev_q + quotient * cur_q
        if next_q > max_den:
            break
        prev_p, prev_q, cur_p, cur_q = (
            cur_p,
            cur_q,
            prev_p + quotient * cur_p,
            next_q,
        )
        numerator, denominator = denominator, numerator - quotient * denominator

    steps = (max_den - prev_q) // cur_q
    semi_p = prev_p + steps * cur_p
    semi_q = prev_q + steps * cur_q

    # convergent (cur_p/cur_q) と semiconvergent (semi_p/semi_q) のどちらが x より小さいか
    if cur_p * den - num * cur_q < 0:
        lower_p, lower_q = cur_p, cur_q
        upper_p, upper_q = semi_p, semi_q
    else:
        lower_p, lower_q = semi_p, semi_q
        upper_p, upper_q = cur_p, cur_q

    if side == -1:
        return (lower_p, lower_q)
    if side == 1:
        return (upper_p, upper_q)

    # side == 0: 距離を通分せずに整数だけで比べる
    # 下側の距離 = (num*lower_q - lower_p*den) / (den*lower_q)
    # 上側の距離 = (upper_p*den - num*upper_q) / (den*upper_q)
    lower_gap = (num * lower_q - lower_p * den) * upper_q
    upper_gap = (upper_p * den - num * upper_q) * lower_q
    if lower_gap < upper_gap:
        return (lower_p, lower_q)
    if upper_gap < lower_gap:
        return (upper_p, upper_q)
    # 同じ距離: q が小さい方、同じなら p が小さい方
    if lower_q < upper_q:
        return (lower_p, lower_q)
    if upper_q < lower_q:
        return (upper_p, upper_q)
    if lower_p <= upper_p:
        return (lower_p, lower_q)
    return (upper_p, upper_q)
```
