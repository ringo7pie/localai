"""H1 hull3d の隠しテスト。モデルには見せない（形式は suites/coding/c1/tests.py と同じ）。

期待値は reference.py で計算した。小さい入力（乱数の束を含む）は oracle.py（O(n**4) の総当たり）と一致し、
大きい入力は Qhull（scipy）の体積・頂点数・面の数と一致することを作成時に確かめた（tests/test_hard.py）。
"""

import math
import random

FORBIDDEN_CALLS = ()

M = 10 ** 6


def _checksum(results):
    acc = 0
    for index, value in enumerate(results):
        if value == "VE":
            code = 99991
        else:
            volume6, faces, vertices = value
            code = (volume6 % ((1 << 61) - 1)) * 31 + faces * 7 + vertices
        acc = (acc * 1000003 + code + index) % ((1 << 61) - 1)
    return acc


def _call(sol, pts):
    try:
        return tuple(sol.hull3d(pts))
    except ValueError:
        return "VE"


def _cube(lo, hi):
    return [(x, y, z) for x in (lo, hi) for y in (lo, hi) for z in (lo, hi)]


def _small_sets(seed, count, size_lo, size_hi, coord):
    rng = random.Random(seed)
    sets = []
    for _ in range(count):
        size = rng.randint(size_lo, size_hi)
        pts = [(rng.randint(-coord, coord), rng.randint(0, coord), rng.randint(0, coord)) for _ in range(size)]
        if rng.random() < 0.15:
            pts = [(x, y, 0) for x, y, _z in pts] + ([(0, 0, 1)] if rng.random() < 0.5 else [])
        sets.append(pts)
    return sets


def _sphere(r2):
    radius = math.isqrt(r2)
    pts = []
    for x in range(-radius, radius + 1):
        for y in range(-radius, radius + 1):
            rest = r2 - x * x - y * y
            if rest < 0:
                continue
            z = math.isqrt(rest)
            if z * z == rest:
                pts.append((x, y, z))
                if z:
                    pts.append((x, y, -z))
    return pts


def case_example_tetrahedron(sol, t):
    t.eq(tuple(sol.hull3d([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])), (1, 4, 4))


def case_example_cube(sol, t):
    t.eq(tuple(sol.hull3d(_cube(0, 1))), (6, 6, 8))


def case_example_lattice_cube(sol, t):
    t.eq(tuple(sol.hull3d([(x, y, z) for x in range(3) for y in range(3) for z in range(3)])), (48, 6, 8))


def case_duplicates_count_once(sol, t):
    pts = _cube(0, 2) * 3
    random.Random(1).shuffle(pts)
    t.eq(tuple(sol.hull3d(pts)), (48, 6, 8))


def case_interior_points_are_ignored(sol, t):
    rng = random.Random(2)
    pts = _cube(0, 4) + [(rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 3)) for _ in range(40)]
    rng.shuffle(pts)
    t.eq(tuple(sol.hull3d(pts)), (384, 6, 8))


def case_too_few_distinct_points(sol, t):
    t.raises(ValueError, sol.hull3d, [])
    t.raises(ValueError, sol.hull3d, [(1, 2, 3)])
    t.raises(ValueError, sol.hull3d, [(0, 0, 0), (1, 0, 0), (0, 1, 0)] * 5)


def case_collinear_or_coplanar(sol, t):
    t.raises(ValueError, sol.hull3d, [(k, 2 * k, 3 * k) for k in range(10)])
    t.raises(ValueError, sol.hull3d, [(x, y, 0) for x in range(5) for y in range(5)])
    t.raises(ValueError, sol.hull3d, [(x, y, 3 - x - y) for x in range(-3, 4) for y in range(-3, 4)])


def case_square_pyramid(sol, t):
    t.eq(tuple(sol.hull3d([(0, 0, 0), (2, 0, 0), (0, 2, 0), (2, 2, 0), (1, 1, 3)])), (24, 5, 5))


def case_triangular_prism(sol, t):
    base = [(0, 0, 0), (2, 0, 0), (0, 2, 0)]
    t.eq(tuple(sol.hull3d(base + [(x, y, 3) for x, y, _z in base])), (36, 5, 6))


def case_octahedron_and_cuboctahedron(sol, t):
    octa = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    t.eq(tuple(sol.hull3d(octa)), (8, 8, 6))
    cubo = []
    for a in (-1, 1):
        for b in (-1, 1):
            cubo += [(a, b, 0), (a, 0, b), (0, a, b)]
    t.eq(tuple(sol.hull3d(cubo)), EXPECTED["cuboctahedron"])


def case_points_on_edges_and_faces_are_not_vertices(sol, t):
    pts = _cube(0, 4)
    pts += [(k, 0, 0) for k in range(5)] + [(0, k, 4) for k in range(5)] + [(4, 4, k) for k in range(5)]
    pts += [(2, 2, 0), (2, 2, 4), (0, 2, 2), (4, 1, 3), (1, 0, 3), (3, 4, 1)]
    t.eq(tuple(sol.hull3d(pts)), (384, 6, 8))
    tetra = [(0, 0, 0), (6, 0, 0), (0, 6, 0), (0, 0, 6)]
    on_edges = [(k, 0, 0) for k in range(7)] + [(0, k, 6 - k) for k in range(7)] + [(k, 6 - k, 0) for k in range(7)]
    t.eq(tuple(sol.hull3d(tetra + on_edges + [(2, 2, 2), (1, 1, 4)])), (216, 4, 4))


def case_pyramid_on_a_cube_face(sol, t):
    t.eq(tuple(sol.hull3d(_cube(0, 2) + [(1, 1, 3)])), (56, 9, 9))


