```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    unique = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(unique)
    if count < 4:
        raise ValueError("need at least 4 distinct points")
    X = [p[0] for p in unique]
    Y = [p[1] for p in unique]
    Z = [p[2] for p in unique]

    # initial non-degenerate tetrahedron (exact integer arithmetic)
    ax, ay, az = X[1] - X[0], Y[1] - Y[0], Z[1] - Z[0]
    i2 = -1
    cross = (0, 0, 0)
    for k in range(2, count):
        bx, by, bz = X[k] - X[0], Y[k] - Y[0], Z[k] - Z[0]
        cx = ay * bz - az * by
        cy = az * bx - ax * bz
        cz = ax * by - ay * bx
        if cx or cy or cz:
            i2 = k
            cross = (cx, cy, cz)
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for k in range(2, count):
        if k == i2:
            continue
        if (cross[0] * (X[k] - X[0]) + cross[1] * (Y[k] - Y[0])
                + cross[2] * (Z[k] - Z[0])) != 0:
            i3 = k
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    face_vertices = []
    face_normal = []
    face_offset = []
    face_outside = []
    face_alive = []
    edges = {}

    def add_face(u, v, w):
        ux, uy, uz = X[u], Y[u], Z[u]
        ex, ey, ez = X[v] - ux, Y[v] - uy, Z[v] - uz
        fx, fy, fz = X[w] - ux, Y[w] - uy, Z[w] - uz
        nx = ey * fz - ez * fy
        ny = ez * fx - ex * fz
        nz = ex * fy - ey * fx
        face_vertices.append((u, v, w))
        face_normal.append((nx, ny, nz))
        face_offset.append(nx * ux + ny * uy + nz * uz)
        face_outside.append([])
        face_alive.append(True)
        fid = len(face_vertices) - 1
        edges[(u, v)] = fid
        edges[(v, w)] = fid
        edges[(w, u)] = fid
        return fid

    tetra = [0, 1, i2, i3]
    for skip in range(4):
        tri = [tetra[i] for i in range(4) if i != skip]
        other = tetra[skip]
        u, v, w = tri
        ex, ey, ez = X[v] - X[u], Y[v] - Y[u], Z[v] - Z[u]
        fx, fy, fz = X[w] - X[u], Y[w] - Y[u], Z[w] - Z[u]
        nx = ey * fz - ez * fy
        ny = ez * fx - ex * fz
        nz = ex * fy - ey * fx
        side = (nx * (X[other] - X[u]) + ny * (Y[other] - Y[u])
                + nz * (Z[other] - Z[u]))
        if side > 0:
            v, w = w, v
        add_face(u, v, w)

    tetra_set = set(tetra)
    order = [k for k in range(count) if k not in tetra_set]
    assigned = [-1] * count
    for q in order:
        qx, qy, qz = X[q], Y[q], Z[q]
        for f in range(4):
            nx, ny, nz = face_normal[f]
            if nx * qx + ny * qy + nz * qz > face_offset[f]:
                face_outside[f].append(q)
                assigned[q] = f
                break
    random.Random(20261018).shuffle(order)

    for p in order:
        f0 = assigned[p]
        if f0 < 0:
            continue
        px, py, pz = X[p], Y[p], Z[p]
        visible = {f0}
        not_visible = set()
        stack = [f0]
        while stack:
            f = stack.pop()
            u, v, w = face_vertices[f]
            for a, b in ((u, v), (v, w), (w, u)):
                g = edges[(b, a)]
                if g in visible or g in not_visible:
                    continue
                nx, ny, nz = face_normal[g]
                if nx * px + ny * py + nz * pz > face_offset[g]:
                    visible.add(g)
                    stack.append(g)
                else:
                    not_visible.add(g)
        horizon = []
        for f in visible:
            u, v, w = face_vertices[f]
            for a, b in ((u, v), (v, w), (w, u)):
                if edges[(b, a)] not in visible:
                    horizon.append((a, b))
        orphans = []
        for f in visible:
            u, v, w = face_vertices[f]
            del edges[(u, v)]
            del edges[(v, w)]
            del edges[(w, u)]
            face_alive[f] = False
            orphans.extend(face_outside[f])
            face_outside[f] = []
        new_faces = [add_face(a, b, p) for a, b in horizon]
        assigned[p] = -2
        for q in orphans:
            if q == p:
                continue
            qx, qy, qz = X[q], Y[q], Z[q]
            assigned[q] = -1
            for nf in new_faces:
                nx, ny, nz = face_normal[nf]
                if nx * qx + ny * qy + nz * qz > face_offset[nf]:
                    face_outside[nf].append(q)
                    assigned[q] = nf
                    break

    ox, oy, oz = X[0], Y[0], Z[0]
    volume6 = 0
    plane_keys = set()
    incident = {}
    for f in range(len(face_vertices)):
        if not face_alive[f]:
            continue
        u, v, w = face_vertices[f]
        ax, ay, az = X[u] - ox, Y[u] - oy, Z[u] - oz
        bx, by, bz = X[v] - ox, Y[v] - oy, Z[v] - oz
        cx, cy, cz = X[w] - ox, Y[w] - oy, Z[w] - oz
        volume6 += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx)
                    + az * (bx * cy - by * cx))
        nx, ny, nz = face_normal[f]
        g = gcd(gcd(abs(nx), abs(ny)), abs(nz))
        unit = (nx // g, ny // g, nz // g)
        plane_keys.add((unit, face_offset[f] // g))
        for vertex in (u, v, w):
            incident.setdefault(vertex, set()).add(unit)

    n_vertices = 0
    for vertex, normals in incident.items():
        normal_list = list(normals)
        first = normal_list[0]
        axis = None
        for other in normal_list[1:]:
            cx = first[1] * other[2] - first[2] * other[1]
            cy = first[2] * other[0] - first[0] * other[2]
            cz = first[0] * other[1] - first[1] * other[0]
            if cx or cy or cz:
                axis = (cx, cy, cz)
                break
        if axis is None:
            continue
        for other in normal_list:
            if axis[0] * other[0] + axis[1] * other[1] + axis[2] * other[2] != 0:
                n_vertices += 1
                break

    return (abs(volume6), len(plane_keys), n_vertices)
```
