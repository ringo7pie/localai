#!/usr/bin/env python3
"""メッシュ（GLB / OBJ / PLY）の防水さと、参照メッシュとの距離を測って JSON で出す。

使い方（venv の python で動かす。GPU があれば距離の計算に CuMesh の cuBVH を使う）:
  measure_mesh.py MESH [MESH ...] [--reference REF] [--samples 1000000] [-o OUT.json]

測るもの:
- 頂点を位置で溶接してから数える。GLB は 1 つの頂点に 2 つの UV を持てないので、テクスチャ付きの低ポリは
  UV の継ぎ目で頂点が分かれ、溶接しないと継ぎ目が開いた辺に見える（配布元 README の Troubleshooting:
  Blender の glTF 取り込みで「Merge Vertices」を付ける、と同じ扱い）。既定は位置が完全に同じ頂点だけを
  まとめる。--weld-tol を付けると、その幅の格子で丸めて同じになる頂点をまとめる。
  溶接で 2 頂点が重なった面（潰れた面）は数えたうえで除く。溶接する前の辺の数と、同じ位置に重なる頂点の数も
  unwelded に出す（番号の上では閉じていて、面が点で接しているだけの場合を見分けるため）。
- is_watertight（trimesh）・境界辺（1 面だけが使う辺）・非多様体辺（3 面以上が使う辺）・向きの食い違う辺・
  殻（辺でつながる面のまとまり）の数・符号付き体積・面数・頂点数。
- --reference を付けると、両方の面から面積に比例して各 --samples 点を取り、もう一方の「面」までの距離
  （点と三角形の最短距離）を求める。両側 Hausdorff（両方向の最大）と Chamfer（両方向の平均の和）を、
  参照の bbox の対角で割った値と、ボクセル（--grid-extent / --voxel-res）単位の値で出す。
  距離の計算は cuda（cuBVH）→ open3d（RaycastingScene、CPU）→ brute（numpy、小さいメッシュだけ）の順に使う。

判定（checks）: 境界辺 = 0、非多様体辺 = 0、両側 Hausdorff / 対角 ≤ 2 / --voxel-res。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SAMPLES = 1_000_000
DEFAULT_VOXEL_RES = 1536
# Trellis.2 / Pixal3D の生成空間は [-0.5, 0.5]^3。1 ボクセル = 1 / 解像度。
DEFAULT_GRID_EXTENT = 1.0
HAUSDORFF_LIMIT_VOXELS = 2.0
BRUTE_FORCE_LIMIT = 20_000_000  # 点の数 × 三角形の数がこれを超えたら brute は使わない
QUERY_CHUNK = 1_000_000


# ---------------------------------------------------------------- 読み込みと溶接


def load_mesh(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """trimesh で読み、(頂点 float64, 面 int64, 読み込みの情報) を返す。Scene は変換を当てて 1 つにまとめる。"""
    import trimesh

    loaded = trimesh.load(str(path), force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise TypeError(f"三角形メッシュとして読めない: {path}（{type(loaded).__name__}）")
    vertices = np.asarray(loaded.vertices, dtype=np.float64)
    faces = np.asarray(loaded.faces, dtype=np.int64)
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError(f"三角形の面が無い: {path}")
    info = {"path": str(path), "bytes": path.stat().st_size, "vertices_raw": len(vertices), "faces_raw": len(faces)}
    return vertices, faces, info


def weld_vertices(vertices: np.ndarray, faces: np.ndarray, tolerance: float = 0.0) -> tuple[np.ndarray, np.ndarray, int]:
    """位置で頂点を溶接する。(頂点, 面, 潰れて除いた面の数) を返す。使われない頂点は落とす。"""
    if tolerance > 0:
        keys = np.round(vertices / tolerance).astype(np.int64)
    else:
        # -0.0 と 0.0 を同じにしてから、値が完全に同じ行をまとめる
        keys = vertices + 0.0
    _unique, first_index, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    welded_faces = inverse[faces]
    degenerate = (
        (welded_faces[:, 0] == welded_faces[:, 1])
        | (welded_faces[:, 1] == welded_faces[:, 2])
        | (welded_faces[:, 2] == welded_faces[:, 0])
    )
    welded_faces = welded_faces[~degenerate]
    welded_vertices = vertices[first_index]
    used = np.unique(welded_faces)
    remap = np.full(len(welded_vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return welded_vertices[used], remap[welded_faces], int(degenerate.sum())


# ---------------------------------------------------------------- 辺と殻


def edge_statistics(faces: np.ndarray, vertex_count: int) -> dict[str, int]:
    """辺の出現回数から、境界辺・非多様体辺・向きの食い違い・殻の数を出す。"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    face_count = len(faces)
    half_edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    low = np.minimum(half_edges[:, 0], half_edges[:, 1])
    high = np.maximum(half_edges[:, 0], half_edges[:, 1])
    keys = low * np.int64(vertex_count) + high
    # 半辺の向き: 小さい番号 → 大きい番号なら +1。同じ辺の 2 つの半辺は、向きがそろっていれば和が 0 になる
    direction = np.where(half_edges[:, 0] < half_edges[:, 1], 1, -1)

    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    new_group = np.empty(len(sorted_keys), dtype=bool)
    new_group[0] = True
    new_group[1:] = sorted_keys[1:] != sorted_keys[:-1]
    group_of_sorted = np.cumsum(new_group) - 1
    counts = np.bincount(group_of_sorted)
    orientation_sum = np.bincount(group_of_sorted, weights=direction[order])

    # 同じ辺を使う面どうしをつなぎ、つながりの数を殻の数とする（頂点だけを共有する面は別の殻）
    face_of_sorted = order % face_count
    same_edge = ~new_group[1:]
    rows = face_of_sorted[:-1][same_edge]
    cols = face_of_sorted[1:][same_edge]
    graph = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(face_count, face_count))
    shell_count, _labels = connected_components(graph, directed=False)

    return {
        "edges": len(counts),
        "boundary_edges": int((counts == 1).sum()),
        "non_manifold_edges": int((counts >= 3).sum()),
        "orientation_inconsistent_edges": int(((counts == 2) & (orientation_sum != 0)).sum()),
        "shells": int(shell_count),
    }


def signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """発散定理による符号付き体積。外向きの面なら正。桁落ちを避けるため bbox の中心を原点にして足す。"""
    centered = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    v0, v1, v2 = centered[faces[:, 0]], centered[faces[:, 1]], centered[faces[:, 2]]
    return float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)


def surface_area(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    v0 = vertices[faces[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(vertices[faces[:, 1]] - v0, vertices[faces[:, 2]] - v0), axis=1)


def topology_report(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    import trimesh

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    stats = edge_statistics(faces, len(vertices))
    volume = signed_volume(vertices, faces)
    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    return {
        "vertices": len(vertices),
        "faces": len(faces),
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        **stats,
        "volume": volume,
        "volume_sign": int(np.sign(volume)),
        "area": float(surface_area(vertices, faces).sum()),
        "bbox_min": bbox_min.tolist(),
        "bbox_max": bbox_max.tolist(),
        "bbox_diagonal": float(np.linalg.norm(bbox_max - bbox_min)),
    }


# ---------------------------------------------------------------- 点の採取と距離


def sample_surface(vertices: np.ndarray, faces: np.ndarray, count: int, rng: np.random.Generator) -> np.ndarray:
    """面積に比例して面を選び、面の中で一様に点を取る。"""
    area = surface_area(vertices, faces)
    cumulative = np.cumsum(area)
    picked = np.searchsorted(cumulative, rng.random(count) * cumulative[-1], side="right")
    picked = np.minimum(picked, len(faces) - 1)
    first = rng.random(count)
    second = rng.random(count)
    outside = first + second > 1.0
    first[outside] = 1.0 - first[outside]
    second[outside] = 1.0 - second[outside]
    v0 = vertices[faces[picked, 0]]
    return v0 + first[:, None] * (vertices[faces[picked, 1]] - v0) + second[:, None] * (vertices[faces[picked, 2]] - v0)


def point_triangle_distance(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """点ごとに、与えた三角形すべてへの最短距離の最小を返す（Ericson の最近点。小さい入力の検算用）。"""
    best = np.full(len(points), np.inf)
    for triangle in triangles:
        a, b, c = triangle
        ab, ac = b - a, c - a
        ap = points - a
        d1, d2 = ap @ ab, ap @ ac
        bp = points - b
        d3, d4 = bp @ ab, bp @ ac
        cp = points - c
        d5, d6 = cp @ ab, cp @ ac
        va = d3 * d6 - d5 * d4
        vb = d5 * d2 - d1 * d6
        vc = d1 * d4 - d3 * d2
        with np.errstate(divide="ignore", invalid="ignore"):
            denominator = 1.0 / (va + vb + vc)
            closest = a + ab * (vb * denominator)[:, None] + ac * (vc * denominator)[:, None]
            # 頂点・辺の領域にある点は、その頂点・辺への最近点に置き換える
            region_a = (d1 <= 0) & (d2 <= 0)
            region_b = (d3 >= 0) & (d4 <= d3)
            region_c = (d6 >= 0) & (d5 <= d6)
            edge_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
            edge_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
            edge_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
            t_ab = d1 / (d1 - d3)
            t_ac = d2 / (d2 - d6)
            t_bc = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        closest = np.where(edge_bc[:, None], b + (c - b) * t_bc[:, None], closest)
        closest = np.where(edge_ac[:, None], a + ac * t_ac[:, None], closest)
        closest = np.where(edge_ab[:, None], a + ab * t_ab[:, None], closest)
        closest = np.where(region_c[:, None], c, closest)
        closest = np.where(region_b[:, None], b, closest)
        closest = np.where(region_a[:, None], a, closest)
        # 潰れた三角形は NaN になるので、NaN を無視して小さい方を取る
        best = np.fmin(best, np.linalg.norm(points - closest, axis=1))
    return best


def choose_backend(requested: str, point_count: int, face_count: int) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            import cumesh  # noqa: F401

            return "cuda"
    except Exception:  # noqa: BLE001, S110 - torch / cumesh が無い・壊れているときは次を試す
        pass
    try:
        import open3d  # noqa: F401

        return "open3d"
    except Exception:  # noqa: BLE001, S110 - open3d が無いときは次を試す
        pass
    if point_count * face_count <= BRUTE_FORCE_LIMIT:
        return "brute"
    raise RuntimeError("距離を計算できる手段が無い（cuda の cuBVH / open3d / 小さい入力の brute）")


def distances_to_surface(points: np.ndarray, vertices: np.ndarray, faces: np.ndarray, backend: str) -> np.ndarray:
    """点から、メッシュの面までの最短距離（符号なし）。"""
    if backend == "cuda":
        import torch
        from cumesh import cuBVH

        bvh = cuBVH(np.ascontiguousarray(vertices, dtype=np.float32), np.ascontiguousarray(faces, dtype=np.int32))
        result = np.empty(len(points), dtype=np.float64)
        for start in range(0, len(points), QUERY_CHUNK):
            chunk = torch.from_numpy(np.ascontiguousarray(points[start:start + QUERY_CHUNK], dtype=np.float32)).cuda()
            distance, _face, _uvw = bvh.unsigned_distance(chunk)
            result[start:start + len(chunk)] = distance.double().cpu().numpy()
        del bvh
        torch.cuda.empty_cache()
        return result
    if backend == "open3d":
        import open3d as o3d

        scene = o3d.t.geometry.RaycastingScene()
        scene.add_triangles(
            o3d.core.Tensor(np.ascontiguousarray(vertices, dtype=np.float32)),
            o3d.core.Tensor(np.ascontiguousarray(faces, dtype=np.uint32)),
        )
        query = o3d.core.Tensor(np.ascontiguousarray(points, dtype=np.float32))
        return scene.compute_distance(query).numpy().astype(np.float64)
    if backend == "brute":
        return point_triangle_distance(points, vertices[faces])
    raise ValueError(f"未知の backend: {backend}")


def align_to_reference(vertices: np.ndarray, reference_vertices: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """bbox の中心と対角をそろえる（等方の拡大と平行移動だけ）。座標系がずれた出力を比べるとき用。"""
    center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    reference_center = (reference_vertices.min(axis=0) + reference_vertices.max(axis=0)) / 2.0
    diagonal = np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))
    reference_diagonal = np.linalg.norm(reference_vertices.max(axis=0) - reference_vertices.min(axis=0))
    scale = reference_diagonal / diagonal if diagonal > 0 else 1.0
    aligned = (vertices - center) * scale + reference_center
    return aligned, {"scale": float(scale), "translation": (reference_center - center * scale).tolist()}


def compare_meshes(
    vertices: np.ndarray, faces: np.ndarray, reference_vertices: np.ndarray, reference_faces: np.ndarray,
    samples: int, backend: str, seed: int, voxel_size: float,
) -> dict[str, Any]:
    """両側の点→面の距離から、Hausdorff と Chamfer を出す。"""
    rng = np.random.default_rng(seed)
    points = sample_surface(vertices, faces, samples, rng)
    reference_points = sample_surface(reference_vertices, reference_faces, samples, rng)
    chosen = choose_backend(backend, samples, max(len(faces), len(reference_faces)))
    started = time.monotonic()
    to_reference = distances_to_surface(points, reference_vertices, reference_faces, chosen)
    from_reference = distances_to_surface(reference_points, vertices, faces, chosen)
    elapsed = time.monotonic() - started
    diagonal = float(np.linalg.norm(reference_vertices.max(axis=0) - reference_vertices.min(axis=0)))
    hausdorff = float(max(to_reference.max(), from_reference.max()))
    chamfer = float(to_reference.mean() + from_reference.mean())
    return {
        "backend": chosen,
        "samples_each": samples,
        "seconds": round(elapsed, 2),
        "reference_bbox_diagonal": diagonal,
        "hausdorff": hausdorff,
        "hausdorff_to_reference": float(to_reference.max()),
        "hausdorff_from_reference": float(from_reference.max()),
        "chamfer_l1": chamfer,
        "chamfer_l2": float((to_reference**2).mean() + (from_reference**2).mean()),
        "p99_to_reference": float(np.percentile(to_reference, 99)),
        "p99_from_reference": float(np.percentile(from_reference, 99)),
        "p999_to_reference": float(np.percentile(to_reference, 99.9)),
        "p999_from_reference": float(np.percentile(from_reference, 99.9)),
        # 2 ボクセルを超えた点の割合。Hausdorff（最大）が一部の外れで決まっているかを見る
        "over_limit_fraction_to_reference": float((to_reference > HAUSDORFF_LIMIT_VOXELS * voxel_size).mean()),
        "over_limit_fraction_from_reference": float((from_reference > HAUSDORFF_LIMIT_VOXELS * voxel_size).mean()),
        "hausdorff_over_diagonal": hausdorff / diagonal if diagonal > 0 else None,
        "chamfer_l1_over_diagonal": chamfer / diagonal if diagonal > 0 else None,
        "voxel_size": voxel_size,
        "hausdorff_voxels": hausdorff / voxel_size,
        "chamfer_l1_voxels": chamfer / voxel_size,
    }


def unwelded_report(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    """溶接する前（ファイルの頂点番号のまま）の辺の数と、同じ位置に重なる頂点の数。

    番号の上では閉じていても、別々の頂点が同じ位置にあると（面が点や辺で接している）、
    位置で溶接したときに非多様体辺や潰れた面になる。その差を見分けるために出す。
    """
    _unique, inverse, counts = np.unique(vertices + 0.0, axis=0, return_inverse=True, return_counts=True)
    shared = counts[inverse.reshape(-1)] > 1
    return {
        **edge_statistics(faces, len(vertices)),
        "coincident_vertices": int(shared.sum()),
        "coincident_groups": int((counts > 1).sum()),
    }


def judge(topology: dict[str, Any], comparison: dict[str, Any] | None, voxel_res: int) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "boundary_edges_zero": topology["boundary_edges"] == 0,
        "non_manifold_edges_zero": topology["non_manifold_edges"] == 0,
    }
    unwelded = topology.get("unwelded")
    if unwelded is not None:
        # 参考（passed には入れない）: ファイルの頂点番号のままで閉じているか
        checks["info_unwelded_closed"] = unwelded["boundary_edges"] == 0 and unwelded["non_manifold_edges"] == 0
    if comparison is not None and comparison.get("hausdorff_over_diagonal") is not None:
        limit = HAUSDORFF_LIMIT_VOXELS / voxel_res
        checks["hausdorff_limit_over_diagonal"] = limit
        checks["hausdorff_within_limit"] = comparison["hausdorff_over_diagonal"] <= limit
    checks["passed"] = all(value for key, value in checks.items() if isinstance(value, bool) and not key.startswith("info_"))
    return checks


def measure(
    path: Path, reference: Path | None = None, samples: int = DEFAULT_SAMPLES, weld_tolerance: float = 0.0,
    backend: str = "auto", seed: int = 0, voxel_res: int = DEFAULT_VOXEL_RES, grid_extent: float = DEFAULT_GRID_EXTENT,
    align: str = "none", reference_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    vertices, faces, info = load_mesh(path)
    result: dict[str, Any] = {**info, "unwelded": unwelded_report(vertices, faces)}
    vertices, faces, degenerate = weld_vertices(vertices, faces, weld_tolerance)
    result.update({"weld_tolerance": weld_tolerance, "degenerate_faces_removed": degenerate})
    result.update(topology_report(vertices, faces))
    comparison = None
    if reference is not None:
        cache_key = f"{reference}|{weld_tolerance}"
        if reference_cache is not None and cache_key in reference_cache:
            reference_vertices, reference_faces = reference_cache[cache_key]
        else:
            reference_vertices, reference_faces, _ = load_mesh(reference)
            reference_vertices, reference_faces, _ = weld_vertices(reference_vertices, reference_faces, weld_tolerance)
            if reference_cache is not None:
                reference_cache[cache_key] = (reference_vertices, reference_faces)
        compared_vertices = vertices
        alignment = None
        if align == "bbox":
            compared_vertices, alignment = align_to_reference(vertices, reference_vertices)
        comparison = compare_meshes(
            compared_vertices, faces, reference_vertices, reference_faces, samples, backend, seed, grid_extent / voxel_res,
        )
        comparison["reference"] = str(reference)
        comparison["alignment"] = alignment
        result["comparison"] = comparison
    result["checks"] = judge(result, comparison, voxel_res)
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="メッシュの防水さと参照メッシュとの距離を測る")
    parser.add_argument("meshes", nargs="+", type=Path)
    parser.add_argument("--reference", type=Path, help="距離を比べる相手（Hausdorff / Chamfer）")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="両面から取る点の数（各）")
    parser.add_argument("--weld-tol", type=float, default=0.0, help="溶接の幅（0 は位置が完全に同じ頂点だけ）")
    parser.add_argument("--backend", choices=("auto", "cuda", "open3d", "brute"), default="auto")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--voxel-res", type=int, default=DEFAULT_VOXEL_RES)
    parser.add_argument("--grid-extent", type=float, default=DEFAULT_GRID_EXTENT, help="生成空間の一辺（ボクセルの大きさ = これ / 解像度）")
    parser.add_argument("--align", choices=("none", "bbox"), default="none", help="比べる前に bbox をそろえるか")
    parser.add_argument("-o", "--output", type=Path, help="結果の JSON の書き先")
    args = parser.parse_args(argv)

    cache: dict[str, Any] = {}
    results = []
    for path in args.meshes:
        try:
            results.append(measure(
                path, args.reference, args.samples, args.weld_tol, args.backend, args.seed,
                args.voxel_res, args.grid_extent, args.align, cache,
            ))
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            results.append({"path": str(path), "error": f"{type(error).__name__}: {error}"})
    text = json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False))
    return 0 if all("error" not in item for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
