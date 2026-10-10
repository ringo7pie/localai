"""scripts/measure_mesh.py の指標（溶接・辺・殻・体積・Hausdorff / Chamfer）の試験。GPU は使わない。

numpy / scipy / trimesh が要る。.venv には pytest を入れないので、uv の一時環境で走らせる:
  uvx --with pytest --with numpy --with scipy --with trimesh pytest tools/comfyui/tests/test_measure_mesh.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR / "scripts"))

import pytest  # noqa: E402

# 依存が無い一時環境（uvx --with pytest だけ）では、収集で落とさずこのファイルを飛ばす。
for dependency_name in ("numpy", "scipy", "trimesh"):
    pytest.importorskip(dependency_name)

import measure_mesh as mm  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402


def sphere(subdivisions: int = 2, radius: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    return np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int64)


def split_every_face(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """面ごとに頂点を別にする（GLB で UV の継ぎ目が全部の辺にある状態と同じ）。"""
    return vertices[faces].reshape(-1, 3), np.arange(len(faces) * 3, dtype=np.int64).reshape(-1, 3)


def test_closed_sphere_is_watertight() -> None:
    vertices, faces = sphere()
    report = mm.topology_report(vertices, faces)
    assert report["is_watertight"] and report["is_winding_consistent"]
    assert report["boundary_edges"] == 0 and report["non_manifold_edges"] == 0
    assert report["orientation_inconsistent_edges"] == 0
    assert report["shells"] == 1
    assert report["edges"] == len(faces) * 3 // 2
    # 正二十面体の細分は球より少し小さい。外向きなので体積は正
    assert report["volume_sign"] == 1
    assert report["volume"] == pytest.approx(4 / 3 * np.pi * 0.5**3, rel=0.05)


def test_hole_gives_boundary_edges() -> None:
    vertices, faces = sphere()
    report = mm.topology_report(vertices, faces[1:])
    assert not report["is_watertight"]
    assert report["boundary_edges"] == 3 and report["non_manifold_edges"] == 0


def test_extra_face_on_edge_is_non_manifold() -> None:
    vertices, faces = sphere()
    a, b = faces[0][0], faces[0][1]
    apex = len(vertices)
    vertices = np.vstack([vertices, [[0.0, 0.0, 2.0]]])
    faces = np.vstack([faces, [[a, b, apex]]])
    stats = mm.edge_statistics(faces, len(vertices))
    assert stats["non_manifold_edges"] == 1
    assert stats["boundary_edges"] == 2  # 足した面の残り 2 辺


def test_flipped_face_is_orientation_inconsistent_and_inverted_volume_is_negative() -> None:
    vertices, faces = sphere()
    flipped = faces.copy()
    flipped[0] = flipped[0][::-1]
    assert mm.edge_statistics(flipped, len(vertices))["orientation_inconsistent_edges"] == 3
    assert mm.signed_volume(vertices, faces[:, ::-1]) < 0


def test_two_spheres_are_two_shells() -> None:
    vertices, faces = sphere()
    both_vertices = np.vstack([vertices, vertices + [2.0, 0.0, 0.0]])
    both_faces = np.vstack([faces, faces + len(vertices)])
    assert mm.edge_statistics(both_faces, len(both_vertices))["shells"] == 2


def test_weld_closes_uv_seams() -> None:
    vertices, faces = sphere()
    split_vertices, split_faces = split_every_face(vertices, faces)
    before = mm.edge_statistics(split_faces, len(split_vertices))
    assert before["boundary_edges"] == len(faces) * 3
    welded_vertices, welded_faces, degenerate = mm.weld_vertices(split_vertices, split_faces)
    assert degenerate == 0
    assert len(welded_vertices) == len(vertices)
    report = mm.topology_report(welded_vertices, welded_faces)
    assert report["is_watertight"] and report["boundary_edges"] == 0 and report["shells"] == 1


def test_weld_with_tolerance_and_degenerate_faces() -> None:
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1e-9, 0, 0]], dtype=np.float64)
    faces = np.array([[0, 1, 2], [0, 3, 2]], dtype=np.int64)
    exact_vertices, _exact_faces, exact_degenerate = mm.weld_vertices(vertices, faces)
    assert len(exact_vertices) == 4 and exact_degenerate == 0
    near_vertices, near_faces, near_degenerate = mm.weld_vertices(vertices, faces, tolerance=1e-6)
    # 0 と 3 がまとまり、2 つめの面は潰れて除かれる
    assert near_degenerate == 1 and len(near_faces) == 1 and len(near_vertices) == 3


def test_unwelded_report_counts_coincident_vertices() -> None:
    # 頂点 0 と 3 が同じ位置にある「点で接する」2 枚の三角形。番号の上では別の頂点
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [-1, 0, 0], [0, -1, 0]], dtype=np.float64)
    faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
    report = mm.unwelded_report(vertices, faces)
    assert report["coincident_vertices"] == 2 and report["coincident_groups"] == 1
    assert report["shells"] == 2


def test_point_triangle_distance_regions() -> None:
    triangle = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    points = np.array([
        [0.25, 0.25, 0.5],   # 面の内側の上 → 0.5
        [-1.0, -1.0, 0.0],   # 頂点 a の領域 → sqrt(2)
        [2.0, 0.0, 0.0],     # 頂点 b の領域 → 1
        [0.5, -1.0, 0.0],    # 辺 ab の領域 → 1
        [1.0, 1.0, 0.0],     # 辺 bc の領域 → sqrt(2)/2
    ])
    expected = [0.5, np.sqrt(2.0), 1.0, 1.0, np.sqrt(2.0) / 2.0]
    assert mm.point_triangle_distance(points, triangle) == pytest.approx(expected)


def test_sample_surface_lies_on_mesh() -> None:
    vertices, faces = sphere(subdivisions=1)
    points = mm.sample_surface(vertices, faces, 2000, np.random.default_rng(0))
    assert points.shape == (2000, 3)
    assert mm.point_triangle_distance(points, vertices[faces]).max() < 1e-9


def test_compare_identical_and_shifted_meshes() -> None:
    vertices, faces = sphere(subdivisions=1)
    same = mm.compare_meshes(vertices, faces, vertices, faces, 500, "brute", 0, 1 / 1536)
    assert same["hausdorff"] < 1e-9 and same["chamfer_l1"] < 1e-9
    shift = 0.01
    moved = mm.compare_meshes(vertices + [shift, 0.0, 0.0], faces, vertices, faces, 500, "brute", 0, 1 / 1536)
    # 平行移動した球どうしの最大のずれは移動量に等しい（点の採取なので少し下回る）
    assert shift * 0.8 < moved["hausdorff"] <= shift + 1e-9
    assert moved["hausdorff_voxels"] == pytest.approx(moved["hausdorff"] * 1536)
    assert moved["hausdorff_over_diagonal"] == pytest.approx(moved["hausdorff"] / moved["reference_bbox_diagonal"])
    assert 0 < moved["over_limit_fraction_to_reference"] <= 1


def test_judge_uses_two_voxels_over_diagonal() -> None:
    topology = {"boundary_edges": 0, "non_manifold_edges": 0, "unwelded": {"boundary_edges": 0, "non_manifold_edges": 3}}
    passed = mm.judge(topology, {"hausdorff_over_diagonal": 1.0 / 1536}, 1536)
    assert passed["hausdorff_limit_over_diagonal"] == pytest.approx(2 / 1536)
    assert passed["passed"] and passed["info_unwelded_closed"] is False
    failed = mm.judge(topology, {"hausdorff_over_diagonal": 3.0 / 1536}, 1536)
    assert not failed["passed"]
    assert not mm.judge({"boundary_edges": 1, "non_manifold_edges": 0}, None, 1536)["passed"]


def test_align_to_reference_matches_bbox() -> None:
    vertices, _faces = sphere(subdivisions=1)
    aligned, info = mm.align_to_reference(vertices * 3 + 5, vertices)
    assert aligned == pytest.approx(vertices)
    assert info["scale"] == pytest.approx(1 / 3)


def test_measure_reads_file_and_compares(tmp_path: Path) -> None:
    vertices, faces = sphere(subdivisions=1)
    split_vertices, split_faces = split_every_face(vertices, faces)
    target = tmp_path / "split.obj"
    trimesh.Trimesh(split_vertices, split_faces, process=False).export(target)
    reference = tmp_path / "sphere.ply"
    trimesh.Trimesh(vertices, faces, process=False).export(reference)
    result = mm.measure(target, reference, samples=300, backend="brute")
    assert result["unwelded"]["boundary_edges"] == len(faces) * 3
    assert result["is_watertight"] and result["checks"]["passed"]
    assert result["comparison"]["hausdorff"] < 1e-6
