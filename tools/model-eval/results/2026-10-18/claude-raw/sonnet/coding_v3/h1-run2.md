```python
import random
from math import gcd


class _Face:
    __slots__ = ("a", "b", "c", "nx", "ny", "nz", "d", "out", "stamp", "vis")


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("need at least 4 distinct points")

    # ---- 最初の四面体を探す（整数だけで判定する） ----
    ax, ay, az = pts[0]
    ux, uy, uz = pts[1][0] - ax, pts[1][1] - ay, pts[1][2] - az
    i2 = -1
    base_normal = (0, 0, 0)
    for idx in range(2, count):
        vx, vy, vz = pts[idx][0] - ax, pts[idx][1] - ay, pts[idx][2] - az
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            i2 = idx
            base_normal = (cx, cy, cz)
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for idx in range(i2 + 1, count):
        if (base_normal[0] * (pts[idx][0] - ax)
                + base_normal[1] * (pts[idx][1] - ay)
                + base_normal[2] * (pts[idx][2] - az)) != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    def make_face(a: int, b: int, c: int) -> _Face:
        pax, pay, paz = pts[a]
        pbx, pby, pbz = pts[b]
        pcx, pcy, pcz = pts[c]
        e1x, e1y, e1z = pbx - pax, pby - pay, pbz - paz
        e2x, e2y, e2z = pcx - pax, pcy - pay, pcz - paz
        face = _Face()
        face.a = a
        face.b = b
        face.c = c
        face.nx = e1y * e2z - e1z * e2y
        face.ny = e1z * e2x - e1x * e2z
        face.nz = e1x * e2y - e1y * e2x
        face.d = face.nx * pax + face.ny * pay + face.nz * paz
        face.out = []
        face.stamp = 0
        face.vis = False
        return face

    edge_map: dict[tuple[int, int], _Face] = {}
    initial_faces: list[_Face] = []
    for a, b, c, opposite in (
        (0, 1, i2, i3),
        (0, 1, i3, i2),
        (0, i2, i3, 1),
        (1, i2, i3, 0),
    ):
        face = make_face(a, b, c)
        ox, oy, oz = pts[opposite]
        pax, pay, paz = pts[a]
        if face.nx * (ox - pax) + face.ny * (oy - pay) + face.nz * (oz - paz) > 0:
            face = make_face(a, c, b)
        initial_faces.append(face)
        edge_map[(face.a, face.b)] = face
        edge_map[(face.b, face.c)] = face
        edge_map[(face.c, face.a)] = face

    used = {0, 1, i2, i3}
    order = [idx for idx in range(count) if idx not in used]
    random.Random(20261018).shuffle(order)

    owner: list[_Face | None] = [None] * count
    for idx in order:
        qx, qy, qz = pts[idx]
        for face in initial_faces:
            if face.nx * qx + face.ny * qy + face.nz * qz > face.d:
                face.out.append(idx)
                owner[idx] = face
                break

    # ---- ランダム順の逐次追加（各点は、自分を見ている面を 1 つだけ持つ） ----
    stamp = 0
    for p in order:
        start = owner[p]
        if start is None:
            continue
        px, py, pz = pts[p]
        stamp += 1
        start.stamp = stamp
        start.vis = True
        visible = [start]
        stack = [start]
        horizon: list[tuple[int, int]] = []
        while stack:
            face = stack.pop()
            fa, fb, fc = face.a, face.b, face.c
            for u, v in ((fa, fb), (fb, fc), (fc, fa)):
                neighbor = edge_map[(v, u)]
                if neighbor.stamp != stamp:
                    neighbor.stamp = stamp
                    neighbor.vis = (neighbor.nx * px + neighbor.ny * py
                                    + neighbor.nz * pz) > neighbor.d
                    if neighbor.vis:
                        visible.append(neighbor)
                        stack.append(neighbor)
                if not neighbor.vis:
                    horizon.append((u, v))

        for face in visible:
            del edge_map[(face.a, face.b)]
            del edge_map[(face.b, face.c)]
            del edge_map[(face.c, face.a)]

        tests = []
        for u, v in horizon:
            new_face = make_face(u, v, p)
            edge_map[(u, v)] = new_face
            edge_map[(v, p)] = new_face
            edge_map[(p, u)] = new_face
            tests.append((new_face.nx, new_face.ny, new_face.nz, new_face.d, new_face))

        for face in visible:
            for q in face.out:
                if q == p:
                    continue
                qx, qy, qz = pts[q]
                for nx, ny, nz, dd, new_face in tests:
                    if nx * qx + ny * qy + nz * qz > dd:
                        new_face.out.append(q)
                        owner[q] = new_face
                        break
                else:
                    owner[q] = None
            face.out = []
        owner[p] = None

    # ---- 体積・面・頂点を数える ----
    final_faces = set(edge_map.values())
    volume6 = 0
    plane_keys = set()
    vertex_planes: dict[int, set] = {}
    for face in final_faces:
        pax, pay, paz = pts[face.a]
        pbx, pby, pbz = pts[face.b]
        pcx, pcy, pcz = pts[face.c]
        volume6 += (pax * (pby * pcz - pbz * pcy)
                    + pay * (pbz * pcx - pbx * pcz)
                    + paz * (pbx * pcy - pby * pcx))
        divisor = gcd(gcd(abs(face.nx), abs(face.ny)), abs(face.nz))
        key = (face.nx // divisor, face.ny // divisor, face.nz // divisor, face.d // divisor)
        plane_keys.add(key)
        for vertex in (face.a, face.b, face.c):
            vertex_planes.setdefault(vertex, set()).add(key)

    n_vertices = sum(1 for keys in vertex_planes.values() if len(keys) >= 3)
    return (volume6, len(plane_keys), n_vertices)
```
