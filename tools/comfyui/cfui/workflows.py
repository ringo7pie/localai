"""PixelArtistry のワークフロー（ComfyUI の UI 形式 JSON）を、この機体向けに書き換える純粋関数。

ファイルシステムにもネットワークにも触れない（読み書きは scripts/adapt_workflows.py が行う）。
torch も ComfyUI も import しないので、素の python から試験できる。

UI 形式の要点（配布元の 4 本で確かめた形）:
  - nodes[] の各要素は id / type / inputs[] / outputs[] / widgets_values を持つ
  - inputs[i]["link"] は入ってくる link の id（無ければ None）
  - outputs[i]["links"] は出ていく link の id の一覧（無ければ None か []）
  - links[] の各要素は [link_id, 元 node_id, 元 slot, 先 node_id, 先 slot, 型]
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

BLENDER_PATH_NODE_TYPE = "PrimitiveString"
# 配布元の既定値。利用者が紫の「Blender path」ノードに自分のパスを貼る前提になっている。
UPSTREAM_BLENDER_VALUE = "blender"
BLENDER_PATH_INPUT_NAME = "blender_path"

WTIVO_NODE_TYPE = "WTiVoNativeMeshToMesh"
LODTAILOR_NODE_TYPE = "LODTailorTheMeshTrimmer"

# LODTailorTheMeshTrimmer.INPUT_TYPES の並び（LODTailor-The-Mesh-Trimmer-ComfyuiNode/__init__.py:832-920）。
# widgets_values はこの順に並ぶ（mesh は結線なので含まない）。
LODTAILOR_WIDGET_NAMES = (
    "blender_path",
    "target_tris",
    "passes",
    "tolerance",
    "intermediate_ratio",
    "last_ratio",
    "final_ratio",
    "triangulate",
    "symmetry",
    "voxel_rebuild",
    "relative_voxel_size",
    "minimum_voxel_size",
    "seal_distance",
    "seal_max_steps",
    "seal_keep_trying",
    "timeout_seconds",
)

# 予備案の Voxel Remesh の細かさ。WTiVo の input_res / final_res（1536）と同じ格子間隔にする。
FALLBACK_RELATIVE_VOXEL_SIZE = 1.0 / 1536.0

# 予備案の写しの UUID を、元の id から決まった値で作るための名前空間。
_FALLBACK_UUID_NAMESPACE = uuid.UUID("6f1d3f0e-6b0b-4c55-9d5a-2f8f3d9a6c01")


class WorkflowFormatError(ValueError):
    """想定した形のワークフローではない（上流が変わった可能性がある）。"""


def _nodes_by_id(workflow: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {node["id"]: node for node in workflow.get("nodes", [])}


def _links_by_id(workflow: dict[str, Any]) -> dict[int, list[Any]]:
    return {link[0]: link for link in workflow.get("links", [])}


def find_blender_path_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Blender のパスを配る PrimitiveString を返す。

    出ていく link の先が `blender_path` という名前の入力になっているものだけを数える
    （PrimitiveString は他の用途にも使われうるので、型だけでは決めない）。
    """

    nodes = _nodes_by_id(workflow)
    links = _links_by_id(workflow)
    found = []
    for node in workflow.get("nodes", []):
        if node.get("type") != BLENDER_PATH_NODE_TYPE:
            continue
        feeds_blender_path = False
        for output in node.get("outputs") or []:
            for link_id in output.get("links") or []:
                link = links.get(link_id)
                if link is None:
                    continue
                target = nodes.get(link[3])
                if target is None:
                    continue
                target_slot = link[4]
                target_inputs = target.get("inputs") or []
                if 0 <= target_slot < len(target_inputs) and (
                    target_inputs[target_slot].get("name") == BLENDER_PATH_INPUT_NAME
                ):
                    feeds_blender_path = True
        if feeds_blender_path:
            found.append(node)
    return found


def set_blender_path(workflow: dict[str, Any], blender_path: str) -> dict[str, Any]:
    """Blender のパスのノードの値を blender_path にした写しを返す。元の dict は変えない。

    配布元の 4 本は、どれも Blender のパスのノードが 1 つで、値が "blender"。
    そうでなければ上流が変わった可能性があるので、黙って進めずに止める。
    """

    adapted = copy.deepcopy(workflow)
    targets = find_blender_path_nodes(adapted)
    if len(targets) != 1:
        raise WorkflowFormatError(
            f"Blender のパスのノード（{BLENDER_PATH_NODE_TYPE} → {BLENDER_PATH_INPUT_NAME}）が "
            f"{len(targets)} 個あります（1 個を想定）"
        )
    node = targets[0]
    values = node.get("widgets_values")
    if not isinstance(values, list) or len(values) != 1 or values[0] != UPSTREAM_BLENDER_VALUE:
        raise WorkflowFormatError(
            f"Blender のパスのノード（id={node.get('id')}）の値が想定と違います: {values!r}"
            f"（[{UPSTREAM_BLENDER_VALUE!r}] を想定）"
        )
    node["widgets_values"] = [blender_path]
    return adapted


def blender_path_value(workflow: dict[str, Any]) -> str | None:
    """Blender のパスのノードの値を返す（1 個でなければ None）。doctor の確認用。"""

    targets = find_blender_path_nodes(workflow)
    if len(targets) != 1:
        return None
    values = targets[0].get("widgets_values")
    if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str):
        return values[0]
    return None