def case_point_in_a_face_plane_outside_the_face(sol, t):
    t.eq(tuple(sol.hull3d(_cube(0, 2) + [(3, 1, 2)])), EXPECTED["face_plane_outside"])
    t.eq(tuple(sol.hull3d(_cube(0, 2) + [(3, 3, 2)])), EXPECTED["edge_line_outside"])


def case_large_coordinates_exact(sol, t):
    tetra = [(-M, -M, -M), (M, -M, -M), (-M, M, -M), (-M, -M, M)]
    t.eq(tuple(sol.hull3d(tetra)), (8 * M ** 3, 4, 4))
    # 内部の点 1 つと、辺の中点 2 つ
    t.eq(tuple(sol.hull3d(tetra + [(-M + 1, -M + 1, -M + 1), (-M, 0, -M), (0, -M, -M)])), (8 * M ** 3, 4, 4))


def case_nearly_flat_with_large_coordinates(sol, t):
    # 大きな正方形の上、高さ 1 の点。体積は小さいが 0 ではない
    square = [(-M, -M, 0), (M, -M, 0), (-M, M, 0), (M, M, 0)]
    t.eq(tuple(sol.hull3d(square + [(1, 2, 1)])), (8 * M * M, 5, 5))
    # 平面 x + y + z = 0 に乗る大きな座標の点と、その平面から 1 だけ離れた点
    plane = [(M, -M, 0), (-M, M, 0), (M - 1, 1, -M), (-500_003, -499_990, 999_993), (999_983, -999_979, -4)]
    t.raises(ValueError, sol.hull3d, plane)
    t.eq(tuple(sol.hull3d(plane + [(1, 0, 0)])), EXPECTED["nearly_flat"])


def case_coplanar_points_with_huge_products(sol, t):
    # 法線 (999_999, 1_000_000, 999_998) の平面に乗る点（向きの値が 10**18 を超え、float では 0 にならない）
    a = (0, 0, 0)
    pts = [a, (1_000_000, -999_999, 0), (999_998, 0, -999_999), (2, -999_999, 999_999), (-1_000_000, 999_999, 0)]
    t.raises(ValueError, sol.hull3d, pts)
    t.eq(tuple(sol.hull3d(pts + [(0, 0, 1)])), EXPECTED["huge_products"])


def case_small_random_sets(sol, t):
    t.eq(_checksum([_call(sol, pts) for pts in _small_sets(31, 250, 4, 10, 3)]), EXPECTED["small_sets"])


def case_medium_grid_sets(sol, t):
    t.eq(_checksum([_call(sol, pts) for pts in _small_sets(32, 25, 15, 30, 3)]), EXPECTED["medium_sets"])


def case_lattice_points_in_a_tilted_region(sol, t):
    pts = [(x, y, z) for x in range(-4, 5) for y in range(-4, 5) for z in range(-4, 5)
           if abs(x + y) + abs(y - z) + abs(z + x) <= 6]
    t.eq(tuple(sol.hull3d(pts)), EXPECTED["tilted"])


def case_performance_random_cube(sol, t):
    rng = random.Random(41)
    pts = [(rng.randint(-M, M), rng.randint(-M, M), rng.randint(-M, M)) for _ in range(3000)]
    t.eq(tuple(sol.hull3d(pts)), EXPECTED["random_cube"])


def case_performance_lattice_cube(sol, t):
    t.eq(tuple(sol.hull3d([(x, y, z) for x in range(13) for y in range(13) for z in range(13)])), (10368, 6, 8))


def case_performance_lattice_sphere(sol, t):
    t.eq(tuple(sol.hull3d(_sphere(5525))), EXPECTED["sphere"])


def case_performance_paraboloid_grid(sol, t):
    pts = [(x, y, x * x + y * y) for x in range(-20, 20) for y in range(-20, 20)]
    t.eq(tuple(sol.hull3d(pts)), EXPECTED["paraboloid"])


def case_performance_all_points_extreme(sol, t):
    t.eq(tuple(sol.hull3d([(k, k * k, k * k * k) for k in range(-1200, 1200)])), EXPECTED["moment"])


EXPECTED = {
    'cuboctahedron': (40, 14, 12),
    'face_plane_outside': (56, 8, 9),
    'edge_line_outside': (64, 8, 8),
    'nearly_flat': (3999986000000, 5, 5),
    'huge_products': (3999988000008, 5, 5),
    'small_sets': 571661612283429173,
    'medium_sets': 2281345516023730212,
    'tilted': (972, 12, 14),
    'random_cube': (46520587130111688296, 196, 100),
    'sphere': (10210736, 1454, 960),
    'paraboloid': (4623840, 1526, 1600),
    'moment': (6354185011197888480, 4796, 2400),
}

CASES = [
    case_example_tetrahedron, case_example_cube, case_example_lattice_cube,
    case_duplicates_count_once, case_interior_points_are_ignored, case_too_few_distinct_points,
    case_collinear_or_coplanar, case_square_pyramid, case_triangular_prism, case_octahedron_and_cuboctahedron,
    case_points_on_edges_and_faces_are_not_vertices, case_pyramid_on_a_cube_face,
    case_point_in_a_face_plane_outside_the_face, case_large_coordinates_exact, case_nearly_flat_with_large_coordinates,
    case_coplanar_points_with_huge_products, case_small_random_sets, case_medium_grid_sets,
    case_lattice_points_in_a_tilted_region, case_performance_random_cube, case_performance_lattice_cube,
    case_performance_lattice_sphere, case_performance_paraboloid_grid, case_performance_all_points_extreme,
]
