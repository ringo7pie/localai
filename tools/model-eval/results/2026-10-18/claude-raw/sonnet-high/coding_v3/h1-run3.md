```python
import random
from math import gcd


def _spans_3d(normals):
    first = normals[0]
    second = None
    for other in normals:
        cx = first[1] * other[2] - first[2] * other[1]
        cy = first[2] * other[0] - first[0] * other[2]
        cz = first[0] * other[1] - first[1] * other[0]
        if cx or cy or cz:
            second = (cx, cy, cz)
            break
    if second is None:
        return False
    for other in normals:
        if second[0] * other[0] + second[1] * other[1] + second[2] * other[2] != 0:
            return True
    return False


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = sorted(set((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("need at least 4 distinct points")
    random.Random(20261018).shuffle(pts)

    p0 = pts[0]
    p1 = pts[1]
    ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    i2 = -1
    cross = (0, 0, 0)
    for i in range(2, count):
        q = pts[i]
        vx, vy, vz = q[0] - p0[0], q[1] - p0[1], q[2] - p0[2]
        cross = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        if cross[0] or cross[1] or cross[2]:
            i2 = i
            break
    if i2 < 0:
        raise ValueError("all points are collinear")
    i3 = -1
    for i in range(2, count):
        if i == i2:
            continue
        q = pts[i]
        if (
            cross[0] * (q[0] - p0[0])
            + cross[1] * (q[1] - p0[1])
            + cross[2] * (q[2] - p0[2])
        ) != 0:
            i3 = i
            break
    if i3 < 0:
        raise ValueError("all points are coplanar")

    face_vertices = []
    face_plane = []
    face_points = []
    alive = []
    edge_owner = {}

    def make_face(a, b, c):
        ax, ay, az = pts[a]
        bx, by, bz = pts[b]
        cx, cy, cz = pts[c]
        ex, ey, ez = bx - ax, by - ay, bz - az
        fx, fy, fz = cx - ax, cy - ay, cz - az
        nx = ey * fz - ez * fy
        ny = ez * fx - ex * fz
        nz = ex * fy - ey * fx
        face_id = len(face_vertices)
        face_vertices.append((a, b, c))
        face_plane.append((nx, ny, nz, nx * ax + ny * ay + nz * az))
        face_points.append(set())
        alive.append(True)
        edge_owner[(a, b)] = face_id
        edge_owner[(b, c)] = face_id
        edge_owner[(c, a)] = face_id
        return face_id

    simplex = [0, 1, i2, i3]
    for skip in range(4):
        tri = [simplex[j] for j in range(4) if j != skip]
        other = pts[simplex[skip]]
        a, b, c = (pts[tri[0]], pts[tri[1]], pts[tri[2]])
        ex, ey, ez = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        fx, fy, fz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx = ey * fz - ez * fy
        ny = ez * fx - ex * fz
        nz = ex * fy - ey * fx
        if nx * (other[0] - a[0]) + ny * (other[1] - a[1]) + nz * (other[2] - a[2]) > 0:
            tri[1], tri[2] = tri[2], tri[1]
        make_face(tri[0], tri[1], tri[2])

    point_faces = [set() for _ in range(count)]
    used = set(simplex)
    remaining = [i for i in range(count) if i not in used]
    for face_id in range(4):
        nx, ny, nz, dd = face_plane[face_id]
        bucket = face_points[face_id]
        for idx in remaining:
            x, y, z = pts[idx]
            if nx * x + ny * y + nz * z > dd:
                bucket.add(idx)
                point_faces[idx].add(face_id)

    for idx in remaining:
        visible = point_faces[idx]
        if not visible:
            continue
        horizon = []
        for face_id in visible:
            a, b, c = face_vertices[face_id]
            for u, v in ((a, b), (b, c), (c, a)):
                neighbor = edge_owner[(v, u)]
                if neighbor not in visible:
                    horizon.append((u, v, face_id, neighbor))
        for face_id in visible:
            a, b, c = face_vertices[face_id]
            del edge_owner[(a, b)]
            del edge_owner[(b, c)]
            del edge_owner[(c, a)]
        for u, v, inside_face, outside_face in horizon:
            new_id = make_face(u, v, idx)
            nx, ny, nz, dd = face_plane[new_id]
            bucket = face_points[new_id]
            for source in (face_points[inside_face], face_points[outside_face]):
                for other in source:
                    if other == idx or other in bucket:
                        continue
                    x, y, z = pts[other]
                    if nx * x + ny * y + nz * z > dd:
                        bucket.add(other)
                        point_faces[other].add(new_id)
        for face_id in visible:
            alive[face_id] = False
            for other in face_points[face_id]:
                if other != idx:
                    point_faces[other].discard(face_id)
            face_points[face_id] = set()
        point_faces[idx] = set()

    origin = pts[0]
    ox, oy, oz = origin
    total = 0
    plane_keys = set()
    vertex_planes = {}
    for face_id in range(len(face_vertices)):
        if not alive[face_id]:
            continue
        a, b, c = face_vertices[face_id]
        ax, ay, az = pts[a][0] - ox, pts[a][1] - oy, pts[a][2] - oz
        bx, by, bz = pts[b][0] - ox, pts[b][1] - oy, pts[b][2] - oz
        cx, cy, cz = pts[c][0] - ox, pts[c][1] - oy, pts[c][2] - oz
        total += (
            ax * (by * cz - bz * cy)
            - ay * (bx * cz - bz * cx)
            + az * (bx * cy - by * cx)
        )
        nx, ny, nz, dd = face_plane[face_id]
        g = gcd(gcd(abs(nx), abs(ny)), gcd(abs(nz), abs(dd)))
        key = (nx // g, ny // g, nz // g, dd // g)
        plane_keys.add(key)
        for vertex in (a, b, c):
            vertex_planes.setdefault(vertex, set()).add(key)

    vertex_count = 0
    for planes in vertex_planes.values():
        if len(planes) >= 3:
            normals = [(k[0], k[1], k[2]) for k in planes]
            if _spans_3d(normals):
                vertex_count += 1

    return (abs(total), len(plane_keys), vertex_count)
```
