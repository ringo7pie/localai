```python
import math
import random


def _spans_space(normals):
    first_x, first_y, first_z = normals[0]
    for second_x, second_y, second_z in normals:
        cross_x = first_y * second_z - first_z * second_y
        cross_y = first_z * second_x - first_x * second_z
        cross_z = first_x * second_y - first_y * second_x
        if cross_x or cross_y or cross_z:
            for third_x, third_y, third_z in normals:
                if cross_x * third_x + cross_y * third_y + cross_z * third_z:
                    return True
            return False
    return False


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    unique = sorted({(int(item[0]), int(item[1]), int(item[2])) for item in points})
    if len(unique) < 4:
        raise ValueError("convex hull needs at least 4 distinct points")
    random.Random(20261018).shuffle(unique)
    count = len(unique)

    # ---- 初期の四面体を選ぶ（整数だけで判定する） ----
    origin_x, origin_y, origin_z = unique[0]
    edge_x = unique[1][0] - origin_x
    edge_y = unique[1][1] - origin_y
    edge_z = unique[1][2] - origin_z
    third = -1
    base_nx = base_ny = base_nz = 0
    for index in range(2, count):
        diff_x = unique[index][0] - origin_x
        diff_y = unique[index][1] - origin_y
        diff_z = unique[index][2] - origin_z
        base_nx = edge_y * diff_z - edge_z * diff_y
        base_ny = edge_z * diff_x - edge_x * diff_z
        base_nz = edge_x * diff_y - edge_y * diff_x
        if base_nx or base_ny or base_nz:
            third = index
            break
    if third < 0:
        raise ValueError("all points are collinear")
    fourth = -1
    for index in range(third + 1, count):
        px, py, pz = unique[index]
        if (
            base_nx * (px - origin_x)
            + base_ny * (py - origin_y)
            + base_nz * (pz - origin_z)
            != 0
        ):
            fourth = index
            break
    if fourth < 0:
        raise ValueError("all points are coplanar")

    chosen = (0, 1, third, fourth)
    chosen_set = set(chosen)
    ordered = [unique[index] for index in chosen]
    ordered.extend(unique[index] for index in range(count) if index not in chosen_set)
    xs = [item[0] for item in ordered]
    ys = [item[1] for item in ordered]
    zs = [item[2] for item in ordered]

    # ---- 三角形の面の表。面は外向きの反時計回り (a, b, c) で持つ ----
    face_vertices = []
    face_plane = []
    face_conflict = []
    face_alive = []
    edge_owner = {}  # 有向辺 (tail -> head) を key = tail * count + head にして面 id を引く
    point_faces = [[] for _ in range(count)]

    def plane_of(first, second, third_vertex):
        base_x, base_y, base_z = xs[first], ys[first], zs[first]
        u_x = xs[second] - base_x
        u_y = ys[second] - base_y
        u_z = zs[second] - base_z
        v_x = xs[third_vertex] - base_x
        v_y = ys[third_vertex] - base_y
        v_z = zs[third_vertex] - base_z
        normal_x = u_y * v_z - u_z * v_y
        normal_y = u_z * v_x - u_x * v_z
        normal_z = u_x * v_y - u_y * v_x
        offset = normal_x * base_x + normal_y * base_y + normal_z * base_z
        return normal_x, normal_y, normal_z, offset

    def add_face(first, second, third_vertex, candidates):
        normal_x, normal_y, normal_z, offset = plane_of(first, second, third_vertex)
        seen_by = [
            point
            for point in candidates
            if normal_x * xs[point] + normal_y * ys[point] + normal_z * zs[point] > offset
        ]
        face_id = len(face_vertices)
        face_vertices.append((first, second, third_vertex))
        face_plane.append((normal_x, normal_y, normal_z, offset))
        face_conflict.append(seen_by)
        face_alive.append(True)
        edge_owner[first * count + second] = face_id
        edge_owner[second * count + third_vertex] = face_id
        edge_owner[third_vertex * count + first] = face_id
        for point in seen_by:
            point_faces[point].append(face_id)
        return face_id

    for first, second, third_vertex, opposite in (
        (0, 1, 2, 3),
        (0, 1, 3, 2),
        (0, 2, 3, 1),
        (1, 2, 3, 0),
    ):
        normal_x, normal_y, normal_z, offset = plane_of(first, second, third_vertex)
        if (
            normal_x * xs[opposite] + normal_y * ys[opposite] + normal_z * zs[opposite]
            > offset
        ):
            second, third_vertex = third_vertex, second
        add_face(first, second, third_vertex, range(4, count))

    # ---- 点を 1 つずつ足す（衝突リスト付きのランダム増分法） ----
    for apex in range(4, count):
        visible = [face for face in point_faces[apex] if face_alive[face]]
        if not visible:
            continue
        visible_set = set(visible)
        horizon = []
        for face in visible:
            va, vb, vc = face_vertices[face]
            for tail, head in ((va, vb), (vb, vc), (vc, va)):
                neighbor = edge_owner[head * count + tail]
                if neighbor not in visible_set:
                    horizon.append((tail, head, face, neighbor))
        for face in visible:
            va, vb, vc = face_vertices[face]
            del edge_owner[va * count + vb]
            del edge_owner[vb * count + vc]
            del edge_owner[vc * count + va]
            face_alive[face] = False
        for tail, head, face, neighbor in horizon:
            candidates = set(face_conflict[face])
            candidates.update(face_conflict[neighbor])
            add_face(tail, head, apex, candidates)
        for face in visible:
            face_conflict[face] = ()

    # ---- 集計 ----
    volume6 = 0
    planes = set()
    incident = {}
    for face in range(len(face_vertices)):
        if not face_alive[face]:
            continue
        normal_x, normal_y, normal_z, offset = face_plane[face]
        volume6 += offset
        divisor = math.gcd(math.gcd(normal_x, normal_y), math.gcd(normal_z, offset))
        planes.add(
            (
                normal_x // divisor,
                normal_y // divisor,
                normal_z // divisor,
                offset // divisor,
            )
        )
        for vertex in face_vertices[face]:
            incident.setdefault(vertex, []).append((normal_x, normal_y, normal_z))

    vertex_count = 0
    for normals in incident.values():
        if _spans_space(normals):
            vertex_count += 1

    return volume6, len(planes), vertex_count
```
