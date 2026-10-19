```python
import random
from math import gcd


def hull3d(points: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    pts = sorted(set((int(p[0]), int(p[1]), int(p[2])) for p in points))
    count = len(pts)
    if count < 4:
        raise ValueError("fewer than 4 distinct points")

    base = pts[0]
    second = pts[1]
    ux, uy, uz = second[0] - base[0], second[1] - base[1], second[2] - base[2]
    third_idx = -1
    cross = None
    for idx in range(2, count):
        q = pts[idx]
        vx, vy, vz = q[0] - base[0], q[1] - base[1], q[2] - base[2]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        if cx or cy or cz:
            third_idx = idx
            cross = (cx, cy, cz)
            break
    if third_idx < 0:
        raise ValueError("all points are collinear")
    fourth_idx = -1
    for idx in range(2, count):
        if idx == third_idx:
            continue
        q = pts[idx]
        val = (cross[0] * (q[0] - base[0]) + cross[1] * (q[1] - base[1])
               + cross[2] * (q[2] - base[2]))
        if val != 0:
            fourth_idx = idx
            break
    if fourth_idx < 0:
        raise ValueError("all points are coplanar")

    rest = [idx for idx in range(2, count) if idx != third_idx and idx != fourth_idx]
    rng = random.Random(20261018)
    rng.shuffle(rest)
    order = [0, 1, third_idx, fourth_idx] + rest
    P = [pts[idx] for idx in order]
    X = [p[0] for p in P]
    Y = [p[1] for p in P]
    Z = [p[2] for p in P]

    FA: list[int] = []
    FB: list[int] = []
    FC: list[int] = []
    NX: list[int] = []
    NY: list[int] = []
    NZ: list[int] = []
    ND: list[int] = []
    alive: list[bool] = []
    conf: list = []

    def new_face(a: int, b: int, c: int) -> int:
        abx, aby, abz = X[b] - X[a], Y[b] - Y[a], Z[b] - Z[a]
        acx, acy, acz = X[c] - X[a], Y[c] - Y[a], Z[c] - Z[a]
        nx = aby * acz - abz * acy
        ny = abz * acx - abx * acz
        nz = abx * acy - aby * acx
        FA.append(a)
        FB.append(b)
        FC.append(c)
        NX.append(nx)
        NY.append(ny)
        NZ.append(nz)
        ND.append(nx * X[a] + ny * Y[a] + nz * Z[a])
        alive.append(True)
        conf.append([])
        return len(FA) - 1

    def above(face: int, q: int) -> bool:
        return NX[face] * X[q] + NY[face] * Y[q] + NZ[face] * Z[q] > ND[face]

    n = count
    emap: dict[int, int] = {}
    tetra = [(0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)]
    for a, b, c, other in tetra:
        face = new_face(a, b, c)
        if above(face, other):
            # flip orientation
            FA.pop(); FB.pop(); FC.pop(); NX.pop(); NY.pop(); NZ.pop()
            ND.pop(); alive.pop(); conf.pop()
            face = new_face(a, c, b)
        emap[FA[face] * n + FB[face]] = face
        emap[FB[face] * n + FC[face]] = face
        emap[FC[face] * n + FA[face]] = face

    pconf: list = [[] for _ in range(n)]
    done = [False] * n
    for idx in range(4):
        done[idx] = True
    for q in range(4, n):
        xq, yq, zq = X[q], Y[q], Z[q]
        for face in range(4):
            if NX[face] * xq + NY[face] * yq + NZ[face] * zq > ND[face]:
                conf[face].append(q)
                pconf[q].append(face)

    for p in range(4, n):
        done[p] = True
        lst = pconf[p]
        pconf[p] = None
        vis = [face for face in lst if alive[face]]
        if not vis:
            continue
        visset = set(vis)
        for face in vis:
            alive[face] = False
        horizon = []
        for face in vis:
            a, b, c = FA[face], FB[face], FC[face]
            for u, v in ((a, b), (b, c), (c, a)):
                other = emap[v * n + u]
                if other not in visset:
                    horizon.append((u, v, face, other))
        for face in vis:
            a, b, c = FA[face], FB[face], FC[face]
            del emap[a * n + b]
            del emap[b * n + c]
            del emap[c * n + a]
        for u, v, f1, f2 in horizon:
            nf = new_face(u, v, p)
            emap[u * n + v] = nf
            emap[v * n + p] = nf
            emap[p * n + u] = nf
            nx, ny, nz, nd = NX[nf], NY[nf], NZ[nf], ND[nf]
            seen = set()
            cl = conf[nf]
            for src in (conf[f1], conf[f2]):
                for q in src:
                    if done[q] or q in seen:
                        continue
                    seen.add(q)
                    if nx * X[q] + ny * Y[q] + nz * Z[q] > nd:
                        cl.append(q)
                        pconf[q].append(nf)
        for face in vis:
            conf[face] = None

    volume6 = 0
    planes = set()
    vplanes: dict[int, set] = {}
    for face in range(len(FA)):
        if not alive[face]:
            continue
        a, b, c = FA[face], FB[face], FC[face]
        ax, ay, az = X[a], Y[a], Z[a]
        bx, by, bz = X[b], Y[b], Z[b]
        cx, cy, cz = X[c], Y[c], Z[c]
        volume6 += (ax * (by * cz - bz * cy)
                    - ay * (bx * cz - bz * cx)
                    + az * (bx * cy - by * cx))
        nx, ny, nz, nd = NX[face], NY[face], NZ[face], ND[face]
        g = gcd(gcd(abs(nx), abs(ny)), abs(nz))
        key = (nx // g, ny // g, nz // g, nd // g)
        planes.add(key)
        for vert in (a, b, c):
            s = vplanes.get(vert)
            if s is None:
                s = set()
                vplanes[vert] = s
            s.add(key)
    n_vertices = sum(1 for s in vplanes.values() if len(s) >= 3)
    return (volume6, len(planes), n_vertices)
```
