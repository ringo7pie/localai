```python
import random


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    uniq = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(uniq)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")
    X = [p[0] for p in uniq]
    Y = [p[1] for p in uniq]
    Z = [p[2] for p in uniq]

    i0, i1 = 0, 1
    ux, uy, uz = X[i1] - X[i0], Y[i1] - Y[i0], Z[i1] - Z[i0]
    i2 = -1
    cx = cy = cz = 0
    for idx in range(2, count):
        vx, vy, vz = X[idx] - X[i0], Y[idx] - Y[i0], Z[idx] - Z[i0]
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
        det = cx * (X[idx] - X[i0]) + cy * (Y[idx] - Y[i0]) + cz * (Z[idx] - Z[i0])
        if det:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    FA: list[int] = []
    FB: list[int] = []
    FC: list[int] = []
    NX: list[int] = []
    NY: list[int] = []
    NZ: list[int] = []
    OFF: list[int] = []
    alive: list[bool] = []
    conf: list = []
    edge: dict = {}
    pconf: list[set] = [set() for _ in range(count)]

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
        OFF.append(nx * ax + ny * ay + nz * az)
        alive.append(True)
        conf.append(set())
        edge[(a, b)] = fid
        edge[(b, c)] = fid
        edge[(c, a)] = fid
        return fid

    def side(a: int, b: int, c: int, d: int) -> int:
        ax, ay, az = X[a], Y[a], Z[a]
        bx, by, bz = X[b] - ax, Y[b] - ay, Z[b] - az
        qx, qy, qz = X[c] - ax, Y[c] - ay, Z[c] - az
        nx = by * qz - bz * qy
        ny = bz * qx - bx * qz
        nz = bx * qy - by * qx
        return nx * (X[d] - ax) + ny * (Y[d] - ay) + nz * (Z[d] - az)

    init = []
    for a, b, c, d in ((i0, i1, i2, i3), (i0, i1, i3, i2), (i0, i2, i3, i1), (i1, i2, i3, i0)):
        if side(a, b, c, d) > 0:
            b, c = c, b
        init.append(make_face(a, b, c))

    base = {i0, i1, i2, i3}
    others = [idx for idx in range(count) if idx not in base]
    for q in others:
        qx, qy, qz = X[q], Y[q], Z[q]
        for fid in init:
            if NX[fid] * qx + NY[fid] * qy + NZ[fid] * qz > OFF[fid]:
                conf[fid].add(q)
                pconf[q].add(fid)

    random.Random(0x5EED).shuffle(others)

    for p in others:
        visset = pconf[p]
        if not visset:
            continue
        vis = list(visset)
        horizon = []
        for fid in vis:
            a, b, c = FA[fid], FB[fid], FC[fid]
            for u, v in ((a, b), (b, c), (c, a)):
                g = edge[(v, u)]
                if g not in visset:
                    horizon.append((u, v, fid, g))
        for fid in vis:
            for q in conf[fid]:
                if q != p:
                    pconf[q].discard(fid)
            alive[fid] = False
            a, b, c = FA[fid], FB[fid], FC[fid]
            del edge[(a, b)]
            del edge[(b, c)]
            del edge[(c, a)]
        for u, v, f1, g in horizon:
            nf = make_face(u, v, p)
            nx, ny, nz, off = NX[nf], NY[nf], NZ[nf], OFF[nf]
            cset = conf[nf]
            for q in conf[f1] | conf[g]:
                if q == p:
                    continue
                if nx * X[q] + ny * Y[q] + nz * Z[q] > off:
                    cset.add(q)
                    pconf[q].add(nf)
        for fid in vis:
            conf[fid] = None
        pconf[p] = set()

    live = [fid for fid in range(len(FA)) if alive[fid]]
    parent = {fid: fid for fid in live}

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for fid in live:
        a, b, c = FA[fid], FB[fid], FC[fid]
        for u, v in ((a, b), (b, c), (c, a)):
            g = edge[(v, u)]
            w = FA[g] + FB[g] + FC[g] - u - v
            if NX[fid] * X[w] + NY[fid] * Y[w] + NZ[fid] * Z[w] == OFF[fid]:
                ra, rb = find(fid), find(g)
                if ra != rb:
                    parent[ra] = rb

    roots = set()
    incident: dict = {}
    volume6 = 0
    for fid in live:
        r = find(fid)
        roots.add(r)
        a, b, c = FA[fid], FB[fid], FC[fid]
        for vtx in (a, b, c):
            incident.setdefault(vtx, set()).add(r)
        volume6 += (X[a] * (Y[b] * Z[c] - Z[b] * Y[c])
                    - Y[a] * (X[b] * Z[c] - Z[b] * X[c])
                    + Z[a] * (X[b] * Y[c] - Y[b] * X[c]))

    n_vertices = sum(1 for s in incident.values() if len(s) >= 3)
    return (volume6, len(roots), n_vertices)
```
