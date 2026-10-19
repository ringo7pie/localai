"""M3 の正解と、標準ライブラリだけのモンテカルロによる検算。

求める確率 = 1 - vol(球 ∪ 内側の立方体 C)。C = [d, 1-d]**3、半辺 a = 1/2 - d、球の半径 R = 1/2。
p = 1 - pi/6 - (2a)**3 + vol(球 ∩ C)。
(a) d = 1/4（a = 1/4）: C の角は中心から a sqrt(3) < R なので C は球に含まれる。p = 1 - pi/6。
(b) d = 1/10（a = 2/5）: a < R < a sqrt(2)。球は C の 6 つの面から高さ h = R - a の帽子としてはみ出し、帽子どうしは
    重ならない（辺までの距離 a sqrt(2) > R）。vol(球 ∩ C) = pi/6 - 6 cap、cap = pi h**2 (3R - h) / 3。
    p = 1 - 8a**3 - 6 cap = 0.488 - 0.028 pi。
(c) d = 3/20（a = 7/20）: a sqrt(2) < R < a sqrt(3)。C の 8 つの角だけが球の外に出る。vol(球 ∩ C) = 8 (a**3 - E)。
    p = 1 - pi/6 - 8E。E = 角 1 つ分の [0, a]**3 のうち球の外の体積
      = ∫∫_{[0,a]**2, rho > rho0} (a - sqrt(R**2 - rho**2)) dA、rho0 = sqrt(R**2 - a**2)。
    極座標で rho について積分すると F(rho) = a rho**2 / 2 + (R**2 - rho**2)**1.5 / 3 で、
    E = 2 ∫_{acos(a/rho0)}^{pi/4} [F(a / cos phi) - F(rho0)] d phi（なめらかな 1 次元の積分を Simpson 法で解く）。
"""

import math
import random

RADIUS = 0.5


def corner_excess(a, big_r=RADIUS, n=20000):
    rho0 = math.sqrt(big_r ** 2 - a ** 2)

    def f(rho):
        return a * rho ** 2 / 2 + (big_r ** 2 - rho ** 2) ** 1.5 / 3

    lo, hi = math.acos(a / rho0), math.pi / 4
    h = (hi - lo) / n
    total = 0.0
    for i in range(n + 1):
        phi = lo + i * h
        weight = 1 if i in (0, n) else (4 if i % 2 else 2)
        total += weight * (f(a / math.cos(phi)) - f(rho0))
    return 2 * total * h / 3


def answers():
    a_b = 0.4
    h = RADIUS - a_b
    cap = math.pi * h * h * (3 * RADIUS - h) / 3
    return {
        "a": 1 - math.pi / 6,
        "b": 1 - 8 * a_b ** 3 - 6 * cap,
        "c": 1 - math.pi / 6 - 8 * corner_excess(0.35),
    }


def p_of_d(d, samples, rng):
    hits = 0
    for _ in range(samples):
        x, y, z = rng.random(), rng.random(), rng.random()
        outside = (x - 0.5) ** 2 + (y - 0.5) ** 2 + (z - 0.5) ** 2 > 0.25
        near = min(x, 1 - x, y, 1 - y, z, 1 - z) <= d
        hits += outside and near
    return hits / samples


def numeric_check(samples=300000, seed=3):
    rng = random.Random(seed)
    return {"a": p_of_d(0.25, samples, rng), "b": p_of_d(0.1, samples, rng), "c": p_of_d(0.15, samples, rng)}
