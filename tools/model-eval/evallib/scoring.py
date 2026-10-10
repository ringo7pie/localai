"""ランキングの式（計画の方針 6。HTML にも同じ文を出す）。

- 能力: 回（問）ごとの点数（0〜1）の平均。答えなし・上限・時間切れは 0 点として平均に入れる。
- 速度点: 時間 T の対数で、最も遅いモデルを 0、最も速いモデルを 1 にする。
    速度点 = (ln T_max − ln T) ÷ (ln T_max − ln T_min)
  時間の幅が 100 秒〜1 時間と広いので、差を対数で比べる。T が無い（1 問も答えていない）モデルは 0。
- 総合 = 0.7 × 能力 + 0.3 × 速度点
"""

from __future__ import annotations

import math
import statistics
from typing import Iterable

WEIGHT_ABILITY = 0.7
WEIGHT_SPEED = 0.3

FORMULA_TEXT = {
    "ability": "能力 = 回（問）ごとの点数（0〜1）の平均。答えなし・上限・時間切れ・時間の上限で飛ばした問は 0 点",
    "speed": "速度点 = (ln T_max − ln T) ÷ (ln T_max − ln T_min)。T は時間の中央値。最も遅いモデルが 0、最も速いモデルが 1",
    "overall": f"総合 = {WEIGHT_ABILITY} × 能力 + {WEIGHT_SPEED} × 速度点",
}


def mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def median(values: Iterable[float | None]) -> float | None:
    items = [value for value in values if value is not None]
    return statistics.median(items) if items else None


def speed_scores(times: dict[str, float | None]) -> dict[str, float | None]:
    """モデルごとの時間 T（秒）から速度点を出す。T が無いモデルは None（総合では 0 として扱う）。"""

    valid = {key: value for key, value in times.items() if value is not None and value > 0}
    if not valid:
        return {key: None for key in times}
    slowest, fastest = max(valid.values()), min(valid.values())
    scores: dict[str, float | None] = {}
    for key in times:
        value = valid.get(key)
        if value is None:
            scores[key] = None
        elif slowest == fastest:
            scores[key] = 1.0
        else:
            scores[key] = (math.log(slowest) - math.log(value)) / (math.log(slowest) - math.log(fastest))
    return scores


def overall(ability: float | None, speed: float | None) -> float | None:
    if ability is None:
        return None
    return WEIGHT_ABILITY * ability + WEIGHT_SPEED * (speed or 0.0)


def rank(values: dict[str, float | None]) -> dict[str, int | None]:
    """大きいほど上の順位（同じ値は同じ順位、次は飛ばす: 1, 2, 2, 4）。値が無いものは None。"""

    ordered = sorted((value for value in values.values() if value is not None), reverse=True)
    ranks: dict[str, int | None] = {}
    for key, value in values.items():
        if value is None:
            ranks[key] = None
        else:
            # 浮動小数の誤差で同点が割れないよう、丸めてから比べる
            ranks[key] = 1 + sum(1 for other in ordered if round(other, 9) > round(value, 9))
    return ranks
