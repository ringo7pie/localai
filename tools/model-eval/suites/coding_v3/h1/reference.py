"""H1 hull3d の参照解（整数の厳密な Quickhull）。

面は外向きの三角形で持ち、点が見える（向きの値が正）面の領域を隣接からたどって消し、境界の辺と点で新しい面を張る。
同じ平面の三角形は最後に平面の式でまとめる。頂点は、その点を角に持つ三角形の法線が 3 次元を張るかで決める
（辺の途中の点は法線が 2 方向、面の内側の点は 1 方向）。
"""

from math import gcd


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def hull3d(points):
    pts = sorted(set(tuple(int(c) for c in p) for p in points))
    if len(pts) < 4:
        raise ValueError("need at least 4 distinct points")
    a = pts[0]
    b = max(pts, key=lambda p: _dot(_sub(p, a), _sub(p, a)))
    ab = _sub(b, a)
    c = max(pts, key=lambda p: _dot(_cross(ab, _sub(p, a)), _cross(ab, _sub(p, a))))
    normal = _cross(ab, _sub(c, a))
    if normal == (0, 0, 0):
        raise ValueError("all points are collinear")
    d = max(pts, key=lambda p: abs(_dot(normal, _sub(p, a))))
    if _dot(normal, _sub(d, a)) == 0:
        raise ValueError("all points are coplanar")

    index = {p: i for i, p in enumerate(pts)}
    ia, ib, ic, id_ = index[a], index[b], index[c], index[d]

    faces = {}       # 面の番号 → (i, j, k, 法線, 定数)。法線は外向き、平面は 法線・x = 定数
    edge_face = {}   # 向きつきの辺 (i, j) → 面の番号
    outside = {}     # 面の番号 → その面から見える点の番号のリスト
    counter = [0]

    def make_face(i, j, k):
        pi, pj, pk = pts[i], pts[j], pts[k]
        n = _cross(_sub(pj, pi), _sub(pk, pi))
        fid = counter[0]
        counter[0] += 1
        faces[fid] = (i, j, k, n, _dot(n, pi))
        edge_face[(i, j)] = fid
        edge_face[(j, k)] = fid
        edge_face[(k, i)] = fid
        outside[fid] = []
        return fid

    tetra = [(ia, ib, ic, id_), (ia, ic, id_, ib), (ia, id_, ib, ic), (ib, id_, ic, ia)]
    initial = []
    for i, j, k, opposite in tetra:
        n = _cross(_sub(pts[j], pts[i]), _sub(pts[k], pts[i]))
        if _dot(n, _sub(pts[opposite], pts[i])) > 0:
            j, k = k, j
        initial.append(make_face(i, j, k))
    used = {ia, ib, ic, id_}
    for pid, p in enumerate(pts):
        if pid in used:
            continue
        for fid in initial:
            _i, _j, _k, n, off = faces[fid]
            if _dot(n, p) > off:
                outside[fid].append(pid)
                break

    pending = [fid for fid in initial if outside[fid]]
    while pending:
        fid = pending.pop()
        if fid not in faces or not outside[fid]:
            continue
        _i, _j, _k, n, off = faces[fid]
        far = max(outside[fid], key=lambda q: _dot(n, pts[q]) - off)
        p = pts[far]
        visible = {fid}
        stack = [fid]
        horizon = []
        while stack:
            cur = stack.pop()
            ci, cj, ck, _n, _off = faces[cur]
            for u, v in ((ci, cj), (cj, ck), (ck, ci)):
                other = edge_face[(v, u)]
                if other in visible:
                    continue
                _oi, _oj, _ok, on, ooff = faces[other]
                if _dot(on, p) > ooff:
                    visible.add(other)
                    stack.append(other)
                else:
                    horizon.append((u, v))
        orphans = []
        for vid in visible:
            vi, vj, vk, _n, _off = faces.pop(vid)
            for u, v in ((vi, vj), (vj, vk), (vk, vi)):
                if edge_face.get((u, v)) == vid:
                    del edge_face[(u, v)]
            orphans.extend(q for q in outside.pop(vid) if q != far)
        new_faces = [make_face(u, v, far) for u, v in horizon]
        for q in orphans:
            point = pts[q]
            for nid in new_faces:
                _i, _j, _k, nn, noff = faces[nid]
                if _dot(nn, point) > noff:
                    outside[nid].append(q)
                    break
        pending.extend(nid for nid in new_faces if outside[nid])

    volume6 = 0
    planes = set()
    corner_normals = {}
    for i, j, k, n, off in faces.values():
        volume6 += _dot(pts[i], _cross(pts[j], pts[k]))
        g = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2]))
        key = (n[0] // g, n[1] // g, n[2] // g)
        planes.add((key, off // g))
        for corner in (i, j, k):
            corner_normals.setdefault(corner, set()).add(key)
    n_vertices = 0
    for normals in corner_normals.values():
        if len(normals) < 3:
            continue
        normals = list(normals)
        first = normals[0]
        second = next((m for m in normals[1:] if _cross(first, m) != (0, 0, 0)), None)
        if second is None:
            continue
        axis = _cross(first, second)
        if any(_dot(axis, m) != 0 for m in normals):
            n_vertices += 1
    return volume6, len(planes), n_vertices
