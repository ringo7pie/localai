```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list({(int(p[0]), int(p[1]), int(p[2])) for p in points})
    n = len(pts)
    if n < 4:
        raise ValueError("fewer than 4 distinct points")
    pts.sort()
    random.Random(1234567).shuffle(pts)
    X = [p[0] for p in pts]
    Y = [p[1] for p in pts]
    Z = [p[2] for p in pts]

    i0, i1 = 0, 1
    ux, uy, uz = X[i1] - X[i0], Y[i1] - Y[i0], Z[i1] - Z[i0]
    i2 = -1
    cx = cy = cz = 0
    for k in range(2, n):
        vx, vy, vz = X[k] - X[i0], Y[k] - Y[i0], Z[k] - Z[i0]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            i2 = k
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for k in range(2, n):
        if k == i2:
            continue
        if cx * (X[k] - X[i0]) + cy * (Y[k] - Y[i0]) + cz * (Z[k] - Z[i0]) != 0:
            i3 = k
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    fa = []
    fb = []
    fc = []
    fnx = []
    fny = []
    fnz = []
    fd = []
    alive = []
    fpts = []
    edge = {}

    def newface(a, b, c):
        ax, ay, az = X[a], Y[a], Z[a]
        bx, by, bz = X[b] - ax, Y[b] - ay, Z[b] - az
        qx, qy, qz = X[c] - ax, Y[c] - ay, Z[c] - az
        nx = by * qz - bz * qy
        ny = bz * qx - bx * qz
        nz = bx * qy - by * qx
        f = len(fa)
        fa.append(a)
        fb.append(b)
        fc.append(c)
        fnx.append(nx)
        fny.append(ny)
        fnz.append(nz)
        fd.append(nx * ax + ny * ay + nz * az)
        alive.append(True)
        fpts.append([])
        edge[(a, b)] = f
        edge[(b, c)] = f
        edge[(c, a)] = f
        return f

    init = (i0, i1, i2, i3)
    sx = sum(X[k] for k in init)
    sy = sum(Y[k] for k in init)
    sz = sum(Z[k] for k in init)
    for tri in ((i0, i1, i2), (i0, i1, i3), (i0, i2, i3), (i1, i2, i3)):
        a, b, c = tri
        ax, ay, az = X[a], Y[a], Z[a]
        bx, by, bz = X[b] - ax, Y[b] - ay, Z[b] - az
        qx, qy, qz = X[c] - ax, Y[c] - ay, Z[c] - az
        nx = by * qz - bz * qy
        ny = bz * qx - bx * qz
        nz = bx * qy - by * qx
        d = nx * ax + ny * ay + nz * az
        if nx * sx + ny * sy + nz * sz - 4 * d > 0:
            b, c = c, b
        newface(a, b, c)

    done = [False] * n
    for k in init:
        done[k] = True
    pfaces = [None] * n
    for k in range(n):
        if done[k]:
            continue
        s = set()
        px, py, pz = X[k], Y[k], Z[k]
        for f in range(4):
            if fnx[f] * px + fny[f] * py + fnz[f] * pz > fd[f]:
                s.add(f)
                fpts[f].append(k)
        pfaces[k] = s

    for p in range(n):
        if done[p]:
            continue
        done[p] = True
        vis = pfaces[p]
        pfaces[p] = None
        if not vis:
            continue
        horizon = []
        for f in vis:
            a, b, c = fa[f], fb[f], fc[f]
            for u, v in ((a, b), (b, c), (c, a)):
                g = edge[(v, u)]
                if g not in vis:
                    horizon.append((u, v, f, g))
        for f in vis:
            alive[f] = False
            a, b, c = fa[f], fb[f], fc[f]
            del edge[(a, b)]
            del edge[(b, c)]
            del edge[(c, a)]
        for u, v, f, g in horizon:
            h = newface(u, v, p)
            nx, ny, nz, d = fnx[h], fny[h], fnz[h], fd[h]
            hp = fpts[h]
            seen = set()
            for lst in (fpts[f], fpts[g]):
                for q in lst:
                    if done[q] or q in seen:
                        continue
                    seen.add(q)
                    if nx * X[q] + ny * Y[q] + nz * Z[q] > d:
                        hp.append(q)
                        pfaces[q].add(h)
        for f in vis:
            for q in fpts[f]:
                if not done[q]:
                    pfaces[q].discard(f)
            fpts[f] = []

    vol6 = 0
    planes = set()
    vplanes = {}
    for f in range(len(fa)):
        if not alive[f]:
            continue
        a, b, c = fa[f], fb[f], fc[f]
        ax, ay, az = X[a], Y[a], Z[a]
        bx, by, bz = X[b], Y[b], Z[b]
        qx, qy, qz = X[c], Y[c], Z[c]
        vol6 += ax * (by * qz - bz * qy) + ay * (bz * qx - bx * qz) + az * (bx * qy - by * qx)
        nx, ny, nz, d = fnx[f], fny[f], fnz[f], fd[f]
        g = gcd(gcd(abs(nx), abs(ny)), gcd(abs(nz), abs(d)))
        key = (nx // g, ny // g, nz // g, d // g)
        planes.add(key)
        for v in (a, b, c):
            s = vplanes.get(v)
            if s is None:
                s = set()
                vplanes[v] = s
            s.add(key)
    nverts = sum(1 for s in vplanes.values() if len(s) >= 3)
    return (vol6, len(planes), nverts)
```
