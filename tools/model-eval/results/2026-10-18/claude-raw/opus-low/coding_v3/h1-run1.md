```python
from math import gcd


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys(tuple(int(c) for c in p) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")
    i0 = 0
    i1 = 1
    i2 = -1
    base = _sub(pts[i1], pts[i0])
    for idx in range(2, count):
        if _cross(base, _sub(pts[idx], pts[i0])) != (0, 0, 0):
            i2 = idx
            break
    if i2 < 0:
        raise ValueError("collinear")
    normal0 = _cross(base, _sub(pts[i2], pts[i0]))
    i3 = -1
    for idx in range(count):
        if _dot(normal0, _sub(pts[idx], pts[i0])) != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("coplanar")

    faces = {}   # fid -> (a, b, c, normal, offset)
    edges = {}   # (u, v) -> fid
    outside = {}
    counter = [0]

    def make_face(a, b, c):
        normal = _cross(_sub(pts[b], pts[a]), _sub(pts[c], pts[a]))
        offset = _dot(normal, pts[a])
        fid = counter[0]
        counter[0] += 1
        faces[fid] = (a, b, c, normal, offset)
        edges[(a, b)] = fid
        edges[(b, c)] = fid
        edges[(c, a)] = fid
        outside[fid] = []
        return fid

    if _dot(normal0, _sub(pts[i3], pts[i0])) > 0:
        i1, i2 = i2, i1
    tetra = [make_face(i0, i1, i2), make_face(i0, i3, i1),
             make_face(i1, i3, i2), make_face(i2, i3, i0)]

    used = {i0, i1, i2, i3}
    for idx in range(count):
        if idx in used:
            continue
        pt = pts[idx]
        for fid in tetra:
            fa = faces[fid]
            if _dot(fa[3], pt) - fa[4] > 0:
                outside[fid].append(idx)
                break

    pending = [fid for fid in tetra if outside[fid]]
    while pending:
        fid = pending.pop()
        if fid not in faces or not outside[fid]:
            continue
        fa = faces[fid]
        normal, offset = fa[3], fa[4]
        best = -1
        bestval = 0
        for idx in outside[fid]:
            val = _dot(normal, pts[idx]) - offset
            if val > bestval:
                bestval = val
                best = idx
        apex = pts[best]
        visible = {fid}
        stack = [fid]
        horizon = []
        while stack:
            cur = stack.pop()
            ca, cb, cc = faces[cur][0], faces[cur][1], faces[cur][2]
            for (u, v) in ((ca, cb), (cb, cc), (cc, ca)):
                nb = edges[(v, u)]
                if nb in visible:
                    continue
                nf = faces[nb]
                if _dot(nf[3], apex) - nf[4] > 0:
                    visible.add(nb)
                    stack.append(nb)
        for cur in visible:
            ca, cb, cc = faces[cur][0], faces[cur][1], faces[cur][2]
            for (u, v) in ((ca, cb), (cb, cc), (cc, ca)):
                if edges[(v, u)] not in visible:
                    horizon.append((u, v))
        orphan = []
        for cur in visible:
            ca, cb, cc = faces[cur][0], faces[cur][1], faces[cur][2]
            for edge in ((ca, cb), (cb, cc), (cc, ca)):
                if edges.get(edge) == cur:
                    del edges[edge]
            orphan.extend(outside[cur])
            del faces[cur]
            del outside[cur]
        new_faces = [make_face(u, v, best) for (u, v) in horizon]
        new_data = [(nf, faces[nf][3], faces[nf][4]) for nf in new_faces]
        for idx in orphan:
            if idx == best:
                continue
            pt = pts[idx]
            for nf, nn, no in new_data:
                if _dot(nn, pt) - no > 0:
                    outside[nf].append(idx)
                    break
        for nf in new_faces:
            if outside[nf]:
                pending.append(nf)

    volume6 = 0
    planes = set()
    vertex_planes = {}
    for (a, b, c, normal, offset) in faces.values():
        volume6 += _dot(pts[a], _cross(pts[b], pts[c]))
        g = gcd(gcd(abs(normal[0]), abs(normal[1])), abs(normal[2]))
        key = (normal[0] // g, normal[1] // g, normal[2] // g)
        planes.add(key)
        for vtx in (a, b, c):
            vertex_planes.setdefault(vtx, set()).add(key)
    n_vertices = sum(1 for s in vertex_planes.values() if len(s) >= 3)
    return (volume6, len(planes), n_vertices)
```
