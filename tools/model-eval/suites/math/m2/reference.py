"""M2 の正解（分割による閉じた式）と、標準ライブラリだけのモンテカルロによる検算。

V1 = 線分 OA のまわりの半径 r の立体（体積 pi r**2 + (4/3) pi r**3、x の平均 1/2、y の平均 0）。
V1 ∩ V2 は A のまわりで 4 つに分かれる（A を原点に u = x - 1, v = y）:
  u <= 0, v >= 0: 2 本の円柱の共通部分（Steinmetz の立体）の 1/4、体積 4r**3/3、∫u = -3 pi r**4/16、∫v = +3 pi r**4/16
  残りの 3 つの象限: 半径 r の球の 1/4 ずつ、体積 pi r**3/3、∫u と ∫v はそれぞれ ±pi r**4/8
合計: 体積 (pi + 4/3) r**3、∫u = -pi r**4/16、∫v = +pi r**4/16。
"""

import math
import random

R = 0.6


def answers():
    r = R
    v1 = math.pi * r ** 2 + 4.0 / 3.0 * math.pi * r ** 3
    inter = (math.pi + 4.0 / 3.0) * r ** 3
    volume = v1 - inter
    moment_x = 0.5 * v1 - (inter - math.pi * r ** 4 / 16.0)
    moment_y = -math.pi * r ** 4 / 16.0
    return {"a": volume, "b": moment_x / volume, "c": moment_y / volume}


def _dist_segment(p, a, b):
    ab = [b[k] - a[k] for k in range(3)]
    ap = [p[k] - a[k] for k in range(3)]
    t = max(0.0, min(1.0, sum(ab[k] * ap[k] for k in range(3)) / sum(x * x for x in ab)))
    return math.dist(p, [a[k] + t * ab[k] for k in range(3)])


def numeric_check(samples=200000, seed=2):
    rng = random.Random(seed)
    lo, hi = (-R, -R, -R), (1 + R, R, R)
    box = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
    count = sx = sy = 0.0
    O, A, B = (0, 0, 0), (1, 0, 0), (1, 1, 0)
    for _ in range(samples):
        p = (rng.uniform(lo[0], hi[0]), rng.uniform(lo[1], hi[1]), rng.uniform(lo[2], hi[2]))
        if _dist_segment(p, O, A) <= R and _dist_segment(p, A, B) > R:
            count += 1
            sx += p[0]
            sy += p[1]
    return {"a": box * count / samples, "b": sx / count, "c": sy / count}
