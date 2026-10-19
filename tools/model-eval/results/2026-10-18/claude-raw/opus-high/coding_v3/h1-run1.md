```python
import math


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    unique_points = set()
    for point in points:
        px, py, pz = point
        unique_points.add((int(px), int(py), int(pz)))
    pts = sorted(unique_points)
    count = len(pts)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    zs = [pt[2] for pt in pts]

    # initial tetrahedron
    i0, i1 = 0, count - 1
    x0, y0, z0 = xs[i0], ys[i0], zs[i0]
    ux, uy, uz = xs[i1] - x0, ys[i1] - y0, zs[i1] - z0
    best_cross = 0
    i2 = -1
    for k in range(count):
        wx, wy, wz = xs[k] - x0, ys[k] - y0, zs[k] - z0
        cx = uy * wz - uz * wy
        cy = uz * wx - ux * wz
        cz = ux * wy - uy * wx
        mag = cx * cx + cy * cy + cz * cz
        if mag > best_cross:
            best_cross = mag
            i2 = k
    if i2 < 0:
        raise ValueError("all points are collinear")
    wx, wy, wz = xs[i2] - x0, ys[i2] - y0, zs[i2] - z0
    bnx = uy * wz - uz * wy
    bny = uz * wx - ux * wz
    bnz = ux * wy - uy * wx
    bd = bnx * x0 + bny * y0 + bnz * z0
    best_dist = 0
    i3 = -1
    for k in range(count):
        val = bnx * xs[k] + bny * ys[k] + bnz * zs[k] - bd
        if val < 0:
            val = -val
        if val > best_dist:
            best_dist = val
            i3 = k
    if i3 < 0:
        raise ValueError("all points are coplanar")

    va, vb, vc, vd = i0, i1, i2, i3
    if bnx * xs[vd] + bny * ys[vd] + bnz * zs[vd] - bd > 0:
        vb, vc = vc, vb

    face_a = []
    face_b = []
    face_c = []
    face_plane = []
    alive = []
    outside = []
    edge_face = {}

    def add_face(pa, pb, pc):
        ax, ay, az = xs[pa], ys[pa], zs[pa]
        ex, ey, ez = xs[pb] - ax, ys[pb] - ay, zs[pb] - az
        fx, fy, fz = xs[pc] - ax, ys[pc] - ay, zs[pc] - az
        nx = ey * fz - ez * fy
        ny = ez * fx - ex * fz
        nz = ex * fy - ey * fx
        fid = len(face_a)
        face_a.append(pa)
        face_b.append(pb)
        face_c.append(pc)
        face_plane.append((nx, ny, nz, nx * ax + ny * ay + nz * az))
        alive.append(True)
        outside.append([])
        edge_face[pa * count + pb] = fid
        edge_face[pb * count + pc] = fid
        edge_face[pc * count + pa] = fid
        return fid

    initial = [
        add_face(va, vb, vc),
        add_face(va, vd, vb),
        add_face(vb, vd, vc),
        add_face(vc, vd, va),
    ]
    used = {va, vb, vc, vd}
    for k in range(count):
        if k in used:
            continue
        qx, qy, qz = xs[k], ys[k], zs[k]
        for fid in initial:
            nx, ny, nz, dd = face_plane[fid]
            if nx * qx + ny * qy + nz * qz > dd:
                outside[fid].append(k)
                break

    stack = [fid for fid in initial if outside[fid]]
    while stack:
        fid = stack.pop()
        if not alive[fid]:
            continue
        out = outside[fid]
        if not out:
            continue
        nx, ny, nz, dd = face_plane[fid]
        eye = out[0]
        best_val = nx * xs[eye] + ny * ys[eye] + nz * zs[eye]
        for q in out:
            val = nx * xs[q] + ny * ys[q] + nz * zs[q]
            if val > best_val:
                best_val = val
                eye = q
        px, py, pz = xs[eye], ys[eye], zs[eye]

        # find visible faces (strictly) and horizon
        visible = {fid}
        not_visible = set()
        horizon = []
        work = [fid]
        while work:
            g = work.pop()
            ga, gb, gc = face_a[g], face_b[g], face_c[g]
            for eu, ev in ((ga, gb), (gb, gc), (gc, ga)):
                h = edge_face[ev * count + eu]
                if h in visible:
                    continue
                if h in not_visible:
                    horizon.append((eu, ev))
                    continue
                hx, hy, hz, hd = face_plane[h]
                if hx * px + hy * py + hz * pz > hd:
                    visible.add(h)
                    work.append(h)
                else:
                    not_visible.add(h)
                    horizon.append((eu, ev))

        pending = []
        for g in visible:
            alive[g] = False
            ga, gb, gc = face_a[g], face_b[g], face_c[g]
            del edge_face[ga * count + gb]
            del edge_face[gb * count + gc]
            del edge_face[gc * count + ga]
            if outside[g]:
                pending.extend(outside[g])
            outside[g] = None

        new_faces = []
        for eu, ev in horizon:
            new_faces.append(add_face(eu, ev, eye))
        new_planes = [(face_plane[nf], outside[nf]) for nf in new_faces]

        for q in pending:
            if q == eye:
                continue
            qx, qy, qz = xs[q], ys[q], zs[q]
            for (nx, ny, nz, dd), lst in new_planes:
                if nx * qx + ny * qy + nz * qz > dd:
                    lst.append(q)
                    break

        for nf in new_faces:
            if outside[nf]:
                stack.append(nf)

    volume6 = 0
    face_keys = set()
    vertex_groups = {}
    for fid in range(len(face_a)):
        if not alive[fid]:
            continue
        pa, pb, pc = face_a[fid], face_b[fid], face_c[fid]
        ax, ay, az = xs[pa], ys[pa], zs[pa]
        bx, by, bz = xs[pb], ys[pb], zs[pb]
        cx, cy, cz = xs[pc], ys[pc], zs[pc]
        volume6 += ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx)
        nx, ny, nz, dd = face_plane[fid]
        div = math.gcd(nx, ny, nz)
        key = (nx // div, ny // div, nz // div, dd // div)
        face_keys.add(key)
        for vert in (pa, pb, pc):
            groups = vertex_groups.get(vert)
            if groups is None:
                groups = set()
                vertex_groups[vert] = groups
            groups.add(key)

    n_vertices = 0
    for groups in vertex_groups.values():
        if len(groups) >= 3:
            n_vertices += 1

    return (abs(volume6), len(face_keys), n_vertices)
```
