```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    uniq = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    if len(uniq) < 4:
        raise ValueError("fewer than 4 distinct points")
    rng = random.Random(20261018)
    rng.shuffle(uniq)
    count = len(uniq)
    xs = [p[0] for p in uniq]
    ys = [p[1] for p in uniq]
    zs = [p[2] for p in uniq]

    # --- initial tetrahedron ---
    ax, ay, az = xs[0], ys[0], zs[0]
    ux, uy, uz = xs[1] - ax, ys[1] - ay, zs[1] - az
    idx2 = -1
    cx = cy = cz = 0
    for idx in range(2, count):
        vx, vy, vz = xs[idx] - ax, ys[idx] - ay, zs[idx] - az
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            idx2 = idx
            break
    if idx2 < 0:
        raise ValueError("all points are collinear")
    idx3 = -1
    for idx in range(2, count):
        if idx == idx2:
            continue
        if cx * (xs[idx] - ax) + cy * (ys[idx] - ay) + cz * (zs[idx] - az):
            idx3 = idx
            break
    if idx3 < 0:
        raise ValueError("all points are coplanar")

    FA: list[int] = []
    FB: list[int] = []
    FC: list[int] = []
    NX: list[int] = []
    NY: list[int] = []
    NZ: list[int] = []
    ND: list[int] = []
    ALIVE: list[bool] = []
    CONF: list = []
    emap: dict[int, int] = {}

    def add_face(a: int, b: int, c: int) -> int:
        x0, y0, z0 = xs[a], ys[a], zs[a]
        bx, by, bz = xs[b] - x0, ys[b] - y0, zs[b] - z0
        qx, qy, qz = xs[c] - x0, ys[c] - y0, zs[c] - z0
        nx = by * qz - bz * qy
        ny = bz * qx - bx * qz
        nz = bx * qy - by * qx
        fid = len(FA)
        FA.append(a)
        FB.append(b)
        FC.append(c)
        NX.append(nx)
        NY.append(ny)
        NZ.append(nz)
        ND.append(nx * x0 + ny * y0 + nz * z0)
        ALIVE.append(True)
        CONF.append([])
        emap[a * count + b] = fid
        emap[b * count + c] = fid
        emap[c * count + a] = fid
        return fid

    tetra = (0, 1, idx2, idx3)
    init_faces = []
    for skip in range(4):
        tri = [tetra[k] for k in range(4) if k != skip]
        rest = tetra[skip]
        a, b, c = tri
        x0, y0, z0 = xs[a], ys[a], zs[a]
        bx, by, bz = xs[b] - x0, ys[b] - y0, zs[b] - z0
        qx, qy, qz = xs[c] - x0, ys[c] - y0, zs[c] - z0
        nx = by * qz - bz * qy
        ny = bz * qx - bx * qz
        nz = bx * qy - by * qx
        if nx * (xs[rest] - x0) + ny * (ys[rest] - y0) + nz * (zs[rest] - z0) > 0:
            b, c = c, b
        init_faces.append(add_face(a, b, c))

    in_tetra = set(tetra)
    point_face = [-1] * count
    for idx in range(count):
        if idx in in_tetra:
            continue
        px, py, pz = xs[idx], ys[idx], zs[idx]
        for fid in init_faces:
            if NX[fid] * px + NY[fid] * py + NZ[fid] * pz > ND[fid]:
                CONF[fid].append(idx)
                point_face[idx] = fid
                break

    # --- incremental insertion ---
    for idx in range(count):
        if idx in in_tetra:
            continue
        f0 = point_face[idx]
        if f0 < 0:
            continue
        px, py, pz = xs[idx], ys[idx], zs[idx]
        visset = {f0}
        stack = [f0]
        horizon = []
        pos = 0
        while pos < len(stack):
            fid = stack[pos]
            pos += 1
            a, b, c = FA[fid], FB[fid], FC[fid]
            for u, v in ((a, b), (b, c), (c, a)):
                gid = emap[v * count + u]
                if gid in visset:
                    continue
                if NX[gid] * px + NY[gid] * py + NZ[gid] * pz > ND[gid]:
                    visset.add(gid)
                    stack.append(gid)
                else:
                    horizon.append((u, v))

        orphans = []
        for fid in stack:
            ALIVE[fid] = False
            a, b, c = FA[fid], FB[fid], FC[fid]
            del emap[a * count + b]
            del emap[b * count + c]
            del emap[c * count + a]
            orphans.extend(CONF[fid])
            CONF[fid] = None

        new_faces = [add_face(u, v, idx) for (u, v) in horizon]

        for q in orphans:
            if q == idx:
                continue
            qx, qy, qz = xs[q], ys[q], zs[q]
            for fid in new_faces:
                if NX[fid] * qx + NY[fid] * qy + NZ[fid] * qz > ND[fid]:
                    CONF[fid].append(q)
                    point_face[q] = fid
                    break
            else:
                point_face[q] = -1

    # --- result ---
    volume6 = 0
    face_keys = set()
    vertex_normals: dict[int, set] = {}
    for fid in range(len(FA)):
        if not ALIVE[fid]:
            continue
        a, b, c = FA[fid], FB[fid], FC[fid]
        x1, y1, z1 = xs[a], ys[a], zs[a]
        x2, y2, z2 = xs[b], ys[b], zs[b]
        x3, y3, z3 = xs[c], ys[c], zs[c]
        volume6 += (
            x1 * (y2 * z3 - z2 * y3)
            - y1 * (x2 * z3 - z2 * x3)
            + z1 * (x2 * y3 - y2 * x3)
        )
        nx, ny, nz = NX[fid], NY[fid], NZ[fid]
        g = gcd(abs(nx), abs(ny), abs(nz))
        key = (nx // g, ny // g, nz // g)
        face_keys.add(key)
        for vid in (a, b, c):
            s = vertex_normals.get(vid)
            if s is None:
                s = set()
                vertex_normals[vid] = s
            s.add(key)

    n_vertices = sum(1 for s in vertex_normals.values() if len(s) >= 3)
    return (volume6, len(face_keys), n_vertices)
```
