凸多面体の平行体にシュタイナーの公式を使う。

V(r) = Vol(T) + S r + M r^2 + (4/3) pi r^3

- Vol(T) = sqrt(2)/12
- 表面積 S = sqrt(3)
- 辺の項: 二面角 theta = acos(1/3)。各辺で角度 (pi - theta) の扇形柱ができるので M = 6 * (pi - theta)/2 = 3(pi - acos(1/3))
- 頂点の項: 頂点の法錐の立体角の合計は 4 pi なので球 1 個分 (4/3) pi r^3

表面積は dV/dr = S + 2 M r + 4 pi r^2。

r = 0.6:

V = sqrt(2)/12 + 0.6 sqrt(3) + 1.08 (pi - acos(1/3)) + 0.288 pi ≈ 4.12534

A = sqrt(3) + 3.6 (pi - acos(1/3)) + 1.44 pi ≈ 13.1342

答え(a): sqrt(2)/12 + 0.6*sqrt(3) + 1.08*(pi - acos(1/3)) + 0.288*pi
答え(b): sqrt(3) + 3.6*(pi - acos(1/3)) + 1.44*pi
