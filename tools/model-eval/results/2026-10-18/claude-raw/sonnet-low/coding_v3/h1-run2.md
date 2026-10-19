```python
from math import gcd


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def hull3d(points):
    pts = list(set(tuple(p) for p in points))
    if len(pts) < 4:
        raise ValueError("not enough distinct points")
    p0 = pts[0]
    p1 = pts[1]
    d1 = _sub(p1, p0)
    p2 = None
    for q in pts[2:]:
        if _cross(d1, _sub(q, p0)) != (0, 0, 0):
            p2 = q
            break
    if p2 is None:
        raise ValueError("collinear")
    nrm = _cross(d1, _sub(p2, p0))
    p3 = None
    for q in pts[2:]:
        w = _sub(q, p0)
        if nrm[0] * w[0] + nrm[1] * w[1] + nrm[2] * w[2] != 0:
            p3 = q
            break
    if p3 is None:
        raise ValueError("coplanar")

    faces = {}
    edge = {}
    out = {}
    counter = [0]

    def add(a, b, c):
        n = _cross(_sub(b, a), _sub(c, a))
        fid = counter[0]
        counter[0] += 1
        faces[fid] = (a, b, c, n[0], n[1], n[2],
                      n[0] * a[0] + n[1] * a[1] + n[2] * a[2])
        edge[(a, b)] = fid
        edge[(b, c)] = fid
        edge[(c, a)] = fid
        out[fid] = []
        return fid

    def add_oriented(x, y, z, inside):
        n = _cross(_sub(y, x), _sub(z, x))
        w = _sub(inside, x)
        if n[0] * w[0] + n[1] * w[1] + n[2] * w[2] > 0:
            y, z = z, y
        return add(x, y, z)

    base = [p0, p1, p2, p3]
    init = [add_oriented(p0, p1, p2, p3), add_oriented(p0, p1, p3, p2),
            add_oriented(p0, p2, p3, p1), add_oriented(p1, p2, p3, p0)]
    used = set(base)
    for q in pts:
        if q in used:
            continue
        for fid in init:
            f = faces[fid]
            if f[3] * q[0] + f[4] * q[1] + f[5] * q[2] - f[6] > 0:
                out[fid].append(q)
                break
    stack = [fid for fid in init if out[fid]]
    while stack:
        fid = stack.pop()
        if fid not in faces or not out[fid]:
            continue
        f = faces[fid]
        nx, ny, nz = f[3], f[4], f[5]
        p = max(out[fid], key=lambda q: nx * q[0] + ny * q[1] + nz * q[2])
        vis = {fid}
        nonvis = set()
        work = [fid]
        horizon = []
        while work:
            g = faces[work.pop()]
            a, b, c = g[0], g[1], g[2]
            for u, v in ((a, b), (b, c), (c, a)):
                h = edge[(v, u)]
                if h in vis:
                    continue
                if h in nonvis:
                    horizon.append((u, v))
                    continue
                hf = faces[h]
                if hf[3] * p[0] + hf[4] * p[1] + hf[5] * p[2] - hf[6] >= 0:
                    vis.add(h)
                    work.append(h)
                else:
                    nonvis.add(h)
                    horizon.append((u, v))
        pending = []
        for g_id in vis:
            g = faces[g_id]
            a, b, c = g[0], g[1], g[2]
            del edge[(a, b)]
            del edge[(b, c)]
            del edge[(c, a)]
            pending.extend(out[g_id])
            del faces[g_id]
            del out[g_id]
        new_ids = [add(u, v, p) for u, v in horizon]
        for q in pending:
            if q == p:
                continue
            for nid in new_ids:
                nf = faces[nid]
                if nf[3] * q[0] + nf[4] * q[1] + nf[5] * q[2] - nf[6] > 0:
                    out[nid].append(q)
                    break
        for nid in new_ids:
            if out[nid]:
                stack.append(nid)

    volume6 = 0
    planes = {}
    vertex_normals = {}
    for f in faces.values():
        a, b, c, nx, ny, nz, d = f
        volume6 += (a[0] * (b[1] * c[2] - b[2] * c[1])
                    - a[1] * (b[0] * c[2] - b[2] * c[0])
                    + a[2] * (b[0] * c[1] - b[1] * c[0]))
        g = gcd(gcd(abs(nx), abs(ny)), gcd(abs(nz), abs(d)))
        key = (nx // g, ny // g, nz // g, d // g)
        planes[key] = True
        for v in (a, b, c):
            vertex_normals.setdefault(v, set()).add(key[:3])

    n_vertices = 0
    for normals in vertex_normals.values():
        normals = list(normals)
        if len(normals) < 3:
            continue
        first = normals[0]
        axis = None
        for other in normals[1:]:
            cr = _cross(first, other)
            if cr != (0, 0, 0):
                axis = cr
                break
        if axis is None:
            continue
        for other in normals:
            if axis[0] * other[0] + axis[1] * other[1] + axis[2] * other[2] != 0:
                n_vertices += 1
                break
    return (volume6, len(planes), n_vertices)
```
