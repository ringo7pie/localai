"""scripts/run_workflow.py（UI 形式 → API 形式の変換と上書き）と scripts/resource_monitor.py の読み取り関数の試験。

GPU もネットワークも使わない。実行: uvx --with pytest pytest tools/comfyui/tests/test_run_workflow.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))
sys.path.insert(0, str(TOOL_DIR / "scripts"))

import pytest  # noqa: E402
import resource_monitor  # noqa: E402
import run_workflow as rw  # noqa: E402

# ---------------------------------------------------------------- 試験用の /object_info（実物から必要な形だけ写した）
OBJECT_INFO = {
    "LoadImage": {
        "input": {"required": {"image": [["a.png", "viking.png"], {"image_upload": True}]}},
        "input_order": {"required": ["image"]}, "output": ["IMAGE", "MASK"],
    },
    "KSampler": {
        "input": {"required": {
            "model": ["MODEL", {}],
            "seed": ["INT", {"default": 0, "control_after_generate": True}],
            "steps": ["INT", {"default": 20}],
            "sampler_name": [["euler", "dpm"], {}],
            "latent_image": ["LATENT", {}],
            "denoise": ["FLOAT", {"default": 1.0}],
        }},
        "input_order": {"required": ["model", "seed", "steps", "sampler_name", "latent_image", "denoise"]},
    },
    "OldSampler": {  # control_after_generate の指定が無い seed（画面は名前で control を付ける）
        "input": {"required": {"noise_seed": ["INT", {"default": 0}], "cfg": ["FLOAT", {"default": 7.0}]}},
        "input_order": {"required": ["noise_seed", "cfg"]},
    },
    "MoGeInference": {
        "input": {"required": {
            "image": ["IMAGE", {}],
            "resolution_level": ["INT", {"default": 9}],
            "apply_mask": ["BOOLEAN", {"default": True}],
            "refine_steps": ["INT", {"default": 3}],
        }},
        "input_order": {"required": ["image", "resolution_level", "apply_mask", "refine_steps"]},
    },
    "MeshReconstructWithQuad": {
        "input": {"required": {
            "mesh": ["MESH", {}],
            "resolution": [[512, 1024, 1536], {"default": 512}],
            "remove_floaters": ["BOOLEAN", {"default": True}],
        }},
        "input_order": {"required": ["mesh", "resolution", "remove_floaters"]},
    },
    "Upsample": {
        "input": {"required": {"latent": ["LATENT", {}], "target_resolution": ["INT", {"default": 1024}]}},
        "input_order": {"required": ["latent", "target_resolution"]},
    },
    "MemoryCleaner": {
        "input": {"optional": {"input_1": ["*", {}], "enabled": ["BOOLEAN", {"default": True}]}},
        "input_order": {"optional": ["input_1", "enabled"]},
    },
    "WTiVoNativeMeshToMesh": {
        "input": {"required": {"mesh": ["MESH", {}], "input_res": ["INT", {"default": 1536}]}},
        "input_order": {"required": ["mesh", "input_res"]},
    },
    "VaeDecodeShapeTrellis": {"input": {"required": {}}, "input_order": {"required": []}},
    "Save3DAdvanced": {
        "input": {"required": {
            "model_3d": ["FILE_3D_GLB,FILE_3D", {}],
            "filename_prefix": ["STRING", {"default": "3d/ComfyUI"}],
            "viewport_state": ["LOAD_3D", {}],
            "width": ["INT", {"default": 1024}],
        }},
        "input_order": {"required": ["model_3d", "filename_prefix", "viewport_state", "width"]},
    },
    "ImageCropToMask": {
        "input": {"required": {
            "images": ["IMAGE", {}],
            "background": ["COLOR", {"default": "#000000", "socketless": True}],
            "mask_input": ["MASK", {"forceInput": True}],
        }},
        "input_order": {"required": ["images", "background", "mask_input"]},
    },
    "PrimitiveBoolean": {"input": {"required": {"value": ["BOOLEAN", {}]}}, "input_order": {"required": ["value"]}},
    "PrimitiveString": {"input": {"required": {"value": ["STRING", {}]}}, "input_order": {"required": ["value"]}},
    "ComfySwitchNode": {
        "input": {
            "required": {"switch": ["BOOLEAN", {}]},
            "optional": {"on_false": ["COMFY_MATCHTYPE_V3", {"lazy": True}], "on_true": ["COMFY_MATCHTYPE_V3", {"lazy": True}]},
        },
        "input_order": {"required": ["switch"], "optional": ["on_false", "on_true"]},
    },
    "LODTailorTheMeshTrimmer": {
        "input": {"required": {"mesh": ["MESH", {}], "blender_path": ["STRING", {"default": "blender"}]}},
        "input_order": {"required": ["mesh", "blender_path"]},
    },
    "Trellis2MeshEncoder": {
        "input": {"required": {"mesh_filename": ["STRING", {"default": "input_mesh.glb"}]}},
        "input_order": {"required": ["mesh_filename"]},
    },
    "ListNode": {
        "input": {"required": {"items": ["COMBO", {"options": ["a", "b"], "multiselect": True}]}},
        "input_order": {"required": ["items"]},
    },
}


def node(node_id, node_type, widgets=None, inputs=None, outputs=None, mode=0, title=None):
    item = {"id": node_id, "type": node_type, "mode": mode, "inputs": inputs or [], "outputs": outputs or []}
    if widgets is not None:
        item["widgets_values"] = widgets
    if title:
        item["title"] = title
    return item


def socket(name, socket_type, link=None, widget=False):
    item = {"name": name, "type": socket_type, "link": link}
    if widget:
        item["widget"] = {"name": name}
    return item


def make_graph() -> dict:
    """配布元のワークフローと同じ形を小さく作る。

    LoadImage(1) → MoGe(2)
    VaeDecodeShape(3) → Quad(4, mode=4 bypass) → MemoryCleaner(5) → WTiVo(6) → Reroute(7) → LODTailor(8)
    PrimitiveString(9) → LODTailor.blender_path
    PrimitiveBoolean(10) → Switch(11).switch ; Quad の代わりに muted(12) を on_true に
    PrimitiveNode(13) → Upsample(14).target_resolution
    Note(15)、Save(16)
    """
    nodes = [
        node(1, "LoadImage", ["viking.png", "image"], outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
        node(2, "MoGeInference", [9, True], inputs=[socket("image", "IMAGE", 1)]),
        node(3, "VaeDecodeShapeTrellis", None, outputs=[{"name": "mesh", "type": "MESH", "links": [2]}]),
        node(4, "MeshReconstructWithQuad", [1536, True], inputs=[socket("mesh", "MESH", 2)],
             outputs=[{"name": "mesh", "type": "MESH", "links": [3]}], mode=rw.MODE_BYPASS),
        node(5, "MemoryCleaner", [True], inputs=[socket("input_1", "*", 3)],
             outputs=[{"name": "output_1", "type": "*", "links": [4]}]),
        node(6, "WTiVoNativeMeshToMesh", ["1536"], inputs=[socket("mesh", "MESH", 4)],
             outputs=[{"name": "mesh", "type": "MESH", "links": [5]}]),
        node(7, "Reroute", None, inputs=[socket("", "*", 5)], outputs=[{"name": "", "type": "MESH", "links": [6]}]),
        node(8, "LODTailorTheMeshTrimmer", ["blender"],
             inputs=[socket("mesh", "MESH", 6), socket("blender_path", "STRING", 7, widget=True)],
             outputs=[{"name": "mesh", "type": "MESH", "links": [10]}]),
        node(9, "PrimitiveString", ["/snap/blender/current/blender"], outputs=[{"name": "STRING", "type": "STRING", "links": [7]}],
             title="Blender path"),
        node(10, "PrimitiveBoolean", [False], outputs=[{"name": "BOOLEAN", "type": "BOOLEAN", "links": [8]}],
             title="Boolean (Switch to Trellis2)"),
        node(11, "ComfySwitchNode", [True],
             inputs=[socket("on_false", "MESH", 11), socket("on_true", "MESH", 9), socket("switch", "BOOLEAN", 8, widget=True)],
             outputs=[{"name": "output", "type": "MESH", "links": []}]),
        node(12, "WTiVoNativeMeshToMesh", [1536], outputs=[{"name": "mesh", "type": "MESH", "links": [9]}], mode=rw.MODE_NEVER),
        node(13, "PrimitiveNode", [2048], outputs=[{"name": "INT", "type": "INT", "links": [12], "widget": {"name": "target_resolution"}}]),
        node(14, "Upsample", [1024], inputs=[socket("latent", "LATENT"), socket("target_resolution", "INT", 12, widget=True)]),
        node(15, "Note", ["memo"]),
        node(16, "Save3DAdvanced", ["3d/out", "", 1024], inputs=[socket("model_3d", "FILE_3D_GLB,FILE_3D", None)]),
        node(17, "VaeDecodeShapeTrellis", None, outputs=[{"name": "mesh", "type": "MESH", "links": [11]}]),
    ]
    links = [
        [1, 1, 0, 2, 0, "IMAGE"], [2, 3, 0, 4, 0, "MESH"], [3, 4, 0, 5, 0, "MESH"], [4, 5, 0, 6, 0, "*"],
        [5, 6, 0, 7, 0, "MESH"], [6, 7, 0, 8, 0, "MESH"], [7, 9, 0, 8, 1, "STRING"], [8, 10, 0, 11, 2, "BOOLEAN"],
        [9, 12, 0, 11, 1, "MESH"], [10, 8, 0, 99, 0, "MESH"], [11, 17, 0, 11, 0, "MESH"], [12, 13, 0, 14, 1, "INT"],
    ]
    return {"nodes": nodes, "links": links, "version": 0.4}


def convert():
    return rw.convert_workflow(make_graph(), OBJECT_INFO)


# ---------------------------------------------------------------- widget の割り当て


def test_widget_layout_adds_control_and_upload_slots() -> None:
    layout = rw.widget_layout(OBJECT_INFO["KSampler"])
    assert [(slot.input_name, slot.kind) for slot in layout] == [
        ("seed", "value"), ("seed", "control"), ("steps", "value"), ("sampler_name", "value"), ("denoise", "value"),
    ]
    load_image = rw.widget_layout(OBJECT_INFO["LoadImage"])
    assert [(slot.input_name, slot.kind) for slot in load_image] == [("image", "value"), ("image", "upload")]


def test_widget_layout_legacy_seed_name_gets_control() -> None:
    layout = rw.widget_layout(OBJECT_INFO["OldSampler"])
    assert [(slot.input_name, slot.kind) for slot in layout] == [
        ("noise_seed", "value"), ("noise_seed", "control"), ("cfg", "value"),
    ]
    values, controls, warnings = rw.assign_widget_values(OBJECT_INFO["OldSampler"], [5, 6.5], "#x")
    # 数が合わないときは、互換の規則を外した並びで読む
    assert values == {"noise_seed": 5, "cfg": 6.5} and controls == {} and warnings == []


def test_widget_types_custom_socketless_and_force_input() -> None:
    layout = rw.widget_layout(OBJECT_INFO["Save3DAdvanced"])
    assert [slot.input_name for slot in layout] == ["filename_prefix", "viewport_state", "width"]
    crop = rw.widget_layout(OBJECT_INFO["ImageCropToMask"])
    assert [slot.input_name for slot in crop] == ["background"]
    assert rw.widget_type_of("FLOAT,INT", {"widgetType": "FLOAT"}) == "FLOAT"
    assert rw.widget_type_of("MESH", {}) is None


def test_assign_widget_values_seed_control_is_not_sent() -> None:
    values, controls, warnings = rw.assign_widget_values(
        OBJECT_INFO["KSampler"], [56, "randomize", 12, "euler", 1], "#3 KSampler")
    assert values == {"seed": 56, "steps": 12, "sampler_name": "euler", "denoise": 1}
    assert controls == {"seed": "randomize"}
    assert warnings == []


def test_assign_widget_values_fills_missing_with_defaults() -> None:
    values, _controls, warnings = rw.assign_widget_values(OBJECT_INFO["MoGeInference"], [9, True], "#56 MoGe")
    assert values == {"resolution_level": 9, "apply_mask": True, "refine_steps": 3}
    assert len(warnings) == 1 and "refine_steps" in warnings[0]


def test_assign_widget_values_warns_on_extra_values() -> None:
    values, _controls, warnings = rw.assign_widget_values(OBJECT_INFO["Upsample"], [1024, 5, 6], "#14")
    assert values == {"target_resolution": 1024}
    assert "後ろの 2 個" in warnings[0]


def test_assign_widget_values_dict_form() -> None:
    values, _controls, warnings = rw.assign_widget_values(
        OBJECT_INFO["KSampler"], {"seed": 3, "steps": "7", "unknown": 1}, "#x")
    assert values == {"seed": 3, "steps": 7} and warnings == []


def test_coerce_widget_values() -> None:
    quad = rw.widget_layout(OBJECT_INFO["MeshReconstructWithQuad"])[0]
    assert rw.coerce_widget_value(quad, "1536") == (1536, None)
    assert rw.coerce_widget_value(quad, 777)[1] is not None
    upsample = rw.widget_layout(OBJECT_INFO["Upsample"])[0]
    assert rw.coerce_widget_value(upsample, "2048") == (2048, None)
    assert rw.coerce_widget_value(upsample, 4.0) == (4, None)
    boolean = rw.widget_layout(OBJECT_INFO["PrimitiveBoolean"])[0]
    assert rw.coerce_widget_value(boolean, "false") == (False, None)


def test_list_values_are_wrapped() -> None:
    workflow = {"nodes": [node(1, "ListNode", [["a", "b"]])], "links": []}
    prompt, _report = rw.convert_workflow(workflow, OBJECT_INFO)
    assert prompt["1"]["inputs"]["items"] == {"__value__": ["a", "b"]}


# ---------------------------------------------------------------- リンクの解決


def test_is_valid_connection() -> None:
    assert rw.is_valid_connection("MESH", "*")
    assert rw.is_valid_connection("", "IMAGE")
    assert rw.is_valid_connection("MESH", "mesh")
    assert not rw.is_valid_connection("MESH", "IMAGE")
    assert rw.is_valid_connection("FILE_3D_GLB,FILE_3D", "FILE_3D_GLB")
    assert not rw.is_valid_connection("FILE_3D_OBJ,FILE_3D_STL", "FILE_3D_GLB")


def test_convert_excludes_frontend_only_muted_and_bypassed() -> None:
    prompt, report = convert()
    assert report["notes"] == ["15"]
    assert sorted(report["frontend_only"]) == ["13", "7"]
    assert report["muted"] == ["12"]
    assert report["bypassed"] == ["4"]
    assert not {"4", "7", "12", "13", "15"} & set(prompt)


def test_bypass_with_any_type_target_uses_same_slot() -> None:
    prompt, _report = convert()
    # MemoryCleaner の * の入力は、bypass した Quad の同じ番号の入力（mesh）の元へつながる
    assert prompt["5"]["inputs"]["input_1"] == ["3", 0]


def test_bypass_prefers_exact_type_then_compatible() -> None:
    workflow = {
        "nodes": [
            node(1, "VaeDecodeShapeTrellis", None, outputs=[{"name": "a", "type": "IMAGE", "links": [1]}]),
            node(2, "VaeDecodeShapeTrellis", None, outputs=[{"name": "b", "type": "MESH", "links": [2]}]),
            node(3, "MeshReconstructWithQuad", [512, True],
                 inputs=[socket("image", "IMAGE", 1), socket("mesh", "MESH", 2)],
                 outputs=[{"name": "out", "type": "MESH", "links": [3]}], mode=rw.MODE_BYPASS),
            node(4, "WTiVoNativeMeshToMesh", [1536], inputs=[socket("mesh", "MESH", 3)]),
        ],
        "links": [[1, 1, 0, 3, 0, "IMAGE"], [2, 2, 0, 3, 1, "MESH"], [3, 3, 0, 4, 0, "MESH"]],
    }
    prompt, _report = rw.convert_workflow(workflow, OBJECT_INFO)
    # 同じ番号（0, IMAGE）は型が合わないので、型が一致する mesh（1）を素通しする
    assert prompt["4"]["inputs"]["mesh"] == ["2", 0]


def test_bypass_without_matching_type_drops_input() -> None:
    workflow = {
        "nodes": [
            node(1, "LoadImage", ["a.png", "image"], outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
            node(2, "MeshReconstructWithQuad", [512, True], inputs=[socket("image", "IMAGE", 1)],
                 outputs=[{"name": "out", "type": "MESH", "links": [2]}], mode=rw.MODE_BYPASS),
            node(3, "WTiVoNativeMeshToMesh", [1536], inputs=[socket("mesh", "MESH", 2)]),
        ],
        "links": [[1, 1, 0, 2, 0, "IMAGE"], [2, 2, 0, 3, 0, "MESH"]],
    }
    prompt, report = rw.convert_workflow(workflow, OBJECT_INFO)
    assert "mesh" not in prompt["3"]["inputs"]
    assert any("bypass" in warning for warning in report["warnings"])


def test_reroute_and_primitive_node_are_resolved() -> None:
    prompt, _report = convert()
    assert prompt["8"]["inputs"]["mesh"] == ["6", 0]
    # PrimitiveNode からのリンクは値に置き換わる（widgets_values の 1024 より勝つ）
    assert prompt["14"]["inputs"]["target_resolution"] == 2048


def test_linked_widget_input_uses_link_and_server_primitives_stay() -> None:
    prompt, _report = convert()
    assert prompt["8"]["inputs"]["blender_path"] == ["9", 0]
    assert prompt["9"] == {"class_type": "PrimitiveString", "inputs": {"value": "/snap/blender/current/blender"},
                           "_meta": {"title": "Blender path"}}
    assert prompt["11"]["class_type"] == "ComfySwitchNode"
    assert prompt["11"]["inputs"]["switch"] == ["10", 0]
    assert prompt["11"]["inputs"]["on_false"] == ["17", 0]


def test_input_from_muted_node_is_removed() -> None:
    prompt, _report = convert()
    assert "on_true" not in prompt["11"]["inputs"]


def test_widget_values_assigned_in_converted_nodes() -> None:
    prompt, report = convert()
    assert prompt["1"]["inputs"] == {"image": "viking.png"}
    assert prompt["6"]["inputs"]["input_res"] == 1536
    assert prompt["16"]["inputs"] == {"filename_prefix": "3d/out", "viewport_state": "", "width": 1024}
    assert any("refine_steps" in warning for warning in report["warnings"])


def test_subgraph_is_rejected() -> None:
    workflow = make_graph()
    workflow["definitions"] = {"subgraphs": [{"id": "0a1b-sub", "name": "inner"}]}
    workflow["nodes"].append(node(40, "0a1b-sub", []))
    assert rw.find_subgraph_nodes(workflow) == ["40"]
    with pytest.raises(rw.WorkflowConversionError, match="subgraph"):
        rw.convert_workflow(workflow, OBJECT_INFO)


def test_unknown_node_type_and_api_format_are_rejected() -> None:
    with pytest.raises(rw.WorkflowConversionError, match="サーバーに無い"):
        rw.convert_workflow({"nodes": [node(1, "NoSuchNode", [])], "links": []}, OBJECT_INFO)
    with pytest.raises(rw.WorkflowConversionError, match="API 形式"):
        rw.convert_workflow({"1": {"class_type": "LoadImage", "inputs": {}}}, OBJECT_INFO)


def test_links_in_object_form() -> None:
    links = rw.parse_links({"links": [{"id": 3, "origin_id": 1, "origin_slot": 0, "target_id": 2, "target_slot": 1, "type": "X"}]})
    assert links[3] == rw.UiLink(3, "1", 0, "2", 1, "X")


# ---------------------------------------------------------------- 上書き


def test_overrides_image_seed_backend_mesh() -> None:
    workflow = make_graph()
    workflow["nodes"].append(node(30, "KSampler", [42, "fixed", 12, "euler", 1]))
    workflow["nodes"].append(node(31, "Trellis2MeshEncoder", ["your_mesh.glb"]))
    prompt, report = rw.convert_workflow(workflow, OBJECT_INFO)
    assert rw.override_image(prompt, "other.png") == ["1"]
    assert prompt["1"]["inputs"]["image"] == "other.png"
    assert rw.override_seed(prompt, report, 7) == ["30.seed"]
    assert prompt["30"]["inputs"]["seed"] == 7
    assert rw.select_backend(prompt, workflow, "trellis2") == ["10"]
    assert prompt["10"]["inputs"]["value"] is True
    rw.select_backend(prompt, workflow, "pixal3d")
    assert prompt["10"]["inputs"]["value"] is False
    assert rw.override_mesh(prompt, "/abs/mesh.glb") == ["31"]
    assert prompt["31"]["inputs"]["mesh_filename"] == "/abs/mesh.glb"


def test_set_literal_refuses_linked_input_and_missing_node() -> None:
    prompt, _report = convert()
    with pytest.raises(rw.WorkflowConversionError, match="リンク"):
        rw.set_literal(prompt, "8", "blender_path", "/x")
    with pytest.raises(rw.WorkflowConversionError, match="API 形式に無い"):
        rw.set_literal(prompt, "4", "resolution", 512)


def test_select_backend_requires_switch() -> None:
    workflow = {"nodes": [node(1, "PrimitiveBoolean", [False], title="something else")], "links": []}
    prompt, _report = rw.convert_workflow(workflow, OBJECT_INFO)
    with pytest.raises(rw.WorkflowConversionError, match="Trellis"):
        rw.select_backend(prompt, workflow, "pixal3d")


def test_parse_set_and_tap_arguments() -> None:
    assert rw.parse_set_argument("324.value=\"/snap/blender/current/blender\"") == ("324", "value", "/snap/blender/current/blender")
    assert rw.parse_set_argument("327.proxy_points=25000000") == ("327", "proxy_points", 25000000)
    assert rw.parse_set_argument("1.image=plain.png") == ("1", "image", "plain.png")
    assert rw.parse_tap_argument("325=3d/tap_quad") == ("325", 0, "3d/tap_quad")
    assert rw.parse_tap_argument("92:1=x") == ("92", 1, "x")
    with pytest.raises(rw.WorkflowConversionError):
        rw.parse_set_argument("novalue")
    with pytest.raises(rw.WorkflowConversionError):
        rw.parse_tap_argument("325")


def test_add_taps_and_tag_prefixes() -> None:
    prompt, _report = convert()
    added = rw.add_taps(prompt, [("6", 0, "3d/tap_wtivo")])
    (tap_id, origin), = added.items()
    assert origin == "6:0" and int(tap_id) > rw.TAP_ID_BASE
    assert prompt[tap_id]["inputs"] == {"mesh": ["6", 0], "filename_prefix": "3d/tap_wtivo"}
    changed = rw.tag_filename_prefixes(prompt, "wf01")
    assert set(changed) == {"16", tap_id}
    assert prompt["16"]["inputs"]["filename_prefix"] == "3d/out_wf01"
    with pytest.raises(rw.WorkflowConversionError):
        rw.add_taps(prompt, [("4", 0, "x")])


def test_add_taps_accepts_only_mesh_outputs() -> None:
    object_info = {**OBJECT_INFO,
                   "WTiVoNativeMeshToMesh": {**OBJECT_INFO["WTiVoNativeMeshToMesh"], "output": ["MESH"]},
                   "LODTailorTheMeshTrimmer": {**OBJECT_INFO["LODTailorTheMeshTrimmer"], "output": ["FILE_3D_GLB"]}}
    prompt, _report = convert()
    assert len(rw.add_taps(prompt, [("6", 0, "3d/ok")], object_info)) == 1
    with pytest.raises(rw.WorkflowConversionError, match="FILE_3D_GLB"):
        rw.add_taps(prompt, [("8", 0, "3d/ng")], object_info)
    with pytest.raises(rw.WorkflowConversionError, match="None"):
        rw.add_taps(prompt, [("6", 3, "3d/ng")], object_info)


# ---------------------------------------------------------------- 結果の整理


def test_collect_output_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    (output_dir / "3d").mkdir(parents=True)
    (output_dir / "3d" / "a_00001.glb").write_bytes(b"glb!")
    entry = {"outputs": {
        "331": {"3d": [{"filename": "a_00001.glb", "subfolder": "3d", "type": "output"}],
                "result": ["3d/a_00001.glb", None, []]},
        "302": {"images": [{"filename": "p.png", "subfolder": "", "type": "temp"}]},
    }}
    files = rw.collect_output_files(entry, {"output": output_dir, "temp": tmp_path / "temp"})
    assert files[0] == {"node": "331", "key": "3d", "type": "output", "path": str(output_dir / "3d" / "a_00001.glb"),
                        "exists": True, "bytes": 4}
    assert files[1]["exists"] is False and files[1]["path"].endswith("temp/p.png")


def test_history_status_times() -> None:
    entry = {"status": {"status_str": "error", "completed": False, "messages": [
        ["execution_start", {"timestamp": 1000}],
        ["execution_error", {"timestamp": 4500, "node_id": "327", "node_type": "WTiVo", "exception_message": "boom",
                             "exception_type": "RuntimeError"}],
    ]}}
    times = rw.history_status_times(entry)
    assert times["server_seconds"] == 3.5
    assert times["error"]["node_id"] == "327"


def test_node_timeline_accumulates_reentry() -> None:
    timeline = rw.NodeTimeline()
    timeline.on_executing("1", 0.0)
    timeline.on_executing("2", 1.0)
    timeline.on_executing("1", 3.0)
    timeline.close(3.5)
    totals = timeline.totals()
    assert totals["1"]["seconds"] == pytest.approx(1.5)
    assert totals["2"]["seconds"] == pytest.approx(2.0)


def test_real_workflows_convert_when_vendor_exists() -> None:
    object_info_path = TOOL_DIR / "logs" / "object_info.json"
    workflow_dir = TOOL_DIR / "vendor" / "ComfyUI" / "user" / "default" / "workflows" / "PixelArtistry"
    if not object_info_path.exists() or not workflow_dir.exists():
        pytest.skip("vendor か logs/object_info.json が無い（setup-server.sh の前）")
    object_info = json.loads(object_info_path.read_text(encoding="utf-8"))
    workflow = json.loads((workflow_dir / "PixelArtistry_01b_Image_to_Watertight_Mesh_2K.json").read_text(encoding="utf-8"))
    prompt, report = rw.convert_workflow(workflow, object_info)
    assert report["bypassed"] == ["325"]
    assert prompt["326"]["inputs"]["input_1"] == ["92", 0]
    assert prompt["122"]["inputs"]["image"] == "viking_wolf_rune_axe.png"
    assert prompt["3"]["inputs"]["seed"] == 56 and report["controls"]["3"] == {"seed": "randomize"}
    assert prompt["328"]["inputs"]["blender_path"] == ["324", 0]
    assert prompt["327"]["inputs"]["proxy_points"] == 25000000
    assert all("refine_steps" in warning for warning in report["warnings"])


# ---------------------------------------------------------------- resource_monitor の読み取り


def test_monitor_parsers() -> None:
    assert resource_monitor.parse_memory_stat("anon 100\nfile 20\nbad x\n") == {"anon": 100, "file": 20}
    meminfo = resource_monitor.parse_meminfo("SwapTotal:  1024 kB\nSwapFree:   512 kB\nHugePages_Total:  0\n")
    assert meminfo == {"SwapTotal": 1024 * 1024, "SwapFree": 512 * 1024, "HugePages_Total": 0}
    assert resource_monitor.parse_gpu_query("965, 37\n") == (965, 37)
    assert resource_monitor.parse_gpu_query("[N/A], [N/A]\n") == (None, None)
    assert resource_monitor.parse_compute_apps("490455, 938\n123, 10\n") == {490455: 938, 123: 10}
