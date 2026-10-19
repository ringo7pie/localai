```python
import math
import random


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    distinct = sorted({(int(p[0]), int(p[1]), int(p[2])) for p in points})
    if len(distinct) < 4:
        raise ValueError("distinct points are fewer than 4")
    pts = distinct
    random.Random(20261018).shuffle(pts)
    count = len(pts)

    # --- 最初の四面体を整数だけで探す ---
    x0, y0, z0 = pts[0]
    ux, uy, uz = pts[1][0] - x0, pts[1][1] - y0, pts[1][2] - z0
    idx_c = -1
    normal = (0, 0, 0)
    for i in range(2, count):
        vx, vy, vz = pts[i][0] - x0, pts[i][1] - y0, pts[i][2] - z0
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            idx_c = i
            normal = (cx, cy, cz)
            break
    if idx_c < 0:
        raise ValueError("all points are collinear")
    idx_d = -1
    orient = 0
    for i in range(2, count):
        if i == idx_c:
            continue
        w = (pts[i][0] - x0) * normal[0] + (pts[i][1] - y0) * normal[1] + (pts[i][2] - z0) * normal[2]
        if w != 0:
            idx_d = i
            orient = w
            break
    if idx_d < 0:
        raise ValueError("all points are coplanar")

    ia, ib, ic, id_ = 0, 1, idx_c, idx_d
    if orient > 0:
        ib, ic = ic, ib  # d が (a, b, c) の裏側に来るように向きをそろえる

    # --- 面の記憶域 ---
    fverts = []
    fplane = []
    fout = []
    falive = []
    edge_face = {}

    def add_face(a, b, c):
        ax, ay, az = pts[a]
        bx, by, bz = pts[b]
        cx, cy, cz = pts[c]
        ex, ey, ez = bx - ax, by - ay, bz - az
        gx, gy, gz = cx - ax, cy - ay, cz - az
        nx = ey * gz - ez * gy
        ny = ez * gx - ex * gz
        nz = ex * gy - ey * gx
        fid = len(fverts)
        fverts.append((a, b, c))
        fplane.append((nx, ny, nz, nx * ax + ny * ay + nz * az))
        fout.append([])
        falive.append(True)
        edge_face[(a, b)] = fid
        edge_face[(b, c)] = fid
        edge_face[(c, a)] = fid
        return fid

    first_faces = [
        add_face(ia, ib, ic),
        add_face(ib, ia, id_),
        add_face(ic, ib, id_),
        add_face(ia, ic, id_),
    ]
    used = {ia, ib, ic, id_}
    first_planes = [(fplane[f], fout[f]) for f in first_faces]
    for q in range(count):
        if q in used:
            continue
        x, y, z = pts[q]
        for (nx, ny, nz, d), lst in first_planes:
            if nx * x + ny * y + nz * z > d:
                lst.append(q)
                break

    # --- 外側の点集合を面ごとに持つ増分構築 ---
    pending = [f for f in first_faces if fout[f]]
    while pending:
        f0 = pending.pop()
        if not falive[f0]:
            continue
        outside = fout[f0]
        if not outside:
            continue
        p = outside.pop()
        px, py, pz = pts[p]

        visible = {f0}
        nonvisible = set()
        stack = [f0]
        horizon = []
        while stack:
            f = stack.pop()
            a, b, c = fverts[f]
            for u, v in ((a, b), (b, c), (c, a)):
                g = edge_face[(v, u)]
                if g in visible:
                    continue
                if g in nonvisible:
                    horizon.append((u, v))
                    continue
                nx, ny, nz, d = fplane[g]
                if nx * px + ny * py + nz * pz > d:
                    visible.add(g)
                    stack.append(g)
                else:
                    nonvisible.add(g)
                    horizon.append((u, v))

        orphans = []
        for f in visible:
            a, b, c = fverts[f]
            del edge_face[(a, b)]
            del edge_face[(b, c)]
            del edge_face[(c, a)]
            falive[f] = False
            orphans.extend(fout[f])
            fout[f] = []

        new_ids = [add_face(u, v, p) for u, v in horizon]
        new_planes = [(fplane[i], fout[i]) for i in new_ids]
        for q in orphans:
            x, y, z = pts[q]
            for (nx, ny, nz, d), lst in new_planes:
                if nx * x + ny * y + nz * z > d:
                    lst.append(q)
                    break
        for i in new_ids:
            if fout[i]:
                pending.append(i)

    # --- 集計 ---
    volume6 = 0
    plane_ids = {}
    vertex_planes = {}
    for fid in range(len(fverts)):
        if not falive[fid]:
            continue
        nx, ny, nz, d = fplane[fid]
        volume6 += d
        g = math.gcd(nx, ny, nz)
        key = (nx // g, ny // g, nz // g, d // g)
        pid = plane_ids.get(key)
        if pid is None:
            pid = len(plane_ids)
            plane_ids[key] = pid
        for v in fverts[fid]:
            holder = vertex_planes.get(v)
            if holder is None:
                holder = set()
                vertex_planes[v] = holder
            holder.add(pid)

    n_faces = len(plane_ids)
    n_vertices = sum(1 for holder in vertex_planes.values() if len(holder) >= 3)
    return (volume6, n_faces, n_vertices)
```
