```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    uniq = list(dict.fromkeys((x, y, z) for x, y, z in points))
    count = len(uniq)
    if count < 4:
        raise ValueError("異なる点が 4 つ未満です")
    random.Random(918273645).shuffle(uniq)
    xs = [pt[0] for pt in uniq]
    ys = [pt[1] for pt in uniq]
    zs = [pt[2] for pt in uniq]

    # ---- 初期四面体 ----
    x0, y0, z0 = xs[0], ys[0], zs[0]
    i1 = -1
    best = 0
    for idx in range(1, count):
        dx = xs[idx] - x0
        dy = ys[idx] - y0
        dz = zs[idx] - z0
        dist = dx * dx + dy * dy + dz * dz
        if dist > best:
            best = dist
            i1 = idx
    ux = xs[i1] - x0
    uy = ys[i1] - y0
    uz = zs[i1] - z0
    i2 = -1
    best = 0
    nx = ny = nz = 0
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
            nx, ny, nz = cx, cy, cz
    if i2 < 0:
        raise ValueError("すべての点が 1 つの直線上にあります")
    i3 = -1
    best = 0
    sign = 0
    for idx in range(count):
        orient = nx * (xs[idx] - x0) + ny * (ys[idx] - y0) + nz * (zs[idx] - z0)
        mag = orient if orient >= 0 else -orient
        if mag > best:
            best = mag
            i3 = idx
            sign = orient
    if i3 < 0:
        raise ValueError("すべての点が 1 つの平面上にあります")
    i0 = 0
    if sign > 0:
        i1, i2 = i2, i1

    # ---- 面の保持 ----
    fa: list[int] = []
    fb: list[int] = []
    fc: list[int] = []
    fnx: list[int] = []
    fny: list[int] = []
    fnz: list[int] = []
    fd: list[int] = []
    alive: list[bool] = []
    outside: list = []
    edge: dict[int, int] = {}

    def add_face(a: int, b: int, c: int) -> int:
        ax = xs[a]
        ay = ys[a]
        az = zs[a]
        bx = xs[b] - ax
        by = ys[b] - ay
        bz = zs[b] - az
        cx = xs[c] - ax
        cy = ys[c] - ay
        cz = zs[c] - az
        fx = by * cz - bz * cy
        fy = bz * cx - bx * cz
        fz = bx * cy - by * cx
        face = len(fa)
        fa.append(a)
        fb.append(b)
        fc.append(c)
        fnx.append(fx)
        fny.append(fy)
        fnz.append(fz)
        fd.append(fx * ax + fy * ay + fz * az)
        alive.append(True)
        outside.append([])
        edge[a * count + b] = face
        edge[b * count + c] = face
        edge[c * count + a] = face
        return face

    add_face(i0, i1, i2)
    add_face(i0, i3, i1)
    add_face(i0, i2, i3)
    add_face(i1, i3, i2)

    # assign: >=0 は割り当てた面、-1 は内側（捨てた）、-2 は挿入済み
    assign = [-1] * count
    for idx in (i0, i1, i2, i3):
        assign[idx] = -2
    for idx in range(count):
        if assign[idx] == -2:
            continue
        px = xs[idx]
        py = ys[idx]
        pz = zs[idx]
        for face in range(4):
            if fnx[face] * px + fny[face] * py + fnz[face] * pz > fd[face]:
                outside[face].append(idx)
                assign[idx] = face
                break

    # ---- 乱択逐次構成 ----
    for pidx in range(count):
        start = assign[pidx]
        if start < 0:
            continue
        px = xs[pidx]
        py = ys[pidx]
        pz = zs[pidx]
        state = {start: True}
        visible = [start]
        stack = [start]
        horizon = []
        while stack:
            face = stack.pop()
            a = fa[face]
            b = fb[face]
            c = fc[face]
            for u, v in ((a, b), (b, c), (c, a)):
                nb = edge[v * count + u]
                st = state.get(nb)
                if st is None:
                    st = fnx[nb] * px + fny[nb] * py + fnz[nb] * pz > fd[nb]
                    state[nb] = st
                    if st:
                        visible.append(nb)
                        stack.append(nb)
                if not st:
                    horizon.append((u, v))

        orphans = []
        for face in visible:
            alive[face] = False
            lst = outside[face]
            if lst:
                orphans.extend(lst)
            outside[face] = None
        assign[pidx] = -2

        new_faces = [add_face(u, v, pidx) for u, v in horizon]

        for q in orphans:
            if q == pidx:
                continue
            qx = xs[q]
            qy = ys[q]
            qz = zs[q]
            for nf in new_faces:
                if fnx[nf] * qx + fny[nf] * qy + fnz[nf] * qz > fd[nf]:
                    outside[nf].append(q)
                    assign[q] = nf
                    break
            else:
                assign[q] = -1

    # ---- 集計 ----
    volume6 = 0
    face_keys = set()
    vert_normals: dict[int, set] = {}
    for face in range(len(fa)):
        if not alive[face]:
            continue
        a = fa[face]
        b = fb[face]
        c = fc[face]
        fx = fnx[face]
        fy = fny[face]
        fz = fnz[face]
        g = gcd(fx, fy, fz)
        key = (fx // g, fy // g, fz // g)
        face_keys.add(key)
        for vtx in (a, b, c):
            normals = vert_normals.get(vtx)
            if normals is None:
                vert_normals[vtx] = {key}
            else:
                normals.add(key)
        ax = xs[a]
        ay = ys[a]
        az = zs[a]
        bx = xs[b]
        by = ys[b]
        bz = zs[b]
        cx = xs[c]
        cy = ys[c]
        cz = zs[c]
        volume6 += ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx)

    n_vertices = 0
    for normals in vert_normals.values():
        if len(normals) >= 3:
            n_vertices += 1
    return (volume6, len(face_keys), n_vertices)
```
