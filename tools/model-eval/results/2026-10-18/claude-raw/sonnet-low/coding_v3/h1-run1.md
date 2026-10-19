```python
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("need at least 4 distinct points")

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    # initial simplex
    i0, i1 = 0, 1
    base = sub(pts[i1], pts[i0])
    i2 = -1
    for idx in range(2, count):
        if cross(base, sub(pts[idx], pts[i0])) != (0, 0, 0):
            i2 = idx
            break
    if i2 < 0:
        raise ValueError("all points collinear")
    normal0 = cross(base, sub(pts[i2], pts[i0]))
    i3 = -1
    for idx in range(2, count):
        w = sub(pts[idx], pts[i0])
        if normal0[0] * w[0] + normal0[1] * w[1] + normal0[2] * w[2] != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points coplanar")

    faces = []  # each: [a, b, c, nx, ny, nz, d, outside, alive]
    edge = {}

    def make_face(a, b, c):
        pa, pb, pc = pts[a], pts[b], pts[c]
        nx, ny, nz = cross(sub(pb, pa), sub(pc, pa))
        d = nx * pa[0] + ny * pa[1] + nz * pa[2]
        fid = len(faces)
        faces.append([a, b, c, nx, ny, nz, d, [], True])
        edge[(a, b)] = fid
        edge[(b, c)] = fid
        edge[(c, a)] = fid
        return fid

    simplex = [i0, i1, i2, i3]
    new_ids = []
    for omit in range(4):
        tri = [simplex[k] for k in range(4) if k != omit]
        a, b, c = tri
        po = pts[simplex[omit]]
        pa, pb, pc = pts[a], pts[b], pts[c]
        nx, ny, nz = cross(sub(pb, pa), sub(pc, pa))
        if nx * (po[0] - pa[0]) + ny * (po[1] - pa[1]) + nz * (po[2] - pa[2]) > 0:
            b, c = c, b
        new_ids.append(make_face(a, b, c))

    used = set(simplex)
    for idx in range(count):
        if idx in used:
            continue
        x, y, z = pts[idx]
        for fid in new_ids:
            f = faces[fid]
            if f[3] * x + f[4] * y + f[5] * z - f[6] > 0:
                f[7].append(idx)
                break

    stack = [fid for fid in new_ids if faces[fid][7]]
    while stack:
        fid = stack.pop()
        f = faces[fid]
        if not f[8] or not f[7]:
            continue
        best = -1
        best_dist = 0
        for idx in f[7]:
            x, y, z = pts[idx]
            dist = f[3] * x + f[4] * y + f[5] * z - f[6]
            if dist > best_dist:
                best_dist = dist
                best = idx
        px, py, pz = pts[best]

        visible = {fid}
        seen_not = set()
        work = [fid]
        while work:
            cur = faces[work.pop()]
            a, b, c = cur[0], cur[1], cur[2]
            for u, v in ((a, b), (b, c), (c, a)):
                g = edge[(v, u)]
                if g in visible or g in seen_not:
                    continue
                gf = faces[g]
                if gf[3] * px + gf[4] * py + gf[5] * pz - gf[6] > 0:
                    visible.add(g)
                    work.append(g)
                else:
                    seen_not.add(g)

        horizon = []
        orphans = []
        for vid in visible:
            vf = faces[vid]
            a, b, c = vf[0], vf[1], vf[2]
            for u, v in ((a, b), (b, c), (c, a)):
                if edge[(v, u)] not in visible:
                    horizon.append((u, v))
            for idx in vf[7]:
                if idx != best:
                    orphans.append(idx)
        for vid in visible:
            vf = faces[vid]
            a, b, c = vf[0], vf[1], vf[2]
            del edge[(a, b)]
            del edge[(b, c)]
            del edge[(c, a)]
            vf[8] = False
            vf[7] = []

        created = [make_face(u, v, best) for (u, v) in horizon]
        for idx in orphans:
            x, y, z = pts[idx]
            for nid in created:
                nf = faces[nid]
                if nf[3] * x + nf[4] * y + nf[5] * z - nf[6] > 0:
                    nf[7].append(idx)
                    break
        for nid in created:
            if faces[nid][7]:
                stack.append(nid)

    volume6 = 0
    plane_keys = set()
    vertex_normals = {}
    for f in faces:
        if not f[8]:
            continue
        a, b, c, nx, ny, nz, d = f[0], f[1], f[2], f[3], f[4], f[5], f[6]
        pa, pb, pc = pts[a], pts[b], pts[c]
        cx, cy, cz = cross(pb, pc)
        volume6 += pa[0] * cx + pa[1] * cy + pa[2] * cz
        g = gcd(gcd(abs(nx), abs(ny)), abs(nz))
        normal = (nx // g, ny // g, nz // g)
        plane_keys.add((normal, d // g))
        for vertex in (a, b, c):
            vertex_normals.setdefault(vertex, set()).add(normal)

    vertex_count = 0
    for normals in vertex_normals.values():
        normal_list = list(normals)
        n1 = normal_list[0]
        n2 = None
        axis = None
        for candidate in normal_list[1:]:
            cr = cross(n1, candidate)
            if cr != (0, 0, 0):
                n2 = candidate
                axis = cr
                break
        if n2 is None:
            continue
        for candidate in normal_list:
            if axis[0] * candidate[0] + axis[1] * candidate[1] + axis[2] * candidate[2] != 0:
                vertex_count += 1
                break

    return (volume6, len(plane_keys), vertex_count)
```
