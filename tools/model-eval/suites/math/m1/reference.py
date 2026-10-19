"""M1 の正解（Steiner の公式）と、標準ライブラリだけのモンテカルロによる検算。

K = T + rB（正四面体 T と半径 r の球の Minkowski 和）。体積 V(r) = V + S r + M r**2 + (4/3) pi r**3。
M = 辺ごとの (長さ × 外角 / 2) の和、外角 = pi - 二面角、二面角 = acos(1/3)。表面積 = V'(r) = S + 2 M r + 4 pi r**2。
"""

import math
import random

R = 0.6
SQ3 = math.sqrt(3.0)
VERTS = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, SQ3 / 2, 0.0), (0.5, SQ3 / 6, math.sqrt(2.0 / 3.0)))


def answers():
    volume = math.sqrt(2.0) / 12.0
    surface = SQ3
    mean_term = 6 * 1.0 * (math.pi - math.acos(1.0 / 3.0)) / 2.0
    return {
        "a": volume + surface * R + mean_term * R ** 2 + 4.0 / 3.0 * math.pi * R ** 3,
        "b": surface + 2 * mean_term * R + 4 * math.pi * R ** 2,
    }


def _sub(p, q):
    return (p[0] - q[0], p[1] - q[1], p[2] - q[2])


def _dot(p, q):
    return p[0] * q[0] + p[1] * q[1] + p[2] * q[2]


def _closest_on_triangle(p, a, b, c):
    """Ericson の方法で三角形 abc 上の p に最も近い点。"""

    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return a
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        t = d1 / (d1 - d3)
        return (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        t = d2 / (d2 - d6)
        return (a[0] + t * ac[0], a[1] + t * ac[1], a[2] + t * ac[2])
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return (b[0] + t * (c[0] - b[0]), b[1] + t * (c[1] - b[1]), b[2] + t * (c[2] - b[2]))
    denom = 1.0 / (va + vb + vc)
    v, w = vb * denom, vc * denom
    return (a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w)


FACES = []
for skip in range(4):
    tri = [VERTS[i] for i in range(4) if i != skip]
    FACES.append((tri, VERTS[skip]))


def distance_to_tetra(p):
    inside = True
    best = float("inf")
    for (a, b, c), opposite in FACES:
        n = (_sub(b, a)[1] * _sub(c, a)[2] - _sub(b, a)[2] * _sub(c, a)[1],
             _sub(b, a)[2] * _sub(c, a)[0] - _sub(b, a)[0] * _sub(c, a)[2],
             _sub(b, a)[0] * _sub(c, a)[1] - _sub(b, a)[1] * _sub(c, a)[0])
        if (_dot(n, _sub(p, a)) > 0) == (_dot(n, _sub(opposite, a)) > 0) or _dot(n, _sub(p, a)) == 0:
            pass
        else:
            inside = False
        q = _closest_on_triangle(p, a, b, c)
        best = min(best, math.dist(p, q))
    return 0.0 if inside else best


def numeric_check(samples=60000, seed=1, band=0.02):
    """モンテカルロで体積と表面積（距離が r ± band の殻の体積 ÷ 2 band）を出す。"""

    rng = random.Random(seed)
    lo = [min(v[k] for v in VERTS) - R - band for k in range(3)]
    hi = [max(v[k] for v in VERTS) + R + band for k in range(3)]
    box = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
    inside = shell = 0
    for _ in range(samples):
        p = tuple(rng.uniform(lo[k], hi[k]) for k in range(3))
        d = distance_to_tetra(p)
        inside += d <= R
        shell += R - band < d <= R + band
    return {"a": box * inside / samples, "b": box * shell / samples / (2 * band)}
