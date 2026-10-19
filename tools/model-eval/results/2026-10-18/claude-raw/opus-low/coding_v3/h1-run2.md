```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys(tuple(int(c) for c in p) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")

    def sub(p, q):
        return (p[0] - q[0], p[1] - q[1], p[2] - q[2])

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    p0 = pts[0]
    i1 = 1
    i2 = None
    for idx in range(2, count):
        if cross(sub(pts[i1], p0), sub(pts[idx], p0)) != (0, 0, 0):
            i2 = idx
            break
    if i2 is None:
        raise ValueError("collinear")
    nrm = cross(sub(pts[i1], p0), sub(pts[i2], p0))
    i3 = None
    for idx in range(count):
        if dot(nrm, sub(pts[idx], p0)) != 0:
            i3 = idx
            break
    if i3 is None:
        raise ValueError("coplanar")

    init = [0, i1, i2, i3]
    rest = [idx for idx in range(count) if idx not in (0, i1, i2, i3)]
    rng = random.Random(12345)
    rng.shuffle(rest)

    face_verts = []
    face_norm = []
    face_alive = []
    face_conf = []
    edge_face = {}
    point_faces = [set() for _ in range(count)]

    def make_face(a, b, c):
        pa = pts[a]
        n = cross(sub(pts[b], pa), sub(pts[c], pa))
        fid = len(face_verts)
        face_verts.append((a, b, c))
        face_norm.append((n, dot(n, pa)))
        face_alive.append(True)
        face_conf.append(set())
        edge_face[(a, b)] = fid
        edge_face[(b, c)] = fid
        edge_face[(c, a)] = fid
        return fid

    a, b, c, d = init
    if dot(cross(sub(pts[b], pts[a]), sub(pts[c], pts[a])), sub(pts[d], pts[a])) > 0:
        b, c = c, b
    initial = [make_face(a, b, c), make_face(a, d, b), make_face(b, d, c), make_face(c, d, a)]

    for q in rest:
        pq = pts[q]
        for fid in initial:
            n, off = face_norm[fid]
            if n[0] * pq[0] + n[1] * pq[1] + n[2] * pq[2] > off:
                face_conf[fid].add(q)
                point_faces[q].add(fid)

    for p in rest:
        visible = point_faces[p]
        if not visible:
            continue
        visible = set(visible)
        horizon = []
        for fid in visible:
            va, vb, vc = face_verts[fid]
            for e0, e1 in ((va, vb), (vb, vc), (vc, va)):
                g = edge_face[(e1, e0)]
                if g not in visible:
                    horizon.append((e0, e1, fid, g))
        for fid in visible:
            face_alive[fid] = False
            va, vb, vc = face_verts[fid]
            for e in ((va, vb), (vb, vc), (vc, va)):
                if edge_face.get(e) == fid:
                    del edge_face[e]
        for fid in visible:
            for q in face_conf[fid]:
                point_faces[q].discard(fid)
        pp = pts[p]
        for e0, e1, f1, f2 in horizon:
            nf = make_face(e0, e1, p)
            n, off = face_norm[nf]
            nx, ny, nz = n
            conf = face_conf[nf]
            for q in face_conf[f1] | face_conf[f2]:
                if q == p or q in conf:
                    continue
                pq = pts[q]
                if nx * pq[0] + ny * pq[1] + nz * pq[2] > off:
                    conf.add(q)
                    point_faces[q].add(nf)
        for fid in visible:
            face_conf[fid] = set()
        point_faces[p] = set()

    vol6 = 0
    keys = set()
    vert_planes = {}
    for fid, alive in enumerate(face_alive):
        if not alive:
            continue
        va, vb, vc = face_verts[fid]
        vol6 += dot(pts[va], cross(pts[vb], pts[vc]))
        n = face_norm[fid][0]
        g = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2]))
        key = (n[0] // g, n[1] // g, n[2] // g)
        keys.add(key)
        for v in (va, vb, vc):
            vert_planes.setdefault(v, set()).add(key)
    n_vertices = sum(1 for s in vert_planes.values() if len(s) >= 3)
    return (vol6, len(keys), n_vertices)
```
