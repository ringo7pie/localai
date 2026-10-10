"""cfui と scripts/adapt_workflows.py の単体試験。GPU もネットワークも torch も使わない。

実行: uvx --with pytest pytest tools/comfyui/tests/test_units.py -q
    （.venv には pytest を入れない。素の python + pytest だけで動く）
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))
sys.path.insert(0, str(TOOL_DIR / "scripts"))

import adapt_workflows  # noqa: E402
import pytest  # noqa: E402
from cfui import checks, config, workflows  # noqa: E402
from cfui.cli import (  # noqa: E402
    build_parser,
    build_serve_command,
    build_serve_env,
    extra_args_from_env,
)

# ---------------------------------------------------------------- 試験用のワークフロー
# 配布元の 02 と同じ形を小さく作る:
#   Quad(325) → MemoryCleaner(326) → WTiVo(327) → LODTailor(328) → Save(329)
#                                              └→ BakeTextureFromVoxel(331)
#   PrimitiveString(324) → LODTailor(328).blender_path
LODTAILOR_VALUES = ["blender", 6000000, 100, 1.05, 0.5, 0.25, 0.2, True, False, True, 0.001, 1e-06, 0.0001, 100, True, 1800]


def make_workflow(with_wtivo: bool = True) -> dict:
    nodes = [
        {"id": 325, "type": "MeshReconstructWithQuad", "mode": 0, "inputs": [],
         "outputs": [{"name": "mesh", "type": "MESH", "links": [1298]}], "widgets_values": [1.0, 1536, True, True]},
        {"id": 326, "type": "MemoryCleaner", "mode": 0,
         "inputs": [{"name": "anything", "type": "*", "link": 1298}],
         "outputs": [{"name": "anything", "type": "*", "links": [1299] if with_wtivo else [1300, 1305]}],
         "widgets_values": []},
        {"id": 324, "type": "PrimitiveString", "mode": 0, "title": "Blender path – set once", "inputs": [],
         "outputs": [{"name": "STRING", "type": "STRING", "links": [1301]}], "widgets_values": ["blender"]},
        {"id": 328, "type": "LODTailorTheMeshTrimmer", "mode": 0,
         "inputs": [{"name": "mesh", "type": "MESH", "link": 1300},
                    {"name": "blender_path", "type": "STRING", "widget": {"name": "blender_path"}, "link": 1301}],
         "outputs": [{"name": "mesh", "type": "MESH", "links": [1302]}],
         "widgets_values": list(LODTAILOR_VALUES)},
        {"id": 329, "type": "Save3DAdvanced", "mode": 0, "inputs": [{"name": "mesh", "type": "MESH", "link": 1302}],
         "outputs": [], "widgets_values": []},
        {"id": 331, "type": "BakeTextureFromVoxel", "mode": 0,
         "inputs": [{"name": "a", "type": "X", "link": None}, {"name": "b", "type": "Y", "link": None},
                    {"name": "mesh", "type": "MESH", "link": 1305}],
         "outputs": [], "widgets_values": []},
    ]
    links = [
        [1298, 325, 0, 326, 0, "MESH"],
        [1301, 324, 0, 328, 1, "STRING"],
        [1302, 328, 0, 329, 0, "MESH"],
    ]
    if with_wtivo:
        nodes.insert(2, {"id": 327, "type": "WTiVoNativeMeshToMesh", "mode": 0,
                         "inputs": [{"name": "mesh", "type": "MESH", "link": 1299}],
                         "outputs": [{"name": "mesh", "type": "MESH", "links": [1300, 1305]}],
                         "widgets_values": [1536, 1536, 12000000, 1.0, 1.5, 20.0, 16, 0.0, "largest"]})
        links += [
            [1299, 326, 0, 327, 0, "*"],
            [1300, 327, 0, 328, 0, "MESH"],
            [1305, 327, 0, 331, 2, "MESH"],
        ]
    else:
        links += [[1300, 326, 0, 328, 0, "MESH"], [1305, 326, 0, 331, 2, "MESH"]]
    return {
        "id": "772b492c-de6a-4904-a5e0-0526674f6555",
        "revision": 0,
        "last_node_id": 352,
        "last_link_id": 1331,
        "nodes": nodes,
        "links": links,
        "groups": [{"title": "PixelArtistry · 1 Watertight High-Poly"}],
        "version": 0.4,
    }


def node_of(workflow: dict, node_id: int) -> dict:
    return next(node for node in workflow["nodes"] if node["id"] == node_id)


def link_of(workflow: dict, link_id: int) -> list:
    return next(link for link in workflow["links"] if link[0] == link_id)


# ---------------------------------------------------------------- workflows.set_blender_path


def test_find_blender_path_nodes_uses_link_target_name() -> None:
    workflow = make_workflow()
    # 結線先が blender_path でない PrimitiveString は数えない
    workflow["nodes"].append({"id": 999, "type": "PrimitiveString", "inputs": [],
                              "outputs": [{"name": "STRING", "links": [2000]}], "widgets_values": ["x"]})
    workflow["links"].append([2000, 999, 0, 329, 0, "STRING"])
    found = workflows.find_blender_path_nodes(workflow)
    assert [node["id"] for node in found] == [324]


def test_set_blender_path_changes_only_the_value() -> None:
    original = make_workflow()
    adapted = workflows.set_blender_path(original, config.BLENDER_PATH)
    assert node_of(adapted, 324)["widgets_values"] == [config.BLENDER_PATH]
    # 元の dict は変えない
    assert node_of(original, 324)["widgets_values"] == ["blender"]
    # それ以外は 1 つも変わっていない（LODTailor の widget の "blender" も結線で上書きされるので触らない）
    node_of(adapted, 324)["widgets_values"] = ["blender"]
    assert adapted == original


def test_set_blender_path_rejects_unexpected_value() -> None:
    workflow = make_workflow()
    node_of(workflow, 324)["widgets_values"] = ["C:/Blender/blender.exe"]
    with pytest.raises(workflows.WorkflowFormatError):
        workflows.set_blender_path(workflow, config.BLENDER_PATH)


def test_set_blender_path_rejects_missing_or_duplicated_node() -> None:
    workflow = make_workflow()
    workflow["links"] = [link for link in workflow["links"] if link[0] != 1301]
    with pytest.raises(workflows.WorkflowFormatError):
        workflows.set_blender_path(workflow, config.BLENDER_PATH)

    workflow = make_workflow()
    workflow["nodes"].append(copy.deepcopy(node_of(workflow, 324)) | {"id": 400, "outputs": [{"links": [2001]}]})
    workflow["links"].append([2001, 400, 0, 328, 1, "STRING"])
    with pytest.raises(workflows.WorkflowFormatError):
        workflows.set_blender_path(workflow, config.BLENDER_PATH)


def test_blender_path_value() -> None:
    adapted = workflows.set_blender_path(make_workflow(), config.BLENDER_PATH)
    assert workflows.blender_path_value(adapted) == config.BLENDER_PATH
    assert workflows.blender_path_value({"nodes": [], "links": []}) is None


# ---------------------------------------------------------------- workflows.make_fallback


def test_make_fallback_removes_wtivo_and_bridges_links() -> None:
    original = make_workflow()
    fallback = workflows.make_fallback(original)

    assert not workflows.has_wtivo(fallback)
    assert all(node["id"] != 327 for node in fallback["nodes"])
    # WTiVo へ入っていた link は消え、出ていた link は WTiVo の入力の元（MemoryCleaner の 0 番）から出る
    assert all(link[0] != 1299 for link in fallback["links"])
    assert link_of(fallback, 1300)[:5] == [1300, 326, 0, 328, 0]
    assert link_of(fallback, 1305)[:5] == [1305, 326, 0, 331, 2]
    assert node_of(fallback, 326)["outputs"][0]["links"] == [1300, 1305]
    # 先の入力側の link id はそのまま
    assert node_of(fallback, 328)["inputs"][0]["link"] == 1300
    assert node_of(fallback, 331)["inputs"][2]["link"] == 1305
    # 元の dict は変えない
    assert workflows.has_wtivo(original)


def test_make_fallback_sets_voxel_remesh_on_following_lodtailor_only() -> None:
    workflow = make_workflow()
    # WTiVo の後ろにない LODTailor（02 の low-poly 用）は変えない
    other = copy.deepcopy(node_of(workflow, 328)) | {"id": 335}
    other["widgets_values"] = list(other["widgets_values"])
    other["widgets_values"][10] = 0.0015
    workflow["nodes"].append(other)

    fallback = workflows.make_fallback(workflow)
    values = node_of(fallback, 328)["widgets_values"]
    names = workflows.LODTAILOR_WIDGET_NAMES
    assert values[names.index("voxel_rebuild")] is True
    assert values[names.index("relative_voxel_size")] == pytest.approx(1 / 1536)
    # 他の widget は変えない
    for index, name in enumerate(names):
        if name not in ("voxel_rebuild", "relative_voxel_size"):
            assert values[index] == LODTAILOR_VALUES[index], name
    assert node_of(fallback, 335)["widgets_values"][10] == 0.0015


def test_make_fallback_gets_distinct_deterministic_id() -> None:
    first = workflows.make_fallback(make_workflow())
    second = workflows.make_fallback(make_workflow())
    assert first["id"] != make_workflow()["id"]
    assert first["id"] == second["id"]


def test_make_fallback_custom_voxel_size() -> None:
    fallback = workflows.make_fallback(make_workflow(), relative_voxel_size=1 / 2048)
    assert node_of(fallback, 328)["widgets_values"][10] == pytest.approx(1 / 2048)


def test_make_fallback_rejects_workflow_without_wtivo() -> None:
    with pytest.raises(workflows.WorkflowFormatError):
        workflows.make_fallback(make_workflow(with_wtivo=False))


def test_lodtailor_widget_names_match_node_source() -> None:
    # 上流のノード定義が手元にあるときだけ、INPUT_TYPES の並びと一致するかを確かめる
    source = config.CUSTOM_NODES_DIR / "LODTailor-The-Mesh-Trimmer-ComfyuiNode" / "__init__.py"
    if not source.is_file():
        pytest.skip("vendor が無い")
    text = source.read_text(encoding="utf-8")
    block = text[text.index("def INPUT_TYPES"):text.index("RETURN_TYPES")]
    names = re.findall(r'^\s{16}"(\w+)": \(', block, flags=re.MULTILINE)
    assert tuple(name for name in names if name != "mesh") == workflows.LODTAILOR_WIDGET_NAMES


# ---------------------------------------------------------------- workflows.dump_workflow


def test_dump_workflow_matches_upstream_layout() -> None:
    workflow = make_workflow()
    text = workflows.dump_workflow(workflow)
    assert text == json.dumps(workflow, indent=2, ensure_ascii=False)
    assert not text.endswith("\n")
    # ensure_ascii=False: 「–」「·」は \u エスケープにしない
    assert "–" in text and "·" in text and "\\u2013" not in text
    assert json.loads(text) == workflow


def test_upstream_workflows_round_trip_when_vendor_exists() -> None:
    source_dir = config.PIXELARTISTRY_DIR / "workflows"
    if not source_dir.is_dir():
        pytest.skip("vendor が無い")
    for file_name in config.WORKFLOW_FILES:
        raw = (source_dir / file_name).read_text(encoding="utf-8")
        workflow = json.loads(raw)
        # 配布元は ensure_ascii=True の indent=2 と完全に同じ（書式を「元に近く」保てる根拠）
        assert json.dumps(workflow, indent=2) == raw, file_name
        adapted = workflows.set_blender_path(workflow, config.BLENDER_PATH)
        assert workflows.blender_path_value(adapted) == config.BLENDER_PATH
        if workflows.has_wtivo(adapted):
            fallback = workflows.make_fallback(adapted)
            assert not workflows.has_wtivo(fallback)
            # 予備案で変わるノードは WTiVo の削除と LODTailor だけ
            before = {node["id"]: node for node in adapted["nodes"]}
            changed = [node["id"] for node in fallback["nodes"] if node != before[node["id"]]]
            changed_types = {before[node_id]["type"] for node_id in changed}
            assert changed_types <= {"LODTailorTheMeshTrimmer", "MemoryCleaner"}, (file_name, changed_types)


# ---------------------------------------------------------------- adapt_workflows.adapt_all


def write_source(directory: Path) -> tuple[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    with_wtivo = "PixelArtistry_01_Image_to_Watertight_Mesh.json"
    without_wtivo = "PixelArtistry_03_Your_Mesh_to_GameReady_Asset.json"
    (directory / with_wtivo).write_text(json.dumps(make_workflow(), indent=2), encoding="utf-8")
    (directory / without_wtivo).write_text(json.dumps(make_workflow(with_wtivo=False), indent=2), encoding="utf-8")
    return with_wtivo, without_wtivo


def test_adapt_all_writes_and_is_idempotent(tmp_path: Path) -> None:
    names = write_source(tmp_path / "src")
    dest = tmp_path / "dest"
    results = adapt_workflows.adapt_all(tmp_path / "src", dest, None, config.BLENDER_PATH, 1 / 1536, False, names)
    assert [status for _path, status in results] == ["written", "written"]
    written = json.loads((dest / names[0]).read_text(encoding="utf-8"))
    assert workflows.blender_path_value(written) == config.BLENDER_PATH

    again = adapt_workflows.adapt_all(tmp_path / "src", dest, None, config.BLENDER_PATH, 1 / 1536, False, names)
    assert [status for _path, status in again] == ["unchanged", "unchanged"]


def test_adapt_all_keeps_user_edits_unless_forced(tmp_path: Path) -> None:
    names = write_source(tmp_path / "src")
    dest = tmp_path / "dest"
    adapt_workflows.adapt_all(tmp_path / "src", dest, None, config.BLENDER_PATH, 1 / 1536, False, names)
    (dest / names[0]).write_text("{}", encoding="utf-8")

    kept = adapt_workflows.adapt_all(tmp_path / "src", dest, None, config.BLENDER_PATH, 1 / 1536, False, names)
    assert kept[0][1] == "kept"
    assert (dest / names[0]).read_text(encoding="utf-8") == "{}"

    forced = adapt_workflows.adapt_all(tmp_path / "src", dest, None, config.BLENDER_PATH, 1 / 1536, True, names)
    assert forced[0][1] == "written"


def test_adapt_all_migrates_untouched_legacy_blender_path(tmp_path: Path) -> None:
    names = write_source(tmp_path / "src")
    dest = tmp_path / "dest"
    fallback_dir = tmp_path / "fallback"
    legacy = config.LEGACY_BLENDER_PATHS[0]
    # 以前の既定値で写した状態を作る（予備案も）
    adapt_workflows.adapt_all(
        tmp_path / "src", dest, fallback_dir, legacy, 1 / 1536, False, names, legacy_blender_paths=()
    )
    assert workflows.blender_path_value(json.loads((dest / names[0]).read_text(encoding="utf-8"))) == legacy

    migrated = adapt_workflows.adapt_all(tmp_path / "src", dest, fallback_dir, config.BLENDER_PATH, 1 / 1536, False, names)
    assert [status for _path, status in migrated] == ["migrated", "migrated", "migrated"]
    assert workflows.blender_path_value(json.loads((dest / names[0]).read_text(encoding="utf-8"))) == config.BLENDER_PATH
    fallback_name_01 = "PixelArtistry_01_Image_to_Watertight_Mesh_noWTiVo.json"
    fallback = json.loads((fallback_dir / fallback_name_01).read_text(encoding="utf-8"))
    assert workflows.blender_path_value(fallback) == config.BLENDER_PATH

    # 2 回目は何も変えない（冪等）
    again = adapt_workflows.adapt_all(tmp_path / "src", dest, fallback_dir, config.BLENDER_PATH, 1 / 1536, False, names)
    assert [status for _path, status in again] == ["unchanged", "unchanged", "unchanged"]


def test_adapt_all_does_not_migrate_edited_legacy_file(tmp_path: Path) -> None:
    names = write_source(tmp_path / "src")
    dest = tmp_path / "dest"
    legacy = config.LEGACY_BLENDER_PATHS[0]
    adapt_workflows.adapt_all(tmp_path / "src", dest, None, legacy, 1 / 1536, False, names, legacy_blender_paths=())
    # 以前の既定値のファイルを UI で手直しした想定: 末尾に 1 文字足す
    edited = (dest / names[0]).read_text(encoding="utf-8") + "\n"
    (dest / names[0]).write_text(edited, encoding="utf-8")

    results = adapt_workflows.adapt_all(tmp_path / "src", dest, None, config.BLENDER_PATH, 1 / 1536, False, names)
    assert results[0][1] == "kept"
    assert (dest / names[0]).read_text(encoding="utf-8") == edited


def test_adapt_all_fallback_only_for_wtivo_workflows(tmp_path: Path) -> None:
    names = write_source(tmp_path / "src")
    fallback_dir = tmp_path / "fallback"
    adapt_workflows.adapt_all(tmp_path / "src", tmp_path / "dest", fallback_dir, config.BLENDER_PATH, 1 / 1536, False, names)
    assert sorted(path.name for path in fallback_dir.iterdir()) == ["PixelArtistry_01_Image_to_Watertight_Mesh_noWTiVo.json"]
    fallback = json.loads((fallback_dir / "PixelArtistry_01_Image_to_Watertight_Mesh_noWTiVo.json").read_text(encoding="utf-8"))
    assert not workflows.has_wtivo(fallback)
    assert workflows.blender_path_value(fallback) == config.BLENDER_PATH


def test_adapt_main_reports_format_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "src"
    source.mkdir()
    for file_name in config.WORKFLOW_FILES:
        (source / file_name).write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    assert adapt_workflows.main(["--source-dir", str(source), "--dest-dir", str(tmp_path / "dest")]) == 1
    assert "写せませんでした" in capsys.readouterr().err


def test_fallback_name() -> None:
    assert adapt_workflows.fallback_name("A.json") == "A_noWTiVo.json"
    assert adapt_workflows.fallback_name("A") == "A_noWTiVo"


# ---------------------------------------------------------------- checks


def test_parse_last_json_line() -> None:
    assert checks.parse_last_json_line('[WTiVo] log\n{"a": 1}\n\n') == {"a": 1}
    assert checks.parse_last_json_line("not json") is None
    assert checks.parse_last_json_line("") is None
    assert checks.parse_last_json_line("[1, 2]") is None


def test_classify_nvcc() -> None:
    output = "nvcc: NVIDIA (R) Cuda compiler driver\nCuda compilation tools, release 12.6, V12.6.85\nBuild cuda_12.6.r12.6"
    assert checks.classify_nvcc(output, "12.6") == (True, "Build cuda_12.6.r12.6")
    assert checks.classify_nvcc(output.replace("12.6", "13.2"), "12.6")[0] is False
    assert checks.classify_nvcc(None, "12.6")[0] is False
    assert checks.classify_nvcc("  ", "12.6")[0] is False


def test_classify_torch_all_ok() -> None:
    probe = {"version": "2.9.1+cu126", "cuda_version": "12.6", "cuda_available": True,
             "device_name": "NVIDIA A30", "capability": "8.0"}
    rows = checks.classify_torch(probe, "2.9.1+cu126", "12.6", "A30")
    assert all(ok for _label, ok, _detail in rows)
    assert len(rows) == 5
    assert "8.0" in rows[-1][2]


def test_classify_torch_failures() -> None:
    rows = checks.classify_torch({"import_error": "No module named torch"}, "2.9.1+cu126", "12.6", "A30")
    assert rows == [("torch の import", False, "No module named torch")]

    probe = {"version": "2.9.1+cu128", "cuda_version": "12.8", "cuda_available": False}
    rows = checks.classify_torch(probe, "2.9.1+cu126", "12.6", "A30")
    assert [ok for _label, ok, _detail in rows] == [True, False, False, False, False]


def test_classify_commit_and_patch() -> None:
    assert checks.classify_commit("abc", "abc") == (True, "HEAD=abc")
    assert checks.classify_commit("abd", "abc")[0] is False
    assert checks.classify_commit(None, "abc")[0] is False
    assert checks.classify_patch("applied", "x.patch")[0] is True
    for state in ("applicable", "conflict", "missing"):
        assert checks.classify_patch(state, "x.patch")[0] is False


def test_classify_import_and_wtivo_module() -> None:
    assert checks.classify_import(None, "/x/cumesh/__init__.py") == (True, "/x/cumesh/__init__.py")
    assert checks.classify_import("ImportError: libc10.so") == (False, "ImportError: libc10.so")

    native = "/t/build"
    assert checks.classify_wtivo_module(None, "/t/build/wtivo_core.cpython-312-x86_64-linux-gnu.so", native)[0]
    # Windows 用の .pyd や別の場所から読まれたものは NG
    assert not checks.classify_wtivo_module(None, "/t/build/wtivo_core.pyd", native)[0]
    assert not checks.classify_wtivo_module(None, "/other/wtivo_core.so", native)[0]
    assert not checks.classify_wtivo_module(None, "/t/buildx/wtivo_core.so", native)[0]
    assert not checks.classify_wtivo_module("ImportError", None, native)[0]
    assert not checks.classify_wtivo_module(None, None, native)[0]


def test_classify_apt_packages() -> None:
    ok, detail = checks.classify_apt_packages({"libcgal-dev": True, "libtbb-dev": True})
    assert ok and "libcgal-dev" in detail
    ok, detail = checks.classify_apt_packages({"libcgal-dev": True, "libopenvdb-dev": False})
    assert not ok and "libopenvdb-dev" in detail and "sudo apt install" in detail


def test_classify_model_file_and_url() -> None:
    assert checks.classify_model_file(10, 10) == (True, "10 バイト")
    assert checks.classify_model_file(None, 10)[0] is False
    assert checks.classify_model_file(9, 10)[0] is False
    assert (
        checks.model_url("https://huggingface.co/", "Comfy-Org/Pixal3D", "vae/x.safetensors")
        == "https://huggingface.co/Comfy-Org/Pixal3D/resolve/main/vae/x.safetensors"
    )


def test_model_table_matches_installer_urls() -> None:
    # 配布元 bat の :models（L407-417）と同じ 9 ファイル・同じ URL
    bat = config.PIXELARTISTRY_DIR / "watertightMeshes_win_installer.bat"
    urls = [checks.model_url(config.HF_BASE_URL, repo, path) for _subdir, _name, repo, path, _size, _sha in config.MODEL_FILES]
    assert len(urls) == 9 and len(set(urls)) == 9
    for subdir, name, _repo, path, _size, sha in config.MODEL_FILES:
        assert path.endswith("/" + name)
        assert re.fullmatch(r"[0-9a-f]{64}", sha), name
    if bat.is_file():
        text = bat.read_text(encoding="utf-8").replace("%HF%", config.HF_BASE_URL)
        for url in urls:
            assert url in text, url


def test_classify_workflows() -> None:
    values = {"a.json": config.BLENDER_PATH, "b.json": config.BLENDER_PATH}
    assert checks.classify_workflows(values, config.BLENDER_PATH)[0] is True
    assert checks.classify_workflows(values | {"c.json": None}, config.BLENDER_PATH)[0] is False
    assert checks.classify_workflows(values | {"c.json": "blender"}, config.BLENDER_PATH)[0] is False


def test_classify_blender() -> None:
    output = "Blender 5.2.2 LTS\n\tbuild date: 2026-09-15\n"
    assert checks.parse_blender_version(output) == (5, 2, 2)
    assert checks.classify_blender(output, 5) == (True, "Blender 5.2.2")
    assert checks.classify_blender("Blender 4.0.2\n", 5)[0] is False
    assert checks.classify_blender("Blender 5.1\n", 5) == (True, "Blender 5.1.0")
    assert checks.classify_blender("snap: command not found", 5)[0] is False
    assert checks.classify_blender(None, 5)[0] is False
    assert checks.classify_blender("", 5)[0] is False


def test_classify_blender_launcher() -> None:
    assert checks.classify_blender_launcher("/snap/blender/7803/blender", config.BLENDER_SNAP_LAUNCHER)[0] is True
    assert checks.classify_blender_launcher("/usr/bin/snap", config.BLENDER_SNAP_LAUNCHER)[0] is False
    assert checks.classify_blender_launcher(None, config.BLENDER_SNAP_LAUNCHER)[0] is False


def test_default_blender_path_avoids_snap_run() -> None:
    # /snap/bin/blender は /usr/bin/snap へのリンクで、snap run が子を別の cgroup へ移す
    assert config.BLENDER_PATH == "/snap/blender/current/blender"
    assert not config.BLENDER_PATH.startswith("/snap/bin/")
    assert config.BLENDER_PATH not in config.LEGACY_BLENDER_PATHS
    assert "/snap/bin/blender" in config.LEGACY_BLENDER_PATHS


def test_classify_port_status() -> None:
    assert checks.classify_port_status(8188, False, False)[0] is True
    assert checks.classify_port_status(8188, True, True)[0] is True
    assert checks.classify_port_status(8188, True, False)[0] is False


def test_classify_selftest() -> None:
    passed = {"faces_in": 5060, "faces_out": 12000, "watertight": True, "seconds": 12.3}
    ok, detail = checks.classify_selftest(passed)
    assert ok and "5060" in detail and "12000" in detail
    assert checks.classify_selftest(passed | {"watertight": False})[0] is False
    assert checks.classify_selftest(passed | {"faces_out": 0})[0] is False
    assert checks.classify_selftest(passed | {"watertight": "True"})[0] is False
    assert checks.classify_selftest({"error": "WTiVo を読み込めません"}) == (False, "WTiVo を読み込めません")
    assert checks.classify_selftest({"skipped": True, "reason": "wtivo_* を import できないため"})[0] is False
    assert checks.classify_selftest(None)[0] is False


def test_classify_vram_is_informational() -> None:
    for used, active in ((None, False), (100, False), (20000, False), (20000, True)):
        assert checks.classify_vram_status(used, 1024, active)[0] is True


def test_summarize() -> None:
    overall, lines = checks.summarize([("a", True, "x"), ("b", False, "y")])
    assert overall is False
    assert lines == ["OK  a: x", "NG  b: y"]
    assert checks.summarize([("a", True, "x")])[0] is True


# ---------------------------------------------------------------- cli（純粋関数）


def test_build_serve_command() -> None:
    command = build_serve_command(python_bin="/v/python", main_py="/c/main.py", host="0.0.0.0", port=8188, extra_args=["--lowvram"])
    assert command == ["/v/python", "/c/main.py", "--listen", "0.0.0.0", "--port", "8188", "--lowvram"]


def test_build_serve_env_points_blender_to_clean_dirs() -> None:
    base = {"PATH": "/usr/bin", "BLENDER_USER_CONFIG": "/home/mt/.config/blender"}
    env = build_serve_env(base, Path("/h/.config/comfyui/blender-clean"))
    assert env["BLENDER_USER_CONFIG"] == "/h/.config/comfyui/blender-clean/config"
    assert env["BLENDER_USER_SCRIPTS"] == "/h/.config/comfyui/blender-clean/scripts"
    assert env["BLENDER_USER_EXTENSIONS"] == "/h/.config/comfyui/blender-clean/extensions"
    assert env["PATH"] == "/usr/bin"
    # 元の環境は変えない
    assert base["BLENDER_USER_CONFIG"] == "/home/mt/.config/blender"


def test_extra_args_from_env() -> None:
    assert extra_args_from_env({}) == []
    assert extra_args_from_env({"COMFYUI_EXTRA_ARGS": "--lowvram --preview-method 'none'"}) == ["--lowvram", "--preview-method", "none"]


def test_parser_defaults() -> None:
    parser = build_parser()
    serve = parser.parse_args(["serve"])
    assert (serve.host, serve.port) == ("0.0.0.0", 8188)
    doctor = parser.parse_args(["doctor", "--skip-selftest"])
    assert doctor.skip_selftest is True


# ---------------------------------------------------------------- 直値の食い違い
# setup-server.sh / build-wtivo.sh は venv を作る前に git を操作するので、config.py と同じ値を直値で持つ。


def test_setup_script_pins_match_config() -> None:
    text = (TOOL_DIR / "setup-server.sh").read_text(encoding="utf-8")
    assert f'COMFYUI_COMMIT="{config.COMFYUI_COMMIT}"' in text
    assert f'COMFYUI_TAG="{config.COMFYUI_TAG}"' in text
    assert f'PIXELARTISTRY_COMMIT="{config.PIXELARTISTRY_COMMIT}"' in text
    for node_name, url, commit in config.CUSTOM_NODES:
        assert f"{node_name} {url} {commit}" in text, node_name
    for name, url, commit in config.EXTENSION_SOURCES:
        assert url in text and commit in text, name


def test_build_wtivo_pins_match_config() -> None:
    text = (TOOL_DIR / "scripts" / "build-wtivo.sh").read_text(encoding="utf-8")
    assert f'SRC_COMMIT="{config.WTIVO_SRC_COMMIT}"' in text
    assert f'SRC_URL="{config.WTIVO_SRC_URL}"' in text
    assert f'APT_PACKAGES="{" ".join(config.WTIVO_APT_PACKAGES)}"' in text


def test_patches_target_expected_files() -> None:
    expected = {
        "wtivo-src-linux-build.patch": {"CMakeLists.txt", "scripts/build_gpupr.py"},
        "wtivo-src-core-vertices-lifetime.patch": {"native/core/wtivo_core.cpp"},
        "wtivo-node-allow-linux.patch": {"wtivo.py"},
        "cumesh-eigen-include.patch": {"setup.py"},
    }
    for patch_name, files in expected.items():
        text = (TOOL_DIR / "patches" / patch_name).read_text(encoding="utf-8")
        assert set(re.findall(r"^\+\+\+ b/(\S+)$", text, flags=re.MULTILINE)) == files, patch_name


def test_service_example() -> None:
    text = (TOOL_DIR / "systemd" / "comfyui.service.example").read_text(encoding="utf-8")
    for line in (
        "EnvironmentFile=-%h/.config/comfyui/comfyui.env",
        "ExecStart=%h/Proj/localai/tools/comfyui/run-comfyui serve",
        "Restart=on-failure",
        "TimeoutStartSec=600",
        "MemoryHigh=44G",
        "MemoryMax=48G",
    ):
        assert line in text.splitlines(), line
