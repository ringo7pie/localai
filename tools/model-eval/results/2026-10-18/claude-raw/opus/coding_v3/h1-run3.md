```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    unique = set()
    for point in points:
        px, py, pz = point
        unique.add((int(px), int(py), int(pz)))
    pts = sorted(unique)
    count = len(pts)
    if count < 4:
        raise ValueError("distinct points are fewer than 4")

    rng = random.Random(918273645)
    rng.shuffle(pts)
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    zs = [pt[2] for pt in pts]

    # --- initial tetrahedron (exact integer tests) ---
    x0, y0, z0 = xs[0], ys[0], zs[0]
    ux, uy, uz = xs[1] - x0, ys[1] - y0, zs[1] - z0
    idx2 = -1
    crx = cry = crz = 0
    for idx in range(2, count):
        vx = xs[idx] - x0
        vy = ys[idx] - y0
        vz = zs[idx] - z0
        crx = uy * vz - uz * vy
        cry = uz * vx - ux * vz
        crz = ux * vy - uy * vx
        if crx or cry or crz:
            idx2 = idx
            break
    if idx2 < 0:
        raise ValueError("all points are collinear")
    idx3 = -1
    orient = 0
    for idx in range(idx2 + 1, count):
        orient = crx * (xs[idx] - x0) + cry * (ys[idx] - y0) + crz * (zs[idx] - z0)
        if orient:
            idx3 = idx
            break
    if idx3 < 0:
        raise ValueError("all points are coplanar")
    if orient > 0:
        ta, tb, tc = 0, idx2, 1
    else:
        ta, tb, tc = 0, 1, idx2
    td = idx3

    # --- face storage ---
    va: list[int] = []
    vb: list[int] = []
    vc: list[int] = []
    nxs: list[int] = []
    nys: list[int] = []
    nzs: list[int] = []
    offs: list[int] = []
    alive: list[bool] = []
    outside: list = []
    edge_face: dict[int, int] = {}

    def add_face(ia: int, ib: int, ic: int) -> int:
        ax, ay, az = xs[ia], ys[ia], zs[ia]
        e1x = xs[ib] - ax
        e1y = ys[ib] - ay
        e1z = zs[ib] - az
        e2x = xs[ic] - ax
        e2y = ys[ic] - ay
        e2z = zs[ic] - az
        nx = e1y * e2z - e1z * e2y
        ny = e1z * e2x - e1x * e2z
        nz = e1x * e2y - e1y * e2x
        face = len(va)
        va.append(ia)
        vb.append(ib)
        vc.append(ic)
        nxs.append(nx)
        nys.append(ny)
        nzs.append(nz)
        offs.append(nx * ax + ny * ay + nz * az)
        alive.append(True)
        outside.append([])
        edge_face[ia * count + ib] = face
        edge_face[ib * count + ic] = face
        edge_face[ic * count + ia] = face
        return face

    add_face(ta, tb, tc)
    add_face(tb, ta, td)
    add_face(tc, tb, td)
    add_face(ta, tc, td)

    # --- initial conflict assignment (one visible face per point) ---
    assigned = [-1] * count
    for pid in range(count):
        if pid == ta or pid == tb or pid == tc or pid == td:
            continue
        qx, qy, qz = xs[pid], ys[pid], zs[pid]
        for face in range(4):
            if nxs[face] * qx + nys[face] * qy + nzs[face] * qz > offs[face]:
                assigned[pid] = face
                outside[face].append(pid)
                break

    # --- randomized incremental construction ---
    for pid in range(count):
        start_face = assigned[pid]
        if start_face < 0:
            continue
        qx, qy, qz = xs[pid], ys[pid], zs[pid]
        alive[start_face] = False
        visible = [start_face]
        stack = [start_face]
        invisible = set()
        horizon = []
        while stack:
            face = stack.pop()
            fa, fb, fc = va[face], vb[face], vc[face]
            for eu, ev in ((fa, fb), (fb, fc), (fc, fa)):
                nb = edge_face[ev * count + eu]
                if nb in invisible:
                    horizon.append((eu, ev))
                elif alive[nb]:
                    if nxs[nb] * qx + nys[nb] * qy + nzs[nb] * qz > offs[nb]:
                        alive[nb] = False
                        visible.append(nb)
                        stack.append(nb)
                    else:
                        invisible.add(nb)
                        horizon.append((eu, ev))
        first_new = len(va)
        for eu, ev in horizon:
            add_face(eu, ev, pid)
        last_new = len(va)
        for face in visible:
            members = outside[face]
            outside[face] = None
            for other in members:
                if other == pid:
                    continue
                rx, ry, rz = xs[other], ys[other], zs[other]
                for new_face in range(first_new, last_new):
                    if nxs[new_face] * rx + nys[new_face] * ry + nzs[new_face] * rz > offs[new_face]:
                        assigned[other] = new_face
                        outside[new_face].append(other)
                        break
                else:
                    assigned[other] = -1
        assigned[pid] = -1

    # --- statistics ---
    volume6 = 0
    facet_ids: dict[tuple[int, int, int], int] = {}
    vertex_facets: dict[int, set] = {}
    for face in range(len(va)):
        if not alive[face]:
            continue
        ia, ib, ic = va[face], vb[face], vc[face]
        ax, ay, az = xs[ia], ys[ia], zs[ia]
        bx, by, bz = xs[ib], ys[ib], zs[ib]
        cx2, cy2, cz2 = xs[ic], ys[ic], zs[ic]
        volume6 += (ax * (by * cz2 - bz * cy2)
                    + ay * (bz * cx2 - bx * cz2)
                    + az * (bx * cy2 - by * cx2))
        nx, ny, nz = nxs[face], nys[face], nzs[face]
        divisor = gcd(nx, ny, nz)
        key = (nx // divisor, ny // divisor, nz // divisor)
        fid = facet_ids.get(key)
        if fid is None:
            fid = len(facet_ids)
            facet_ids[key] = fid
        for vertex in (ia, ib, ic):
            group = vertex_facets.get(vertex)
            if group is None:
                group = set()
                vertex_facets[vertex] = group
            group.add(fid)

    n_faces = len(facet_ids)
    n_vertices = 0
    for group in vertex_facets.values():
        if len(group) >= 3:
            n_vertices += 1
    return (volume6, n_faces, n_vertices)
```
