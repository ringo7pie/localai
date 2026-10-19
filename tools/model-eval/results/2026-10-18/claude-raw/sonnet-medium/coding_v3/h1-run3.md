```python
import random
from math import gcd


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _sub(u, v):
    return (u[0] - v[0], u[1] - v[1], u[2] - v[2])


def hull3d(points):
    pts = sorted(set((int(x), int(y), int(z)) for x, y, z in points))
    if len(pts) < 4:
        raise ValueError("need at least 4 distinct points")

    p0 = pts[0]
    p1 = pts[1]
    d01 = _sub(p1, p0)
    i2 = -1
    normal2 = None
    for idx in range(2, len(pts)):
        cr = _cross(d01, _sub(pts[idx], p0))
        if cr != (0, 0, 0):
            i2 = idx
            normal2 = cr
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for idx in range(2, len(pts)):
        if idx != i2 and _dot(normal2, _sub(pts[idx], p0)) != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    rest = [pts[k] for k in range(2, len(pts)) if k != i2 and k != i3]
    random.Random(12345).shuffle(rest)
    P = [p0, p1, pts[i2], pts[i3]] + rest
    count = len(P)

    faces = {}       # id -> (a, b, c, nx, ny, nz, d)
    conflict = {}    # id -> list of point indices
    edge = {}        # (u, v) -> face id
    conf = [set() for _ in range(count)]
    counter = [0]

    def make(a, b, c):
        pa = P[a]
        nrm = _cross(_sub(P[b], pa), _sub(P[c], pa))
        return (a, b, c, nrm[0], nrm[1], nrm[2], _dot(nrm, pa))

    def add_face(a, b, c, candidates):
        face = make(a, b, c)
        fid = counter[0]
        counter[0] += 1
        faces[fid] = face
        edge[(a, b)] = fid
        edge[(b, c)] = fid
        edge[(c, a)] = fid
        nx, ny, nz, d = face[3], face[4], face[5], face[6]
        lst = []
        for q in candidates:
            pq = P[q]
            if nx * pq[0] + ny * pq[1] + nz * pq[2] > d:
                lst.append(q)
                conf[q].add(fid)
        conflict[fid] = lst
        return fid

    base = range(4, count)
    for (a, b, c, opp) in ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)):
        face = make(a, b, c)
        if _dot((face[3], face[4], face[5]), P[opp]) > face[6]:
            b, c = c, b
        add_face(a, b, c, base)

    for p in range(4, count):
        if not conf[p]:
            continue
        vis = set(conf[p])
        horizon = []
        for f in vis:
            a, b, c = faces[f][0], faces[f][1], faces[f][2]
            for (u, v) in ((a, b), (b, c), (c, a)):
                g = edge[(v, u)]
                if g not in vis:
                    horizon.append((u, v, f, g))
        for f in vis:
            a, b, c = faces[f][0], faces[f][1], faces[f][2]
            del edge[(a, b)]
            del edge[(b, c)]
            del edge[(c, a)]
        for (u, v, f, g) in horizon:
            cand = set(conflict[f])
            cand.update(conflict[g])
            add_face(u, v, p, cand)
        for f in vis:
            for q in conflict[f]:
                conf[q].discard(f)
            del conflict[f]
            del faces[f]

    volume6 = 0
    planes = {}
    vertex_planes = {}
    for (a, b, c, nx, ny, nz, d) in faces.values():
        volume6 += nx * (P[a][0] - p0[0]) + ny * (P[a][1] - p0[1]) + nz * (P[a][2] - p0[2])
        g = gcd(gcd(abs(nx), abs(ny)), abs(nz))
        key = (nx // g, ny // g, nz // g, d // g)
        planes[key] = True
        normal = key[:3]
        for v in (a, b, c):
            vertex_planes.setdefault(v, set()).add(normal)

    n_vertices = 0
    for normals in vertex_planes.values():
        if len(normals) < 3:
            continue
        lst = list(normals)
        n1 = lst[0]
        cross12 = None
        for n2 in lst[1:]:
            cr = _cross(n1, n2)
            if cr != (0, 0, 0):
                cross12 = cr
                break
        if cross12 is None:
            continue
        for n3 in lst:
            if _dot(cross12, n3) != 0:
                n_vertices += 1
                break

    return (volume6, len(planes), n_vertices)
```
