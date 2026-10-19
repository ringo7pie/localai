```python
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(set((int(x), int(y), int(z)) for x, y, z in points))
    if len(pts) < 4:
        raise ValueError("need at least 4 distinct points")
    count = len(pts)
    X = [p[0] for p in pts]
    Y = [p[1] for p in pts]
    Z = [p[2] for p in pts]

    def cross(ax, ay, az, bx, by, bz):
        return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)

    # initial simplex
    i0, i1 = 0, 1
    i2 = -1
    for idx in range(2, count):
        c = cross(X[i1] - X[i0], Y[i1] - Y[i0], Z[i1] - Z[i0],
                  X[idx] - X[i0], Y[idx] - Y[i0], Z[idx] - Z[i0])
        if c != (0, 0, 0):
            i2 = idx
            normal0 = c
            break
    if i2 < 0:
        raise ValueError("all points collinear")
    i3 = -1
    for idx in range(2, count):
        if idx == i2:
            continue
        val = (normal0[0] * (X[idx] - X[i0]) + normal0[1] * (Y[idx] - Y[i0])
               + normal0[2] * (Z[idx] - Z[i0]))
        if val != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points coplanar")

    verts = []
    nrm = []
    dist = []
    outs = []
    alive = []
    emap = {}

    def make_face(a, b, c):
        n = cross(X[b] - X[a], Y[b] - Y[a], Z[b] - Z[a],
                  X[c] - X[a], Y[c] - Y[a], Z[c] - Z[a])
        d = n[0] * X[a] + n[1] * Y[a] + n[2] * Z[a]
        fid = len(verts)
        verts.append((a, b, c))
        nrm.append(n)
        dist.append(d)
        outs.append([])
        alive.append(True)
        emap[(a, b)] = fid
        emap[(b, c)] = fid
        emap[(c, a)] = fid
        return fid

    base = [i0, i1, i2, i3]
    initial = []
    for skip in range(4):
        tri = [base[k] for k in range(4) if k != skip]
        opp = base[skip]
        a, b, c = tri
        n = cross(X[b] - X[a], Y[b] - Y[a], Z[b] - Z[a],
                  X[c] - X[a], Y[c] - Y[a], Z[c] - Z[a])
        side = n[0] * (X[opp] - X[a]) + n[1] * (Y[opp] - Y[a]) + n[2] * (Z[opp] - Z[a])
        if side > 0:
            b, c = c, b
        initial.append(make_face(a, b, c))

    for q in range(count):
        if q in base:
            continue
        for fid in initial:
            n = nrm[fid]
            if n[0] * X[q] + n[1] * Y[q] + n[2] * Z[q] - dist[fid] > 0:
                outs[fid].append(q)
                break

    stack = [fid for fid in initial if outs[fid]]
    while stack:
        f = stack.pop()
        if not alive[f] or not outs[f]:
            continue
        nx, ny, nz = nrm[f]
        df = dist[f]
        best = max(outs[f], key=lambda q: nx * X[q] + ny * Y[q] + nz * Z[q] - df)
        bx, by, bz = X[best], Y[best], Z[best]

        visible = {f}
        frontier = [f]
        hidden = set()
        horizon = []
        while frontier:
            g = frontier.pop()
            a, b, c = verts[g]
            for u, v in ((a, b), (b, c), (c, a)):
                h = emap[(v, u)]
                if h in visible:
                    continue
                if h in hidden:
                    horizon.append((u, v))
                    continue
                n = nrm[h]
                if n[0] * bx + n[1] * by + n[2] * bz - dist[h] > 0:
                    visible.add(h)
                    frontier.append(h)
                else:
                    hidden.add(h)
                    horizon.append((u, v))

        pool = []
        for g in visible:
            pool.extend(outs[g])
            a, b, c = verts[g]
            del emap[(a, b)]
            del emap[(b, c)]
            del emap[(c, a)]
            alive[g] = False
            outs[g] = []

        new_faces = [make_face(u, v, best) for u, v in horizon]
        for q in pool:
            if q == best:
                continue
            qx, qy, qz = X[q], Y[q], Z[q]
            for fid in new_faces:
                n = nrm[fid]
                if n[0] * qx + n[1] * qy + n[2] * qz - dist[fid] > 0:
                    outs[fid].append(q)
                    break
        for fid in new_faces:
            if outs[fid]:
                stack.append(fid)

    volume6 = 0
    planes = set()
    vertex_normals = {}
    for fid in range(len(verts)):
        if not alive[fid]:
            continue
        a, b, c = verts[fid]
        n = nrm[fid]
        volume6 += (X[a] * (Y[b] * Z[c] - Z[b] * Y[c])
                    - Y[a] * (X[b] * Z[c] - Z[b] * X[c])
                    + Z[a] * (X[b] * Y[c] - Y[b] * X[c]))
        g = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2]))
        key = (n[0] // g, n[1] // g, n[2] // g)
        planes.add((key, dist[fid] // g))
        for v in (a, b, c):
            vertex_normals.setdefault(v, set()).add(key)

    n_vertices = 0
    for normals in vertex_normals.values():
        normals = list(normals)
        first = normals[0]
        second = None
        for cand in normals:
            if cross(*first, *cand) != (0, 0, 0):
                second = cand
                break
        if second is None:
            continue
        axis = cross(*first, *second)
        for cand in normals:
            if axis[0] * cand[0] + axis[1] * cand[1] + axis[2] * cand[2] != 0:
                n_vertices += 1
                break

    return (abs(volume6), len(planes), n_vertices)
```
