```python
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    uniq = sorted(set((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(uniq)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")
    xs = [p[0] for p in uniq]
    ys = [p[1] for p in uniq]
    zs = [p[2] for p in uniq]

    # ---- initial tetrahedron (exact integer arithmetic) ----
    i0 = 0
    x0, y0, z0 = xs[i0], ys[i0], zs[i0]
    best = -1
    i1 = -1
    for idx in range(1, count):
        dx = xs[idx] - x0
        dy = ys[idx] - y0
        dz = zs[idx] - z0
        dist = dx * dx + dy * dy + dz * dz
        if dist > best:
            best = dist
            i1 = idx
    ux, uy, uz = xs[i1] - x0, ys[i1] - y0, zs[i1] - z0
    best = 0
    i2 = -1
    for idx in range(count):
        vx = xs[idx] - x0
        vy = ys[idx] - y0
        vz = zs[idx] - z0
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        mag = cx * cx + cy * cy + cz * cz
        if mag > best:
            best = mag
            i2 = idx
    if i2 < 0:
        raise ValueError("all points are collinear")
    vx, vy, vz = xs[i2] - x0, ys[i2] - y0, zs[i2] - z0
    pnx = uy * vz - uz * vy
    pny = uz * vx - ux * vz
    pnz = ux * vy - uy * vx
    pd = pnx * x0 + pny * y0 + pnz * z0
    best = 0
    i3 = -1
    for idx in range(count):
        val = abs(pnx * xs[idx] + pny * ys[idx] + pnz * zs[idx] - pd)
        if val > best:
            best = val
            i3 = idx
    if i3 < 0:
        raise ValueError("all points are coplanar")

    # ---- face storage ----
    fa: list[int] = []
    fb: list[int] = []
    fc: list[int] = []
    fnx: list[int] = []
    fny: list[int] = []
    fnz: list[int] = []
    fd: list[int] = []
    alive: list[bool] = []
    outside: list = []
    edges: dict[int, int] = {}

    def normal_of(a: int, b: int, c: int):
        ax, ay, az = xs[a], ys[a], zs[a]
        bx, by, bz = xs[b] - ax, ys[b] - ay, zs[b] - az
        cx, cy, cz = xs[c] - ax, ys[c] - ay, zs[c] - az
        nx = by * cz - bz * cy
        ny = bz * cx - bx * cz
        nz = bx * cy - by * cx
        return nx, ny, nz, nx * ax + ny * ay + nz * az

    def make_face(a: int, b: int, c: int) -> int:
        nx, ny, nz, d = normal_of(a, b, c)
        fid = len(fa)
        fa.append(a)
        fb.append(b)
        fc.append(c)
        fnx.append(nx)
        fny.append(ny)
        fnz.append(nz)
        fd.append(d)
        alive.append(True)
        outside.append([])
        edges[a * count + b] = fid
        edges[b * count + c] = fid
        edges[c * count + a] = fid
        return fid

    simplex = (i0, i1, i2, i3)
    for a, b, c, other in (
        (i0, i1, i2, i3),
        (i0, i1, i3, i2),
        (i0, i2, i3, i1),
        (i1, i2, i3, i0),
    ):
        nx, ny, nz, d = normal_of(a, b, c)
        if nx * xs[other] + ny * ys[other] + nz * zs[other] > d:
            b, c = c, b
        make_face(a, b, c)

    simplex_set = set(simplex)
    for idx in range(count):
        if idx in simplex_set:
            continue
        qx, qy, qz = xs[idx], ys[idx], zs[idx]
        for f in range(4):
            if fnx[f] * qx + fny[f] * qy + fnz[f] * qz > fd[f]:
                outside[f].append(idx)
                break

    stack = [f for f in range(4) if outside[f]]

    # ---- QuickHull-style incremental construction with outside sets ----
    while stack:
        f = stack.pop()
        if not alive[f]:
            continue
        out = outside[f]
        if not out:
            continue
        nx, ny, nz = fnx[f], fny[f], fnz[f]
        best = None
        apex = -1
        for q in out:
            val = nx * xs[q] + ny * ys[q] + nz * zs[q]
            if best is None or val > best:
                best = val
                apex = q
        px, py, pz = xs[apex], ys[apex], zs[apex]

        status = {f: True}
        visible = [f]
        horizon = []
        pos = 0
        while pos < len(visible):
            g = visible[pos]
            pos += 1
            a, b, c = fa[g], fb[g], fc[g]
            for u, v in ((a, b), (b, c), (c, a)):
                h = edges[v * count + u]
                st = status.get(h)
                if st is None:
                    st = fnx[h] * px + fny[h] * py + fnz[h] * pz > fd[h]
                    status[h] = st
                    if st:
                        visible.append(h)
                if not st:
                    horizon.append((u, v))

        orphans = []
        for g in visible:
            alive[g] = False
            lst = outside[g]
            if lst:
                orphans.extend(lst)
            outside[g] = None

        new_faces = [make_face(u, v, apex) for u, v in horizon]

        for q in orphans:
            if q == apex:
                continue
            qx, qy, qz = xs[q], ys[q], zs[q]
            for nf in new_faces:
                if fnx[nf] * qx + fny[nf] * qy + fnz[nf] * qz > fd[nf]:
                    outside[nf].append(q)
                    break

        for nf in new_faces:
            if outside[nf]:
                stack.append(nf)

    # ---- measurements ----
    volume6 = 0
    planes: set = set()
    vertex_planes: dict[int, set] = {}
    for f in range(len(fa)):
        if not alive[f]:
            continue
        a, b, c = fa[f], fb[f], fc[f]
        ax, ay, az = xs[a], ys[a], zs[a]
        bx, by, bz = xs[b], ys[b], zs[b]
        cx, cy, cz = xs[c], ys[c], zs[c]
        volume6 += ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx)
        nx, ny, nz, d = fnx[f], fny[f], fnz[f], fd[f]
        divisor = gcd(gcd(abs(nx), abs(ny)), abs(nz))
        key = (nx // divisor, ny // divisor, nz // divisor, d // divisor)
        planes.add(key)
        for vert in (a, b, c):
            entry = vertex_planes.get(vert)
            if entry is None:
                entry = set()
                vertex_planes[vert] = entry
            entry.add(key)

    n_vertices = sum(1 for entry in vertex_planes.values() if len(entry) >= 3)
    return (abs(volume6), len(planes), n_vertices)
```
