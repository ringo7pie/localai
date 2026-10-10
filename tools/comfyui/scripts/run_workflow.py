#!/usr/bin/env python3
"""UI 形式のワークフロー（ComfyUI の画面で保存する JSON）を API 形式（POST /prompt の prompt）に変え、
ComfyUI に投入して /history で終わりを確かめ、出力ファイルの一覧を JSON で返す。

ComfyUI v0.38.2 の Python 側には UI 形式 → API 形式の変換が無い（画面のフロントエンドが
graphToPrompt / ExecutableNodeDTO で行う）。そこで同じ規則をここに書き直した。規則は
comfyui_frontend_package 1.53.6 の settingStore-*.js を読んで合わせた（2026-10-03）:

- widgets_values は /object_info の入力の順（required → optional、input_order の順）で widget の入力に割り当てる。
  INT は control_after_generate（指定が無ければ名前が seed / noise_seed のとき）の値を 1 つ余分に持つ
  （例 KSampler の [42, "fixed", ...]）。image_upload などアップロード用の入力も 1 つ余分に持つ
  （LoadImage の [ファイル名, "image"]）。どちらも API には送らない。
  値が足りないとき（ワークフローの保存後にノードが入力を増やした）は既定値で埋める（画面と同じ）。
- リンクのある入力はリンクが勝つ。旧式の PrimitiveNode（画面だけのノード）からのリンクは、その値に置き換える。
  PrimitiveString / PrimitiveBoolean / ComfySwitchNode はサーバー側のノードなので、そのまま出す。
- Note / MarkdownNote / PrimitiveNode / Reroute は画面だけのノードなので出さない。Reroute は素通しする。
- mode=2（muted）のノードは出さない。その出力を受けていた入力は外す（画面と同じ）。
- mode=4（bypass）のノードは出さず、出力を「同じ型の入力」の元へ付け替える（_getBypassSlotIndex と同じ順:
  受け手の型が * なら同じ番号の入力、次に同じ番号で型が合う入力、次に型が完全に一致する最初の入力、
  最後に型が両立する最初の入力）。
- subgraph（definitions.subgraphs）を使うノードがあれば、未対応として止める。

使い方:
  run_workflow.py convert WORKFLOW.json [-o api.json] [上書きの引数]
  run_workflow.py run WORKFLOW.json [--tag TAG] [--tap NODE[:SLOT]=PREFIX ...] [--monitor] [--free-before] [上書きの引数]
上書きの引数: --image / --seed / --backend pixal3d|trellis2 / --mesh / --set NODE.INPUT=VALUE

run の結果（変換の報告・ノードごとの所要時間・出力ファイル・資源のピーク）は
vendor/ComfyUI/output/localai_runs/<tag>/run.json に書き、標準出力の最後の 1 行にも JSON で出す。
変換は標準ライブラリだけで動く。run は aiohttp があれば WebSocket でノードごとの時間を取り、
無ければ /history を数秒ごとに見る（ノードごとの時間は取れない）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# scripts/ の 1 つ上（tools/comfyui）と scripts/ 自身を import 先に足す。cfui を入れていない python でも動くように。
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR.parent))
sys.path.insert(0, str(SCRIPTS_DIR))

from cfui import config  # noqa: E402

DEFAULT_SERVER = f"http://127.0.0.1:{config.PORT}"
RUNS_SUBDIR = "localai_runs"

MODE_NEVER = 2
MODE_BYPASS = 4

# 画面だけのノード（isVirtualNode）。API には出さない。
NOTE_TYPES = frozenset({"Note", "MarkdownNote"})
PRIMITIVE_NODE_TYPE = "PrimitiveNode"
REROUTE_TYPE = "Reroute"
FRONTEND_ONLY_TYPES = NOTE_TYPES | {PRIMITIVE_NODE_TYPE, REROUTE_TYPE}

# 画面で widget になる入力の型。COMBO は型が選択肢の list のときもある。
PRIMITIVE_WIDGET_TYPES = frozenset({"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"})
# 拡張が widget を作る型（Save3DAdvanced の viewport_state、ImageCropToMask の background など）。
CUSTOM_WIDGET_TYPES = frozenset({"COLOR", "LOAD_3D", "LOAD_3D_ANIMATION"})
UPLOAD_OPTION_KEYS = ("image_upload", "video_upload", "audio_upload", "file_upload")
# 画面は INT の入力名が seed / noise_seed なら、指定が無くても control_after_generate を付ける。
LEGACY_SEED_NAMES = ("seed", "noise_seed")

BACKEND_SWITCH_TITLE_RE = re.compile(r"trellis", re.IGNORECASE)
BACKENDS = ("pixal3d", "trellis2")
MESH_ENCODER_TYPE = "Trellis2MeshEncoder"
TAP_NODE_TYPE = "SaveGLB"
TAP_OUTPUT_TYPE = "MESH"
TAP_ID_BASE = 90000


class WorkflowConversionError(ValueError):
    """UI 形式から API 形式へ変えられないとき（未知のノード、subgraph、壊れたリンクなど）。"""


class PromptRejected(RuntimeError):
    """POST /prompt が検証で拒否されたとき。body に node_errors が入る。"""

    def __init__(self, body: Any) -> None:
        super().__init__(json.dumps(body, ensure_ascii=False)[:4000])
        self.body = body


# ---------------------------------------------------------------- widget の割り当て


@dataclass(frozen=True)
class WidgetSlot:
    """widgets_values の 1 つの位置。kind は value（入力の値）/ control（seed の後ろ）/ upload。"""

    input_name: str
    kind: str
    widget_type: str
    options: dict[str, Any]
    combo_values: tuple[Any, ...] | None


def iter_input_specs(node_def: dict[str, Any]) -> Iterator[tuple[str, Any, dict[str, Any], str]]:
    """/object_info の 1 ノード分から (入力名, 型, オプション, required/optional) を画面と同じ順に返す。"""
    inputs = node_def.get("input") or {}
    order = node_def.get("input_order") or {}
    for category in ("required", "optional"):
        section = inputs.get(category) or {}
        names = order.get(category) or list(section)
        for name in names:
            spec = section.get(name)
            if spec is None:
                continue
            input_type = spec[0]
            options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            yield name, input_type, options, category


def widget_type_of(input_type: Any, options: dict[str, Any]) -> str | None:
    """入力が画面で widget になるならその型を、ソケットだけなら None を返す。"""
    if options.get("forceInput"):
        return None
    if isinstance(input_type, list):
        return "COMBO"
    if "widgetType" in options:
        return str(options["widgetType"])
    if input_type in PRIMITIVE_WIDGET_TYPES or input_type in CUSTOM_WIDGET_TYPES:
        return str(input_type)
    if options.get("socketless"):
        return str(input_type)
    return None


def has_control_widget(widget_type: str, input_name: str, options: dict[str, Any], legacy_seed: bool = True) -> bool:
    """seed の後ろに control_after_generate（fixed / randomize など）の値が並ぶか。"""
    flag = options.get("control_after_generate")
    if widget_type == "INT" and flag is None:
        return legacy_seed and input_name in LEGACY_SEED_NAMES
    return bool(flag)


def widget_layout(node_def: dict[str, Any], legacy_seed: bool = True) -> list[WidgetSlot]:
    """widgets_values の各位置が、どの入力のどの値かを並べる。"""
    slots: list[WidgetSlot] = []
    for name, input_type, options, _category in iter_input_specs(node_def):
        widget_type = widget_type_of(input_type, options)
        if widget_type is None:
            continue
        if isinstance(input_type, list):
            combo_values: tuple[Any, ...] | None = tuple(input_type)
        elif widget_type == "COMBO":
            combo_values = tuple(options.get("options") or ())
        else:
            combo_values = None
        slots.append(WidgetSlot(name, "value", widget_type, options, combo_values))
        if has_control_widget(widget_type, name, options, legacy_seed):
            slots.append(WidgetSlot(name, "control", widget_type, options, None))
        if any(options.get(key) for key in UPLOAD_OPTION_KEYS):
            slots.append(WidgetSlot(name, "upload", widget_type, options, None))
    return slots


def default_widget_value(slot: WidgetSlot) -> tuple[bool, Any]:
    """値が足りない widget の既定値。画面と同じく default、COMBO なら最初の選択肢。"""
    if "default" in slot.options:
        return True, slot.options["default"]
    if slot.combo_values:
        return True, slot.combo_values[0]
    return False, None


def coerce_widget_value(slot: WidgetSlot, value: Any) -> tuple[Any, str | None]:
    """値を入力の型に合わせる。合わせられないときは値をそのまま返し、警告を添える。"""
    widget_type = slot.widget_type
    if widget_type == "INT" and isinstance(value, str):
        try:
            return int(float(value)) if "." in value else int(value), None
        except ValueError:
            return value, f"{slot.input_name}: INT に変えられない値 {value!r}"
    if widget_type == "INT" and isinstance(value, float) and value.is_integer():
        return int(value), None
    if widget_type == "FLOAT" and isinstance(value, str):
        try:
            return float(value), None
        except ValueError:
            return value, f"{slot.input_name}: FLOAT に変えられない値 {value!r}"
    if widget_type == "BOOLEAN" and isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true", None
    if widget_type == "COMBO" and slot.combo_values is not None:
        if value in slot.combo_values:
            return value, None
        # 保存時と選択肢の型が違う（"1536" と 1536 など）だけなら合わせる
        for candidate in slot.combo_values:
            if str(candidate) == str(value):
                return candidate, None
        return value, f"{slot.input_name}: 選択肢に無い値 {value!r}（サーバーの検証で落ちる可能性）"
    return value, None


def assign_widget_values(
    node_def: dict[str, Any], widgets_values: Any, node_label: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """widgets_values を入力名に割り当てる。(値, control の値, 警告) を返す。"""
    warnings: list[str] = []
    values: dict[str, Any] = {}
    controls: dict[str, Any] = {}

    if isinstance(widgets_values, dict):
        # 一部の custom node（VHS など）は名前つきで保存する
        known = {slot.input_name: slot for slot in widget_layout(node_def) if slot.kind == "value"}
        for name, raw in widgets_values.items():
            if name in known:
                value, warning = coerce_widget_value(known[name], raw)
                values[name] = value
                if warning:
                    warnings.append(f"{node_label}: {warning}")
        return values, controls, warnings

    raw_values = list(widgets_values or [])
    layout = widget_layout(node_def)
    if len(raw_values) != len(layout):
        # seed / noise_seed の互換規則を外すと数が合うなら、そちらを使う
        alternative = widget_layout(node_def, legacy_seed=False)
        if len(alternative) == len(raw_values) and alternative != layout:
            layout = alternative
        elif len(raw_values) > len(layout):
            warnings.append(
                f"{node_label}: widgets_values が {len(raw_values)} 個で、widget は {len(layout)} 個。後ろの "
                f"{len(raw_values) - len(layout)} 個は使わない（画面も同じく無視する）"
            )
        else:
            missing = [slot.input_name for slot in layout[len(raw_values):] if slot.kind == "value"]
            warnings.append(f"{node_label}: widgets_values が足りない。既定値で埋める: {', '.join(missing)}")

    for index, slot in enumerate(layout):
        if index < len(raw_values):
            raw = raw_values[index]
        else:
            if slot.kind != "value":
                continue
            found, raw = default_widget_value(slot)
            if not found:
                continue
        if slot.kind == "control":
            controls[slot.input_name] = raw
            continue
        if slot.kind == "upload":
            continue
        value, warning = coerce_widget_value(slot, raw)
        values[slot.input_name] = value
        if warning:
            warnings.append(f"{node_label}: {warning}")
    return values, controls, warnings


def wrap_literal(value: Any) -> Any:
    """API 形式では長さ 2 の list がリンクと読まれるので、list の値は {"__value__": ...} で包む（画面と同じ）。"""
    if isinstance(value, list):
        return {"__value__": value}
    return value


# ---------------------------------------------------------------- リンクの解決


def is_valid_connection(type_a: Any, type_b: Any) -> bool:
    """LiteGraph.isValidConnection と同じ判定。* と空は何にでもつながる。"," 区切りは 1 つでも合えばよい。"""
    normalized_a = 0 if type_a in ("", "*", None) else type_a
    normalized_b = 0 if type_b in ("", "*", None) else type_b
    if not normalized_a or not normalized_b or normalized_a == normalized_b:
        return True
    text_a = str(normalized_a).lower()
    text_b = str(normalized_b).lower()
    if "," not in text_a and "," not in text_b:
        return text_a == text_b
    return any(is_valid_connection(part_a, part_b) for part_a in text_a.split(",") for part_b in text_b.split(","))


@dataclass(frozen=True)
class UiLink:
    link_id: int
    origin_id: str
    origin_slot: int
    target_id: str
    target_slot: int
    link_type: Any


def parse_links(workflow: dict[str, Any]) -> dict[int, UiLink]:
    """links は v0.4 の配列形式 [id, 元, 元の番号, 先, 先の番号, 型] と、オブジェクト形式の両方を読む。"""
    links: dict[int, UiLink] = {}
    for raw in workflow.get("links") or []:
        if isinstance(raw, dict):
            link = UiLink(int(raw["id"]), str(raw["origin_id"]), int(raw["origin_slot"]),
                          str(raw["target_id"]), int(raw["target_slot"]), raw.get("type"))
        else:
            link = UiLink(int(raw[0]), str(raw[1]), int(raw[2]), str(raw[3]), int(raw[4]), raw[5] if len(raw) > 5 else None)
        links[link.link_id] = link
    return links


def find_subgraph_nodes(workflow: dict[str, Any]) -> list[str]:
    """subgraph を中身に持つノード（type が definitions.subgraphs の id）の id を返す。"""
    subgraph_ids = {str(item.get("id")) for item in (workflow.get("definitions") or {}).get("subgraphs") or []}
    return [str(node["id"]) for node in workflow.get("nodes") or [] if str(node.get("type")) in subgraph_ids]


class UiGraph:
    """UI 形式のグラフ。入力から「実際に値を出すノードの出力」をたどる。"""

    def __init__(self, workflow: dict[str, Any]) -> None:
        self.nodes: dict[str, dict[str, Any]] = {str(node["id"]): node for node in workflow.get("nodes") or []}
        self.links = parse_links(workflow)
        self.warnings: list[str] = []

    def label(self, node_id: str) -> str:
        node = self.nodes[node_id]
        title = node.get("title")
        return f"#{node_id} {node.get('type')}" + (f" 「{title}」" if title else "")

    def resolve_input(self, node_id: str, slot: int, visited: set[str], want_type: Any = None) -> tuple | None:
        """ExecutableNodeDTO.resolveInput と同じ。("link", 元の id, 元の番号) / ("value", 値) / None を返す。"""
        key = f"{node_id}[I]{slot}"
        if key in visited:
            raise WorkflowConversionError(f"リンクが循環している: {self.label(node_id)} の入力 {slot}")
        visited.add(key)
        inputs = self.nodes[node_id].get("inputs") or []
        if slot >= len(inputs):
            raise WorkflowConversionError(f"{self.label(node_id)} に入力 {slot} が無い")
        link_id = inputs[slot].get("link")
        if link_id is None:
            return None
        link = self.links.get(int(link_id))
        if link is None:
            raise WorkflowConversionError(f"{self.label(node_id)} の入力 {slot} のリンク {link_id} が links に無い")
        if link.origin_id not in self.nodes:
            raise WorkflowConversionError(f"リンク {link_id} の元 #{link.origin_id} が nodes に無い")
        requested = want_type if want_type is not None else inputs[slot].get("type")
        return self.resolve_output(link.origin_id, link.origin_slot, requested, visited)

    def bypass_slot_index(self, node_id: str, slot: int, want_type: Any) -> int:
        """_getBypassSlotIndex と同じ順で、bypass したノードのどの入力を素通しするかを決める。-1 は該当なし。"""
        node = self.nodes[node_id]
        inputs = node.get("inputs") or []
        outputs = node.get("outputs") or []
        output_type = outputs[slot].get("type") if slot < len(outputs) else None
        if want_type in ("*", ""):
            return slot if len(inputs) > slot else 0
        if slot < len(inputs):
            opposite_type = inputs[slot].get("type")
            if is_valid_connection(opposite_type, output_type) and is_valid_connection(opposite_type, want_type):
                return slot
        for index, item in enumerate(inputs):
            if item.get("type") == want_type:
                return index
        for index, item in enumerate(inputs):
            if is_valid_connection(item.get("type"), output_type) and is_valid_connection(item.get("type"), want_type):
                return index
        return -1

    def resolve_output(self, node_id: str, slot: int, want_type: Any, visited: set[str]) -> tuple | None:
        key = f"{node_id}[O]{slot}"
        if key in visited:
            raise WorkflowConversionError(f"リンクが循環している: {self.label(node_id)} の出力 {slot}")
        visited.add(key)
        node = self.nodes[node_id]
        mode = node.get("mode", 0)
        if mode == MODE_NEVER:
            return None
        if mode == MODE_BYPASS:
            index = self.bypass_slot_index(node_id, slot, want_type)
            if index == -1:
                self.warnings.append(f"{self.label(node_id)}（bypass）の出力 {slot} に型 {want_type} の入力が無い。入力を外す")
                return None
            # 画面と同じく、素通しした先では型を引き継がない（その入力自身の型でたどる）
            return self.resolve_input(node_id, index, visited)
        node_type = node.get("type")
        if node_type == PRIMITIVE_NODE_TYPE:
            values = node.get("widgets_values") or []
            if not values:
                raise WorkflowConversionError(f"{self.label(node_id)} に値が無い")
            return ("value", values[0])
        if node_type == REROUTE_TYPE:
            return self.resolve_input(node_id, slot, visited, want_type)
        if node_type in NOTE_TYPES:
            return None
        return ("link", node_id, slot)


# ---------------------------------------------------------------- 変換


def convert_workflow(workflow: dict[str, Any], object_info: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """UI 形式 → API 形式。(prompt, 報告) を返す。報告には外したノード・警告・seed の位置が入る。"""
    if "nodes" not in workflow:
        if all(isinstance(value, dict) and "class_type" in value for value in workflow.values()):
            raise WorkflowConversionError("すでに API 形式（class_type を持つ辞書）になっている")
        raise WorkflowConversionError("UI 形式のワークフローではない（nodes が無い）")
    subgraph_nodes = find_subgraph_nodes(workflow)
    if subgraph_nodes:
        raise WorkflowConversionError(f"subgraph を使うノードがある（未対応）: {', '.join(subgraph_nodes)}")

    graph = UiGraph(workflow)
    report: dict[str, Any] = {
        "subgraphs": [], "notes": [], "frontend_only": [], "muted": [], "bypassed": [],
        "warnings": [], "controls": {}, "seed_inputs": [], "titles": {},
    }
    prompt: dict[str, Any] = {}

    for node_id, node in graph.nodes.items():
        node_type = node.get("type")
        mode = node.get("mode", 0)
        if node_type in NOTE_TYPES:
            report["notes"].append(node_id)
            continue
        if node_type in FRONTEND_ONLY_TYPES:
            report["frontend_only"].append(node_id)
            continue
        if mode == MODE_NEVER:
            report["muted"].append(node_id)
            continue
        if mode == MODE_BYPASS:
            report["bypassed"].append(node_id)
            continue
        node_def = object_info.get(node_type)
        if node_def is None:
            raise WorkflowConversionError(f"{graph.label(node_id)}: サーバーに無いノード型（custom node の読み込み失敗？）")

        values, controls, warnings = assign_widget_values(node_def, node.get("widgets_values"), graph.label(node_id))
        report["warnings"].extend(warnings)
        if controls:
            report["controls"][node_id] = controls
            report["seed_inputs"].extend([node_id, name] for name in controls)
        inputs: dict[str, Any] = {name: wrap_literal(value) for name, value in values.items()}

        for slot, ui_input in enumerate(node.get("inputs") or []):
            resolved = graph.resolve_input(node_id, slot, set())
            if resolved is None:
                continue
            name = ui_input.get("name")
            if resolved[0] == "value":
                inputs[name] = wrap_literal(resolved[1])
            else:
                inputs[name] = [resolved[1], int(resolved[2])]

        title = node.get("title") or node_def.get("display_name") or node_type
        prompt[node_id] = {"class_type": node_type, "inputs": inputs, "_meta": {"title": title}}
        report["titles"][node_id] = title

    # 出さなかったノードを指すリンクを外す（画面の graphToPrompt と同じ後始末）
    for node_id, item in prompt.items():
        for name, value in list(item["inputs"].items()):
            if isinstance(value, list) and len(value) == 2 and value[0] not in prompt:
                del item["inputs"][name]
                report["warnings"].append(f"{graph.label(node_id)}.{name}: 元 #{value[0]} を出さないので入力を外した")
    report["warnings"].extend(graph.warnings)
    return prompt, report


# ---------------------------------------------------------------- 上書き


def _literal_inputs(prompt: dict[str, Any], node_id: str) -> dict[str, Any]:
    if node_id not in prompt:
        raise WorkflowConversionError(f"ノード #{node_id} は API 形式に無い（bypass / muted / 画面だけのノード？）")
    return prompt[node_id]["inputs"]


def set_literal(prompt: dict[str, Any], node_id: str, input_name: str, value: Any) -> None:
    """リテラルの入力を書き換える。リンクでつながった入力は書き換えない（元のノードを書き換えること）。"""
    inputs = _literal_inputs(prompt, node_id)
    current = inputs.get(input_name)
    if isinstance(current, list):
        raise WorkflowConversionError(f"#{node_id}.{input_name} はリンク {current} でつながっている。元のノードを書き換えること")
    inputs[input_name] = wrap_literal(value)


def override_image(prompt: dict[str, Any], image_name: str) -> list[str]:
    changed = [node_id for node_id, item in prompt.items() if item["class_type"] == "LoadImage"]
    if not changed:
        raise WorkflowConversionError("LoadImage が無い")
    for node_id in changed:
        set_literal(prompt, node_id, "image", image_name)
    return changed


def override_seed(prompt: dict[str, Any], report: dict[str, Any], seed: int) -> list[str]:
    """control_after_generate を持つ入力（seed）を、すべて同じ値に固定する。"""
    changed = []
    for node_id, name in report.get("seed_inputs", []):
        if node_id in prompt and not isinstance(prompt[node_id]["inputs"].get(name), list):
            prompt[node_id]["inputs"][name] = int(seed)
            changed.append(f"{node_id}.{name}")
    if not changed:
        raise WorkflowConversionError("seed の入力が無い")
    return changed


def select_backend(prompt: dict[str, Any], workflow: dict[str, Any], backend: str) -> list[str]:
    """Pixal3D / Trellis.2 の切り替え。題名に Trellis を含む PrimitiveBoolean を、trellis2 なら真にする。"""
    if backend not in BACKENDS:
        raise WorkflowConversionError(f"backend は {BACKENDS} のどれか: {backend}")
    switches = [
        str(node["id"]) for node in workflow.get("nodes") or []
        if node.get("type") == "PrimitiveBoolean" and BACKEND_SWITCH_TITLE_RE.search(node.get("title") or "")
    ]
    if not switches:
        raise WorkflowConversionError("Pixal3D / Trellis.2 を切り替える PrimitiveBoolean（題名に Trellis）が無い")
    for node_id in switches:
        set_literal(prompt, node_id, "value", backend == "trellis2")
    return switches


def override_mesh(prompt: dict[str, Any], mesh_filename: str) -> list[str]:
    changed = [node_id for node_id, item in prompt.items() if item["class_type"] == MESH_ENCODER_TYPE]
    if not changed:
        raise WorkflowConversionError(f"{MESH_ENCODER_TYPE} が無い")
    for node_id in changed:
        set_literal(prompt, node_id, "mesh_filename", mesh_filename)
    return changed


def tag_filename_prefixes(prompt: dict[str, Any], tag: str) -> list[str]:
    """filename_prefix の後ろに _tag を付け、回ごとの出力を見分けられるようにする。"""
    changed = []
    for node_id, item in prompt.items():
        prefix = item["inputs"].get("filename_prefix")
        if isinstance(prefix, str):
            item["inputs"]["filename_prefix"] = f"{prefix}_{tag}"
            changed.append(node_id)
    return changed


def parse_set_argument(text: str) -> tuple[str, str, Any]:
    """--set NODE.INPUT=VALUE を読む。VALUE は JSON として読めなければ文字列のまま。"""
    target, separator, raw_value = text.partition("=")
    node_id, dot, input_name = target.partition(".")
    if not separator or not dot or not node_id or not input_name:
        raise WorkflowConversionError(f"--set は NODE.INPUT=VALUE の形: {text}")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return node_id, input_name, value


def parse_tap_argument(text: str) -> tuple[str, int, str]:
    """--tap NODE[:SLOT]=PREFIX を読む。SLOT の既定は 0。"""
    target, separator, prefix = text.partition("=")
    if not separator or not prefix:
        raise WorkflowConversionError(f"--tap は NODE[:SLOT]=PREFIX の形: {text}")
    node_id, colon, slot_text = target.partition(":")
    return node_id, int(slot_text) if colon else 0, prefix


def add_taps(
    prompt: dict[str, Any], taps: list[tuple[str, int, str]], object_info: dict[str, Any] | None = None
) -> dict[str, str]:
    """途中の MESH を SaveGLB で output/ に書き出すノードを足す。{足した id: 元の id:番号} を返す。

    object_info を渡すと、出力の型が MESH かを確かめる。SaveGLB は ComfyUI の File3D の派生でない 3D ファイル
    （LODTailorBakeForger の _BakedFile3D など）を MESH として扱って AttributeError で止まり、
    その回の残りも実行されなくなるため（2026-10-03 の 02 で起きた）。
    """
    numeric_ids = [int(node_id) for node_id in prompt if node_id.isdigit()]
    next_id = max([TAP_ID_BASE, *numeric_ids]) + 1
    added = {}
    for node_id, slot, prefix in taps:
        if node_id not in prompt:
            raise WorkflowConversionError(f"--tap の #{node_id} は API 形式に無い（bypass / muted？）")
        if object_info is not None:
            outputs = (object_info.get(prompt[node_id]["class_type"]) or {}).get("output") or []
            output_type = outputs[slot] if slot < len(outputs) else None
            if output_type != TAP_OUTPUT_TYPE:
                raise WorkflowConversionError(
                    f"--tap の #{node_id}:{slot} の出力は {output_type}（{TAP_OUTPUT_TYPE} だけ取り出せる）。"
                    "3D ファイルの出力は、そのノードが書いたファイルを直接測ること"
                )
        tap_id = str(next_id)
        next_id += 1
        prompt[tap_id] = {
            "class_type": TAP_NODE_TYPE,
            "inputs": {"mesh": [node_id, slot], "filename_prefix": prefix},
            "_meta": {"title": f"tap #{node_id}:{slot}"},
        }
        added[tap_id] = f"{node_id}:{slot}"
    return added


# ---------------------------------------------------------------- 出力と時間の整理


def collect_output_files(history_entry: dict[str, Any], folders: dict[str, Path]) -> list[dict[str, Any]]:
    """/history の outputs から、filename を持つ項目を絶対パスにして並べる。"""
    files = []
    seen = set()
    for node_id, node_output in (history_entry.get("outputs") or {}).items():
        for key, items in node_output.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or "filename" not in item:
                    continue
                folder_type = item.get("type") or "output"
                base = folders.get(folder_type, folders["output"])
                path = base / (item.get("subfolder") or "") / item["filename"]
                if (node_id, str(path)) in seen:
                    continue
                seen.add((node_id, str(path)))
                exists = path.exists()
                files.append({
                    "node": node_id, "key": key, "type": folder_type, "path": str(path),
                    "exists": exists, "bytes": path.stat().st_size if exists else None,
                })
    return files


def history_status_times(history_entry: dict[str, Any]) -> dict[str, Any]:
    """status.messages の execution_start / 終わりの時刻（ミリ秒）から、サーバー側の所要時間を出す。"""
    status = history_entry.get("status") or {}
    stamps: dict[str, int] = {}
    error = None
    for message in status.get("messages") or []:
        if not isinstance(message, (list, tuple)) or len(message) != 2:
            continue
        event, data = message
        if isinstance(data, dict) and "timestamp" in data:
            stamps[event] = data["timestamp"]
        if event == "execution_error":
            error = {key: data.get(key) for key in ("node_id", "node_type", "exception_type", "exception_message")}
    start = stamps.get("execution_start")
    end = next((stamps[event] for event in ("execution_success", "execution_error", "execution_interrupted") if event in stamps), None)
    return {
        "status_str": status.get("status_str"),
        "completed": status.get("completed"),
        "server_seconds": (end - start) / 1000.0 if start is not None and end is not None else None,
        "error": error,
    }


class NodeTimeline:
    """WebSocket の executing の切り替わりから、ノードごとの所要時間を積み上げる。"""

    def __init__(self) -> None:
        self.current: str | None = None
        self.current_start: float | None = None
        self.intervals: list[tuple[str, float, float]] = []
        self.cached: list[str] = []

    def on_executing(self, node_id: str | None, now: float) -> None:
        if self.current is not None and self.current_start is not None:
            self.intervals.append((self.current, self.current_start, now))
        self.current = node_id
        self.current_start = now if node_id is not None else None

    def close(self, now: float) -> None:
        self.on_executing(None, now)

    def totals(self) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for node_id, start, end in self.intervals:
            entry = result.setdefault(node_id, {"seconds": 0.0, "first_start": start, "last_end": end})
            entry["seconds"] += end - start
            entry["first_start"] = min(entry["first_start"], start)
            entry["last_end"] = max(entry["last_end"], end)
        return result


# ---------------------------------------------------------------- サーバーとのやりとり


def http_json(url: str, payload: Any = None, timeout: float = 60.0) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"http_status": error.code, "body": body.decode("utf-8", "replace")[:2000]}
        raise PromptRejected(parsed) from error
    return json.loads(body) if body else None


def fetch_object_info(server: str) -> dict[str, Any]:
    return http_json(f"{server}/object_info", timeout=120.0)


def upload_image(server: str, path: Path) -> str:
    """input/ に無い画像を /upload/image で送る（multipart を標準ライブラリで組む）。サーバー上の名前を返す。"""
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"{server}/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(request, timeout=120.0) as response:
        result = json.loads(response.read())
    return f"{result['subfolder']}/{result['name']}" if result.get("subfolder") else result["name"]


def interrupt(server: str) -> None:
    try:
        http_json(f"{server}/interrupt", payload={}, timeout=10.0)
    except (OSError, PromptRejected):
        pass


FREE_SETTLE_SECONDS = 5.0


def free_memory(server: str, settle_seconds: float = FREE_SETTLE_SECONDS) -> None:
    """POST /free でモデルを降ろし、実行結果のキャッシュも捨てる（main.py の prompt_worker が e.reset() する）。

    ComfyUI は前の回と同じ入力のノードの結果をキャッシュから使うので、回ごとの時間と RAM をそろえて測るときに使う。
    フラグは待ち行列が空のときにすぐ処理されるが、終わった合図は無いので少し待つ。
    """
    http_json(f"{server}/free", payload={"unload_models": True, "free_memory": True}, timeout=30.0)
    time.sleep(settle_seconds)


def wait_history(server: str, prompt_id: str, timeout: float, poll_seconds: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        history = http_json(f"{server}/history/{prompt_id}")
        entry = (history or {}).get(prompt_id)
        status = (entry or {}).get("status") or {}
        if entry and status.get("completed") is not None and (
            status.get("status_str") in ("success", "error") or entry.get("outputs")
        ):
            return entry
        if time.monotonic() > deadline:
            raise TimeoutError(f"{timeout} 秒たっても終わらない: {prompt_id}")
        time.sleep(poll_seconds)


async def _run_with_websocket(
    server: str, payload: dict[str, Any], timeout: float, events_path: Path | None, timeline: NodeTimeline
) -> str:
    """WebSocket で進行を受けながら投入し、終わりの通知まで待つ。prompt_id を返す。"""
    import aiohttp

    ws_url = server.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + f"/ws?clientId={payload['client_id']}"
    events_file = events_path.open("a", encoding="utf-8") if events_path else None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None)) as session, \
                session.ws_connect(ws_url, heartbeat=30, max_msg_size=0) as ws:
            async with session.post(f"{server}/prompt", json=payload) as response:
                body = await response.json(content_type=None)
                if response.status != 200 or "prompt_id" not in body:
                    raise PromptRejected(body)
            prompt_id = body["prompt_id"]
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{timeout} 秒たっても終わらない: {prompt_id}")
                try:
                    message = await ws.receive(timeout=min(remaining, 60.0))
                except asyncio.TimeoutError:
                    continue
                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    # 切れたら /history を見る方に切り替える（ノードごとの時間はここで途切れる）
                    timeline.close(time.time())
                    return prompt_id
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                now = time.time()
                event = json.loads(message.data)
                event_type = event.get("type")
                data = event.get("data") or {}
                if events_file and event_type not in ("progress_state",):
                    events_file.write(json.dumps({"t": now, **event}, ensure_ascii=False) + "\n")
                    events_file.flush()
                if data.get("prompt_id") not in (None, prompt_id):
                    continue
                if event_type == "executing":
                    node = data.get("node")
                    timeline.on_executing(None if node is None else str(node), now)
                    if node is None and data.get("prompt_id") == prompt_id:
                        return prompt_id
                elif event_type == "execution_cached":
                    timeline.cached.extend(str(node) for node in data.get("nodes") or [])
                elif event_type in ("execution_success", "execution_error", "execution_interrupted"):
                    timeline.close(now)
                    return prompt_id
    finally:
        if events_file:
            events_file.close()


def submit_and_wait(
    server: str, prompt: dict[str, Any], workflow: dict[str, Any] | None, timeout: float,
    events_path: Path | None, timeline: NodeTimeline,
) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {"prompt": prompt, "client_id": uuid.uuid4().hex}
    if workflow is not None:
        # 画面から投入したときと同じく、出力の metadata にワークフローを入れる
        payload["extra_data"] = {"extra_pnginfo": {"workflow": workflow}}
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        body = http_json(f"{server}/prompt", payload=payload)
        prompt_id = body["prompt_id"]
    else:
        prompt_id = asyncio.run(_run_with_websocket(server, payload, timeout, events_path, timeline))
    return prompt_id, wait_history(server, prompt_id, timeout)


# ---------------------------------------------------------------- CLI


def build_prompt(args: argparse.Namespace, workflow: dict[str, Any], object_info: dict[str, Any], server: str | None):
    prompt, report = convert_workflow(workflow, object_info)
    overrides: dict[str, Any] = {}
    if args.image:
        image_path = Path(args.image)
        image_name = args.image
        if image_path.is_file() and image_path.resolve().parent != (config.INPUT_DIR).resolve():
            if server is None:
                raise WorkflowConversionError("input/ に無い画像は run（サーバーへ送る）でしか使えない")
            image_name = upload_image(server, image_path)
        elif image_path.is_file():
            image_name = image_path.name
        overrides["image"] = {"value": image_name, "nodes": override_image(prompt, image_name)}
    if args.seed is not None:
        overrides["seed"] = {"value": args.seed, "inputs": override_seed(prompt, report, args.seed)}
    if args.backend:
        overrides["backend"] = {"value": args.backend, "nodes": select_backend(prompt, workflow, args.backend)}
    if args.mesh:
        overrides["mesh"] = {"value": args.mesh, "nodes": override_mesh(prompt, args.mesh)}
    for text in args.set or []:
        node_id, input_name, value = parse_set_argument(text)
        set_literal(prompt, node_id, input_name, value)
        overrides.setdefault("set", []).append({"node": node_id, "input": input_name, "value": value})
    if getattr(args, "tag", None):
        overrides["tag"] = {"value": args.tag, "nodes": tag_filename_prefixes(prompt, args.tag)}
    taps = [parse_tap_argument(text) for text in getattr(args, "tap", None) or []]
    if taps:
        overrides["taps"] = add_taps(prompt, taps, object_info)
    # 報告用に、seed の実際の値を控える（API から投入すると randomize は効かず、この値で固定になる）
    report["seed_values"] = {
        f"{node_id}.{name}": prompt[node_id]["inputs"].get(name)
        for node_id, name in report["seed_inputs"] if node_id in prompt
    }
    return prompt, report, overrides


def load_object_info(args: argparse.Namespace) -> dict[str, Any]:
    if args.object_info:
        return json.loads(Path(args.object_info).read_text(encoding="utf-8"))
    return fetch_object_info(args.server)


def cmd_convert(args: argparse.Namespace) -> int:
    workflow = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    object_info = load_object_info(args)
    prompt, report, overrides = build_prompt(args, workflow, object_info, None)
    text = json.dumps(prompt, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    summary = {key: report[key] for key in ("notes", "frontend_only", "muted", "bypassed", "warnings", "seed_values")}
    print(json.dumps({"nodes": len(prompt), "overrides": overrides, **summary}, ensure_ascii=False), file=sys.stderr)
    return 0


def _comfy_main_pid() -> int | None:
    import subprocess

    try:
        output = subprocess.run(
            ["systemctl", "--user", "show", config.SERVICE_NAME, "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(output) if output.isdigit() and int(output) > 0 else None


def cmd_run(args: argparse.Namespace) -> int:
    workflow_path = Path(args.workflow)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    tag = args.tag or time.strftime("%Y%m%d_%H%M%S")
    args.tag = tag
    run_dir = Path(args.run_dir) if args.run_dir else config.COMFYUI_DIR / "output" / RUNS_SUBDIR / tag
    run_dir.mkdir(parents=True, exist_ok=True)

    object_info = load_object_info(args)
    prompt, report, overrides = build_prompt(args, workflow, object_info, args.server)
    (run_dir / "api_prompt.json").write_text(json.dumps(prompt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.free_before:
        free_memory(args.server)

    monitor = None
    if args.monitor:
        from resource_monitor import ResourceMonitor, default_cgroup_dir

        main_pid = _comfy_main_pid()
        guard_bytes = int(args.guard_mem_gib * 1024**3) if args.guard_mem_gib else None

        def on_guard(reason: str) -> None:
            # RAM の歯止め: まず ComfyUI に中断を頼み、子プロセス（WTiVo / Blender）も止める
            interrupt(args.server)
            if monitor is not None:
                monitor.terminate_children(main_pid)

        monitor = ResourceMonitor(
            cgroup_dir=default_cgroup_dir(), main_pid=main_pid, interval=args.monitor_interval,
            csv_path=run_dir / "resources.csv", guard_bytes=guard_bytes, on_guard=on_guard,
        )
        monitor.start()

    timeline = NodeTimeline()
    started = time.time()
    result: dict[str, Any] = {
        "workflow": str(workflow_path), "tag": tag, "run_dir": str(run_dir), "server": args.server,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "overrides": overrides,
        "free_before": bool(args.free_before),
        "conversion": {key: report[key] for key in ("notes", "frontend_only", "muted", "bypassed", "warnings", "seed_values")},
    }
    exit_code = 0
    try:
        prompt_id, entry = submit_and_wait(
            args.server, prompt, None if args.no_workflow_metadata else workflow, args.timeout,
            run_dir / "events.jsonl", timeline,
        )
        result["prompt_id"] = prompt_id
        result["history"] = history_status_times(entry)
        folders = {
            "output": config.COMFYUI_DIR / "output", "temp": config.COMFYUI_DIR / "temp", "input": config.INPUT_DIR,
        }
        result["outputs"] = collect_output_files(entry, folders)
        if result["history"]["status_str"] != "success":
            exit_code = 1
    except PromptRejected as error:
        result["rejected"] = error.body
        exit_code = 2
    except TimeoutError as error:
        result["timeout"] = str(error)
        interrupt(args.server)
        exit_code = 3
    finally:
        finished = time.time()
        result["wall_seconds"] = round(finished - started, 2)
        if monitor is not None:
            monitor.stop()
            result["resources"] = monitor.summary()
            result["guard_triggered"] = monitor.guard_reason
        totals = timeline.totals()
        node_rows = []
        for node_id, entry_times in sorted(totals.items(), key=lambda item: item[1]["first_start"]):
            row = {
                "node": node_id, "class_type": prompt.get(node_id, {}).get("class_type"),
                "title": prompt.get(node_id, {}).get("_meta", {}).get("title"),
                "seconds": round(entry_times["seconds"], 2),
                "start_offset": round(entry_times["first_start"] - started, 2),
            }
            if monitor is not None:
                row.update(monitor.peaks_between(entry_times["first_start"], entry_times["last_end"]))
            node_rows.append(row)
        result["node_timings"] = node_rows
        result["cached_nodes"] = timeline.cached
        (run_dir / "run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in (
        "tag", "prompt_id", "wall_seconds", "history", "rejected", "timeout", "guard_triggered", "run_dir",
    )}, ensure_ascii=False))
    return exit_code


def add_override_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--image", help="LoadImage の画像。input/ の名前か、ファイルのパス（input/ の外なら送る）")
    parser.add_argument("--seed", type=int, help="seed（control_after_generate を持つ入力）をすべてこの値にする")
    parser.add_argument("--backend", choices=BACKENDS, help="Pixal3D / Trellis.2 の切り替え（PrimitiveBoolean）")
    parser.add_argument("--mesh", help=f"{MESH_ENCODER_TYPE} の mesh_filename（03 用。input/ の名前か絶対パス）")
    parser.add_argument("--set", action="append", metavar="NODE.INPUT=VALUE", help="任意の入力の値（VALUE は JSON）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UI 形式のワークフローを API 形式に変えて ComfyUI で実行する")
    parser.add_argument("--server", default=os.environ.get("COMFYUI_SERVER", DEFAULT_SERVER))
    parser.add_argument("--object-info", help="/object_info の JSON ファイル（無ければサーバーから取る）")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="API 形式に変えて出す（投入しない）")
    convert.add_argument("workflow")
    convert.add_argument("-o", "--output")
    add_override_arguments(convert)
    convert.set_defaults(func=cmd_convert)

    run = sub.add_parser("run", help="変えて投入し、終わるまで待つ")
    run.add_argument("workflow")
    add_override_arguments(run)
    run.add_argument("--tag", help="回の名前（filename_prefix の後ろと記録のフォルダ名に使う）")
    run.add_argument("--tap", action="append", metavar="NODE[:SLOT]=PREFIX", help="途中の MESH を SaveGLB で書き出す")
    run.add_argument("--run-dir", help=f"記録の置き場（既定 output/{RUNS_SUBDIR}/<tag>）")
    run.add_argument("--timeout", type=float, default=4 * 3600.0)
    run.add_argument("--monitor", action="store_true", help="RAM（cgroup）・VRAM・swap を 1 秒ごとに記録する")
    run.add_argument("--monitor-interval", type=float, default=1.0)
    run.add_argument("--guard-mem-gib", type=float, default=0.0,
                     help="cgroup の anon + swap がこれを超えたら中断する（0 で無効）")
    run.add_argument("--no-workflow-metadata", action="store_true", help="extra_pnginfo にワークフローを入れない")
    run.add_argument("--free-before", action="store_true",
                     help="投入の前に /free でモデルとキャッシュを捨てる（前の回の結果を使わずに測る）")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except WorkflowConversionError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
