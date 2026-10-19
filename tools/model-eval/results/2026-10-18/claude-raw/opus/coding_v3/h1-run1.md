```python
import math
import random


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    unique = sorted({(int(pt[0]), int(pt[1]), int(pt[2])) for pt in points})
    count = len(unique)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")
    xs = [pt[0] for pt in unique]
    ys = [pt[1] for pt in unique]
    zs = [pt[2] for pt in unique]

    # ---- initial tetrahedron (exact integer arithmetic) ----
    ia = 0
    ax, ay, az = xs[ia], ys[ia], zs[ia]

    def dist2(idx):
        dx = xs[idx] - ax
        dy = ys[idx] - ay
        dz = zs[idx] - az
        return dx * dx + dy * dy + dz * dz

    ib = max(range(count), key=dist2)
    ux, uy, uz = xs[ib] - ax, ys[ib] - ay, zs[ib] - az

    def cross2(idx):
        vx = xs[idx] - ax
        vy = ys[idx] - ay
        vz = zs[idx] - az
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        return cx * cx + cy * cy + cz * cz

    ic = max(range(count), key=cross2)
    if cross2(ic) == 0:
        raise ValueError("all points are collinear")
    vx, vy, vz = xs[ic] - ax, ys[ic] - ay, zs[ic] - az
    pnx = uy * vz - uz * vy
    pny = uz * vx - ux * vz
    pnz = ux * vy - uy * vx
    poff = pnx * ax + pny * ay + pnz * az

    def orient(idx):
        return pnx * xs[idx] + pny * ys[idx] + pnz * zs[idx] - poff

    idd = max(range(count), key=lambda idx: abs(orient(idx)))
    side = orient(idd)
    if side == 0:
        raise ValueError("all points are coplanar")
    if side > 0:
        ib, ic = ic, ib  # make the fourth point lie below plane (a, b, c)

    face_verts = []
    face_plane = []
    face_conf = []
    face_alive = []
    edge_face = {}

    def add_face(va, vb, vc):
        bx, by, bz = xs[va], ys[va], zs[va]
        e1x = xs[vb] - bx
        e1y = ys[vb] - by
        e1z = zs[vb] - bz
        e2x = xs[vc] - bx
        e2y = ys[vc] - by
        e2z = zs[vc] - bz
        fnx = e1y * e2z - e1z * e2y
        fny = e1z * e2x - e1x * e2z
        fnz = e1x * e2y - e1y * e2x
        fid = len(face_verts)
        face_verts.append((va, vb, vc))
        face_plane.append((fnx, fny, fnz, fnx * bx + fny * by + fnz * bz))
        face_conf.append(None)
        face_alive.append(True)
        edge_face[va * count + vb] = fid
        edge_face[vb * count + vc] = fid
        edge_face[vc * count + va] = fid
        return fid

    init_faces = (
        add_face(ia, ib, ic),
        add_face(ia, idd, ib),
        add_face(ib, idd, ic),
        add_face(ic, idd, ia),
    )
    for fid in init_faces:
        face_conf[fid] = []

    # conflict graph: point -> set of faces it strictly sees, face -> list of points
    point_conf = [None] * count
    for qi in range(count):
        qx, qy, qz = xs[qi], ys[qi], zs[qi]
        seen = set()
        for fid in init_faces:
            fnx, fny, fnz, foff = face_plane[fid]
            if fnx * qx + fny * qy + fnz * qz > foff:
                seen.add(fid)
                face_conf[fid].append(qi)
        point_conf[qi] = seen

    initial = {ia, ib, ic, idd}
    order = [idx for idx in range(count) if idx not in initial]
    random.Random(20261018).shuffle(order)

    for pid in order:
        visible = point_conf[pid]
        point_conf[pid] = None
        if not visible:
            continue  # inside or on the current hull

        horizon = []
        for fid in visible:
            va, vb, vc = face_verts[fid]
            nb = edge_face[vb * count + va]
            if nb not in visible:
                horizon.append((va, vb, fid, nb))
            nb = edge_face[vc * count + vb]
            if nb not in visible:
                horizon.append((vb, vc, fid, nb))
            nb = edge_face[va * count + vc]
            if nb not in visible:
                horizon.append((vc, va, fid, nb))

        for fid in visible:
            va, vb, vc = face_verts[fid]
            face_alive[fid] = False
            del edge_face[va * count + vb]
            del edge_face[vb * count + vc]
            del edge_face[vc * count + va]

        for va, vb, dead_face, kept_face in horizon:
            hid = add_face(va, vb, pid)
            fnx, fny, fnz, foff = face_plane[hid]
            conf_dead = face_conf[dead_face]
            conf_kept = face_conf[kept_face]
            if conf_kept:
                cand = set(conf_dead)
                cand.update(conf_kept)
            else:
                cand = conf_dead
            new_conf = [
                qi for qi in cand
                if fnx * xs[qi] + fny * ys[qi] + fnz * zs[qi] > foff
            ]
            face_conf[hid] = new_conf
            for qi in new_conf:
                point_conf[qi].add(hid)

        for fid in visible:
            for qi in face_conf[fid]:
                seen = point_conf[qi]
                if seen is not None:
                    seen.discard(fid)
            face_conf[fid] = None

    # ---- results ----
    volume6 = 0
    normals = set()
    vertex_normals = {}
    for fid in range(len(face_verts)):
        if not face_alive[fid]:
            continue
        va, vb, vc = face_verts[fid]
        ax_, ay_, az_ = xs[va], ys[va], zs[va]
        bx_, by_, bz_ = xs[vb], ys[vb], zs[vb]
        cx_, cy_, cz_ = xs[vc], ys[vc], zs[vc]
        volume6 += (
            ax_ * (by_ * cz_ - bz_ * cy_)
            + ay_ * (bz_ * cx_ - bx_ * cz_)
            + az_ * (bx_ * cy_ - by_ * cx_)
        )
        fnx, fny, fnz, _ = face_plane[fid]
        divisor = math.gcd(fnx, fny, fnz)
        key = (fnx // divisor, fny // divisor, fnz // divisor)
        normals.add(key)
        for vid in (va, vb, vc):
            group = vertex_normals.get(vid)
            if group is None:
                vertex_normals[vid] = {key}
            else:
                group.add(key)

    n_vertices = sum(1 for group in vertex_normals.values() if len(group) >= 3)
    return (volume6, len(normals), n_vertices)
```
