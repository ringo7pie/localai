```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    distinct = list(dict.fromkeys((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(distinct)
    if count < 4:
        raise ValueError("need at least 4 distinct points")

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0])

    def sub(u, v):
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    # Find 4 non-coplanar points with exact integer arithmetic.
    p0 = distinct[0]
    p1 = distinct[1]
    edge = sub(p1, p0)
    i2 = -1
    normal0 = (0, 0, 0)
    for idx in range(2, count):
        candidate = cross(edge, sub(distinct[idx], p0))
        if candidate != (0, 0, 0):
            i2 = idx
            normal0 = candidate
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for idx in range(2, count):
        if idx == i2:
            continue
        diff = sub(distinct[idx], p0)
        if normal0[0] * diff[0] + normal0[1] * diff[1] + normal0[2] * diff[2] != 0:
            i3 = idx
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    rng = random.Random(20261018)
    rest = [distinct[idx] for idx in range(count) if idx not in (0, 1, i2, i3)]
    rng.shuffle(rest)
    orig = [p0, p1, distinct[i2], distinct[i3]] + rest

    # Symbolic-like perturbation with exact big integers: the scale K is far larger
    # than the perturbation effect, so non-degenerate orientations never change,
    # while the perturbed points are in general position.
    scale = 1 << 100
    radius = 1 << 40
    pts = [(scale * x + rng.randint(-radius, radius),
            scale * y + rng.randint(-radius, radius),
            scale * z + rng.randint(-radius, radius)) for (x, y, z) in orig]

    fa = []
    fb = []
    fc = []
    fplane = []
    conf = []
    edge_face = {}

    def make_face(a, b, c):
        ax, ay, az = pts[a]
        bx, by, bz = pts[b]
        cx, cy, cz = pts[c]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        fa.append(a)
        fb.append(b)
        fc.append(c)
        fplane.append((nx, ny, nz, nx * ax + ny * ay + nz * az))
        conf.append(set())
        return len(fa) - 1

    def register(face):
        a, b, c = fa[face], fb[face], fc[face]
        edge_face[a * count + b] = face
        edge_face[b * count + c] = face
        edge_face[c * count + a] = face

    for a, b, c, opposite in ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)):
        face = make_face(a, b, c)
        nx, ny, nz, dist = fplane[face]
        ox, oy, oz = pts[opposite]
        if nx * ox + ny * oy + nz * oz > dist:
            fa.pop(); fb.pop(); fc.pop(); fplane.pop(); conf.pop()
            face = make_face(a, c, b)
        register(face)

    pface = [set() for _ in range(count)]
    for q in range(4, count):
        qx, qy, qz = pts[q]
        for face in range(4):
            nx, ny, nz, dist = fplane[face]
            if nx * qx + ny * qy + nz * qz > dist:
                conf[face].add(q)
                pface[q].add(face)

    alive = [True] * len(fa)

    for p in range(4, count):
        visible = pface[p]
        if not visible:
            continue
        visible = set(visible)
        horizon = []
        for face in visible:
            a, b, c = fa[face], fb[face], fc[face]
            for u, v in ((a, b), (b, c), (c, a)):
                other = edge_face[v * count + u]
                if other not in visible:
                    horizon.append((u, v, face, other))
        for u, v, face, other in horizon:
            new_face = make_face(u, v, p)
            alive.append(True)
            nx, ny, nz, dist = fplane[new_face]
            candidates = conf[face] | conf[other]
            candidates.discard(p)
            bucket = conf[new_face]
            for q in candidates:
                qx, qy, qz = pts[q]
                if nx * qx + ny * qy + nz * qz > dist:
                    bucket.add(q)
                    pface[q].add(new_face)
            edge_face[u * count + v] = new_face
            edge_face[v * count + p] = new_face
            edge_face[p * count + u] = new_face
        for face in visible:
            alive[face] = False
            for q in conf[face]:
                pface[q].discard(face)
            conf[face] = None

    volume6 = 0
    planes = set()
    normals_at = {}
    for face in range(len(fa)):
        if not alive[face]:
            continue
        a, b, c = fa[face], fb[face], fc[face]
        pa, pb, pc = orig[a], orig[b], orig[c]
        volume6 += pa[0] * (pb[1] * pc[2] - pb[2] * pc[1]) \
            + pa[1] * (pb[2] * pc[0] - pb[0] * pc[2]) \
            + pa[2] * (pb[0] * pc[1] - pb[1] * pc[0])
        normal = cross(sub(pb, pa), sub(pc, pa))
        if normal == (0, 0, 0):
            continue
        divisor = gcd(gcd(abs(normal[0]), abs(normal[1])), abs(normal[2]))
        normal = (normal[0] // divisor, normal[1] // divisor, normal[2] // divisor)
        offset = normal[0] * pa[0] + normal[1] * pa[1] + normal[2] * pa[2]
        planes.add((normal, offset))
        for vertex in (a, b, c):
            normals_at.setdefault(vertex, set()).add(normal)

    n_vertices = 0
    for normal_set in normals_at.values():
        if len(normal_set) < 3:
            continue
        normal_list = list(normal_set)
        first = normal_list[0]
        axis = None
        for other in normal_list[1:]:
            candidate = cross(first, other)
            if candidate != (0, 0, 0):
                axis = candidate
                break
        if axis is None:
            continue
        for other in normal_list[1:]:
            if axis[0] * other[0] + axis[1] * other[1] + axis[2] * other[2] != 0:
                n_vertices += 1
                break

    return (abs(volume6), len(planes), n_vertices)
```
