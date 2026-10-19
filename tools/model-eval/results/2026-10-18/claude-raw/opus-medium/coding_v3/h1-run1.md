```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")

    x0, y0, z0 = pts[0]
    x1, y1, z1 = pts[1]
    ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
    i2 = -1
    cx = cy = cz = 0
    for idx in range(2, count):
        vx, vy, vz = pts[idx][0] - x0, pts[idx][1] - y0, pts[idx][2] - z0
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            i2 = idx
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for idx in range(2, count):
        if idx == i2:
            continue
        wx, wy, wz = pts[idx][0] - x0, pts[idx][1] - y0, pts[idx][2] - z0
        if cx * wx + cy * wy + cz * wz != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    rest = [idx for idx in range(2, count) if idx != i2 and idx != i3]
    rng = random.Random(0x5EED)
    rng.shuffle(rest)
    order = [0, 1, i2, i3] + rest
    X = [pts[idx][0] for idx in order]
    Y = [pts[idx][1] for idx in order]
    Z = [pts[idx][2] for idx in order]

    FA: list[int] = []
    FB: list[int] = []
    FC: list[int] = []
    NX: list[int] = []
    NY: list[int] = []
    NZ: list[int] = []
    FD: list[int] = []
    alive: list[bool] = []
    vismark: list[int] = []
    conf: list = []
    edge: dict = {}
    pconf: list[list[int]] = [[] for _ in range(count)]
    seen = [-1] * count

    def make_face(a: int, b: int, c: int) -> int:
        ax, ay, az = X[a], Y[a], Z[a]
        bx, by, bz = X[b] - ax, Y[b] - ay, Z[b] - az
        qx, qy, qz = X[c] - ax, Y[c] - ay, Z[c] - az
        nx = by * qz - bz * qy
        ny = bz * qx - bx * qz
        nz = bx * qy - by * qx
        fid = len(FA)
        FA.append(a)
        FB.append(b)
        FC.append(c)
        NX.append(nx)
        NY.append(ny)
        NZ.append(nz)
        FD.append(nx * ax + ny * ay + nz * az)
        alive.append(True)
        vismark.append(-1)
        conf.append([])
        return fid

    # initial tetrahedron, oriented outward
    a, b, c, d = 0, 1, 2, 3
    tmp = make_face(a, b, c)
    if NX[tmp] * X[d] + NY[tmp] * Y[d] + NZ[tmp] * Z[d] > FD[tmp]:
        b, c = c, b
    FA.clear(); FB.clear(); FC.clear(); NX.clear(); NY.clear(); NZ.clear()
    FD.clear(); alive.clear(); vismark.clear(); conf.clear()
    init = [(a, b, c), (b, a, d), (c, b, d), (a, c, d)]
    for (fa, fb, fc) in init:
        fid = make_face(fa, fb, fc)
        edge[(fa, fb)] = fid
        edge[(fb, fc)] = fid
        edge[(fc, fa)] = fid
    for q in range(4, count):
        xq, yq, zq = X[q], Y[q], Z[q]
        for fid in range(4):
            if NX[fid] * xq + NY[fid] * yq + NZ[fid] * zq > FD[fid]:
                conf[fid].append(q)
                pconf[q].append(fid)

    for p in range(4, count):
        vis = [f for f in pconf[p] if alive[f]]
        pconf[p] = []
        if not vis:
            continue
        for f in vis:
            vismark[f] = p
        horizon = []
        for f in vis:
            fa, fb, fc = FA[f], FB[f], FC[f]
            for (u, v) in ((fa, fb), (fb, fc), (fc, fa)):
                g = edge[(v, u)]
                if vismark[g] != p:
                    horizon.append((u, v, f, g))
        for f in vis:
            alive[f] = False
            fa, fb, fc = FA[f], FB[f], FC[f]
            del edge[(fa, fb)]
            del edge[(fb, fc)]
            del edge[(fc, fa)]
        for (u, v, f, g) in horizon:
            nf = make_face(u, v, p)
            nx, ny, nz, nd = NX[nf], NY[nf], NZ[nf], FD[nf]
            cl = conf[nf]
            for src in (conf[f], conf[g]):
                for q in src:
                    if q == p or seen[q] == nf:
                        continue
                    seen[q] = nf
                    if nx * X[q] + ny * Y[q] + nz * Z[q] > nd:
                        cl.append(q)
                        pconf[q].append(nf)
            edge[(u, v)] = nf
            edge[(v, p)] = nf
            edge[(p, u)] = nf
        for f in vis:
            conf[f] = None

    volume6 = 0
    face_keys = set()
    vert_planes: dict = {}
    for f in range(len(FA)):
        if not alive[f]:
            continue
        fa, fb, fc = FA[f], FB[f], FC[f]
        ax, ay, az = X[fa], Y[fa], Z[fa]
        bx, by, bz = X[fb], Y[fb], Z[fb]
        qx, qy, qz = X[fc], Y[fc], Z[fc]
        volume6 += ax * (by * qz - bz * qy) - ay * (bx * qz - bz * qx) + az * (bx * qy - by * qx)
        nx, ny, nz = NX[f], NY[f], NZ[f]
        g = gcd(gcd(abs(nx), abs(ny)), abs(nz))
        key = (nx // g, ny // g, nz // g)
        face_keys.add(key)
        for vtx in (fa, fb, fc):
            s = vert_planes.get(vtx)
            if s is None:
                s = set()
                vert_planes[vtx] = s
            s.add(key)
    n_vertices = sum(1 for s in vert_planes.values() if len(s) >= 3)
    return (volume6, len(face_keys), n_vertices)
```
