"""H1 の総当たりのオラクル（O(n**4)。小さい入力だけ）。参照解とは別の作り。

支える平面: 3 点で張る平面のうち、すべての点が片側（境界を含む）にあるもの。面 = その平面の集合。
頂点 = 3 次元を張る法線の面に乗る点。体積 = 各面の多角形（平面に射影した 2 次元の凸包）と原点で作る錐の和。
"""

from fractions import Fraction
from itertools import combinations
from math import gcd


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return sum(x * y for x, y in zip(u, v))


def _hull2d_area2(points2d):
    pts = sorted(set(points2d))
    if len(pts) < 3:
        return 0

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    ring = lower[:-1] + upper[:-1]
    return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
                   for i in range(len(ring))))


def hull3d_brute(points):
    pts = sorted(set(tuple(p) for p in points))
    if len(pts) < 4:
        raise ValueError
    flat = True
    for a, b, c in combinations(pts, 3):
        n = _cross(_sub(b, a), _sub(c, a))
        if n != (0, 0, 0):
            flat = all(_dot(n, _sub(p, a)) == 0 for p in pts)
            break
    if flat:
        raise ValueError
    planes = {}
    for a, b, c in combinations(pts, 3):
        n = _cross(_sub(b, a), _sub(c, a))
        if n == (0, 0, 0):
            continue
        values = [_dot(n, _sub(p, a)) for p in pts]
        if all(v <= 0 for v in values):
            pass
        elif all(v >= 0 for v in values):
            n = (-n[0], -n[1], -n[2])
        else:
            continue
        g = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2]))
        n = (n[0] // g, n[1] // g, n[2] // g)
        planes[(n, _dot(n, a))] = n
    if not planes:
        raise ValueError
    volume6 = Fraction(0)
    for (n, off) in planes:
        on_plane = [p for p in pts if _dot(n, p) == off]
        drop = max(range(3), key=lambda k: abs(n[k]))
        keep = [k for k in range(3) if k != drop]
        area2 = _hull2d_area2([(p[keep[0]], p[keep[1]]) for p in on_plane])
        volume6 += Fraction(area2 * off, abs(n[drop]))
    n_vertices = 0
    for p in pts:
        normals = [n for (n, off) in planes if _dot(n, p) == off]
        rank3 = any(_dot(_cross(x, y), z) != 0 for x, y, z in combinations(normals, 3))
        n_vertices += rank3
    assert volume6.denominator == 1
    return int(volume6), len(planes), n_vertices