def has_wtivo(workflow: dict[str, Any]) -> bool:
    return any(node.get("type") == WTIVO_NODE_TYPE for node in workflow.get("nodes", []))


def _remove_node_and_bridge(workflow: dict[str, Any], node_id: int) -> list[int]:
    """MESH → MESH のノードを 1 つ外し、入力の元を出力の先へ直接つなぐ。

    つなぎ直した先の node id の一覧を返す。workflow は直接書き換える。
    """

    nodes = _nodes_by_id(workflow)
    links = _links_by_id(workflow)
    node = nodes[node_id]

    connected_inputs = [entry for entry in node.get("inputs") or [] if entry.get("link") is not None]
    if len(connected_inputs) != 1:
        raise WorkflowFormatError(
            f"{node.get('type')}（id={node_id}）の結線された入力が {len(connected_inputs)} 本あります（1 本を想定）"
        )
    incoming = links[connected_inputs[0]["link"]]
    origin_id, origin_slot = incoming[1], incoming[2]
    origin_outputs = nodes[origin_id].get("outputs") or []
    origin_links = origin_outputs[origin_slot].get("links") or []

    outgoing_ids = []
    for output in node.get("outputs") or []:
        outgoing_ids.extend(output.get("links") or [])

    retargeted = []
    for link_id in outgoing_ids:
        link = links[link_id]
        # 出ていく link の元を、外すノードではなく、その入力の元に付け替える（先と型はそのまま）。
        link[1] = origin_id
        link[2] = origin_slot
        retargeted.append(link[3])

    # 元ノードの出力からは、外すノードへの link を抜き、付け替えた link を足す。
    new_origin_links = [link_id for link_id in origin_links if link_id != incoming[0]]
    new_origin_links.extend(outgoing_ids)
    origin_outputs[origin_slot]["links"] = new_origin_links

    workflow["links"] = [link for link in workflow["links"] if link[0] != incoming[0]]
    workflow["nodes"] = [entry for entry in workflow["nodes"] if entry["id"] != node_id]
    return retargeted


def _set_lodtailor_widget(node: dict[str, Any], name: str, value: Any) -> None:
    values = node.get("widgets_values")
    if not isinstance(values, list) or len(values) != len(LODTAILOR_WIDGET_NAMES):
        raise WorkflowFormatError(
            f"{LODTAILOR_NODE_TYPE}（id={node.get('id')}）の widgets_values の数が想定と違います"
            f"（{len(values) if isinstance(values, list) else values!r} 個、{len(LODTAILOR_WIDGET_NAMES)} 個を想定）"
        )
    values[LODTAILOR_WIDGET_NAMES.index(name)] = value


def make_fallback(
    workflow: dict[str, Any], relative_voxel_size: float = FALLBACK_RELATIVE_VOXEL_SIZE
) -> dict[str, Any]:
    """予備案の写しを返す: WTiVo を外し、直後の LODTailor の Voxel Remesh で防水化する。

    - WTiVoNativeMeshToMesh を消し、その入力の元を出力の先へ直接つなぐ
    - WTiVo の出力を受けていた LODTailorTheMeshTrimmer の voxel_rebuild を真、
      relative_voxel_size を relative_voxel_size（既定 1/1536）にする
    - workflow の id は、元の id から決まる別の UUID にする（同じ id の写しが 2 つ並ばないように）
    それ以外は変えない。WTiVo を含まないワークフローは WorkflowFormatError にする。
    """

    fallback = copy.deepcopy(workflow)
    wtivo_ids = [node["id"] for node in fallback.get("nodes", []) if node.get("type") == WTIVO_NODE_TYPE]
    if not wtivo_ids:
        raise WorkflowFormatError(f"{WTIVO_NODE_TYPE} がありません（予備案は要りません）")

    retargeted_ids: list[int] = []
    for node_id in wtivo_ids:
        retargeted_ids.extend(_remove_node_and_bridge(fallback, node_id))

    nodes = _nodes_by_id(fallback)
    lodtailor_ids = [
        target_id for target_id in retargeted_ids if nodes[target_id].get("type") == LODTAILOR_NODE_TYPE
    ]
    if not lodtailor_ids:
        raise WorkflowFormatError(f"WTiVo の出力を受ける {LODTAILOR_NODE_TYPE} がありません")
    for target_id in lodtailor_ids:
        _set_lodtailor_widget(nodes[target_id], "voxel_rebuild", True)
        _set_lodtailor_widget(nodes[target_id], "relative_voxel_size", relative_voxel_size)

    if isinstance(fallback.get("id"), str):
        fallback["id"] = str(uuid.uuid5(_FALLBACK_UUID_NAMESPACE, fallback["id"] + ":noWTiVo"))
    return fallback


def dump_workflow(workflow: dict[str, Any]) -> str:
    """配布元に近い書式で文字列にする。

    配布元の 4 本は json.dumps(indent=2) と 1 文字も違わない（末尾の改行なし）。
    ensure_ascii=False にするので、配布元で \\u2013 などと書かれた文字はそのままの文字になる。
    """

    return json.dumps(workflow, indent=2, ensure_ascii=False)
