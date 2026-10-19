```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("need at least 4 distinct points")

    def sub(u, v):
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0])

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    # initial tetrahedron
    i0 = 0
    i1 = 1
    i2 = -1
    base = sub(pts[i1], pts[i0])
    for idx in range(2, count):
        if cross(base, sub(pts[idx], pts[i0])) != (0, 0, 0):
            i2 = idx
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    normal0 = cross(base, sub(pts[i2], pts[i0]))
    i3 = -1
    for idx in range(2, count):
        if idx != i2 and dot(normal0, sub(pts[idx], pts[i0])) != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    faces = {}
    edge_map = {}
    next_id = [0]
    pf = [set() for _ in range(count)]

    def make_face(i, j, k):
        normal = cross(sub(pts[j], pts[i]), sub(pts[k], pts[i]))
        offset = dot(normal, pts[i])
        fid = next_id[0]
        next_id[0] += 1
        faces[fid] = (i, j, k, normal, offset, set())
        edge_map[(i, j)] = fid
        edge_map[(j, k)] = fid
        edge_map[(k, i)] = fid
        return fid

    def assign(fid, candidates):
        face = faces[fid]
        normal = face[3]
        offset = face[4]
        outside = face[5]
        nx, ny, nz = normal
        for q in candidates:
            pq = pts[q]
            if nx * pq[0] + ny * pq[1] + nz * pq[2] > offset:
                outside.add(q)
                pf[q].add(fid)

    tetra = [i0, i1, i2, i3]
    initial_ids = []
    for omit in range(4):
        tri = [tetra[t] for t in range(4) if t != omit]
        opposite = tetra[omit]
        x, y, z = tri
        normal = cross(sub(pts[y], pts[x]), sub(pts[z], pts[x]))
        if dot(normal, sub(pts[opposite], pts[x])) > 0:
            y, z = z, y
        initial_ids.append(make_face(x, y, z))

    rest = [idx for idx in range(count) if idx not in tetra]
    random.Random(12345).shuffle(rest)
    for fid in initial_ids:
        assign(fid, rest)

    for p in rest:
        visible = set(pf[p])
        if not visible:
            continue
        horizon = []
        for fid in visible:
            a, b, c = faces[fid][0], faces[fid][1], faces[fid][2]
            for u, v in ((a, b), (b, c), (c, a)):
                neighbor = edge_map[(v, u)]
                if neighbor not in visible:
                    cand = faces[fid][5] | faces[neighbor][5]
                    cand.discard(p)
                    horizon.append((u, v, cand))
        for fid in visible:
            a, b, c, _n, _o, outside = faces[fid]
            del edge_map[(a, b)]
            del edge_map[(b, c)]
            del edge_map[(c, a)]
            for q in outside:
                pf[q].discard(fid)
            del faces[fid]
        for u, v, cand in horizon:
            new_id = make_face(u, v, p)
            assign(new_id, cand)

    volume6 = 0
    planes = set()
    vertex_planes = {}
    for i, j, k, normal, offset, _outside in faces.values():
        volume6 += dot(pts[i], cross(pts[j], pts[k]))
        g = gcd(gcd(abs(normal[0]), abs(normal[1])), abs(normal[2]))
        key = (normal[0] // g, normal[1] // g, normal[2] // g, offset // g)
        planes.add(key)
        for v in (i, j, k):
            vertex_planes.setdefault(v, set()).add(key)
    n_vertices = sum(1 for keys in vertex_planes.values() if len(keys) >= 3)
    return (abs(volume6), len(planes), n_vertices)
```
