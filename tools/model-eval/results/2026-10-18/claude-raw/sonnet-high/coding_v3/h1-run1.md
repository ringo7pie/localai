```python
import math
import random


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("need at least 4 distinct points")

    X = [p[0] for p in pts]
    Y = [p[1] for p in pts]
    Z = [p[2] for p in pts]

    # ---- initial non-degenerate tetrahedron ----
    ux, uy, uz = X[1] - X[0], Y[1] - Y[0], Z[1] - Z[0]
    i2 = -1
    normal = (0, 0, 0)
    for i in range(2, count):
        vx, vy, vz = X[i] - X[0], Y[i] - Y[0], Z[i] - Z[0]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            i2 = i
            normal = (cx, cy, cz)
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    side = 0
    for i in range(2, count):
        if i == i2:
            continue
        side = (
            normal[0] * (X[i] - X[0])
            + normal[1] * (Y[i] - Y[0])
            + normal[2] * (Z[i] - Z[0])
        )
        if side != 0:
            i3 = i
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    t0, t1, t2, t3 = 0, 1, i2, i3
    if side > 0:
        t1, t2 = t2, t1  # now (t0, t1, t2) is outward and t3 is below it

    fverts = []
    fnorm = []
    fconf = []
    edge_face = {}

    def add_face(a, b, c):
        ax, ay, az = X[a], Y[a], Z[a]
        ex, ey, ez = X[b] - ax, Y[b] - ay, Z[b] - az
        fx, fy, fz = X[c] - ax, Y[c] - ay, Z[c] - az
        nx = ey * fz - ez * fy
        ny = ez * fx - ex * fz
        nz = ex * fy - ey * fx
        fverts.append((a, b, c))
        fnorm.append((nx, ny, nz, nx * ax + ny * ay + nz * az))
        fconf.append(None)
        return len(fverts) - 1

    initial = [
        add_face(t0, t1, t2),
        add_face(t0, t3, t1),
        add_face(t1, t3, t2),
        add_face(t2, t3, t0),
    ]
    for fid in initial:
        a, b, c = fverts[fid]
        edge_face[(a, b)] = fid
        edge_face[(b, c)] = fid
        edge_face[(c, a)] = fid

    used = {t0, t1, t2, t3}
    order = [i for i in range(count) if i not in used]
    random.Random(20261018).shuffle(order)

    pconf = [set() for _ in range(count)]
    for fid in initial:
        nx, ny, nz, d = fnorm[fid]
        conf = []
        for q in order:
            if nx * X[q] + ny * Y[q] + nz * Z[q] > d:
                conf.append(q)
                pconf[q].add(fid)
        fconf[fid] = conf

    mark = [0] * count
    stamp = 0

    # ---- incremental insertion with a conflict graph ----
    for p in order:
        vis = pconf[p]
        if not vis:
            continue
        vset = set(vis)

        horizon = []
        for f in vset:
            a, b, c = fverts[f]
            for u, v in ((a, b), (b, c), (c, a)):
                g = edge_face[(v, u)]
                if g not in vset:
                    horizon.append((u, v, f, g))

        for f in vset:
            a, b, c = fverts[f]
            del edge_face[(a, b)]
            del edge_face[(b, c)]
            del edge_face[(c, a)]

        for u, v, f, g in horizon:
            nid = add_face(u, v, p)
            nx, ny, nz, d = fnorm[nid]
            conf = []
            stamp += 1
            for q in fconf[f]:
                mark[q] = stamp
                if nx * X[q] + ny * Y[q] + nz * Z[q] > d:
                    conf.append(q)
            for q in fconf[g]:
                if mark[q] != stamp and nx * X[q] + ny * Y[q] + nz * Z[q] > d:
                    conf.append(q)
            fconf[nid] = conf
            for q in conf:
                pconf[q].add(nid)
            edge_face[(u, v)] = nid
            edge_face[(v, p)] = nid
            edge_face[(p, u)] = nid

        for f in vset:
            for q in fconf[f]:
                pconf[q].discard(f)
            fconf[f] = None

    # ---- collect results ----
    volume6 = 0
    planes = set()
    vertex_normals = {}
    gcd = math.gcd
    for fid in range(len(fverts)):
        if fconf[fid] is None:
            continue
        a, b, c = fverts[fid]
        volume6 += (
            X[a] * (Y[b] * Z[c] - Z[b] * Y[c])
            - Y[a] * (X[b] * Z[c] - Z[b] * X[c])
            + Z[a] * (X[b] * Y[c] - Y[b] * X[c])
        )
        nx, ny, nz, d = fnorm[fid]
        g = gcd(gcd(nx, ny), nz)
        key = (nx // g, ny // g, nz // g)
        planes.add((key, d // g))
        for vertex in (a, b, c):
            bucket = vertex_normals.get(vertex)
            if bucket is None:
                vertex_normals[vertex] = {key}
            else:
                bucket.add(key)

    n_vertices = 0
    for normals in vertex_normals.values():
        if len(normals) < 3:
            continue
        first = None
        second = None
        spans = False
        for n in normals:
            if first is None:
                first = n
                continue
            if second is None:
                cx = first[1] * n[2] - first[2] * n[1]
                cy = first[2] * n[0] - first[0] * n[2]
                cz = first[0] * n[1] - first[1] * n[0]
                if cx or cy or cz:
                    second = (cx, cy, cz)
                continue
            if second[0] * n[0] + second[1] * n[1] + second[2] * n[2] != 0:
                spans = True
                break
        if spans:
            n_vertices += 1

    return (abs(volume6), len(planes), n_vertices)
```
