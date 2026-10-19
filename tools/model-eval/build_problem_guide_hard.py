#!/usr/bin/env python3
"""2026-10-18 の評価で出した 9 問（難しいコーディング 6 問・数学 3 問）の「出題内容の解説書」を、1 ファイルで完結する HTML にする。

  build_problem_guide_hard.py                       # suites/problem_guide_hard.json と results/2026-10-18/summary.json
                                                    #   → Documents/AIモデル評価_出題内容_2026-10-18.html
  build_problem_guide_hard.py --out work/guide.html # 出力先を変える（--summary と --guide も変えられる）

入力:
- suites/problem_guide_hard.json: 問題ごとの解説（やること・具体例・難しさ・採点の仕方・用語）。手で書く。
- 各問題の原文: suites/coding_v3/<問>/prompt.md と tests.py、suites/math/<問>/prompt.md と answer.json（原文は折りたたんで載せる）。
- results/2026-10-18/summary.json: モデルごと・問題ごとの点（「この問題の結果」の色つきのマス）。
- results/2026-10-18/frozen.json: 採点の改定の記録（4 節の表）。

解説の本文と原文が食い違っていないかは、読み込みのときに検査する（具体例の文字列が問題文にあること、隠しテストの件数、
数学の小問が answer.json と同じこと）。食い違いがあれば HTML を作らずに一覧を出して終了コード 1 で止まる。
数学の正解の式と値は answer.json からそのまま載せる（解説の本文には書かない）。HTML は手で書き換えない。

見た目・色・点のマスの色づけは build_report.py と build_problem_guide.py（2026-10-08 の解説書）の部品を使う。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from build_problem_guide import EXTRA_STYLE, SURFACE, bullet_list, terms_block  # noqa: E402
from build_report import (  # noqa: E402
    COLOR_NA, STYLE, _ink_on, _mix, cell_fill, cell_texts, cell_tip, esc, fmt_pct, grade_legend,
)
from evallib import common  # noqa: E402

DATE = "2026-10-18"
GUIDE_PATH = common.SUITES_DIR / "problem_guide_hard.json"
DEFAULT_SUMMARY = common.RESULTS_ROOT / DATE / "summary.json"
DEFAULT_OUT = common.REPO_DIR / "Documents" / f"AIモデル評価_出題内容_{DATE}.html"
REPORT_NAME = f"AIモデル評価_{DATE}.html"

# 種類の色。2026-10-08 の解説書と同じ色（コーディングは青、数学は 3D 数学と同じオレンジ）。種類の名前も必ず文字で出す
CATEGORY_COLORS = {"coding_v3": "#2a78d6", "math": "#eb6834"}
CATEGORY_ORDER = tuple(CATEGORY_COLORS)
CATEGORY_ITEMS = {"coding_v3": common.CODING_V3_ITEMS, "math": common.MATH_ITEMS}
EXPECTED_IDS = common.CODING_V3_ITEMS + common.MATH_ITEMS
REQUIRED_KEYS = ("id", "title", "category", "one_line", "task", "difficulty", "measures", "grading", "terms")
CODING_KEYS = ("example",)
MATH_KEYS = ("situation", "parts")
# 図の色
INK = "#3b3a37"
INK_SOFT = "#76756f"

STYLE_HARD = """
.parts td.formula{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;font-size:.85rem;overflow-wrap:anywhere}
.figures{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start}
.fig-caption{font-size:.82rem;color:var(--text-secondary);margin:2px 0 8px}
.result-note{margin:6px 0;padding:8px 12px;border-left:4px solid var(--cat);background:var(--surface-2);border-radius:0 6px 6px 0}
.summary-lines{margin:4px 0 8px;padding-left:20px;font-size:.9rem}
.run-sub{font-size:.7rem;font-weight:600}
table.amend td{vertical-align:top;font-size:.88rem}
"""


# ------------------------------------------------------------------------------------------------ 原文と検査


def prompt_path(problem_id: str) -> Path:
    return common.item_dir(category_of(problem_id), problem_id) / "prompt.md"


def category_of(problem_id: str) -> str:
    for category, items in CATEGORY_ITEMS.items():
        if problem_id in items:
            return category
    raise ValueError(f"unknown item: {problem_id}")


def count_hidden_cases(problem_id: str) -> int:
    text = (common.item_dir("coding_v3", problem_id) / "tests.py").read_text(encoding="utf-8")
    return len(re.findall(r"^def case_", text, flags=re.MULTILINE))


def math_answer(problem_id: str) -> dict[str, Any]:
    return common.read_json(common.item_dir("math", problem_id) / "answer.json")


def validate_guide(guide: dict[str, Any]) -> list[str]:
    """解説（problem_guide_hard.json）が原文と食い違っていないかの検査。問題の一覧を返す（空なら問題なし）。"""

    errors: list[str] = []
    for category in CATEGORY_ORDER:
        if not ((guide.get("categories") or {}).get(category) or {}).get("label"):
            errors.append(f"categories.{category}.label が無い")
    problems = guide.get("problems") or []
    ids = [problem.get("id") for problem in problems]
    if ids != list(EXPECTED_IDS):
        errors.append(f"問題の ID と順序が違う: {ids}（期待 {list(EXPECTED_IDS)}）")
    for problem in problems:
        item = problem.get("id", "?")
        if item not in EXPECTED_IDS:
            continue
        category = category_of(item)
        for key in REQUIRED_KEYS + (CODING_KEYS if category == "coding_v3" else MATH_KEYS):
            if not problem.get(key):
                errors.append(f"{item}: 必須の鍵 {key} が無い（または空）")
        if problem.get("category") != category:
            errors.append(f"{item}: category が {problem.get('category')}（期待 {category}）")
        if not (problem.get("grading") or {}).get("summary"):
            errors.append(f"{item}: grading.summary が無い")
        if category == "coding_v3":
            text = prompt_path(item).read_text(encoding="utf-8")
            for number, example in enumerate(problem.get("example") or [], start=1):
                for key in ("input", "output"):
                    if example.get(key) not in text:
                        errors.append(f"{item}: 具体例 {number} の {key} が問題文に無い: {example.get(key)!r}")
            actual = count_hidden_cases(item)
            grading = problem.get("grading") or {}
            listed = sum(entry["n"] for entry in grading.get("cases") or [])
            if grading.get("case_total") != actual:
                errors.append(f"{item}: case_total {grading.get('case_total')} が tests.py の case_ の数 {actual} と違う")
            if listed != actual:
                errors.append(f"{item}: cases の n の合計 {listed} が tests.py の case_ の数 {actual} と違う")
        else:
            keys = [part.get("key") for part in problem.get("parts") or []]
            expected = [part["key"] for part in math_answer(item)["parts"]]
            if keys != expected:
                errors.append(f"{item}: parts の鍵 {keys} が answer.json の {expected} と違う")
            text = prompt_path(item).read_text(encoding="utf-8")
            for key in keys:
                if f"({key})" not in text:
                    errors.append(f"{item}: 小問 ({key}) が問題文に無い")
    return errors


# ------------------------------------------------------------------------------------------------ 図（SVG）


def svg_open(width: int, height: int, label: str) -> str:
    return (f'<svg class="figure" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
            f'aria-label="{esc(label)}">')


def offset_triangle_svg() -> str:
    """M1 の考え方を 2 次元で描く。1 辺 1 の正三角形と、それを r = 0.6 だけ太らせた図形（角は半径 r の円弧）。"""

    scale, radius = 120.0, 0.6 * 120.0
    height = math.sqrt(3) / 2 * scale
    top = (165.0, 95.0)
    right = (top[0] + scale / 2, top[1] + height)
    left = (top[0] - scale / 2, top[1] + height)
    vertices = [top, right, left]  # 画面で時計回り
    center = (sum(point[0] for point in vertices) / 3, sum(point[1] for point in vertices) / 3)

    def normal(first, second):
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        nx, ny = dy / length, -dx / length
        middle = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
        if (middle[0] - center[0]) * nx + (middle[1] - center[1]) * ny < 0:
            nx, ny = -nx, -ny
        return nx, ny

    normals = [normal(vertices[index], vertices[(index + 1) % 3]) for index in range(3)]
    path = []
    for index in range(3):
        start, end = vertices[index], vertices[(index + 1) % 3]
        nx, ny = normals[index]
        first = (start[0] + nx * radius, start[1] + ny * radius)
        second = (end[0] + nx * radius, end[1] + ny * radius)
        if not path:
            path.append(f"M{first[0]:.1f},{first[1]:.1f}")
        path.append(f"L{second[0]:.1f},{second[1]:.1f}")
        next_nx, next_ny = normals[(index + 1) % 3]
        arc_end = (end[0] + next_nx * radius, end[1] + next_ny * radius)
        path.append(f"A{radius:.1f},{radius:.1f} 0 0 1 {arc_end[0]:.1f},{arc_end[1]:.1f}")
    triangle = " ".join(f"{x:.1f},{y:.1f}" for x, y in vertices)
    parts = [svg_open(330, 300, "1 辺 1 の正三角形と、そこから距離 0.6 以内の点が作る、角の丸い三角形の図形"),
             f'<path d="{" ".join(path)}Z" fill="{_mix(SURFACE, CATEGORY_COLORS["math"], 0.25)}" stroke="{INK}" stroke-width="1.5"/>',
             f'<polygon points="{triangle}" fill="{_mix(SURFACE, CATEGORY_COLORS["math"], 0.7)}" stroke="{INK}" stroke-width="1.5"/>']
    # r の矢印（下の辺から外へ）
    bottom_mid = ((right[0] + left[0]) / 2, right[1])
    parts.append(f'<line x1="{bottom_mid[0]:.1f}" y1="{bottom_mid[1]:.1f}" x2="{bottom_mid[0]:.1f}" y2="{bottom_mid[1] + radius:.1f}" '
                 f'stroke="{INK}" stroke-width="1.2" stroke-dasharray="4 3"/>')
    parts.append(f'<text x="{bottom_mid[0] + 6:.1f}" y="{bottom_mid[1] + radius / 2 + 4:.1f}">r = 0.6</text>')
    parts.append(f'<text x="{center[0]:.1f}" y="{center[1] + 18:.1f}" text-anchor="middle">T</text>')
    parts.append(f'<text class="sub-text" x="{top[0] + 70:.1f}" y="{top[1] - 50:.1f}">角は半径 r の円弧</text>')
    parts.append("</svg>")
    return "".join(parts)


def capsules_svg() -> str:
    """M2 の z = 0 の断面。V1（OA のまわり）を塗り、V2（AB のまわり）を点線で重ね、V2 の中は塗らない（W = V1 \\ V2）。"""

    scale, radius = 110.0, 0.6 * 110.0
    origin = (85.0, 215.0)  # 画面の (0, 0)

    def screen(x, y):
        return origin[0] + x * scale, origin[1] - y * scale

    point_o, point_a, point_b = screen(0, 0), screen(1, 0), screen(1, 1)

    def capsule(first, second):
        # 2 点を結ぶ線分のまわりの半径 radius の帯（両端は半円）
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        nx, ny = -dy / length * radius, dx / length * radius
        return (f"M{first[0] + nx:.1f},{first[1] + ny:.1f} L{second[0] + nx:.1f},{second[1] + ny:.1f} "
                f"A{radius:.1f},{radius:.1f} 0 0 0 {second[0] - nx:.1f},{second[1] - ny:.1f} "
                f"L{first[0] - nx:.1f},{first[1] - ny:.1f} A{radius:.1f},{radius:.1f} 0 0 0 {first[0] + nx:.1f},{first[1] + ny:.1f}Z")

    parts = [svg_open(330, 318, "高さ 0 での断面。線分 OA のまわりの帯から、線分 AB のまわりの帯と重なる部分を除いた図形"),
             f'<path d="{capsule(point_o, point_a)}" fill="{_mix(SURFACE, CATEGORY_COLORS["math"], 0.45)}" stroke="{INK}" '
             'stroke-width="1.5"/>',
             f'<path d="{capsule(point_a, point_b)}" fill="{SURFACE}" stroke="{INK}" stroke-width="1.5" stroke-dasharray="6 4"/>']
    for first, second in ((point_o, point_a), (point_a, point_b)):
        parts.append(f'<line x1="{first[0]:.1f}" y1="{first[1]:.1f}" x2="{second[0]:.1f}" y2="{second[1]:.1f}" stroke="{INK}" '
                     'stroke-width="4" stroke-linecap="round"/>')
    for name, point, dx, dy, anchor in (("O", point_o, -8, 18, "end"), ("A", point_a, 8, 18, "start"),
                                         ("B", point_b, 8, -6, "start")):
        parts.append(f'<circle cx="{point[0]:.1f}" cy="{point[1]:.1f}" r="4.5" fill="#0b0b0b"/>')
        parts.append(f'<text x="{point[0] + dx:.1f}" y="{point[1] + dy:.1f}" text-anchor="{anchor}">{name}</text>')
    parts.append(f'<text x="{point_o[0] + 8:.1f}" y="{point_o[1] - 26:.1f}">W</text>')
    parts.append(f'<text class="sub-text" x="{point_b[0] - 40:.1f}" y="{point_b[1] - radius - 6:.1f}">V2（点線。中は取り除く）</text>')
    parts.append('<text class="sub-text" x="12" y="310">x → 右、y → 上。半径 r = 0.6</text>')
    parts.append("</svg>")
    return "".join(parts)


def cube_section_svg(d_text: str, d_value: float) -> str:
    """M3 の真ん中の高さでの断面。面から d 以内の帯のうち、内接球の外の部分を塗る。"""

    size, pad = 120.0, 14.0
    band = d_value * size
    color = _mix(SURFACE, CATEGORY_COLORS["math"], 0.6)
    outer = f"M{pad},{pad} h{size} v{size} h{-size} Z"
    inner = f"M{pad + band},{pad + band} v{size - 2 * band} h{size - 2 * band} v{-(size - 2 * band)} Z"
    center = pad + size / 2
    parts = [svg_open(int(size + 2 * pad), int(size + 2 * pad + 22),
                      f"立方体の真ん中の断面。d = {d_text} のとき、面から d 以内で、内接球の外にある部分"),
             f'<path d="{outer} {inner}" fill="{color}" fill-rule="evenodd"/>',
             f'<circle cx="{center}" cy="{center}" r="{size / 2}" fill="{SURFACE}"/>',
             f'<rect x="{pad}" y="{pad}" width="{size}" height="{size}" fill="none" stroke="{INK}" stroke-width="1.5"/>',
             f'<path d="{inner}" fill="none" stroke="{INK_SOFT}" stroke-width="1" stroke-dasharray="2 3"/>',
             f'<circle cx="{center}" cy="{center}" r="{size / 2}" fill="none" stroke="{INK}" stroke-width="1.2" stroke-dasharray="5 4"/>',
             f'<text x="{center}" y="{size + 2 * pad + 16}" text-anchor="middle">d = {esc(d_text)}</text>',
             "</svg>"]
    return "".join(parts)


# 2 × 3 の盤面の 5 通りの敷き詰め。駒ごとのマス（行, 列）
TILINGS_2X3 = (
    (((0, 0), (1, 0)), ((0, 1), (1, 1)), ((0, 2), (1, 2))),
    (((0, 0), (1, 0)), ((0, 1), (0, 2)), ((1, 1), (1, 2))),
    (((0, 0), (0, 1)), ((1, 0), (1, 1)), ((0, 2), (1, 2))),
    (((0, 0), (0, 1), (1, 0)), ((1, 1), (1, 2), (0, 2))),
    (((0, 0), (1, 0), (1, 1)), ((0, 1), (0, 2), (1, 2))),
)


def tilings_svg() -> str:
    """H6 の例 ["...", "..."] の 5 通りの敷き詰め（ドミノだけ 3 通り、L トロミノ 2 つで 2 通り）。"""

    cell, gap, pad = 26.0, 22.0, 10.0
    shades = (_mix(SURFACE, CATEGORY_COLORS["coding_v3"], 0.25), _mix(SURFACE, CATEGORY_COLORS["coding_v3"], 0.55),
              _mix(SURFACE, CATEGORY_COLORS["coding_v3"], 0.85))
    width = pad * 2 + len(TILINGS_2X3) * 3 * cell + (len(TILINGS_2X3) - 1) * gap
    parts = [svg_open(int(width), int(pad * 2 + 2 * cell + 20), "2 行 3 列の盤面を、ドミノと L トロミノで敷き詰める 5 通りの方法")]
    for index, tiling in enumerate(TILINGS_2X3):
        left = pad + index * (3 * cell + gap)
        owner = {square: piece for piece, squares in enumerate(tiling) for square in squares}
        for (row, column), piece in owner.items():
            fill = shades[piece % len(shades)]
            parts.append(f'<rect x="{left + column * cell:.1f}" y="{pad + row * cell:.1f}" width="{cell}" height="{cell}" '
                         f'fill="{fill}"/>')
        # 駒の境目を太く、同じ駒の中は細く描く
        for row in range(2):
            for column in range(3):
                x, y = left + column * cell, pad + row * cell
                if column < 2:
                    thick = owner[(row, column)] != owner[(row, column + 1)]
                    parts.append(f'<line x1="{x + cell:.1f}" y1="{y:.1f}" x2="{x + cell:.1f}" y2="{y + cell:.1f}" stroke="{INK}" '
                                 f'stroke-width="{2.5 if thick else 0.5}"/>')
                if row < 1:
                    thick = owner[(row, column)] != owner[(row + 1, column)]
                    parts.append(f'<line x1="{x:.1f}" y1="{y + cell:.1f}" x2="{x + cell:.1f}" y2="{y + cell:.1f}" stroke="{INK}" '
                                 f'stroke-width="{2.5 if thick else 0.5}"/>')
        parts.append(f'<rect x="{left:.1f}" y="{pad:.1f}" width="{3 * cell}" height="{2 * cell}" fill="none" stroke="{INK}" '
                     'stroke-width="2.5"/>')
        kind = "ドミノ" if all(len(piece) == 2 for piece in tiling) else "L 字"
        parts.append(f'<text class="sub-text" x="{left + 1.5 * cell:.1f}" y="{pad + 2 * cell + 16:.1f}" text-anchor="middle">'
                     f'{index + 1}（{kind}）</text>')
    parts.append("</svg>")
    return "".join(parts)


FIGURES = {
    "m1": lambda: offset_triangle_svg(),
    "m2": lambda: capsules_svg(),
    "m3": lambda: ('<div class="figures">' + "".join(cube_section_svg(text, value) for text, value in
                                                      (("1/4", 0.25), ("1/10", 0.1), ("3/20", 0.15))) + "</div>"),
}


# ------------------------------------------------------------------------------------------------ 結果のマス


def is_claude(model: dict[str, Any]) -> bool:
    return model.get("backend") == "claude"


def short_pct(score: float) -> str:
    return f"{score * 100:.0f}"


def model_cell(summary: dict[str, Any], problem: dict[str, Any], model: dict[str, Any]) -> dict[str, Any] | None:
    suite = summary["suites"].get(problem["category"]) or {}
    return (((suite.get("models") or {}).get(model["key"]) or {}).get("items") or {}).get(problem["id"])


def results_grid(summary: dict[str, Any], problem: dict[str, Any]) -> str:
    boxes = []
    for model in summary["models"]:
        cell = model_cell(summary, problem, model)
        if cell is None:
            fill, main, sub, tip = COLOR_NA, "記録なし", "", f"記録なし\n{model['label']} / {problem['id']}"
        elif is_claude(model) and cell.get("run_details"):
            fill = cell_fill(cell)
            details = cell["run_details"]
            main = fmt_pct(cell.get("score"))
            sub = "3 回: " + "・".join(short_pct(detail["score"]) for detail in details) if len(details) == 3 else \
                f"{len(details)} 回: " + "・".join(short_pct(detail["score"]) for detail in details)
            lines = [f"{model['label']} / {problem['id'].upper()}（{len(details)} 回の平均 {main}）"]
            for detail in details:
                failed = "、".join(detail.get("failed_cases") or [])
                lines.append(f"{detail['run']} 回目: {fmt_pct(detail['score'])}" + (f"（落ちたケース: {failed}）" if failed else ""))
            tip = "\n".join(lines)
        else:
            fill = cell_fill(cell)
            main, sub = cell_texts(cell)
            tip = cell_tip(cell, model["label"], problem["id"].upper())
        ink = _ink_on(fill)
        sub_html = f'<span class="res-sub">{esc(sub)}</span>' if sub else ""
        boxes.append(f'<div class="res" role="listitem" title="{esc(tip)}">'
                     f'<div class="res-cell" style="background:{fill};color:{ink}"><span class="res-main">{esc(main)}</span>'
                     f'{sub_html}</div><div class="res-name">{esc(model["label"])}</div></div>')
    return f'<div class="results" role="list" aria-label="モデルごとの結果">{"".join(boxes)}</div>'


def results_summary(summary: dict[str, Any], problem: dict[str, Any]) -> str:
    """結果のまとめの文（記録から作る）。Claude は回ごと、ローカルはモデルごと。"""

    claude_runs, claude_misses = 0, []
    local = {"full": [], "partial": [], "zero": []}
    for model in summary["models"]:
        cell = model_cell(summary, problem, model)
        if cell is None:
            continue
        if is_claude(model):
            for detail in cell.get("run_details") or []:
                claude_runs += 1
                if detail["score"] < 1.0:
                    claude_misses.append(f"{model['label']} の {detail['run']} 回目 {fmt_pct(detail['score'])}")
        else:
            score = float(cell.get("score") or 0.0) if cell.get("cell") == "scored" else 0.0
            key = "full" if score >= 1.0 else "partial" if score > 0 else "zero"
            local[key].append(model["label"] + (f" {fmt_pct(score)}" if key == "partial" else ""))
    lines = []
    if claude_runs:
        line = f"Claude: {claude_runs} 回中 {claude_runs - len(claude_misses)} 回が満点。"
        if claude_misses:
            line += "満点でなかった回: " + "、".join(claude_misses) + "。"
        lines.append(line)
    pieces = [f"{name} {len(local[key])}（{'、'.join(local[key])}）" for key, name in
              (("full", "満点"), ("partial", "部分点"), ("zero", "0 点・答えなし")) if local[key]]
    if pieces:
        lines.append("ローカル: " + "。".join(pieces) + "。")
    return '<ul class="summary-lines">' + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>"


# ------------------------------------------------------------------------------------------------ カード


def chip(guide: dict[str, Any], category: str) -> str:
    return (f'<span class="chip-cat cat-{category}"><i class="dot"></i>'
            f'{esc(guide["categories"][category]["label"])}</span>')


def heading_text(problem: dict[str, Any]) -> str:
    return f"{problem['id'].upper()} {problem['title']}"


def example_block(problem: dict[str, Any]) -> str:
    parts = []
    for example in problem["example"]:
        parts.append(f'<div class="example"><div><div class="ex-label">入力</div><pre>{esc(example["input"])}</pre></div>'
                     '<div class="ex-arrow" aria-hidden="true">→</div>'
                     f'<div><div class="ex-label">期待する答え</div><pre>{esc(example["output"])}</pre></div></div>')
        if example.get("note"):
            parts.append(f'<p class="ex-note">{esc(example["note"])}</p>')
    return "".join(parts)


def parts_table(problem: dict[str, Any]) -> str:
    answer = {part["key"]: part for part in math_answer(problem["id"])["parts"]}
    rows = "".join(f'<tr><td class="strong">({esc(part["key"])})</td><td>{esc(part["ask"])}</td>'
                   f'<td class="formula">{esc(answer[part["key"]]["formula"])}</td>'
                   f'<td class="num">{answer[part["key"]]["value"]:.7g}</td></tr>' for part in problem["parts"])
    return ('<table class="data parts"><thead><tr><th>小問</th><th>何を答えるか</th><th>正解の式</th><th>正解の値</th></tr></thead>'
            f'<tbody>{rows}</tbody></table><p class="caption">正解は answer.json の値（式の値。乱数で点を打つモンテカルロ法でも'
            '確かめた）。答えは式でも、有効数字 6 桁以上の小数でもよい。</p>')


def grading_block(problem: dict[str, Any]) -> str:
    grading = problem["grading"]
    parts = [f'<p>{esc(grading["summary"])}</p>']
    if grading.get("cases"):
        parts.append(f'<p class="k">ケースの種類（合計 {grading["case_total"]} ケース）</p><ul>'
                     + "".join(f'<li>{esc(entry["kind"])}（{entry["n"]} ケース）</li>' for entry in grading["cases"]) + "</ul>")
    return "".join(parts)


def original_block(problem: dict[str, Any]) -> str:
    text = common.build_prompt(problem["category"], problem["id"])
    note = ("AI に送った問題文の全文です。共通の指示（PREAMBLE）と、問題ごとの文を空行でつなぎます。" if problem["category"] == "coding_v3"
            else "AI に送った問題文の全文です。問題ごとの文と、答えの書き方（POSTAMBLE）を空行でつなぎます。")
    return f'<details><summary>問題文の原文（{esc(note)}）</summary><pre>{esc(text)}</pre></details>'


def problem_card(guide: dict[str, Any], summary: dict[str, Any], problem: dict[str, Any]) -> str:
    category = problem["category"]
    body = [f'<p class="one-line">{esc(problem["one_line"])}</p>', f'<h4>やること</h4><p>{esc(problem["task"])}</p>']
    if category == "math":
        caption = "".join(f"<p>{esc(line)}</p>" for line in problem["situation"])
        body.append(f'<h4>問題の状況</h4><div class="situation">{caption}{FIGURES[problem["id"]]()}</div>')
        body.append(f'<h4>小問と正解</h4>{parts_table(problem)}')
    else:
        body.append(f'<h4>具体例</h4>{example_block(problem)}')
        if problem["id"] == "h6":
            body.append(tilings_svg() + '<p class="fig-caption">["...", "..."]（2 行 3 列）の 5 通り。太い線が駒の境目。</p>')
    body.append(f'<h4>何が難しいか</h4>{bullet_list(problem["difficulty"])}')
    body.append(f'<h4>何の力を見るか</h4><p>{esc(problem["measures"])}</p>')
    body.append(f'<h4>採点の仕方</h4>{grading_block(problem)}')
    body.append(f'<h4>用語</h4>{terms_block(problem["terms"])}')
    result = results_summary(summary, problem)
    if problem.get("result_note"):
        result += f'<p class="result-note">{esc(problem["result_note"])}</p>'
    body.append(f'<h4>この問題の結果</h4>{result}{results_grid(summary, problem)}')
    body.append(original_block(problem))
    return (f'<article class="card cat-{category}" id="p-{problem["id"]}"><header>{chip(guide, category)}'
            f'<h3>{esc(heading_text(problem))}</h3></header>{"".join(body)}</article>')


# ------------------------------------------------------------------------------------------------ 節


def category_style() -> str:
    return "".join(f".cat-{category}{{--cat:{color};--band:{_mix(SURFACE, color, 0.16)}}}"
                   for category, color in CATEGORY_COLORS.items())


def section_overview(guide: dict[str, Any], summary: dict[str, Any]) -> str:
    overview = guide["overview"]
    cards = []
    for exam in overview["exams"]:
        category = exam["category"]
        cards.append(f'<div class="exam cat-{category}"><div class="chips">{chip(guide, category)}</div>'
                     f'<h3>{esc(exam["name"])}</h3><p>{esc(exam["why"])}</p>'
                     f'<dl><dt>問題数</dt><dd>{esc(exam["count_text"])}</dd><dt>点の付け方</dt><dd>{esc(exam["points"])}</dd></dl></div>')
    claude = [model["label"] for model in summary["models"] if is_claude(model)]
    local = [model["label"] for model in summary["models"] if not is_claude(model)]
    return (f'<p class="lead-text">{esc(overview["lead"])}</p>'
            f'<div class="exam-cards">{"".join(cards)}</div>'
            '<h3>解いたモデル</h3>'
            f'<p><span class="k">Claude {len(claude)} 種</span>: {esc("、".join(claude))}</p>'
            f'<p><span class="k">ローカル {len(local)} 種</span>: {esc("、".join(local))}</p>'
            f'<h3>解かせ方</h3>{bullet_list(overview["how"])}'
            f'<h3>正解と採点の確かさ</h3>{bullet_list(overview["fairness"])}'
            f'<h3>用語</h3>{terms_block(overview["terms"])}'
            f'<h3>結果のマスの見方</h3><p>{esc(overview["result_note"])}</p>{grade_legend()}')


def section_problems(guide: dict[str, Any], summary: dict[str, Any], category: str) -> str:
    intro = (f'<div class="kind-intro cat-{category}">{chip(guide, category)}'
             f'<p>{esc(guide["categories"][category]["intro"])}</p></div>')
    return intro + "".join(problem_card(guide, summary, problem) for problem in guide["problems"]
                           if problem["category"] == category)


def section_amendments(frozen: dict[str, Any] | None) -> str:
    amendments = (frozen or {}).get("amendments") or []
    if not amendments:
        return '<p class="muted">改定の記録は無い。</p>'
    rows = "".join(f'<tr><td>{esc(entry["at"][5:16].replace("T", " "))}</td><td><code>{esc(entry["file"])}</code></td>'
                   f'<td>{esc(entry["reason"])}</td></tr>' for entry in amendments)
    return ('<p>問題文は一度も変えず、隠しテストと採点の仕組みだけを直しました。直したあとは、すべてのモデルの答えを同じ採点器で採点し直しています。</p>'
            '<table class="data amend"><thead><tr><th>日時</th><th>直したファイル</th><th>理由</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def section_appendix(guide: dict[str, Any]) -> str:
    rows = [
        ("問題文", "tools/model-eval/suites/coding_v3/PREAMBLE.md と h1〜h6/prompt.md、suites/math/m1〜m3/prompt.md と POSTAMBLE.md"),
        ("隠しテスト・参照解・オラクル", "tools/model-eval/suites/coding_v3/<問>/tests.py・reference.py・oracle.py"),
        ("数学の正解と検算", "tools/model-eval/suites/math/<問>/answer.json・reference.py、verify_numeric.json"),
        ("点の記録", f"tools/model-eval/results/{DATE}/summary.json"),
        ("この解説の本文", "tools/model-eval/suites/problem_guide_hard.json（作り直すのは tools/model-eval/build_problem_guide_hard.py）"),
    ]
    table = "".join(f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td></tr>" for name, path in rows)
    return f'<table class="data kv"><tbody>{table}</tbody></table><p>{esc(guide["appendix"]["closing"])}</p>'


def build_html(guide: dict[str, Any], summary: dict[str, Any], frozen: dict[str, Any] | None = None) -> str:
    counts = {category: sum(1 for problem in guide["problems"] if problem["category"] == category) for category in CATEGORY_ORDER}
    sections = [
        ("s1", "1. 全体像", section_overview(guide, summary)),
        ("s2", f"2. 難しいコーディング（{counts['coding_v3']} 問）", section_problems(guide, summary, "coding_v3")),
        ("s3", f"3. 数学（{counts['math']} 問）", section_problems(guide, summary, "math")),
        ("s4", "4. 採点の改定の記録", section_amendments(frozen)),
        ("s5", "5. 生データの場所", section_appendix(guide)),
    ]
    toc = "".join(f'<li><a href="#{anchor}">{esc(title)}</a></li>' for anchor, title, _body in sections)
    groups = "".join(
        f'<div class="toc-group cat-{category}">{chip(guide, category)}<ul>'
        + "".join(f'<li><a href="#p-{problem["id"]}">{esc(heading_text(problem))}</a></li>'
                  for problem in guide["problems"] if problem["category"] == category) + "</ul></div>"
        for category in CATEGORY_ORDER)
    body = "".join(f'<section id="{anchor}"><h2>{esc(title)}</h2>{content}</section>' for anchor, title, content in sections)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>AI モデル評価 {DATE} 出題内容の解説</title>'
        f'<style>{STYLE}{EXTRA_STYLE}{STYLE_HARD}{category_style()}</style></head>'
        '<body class="viz-root"><main>'
        f'<h1>評価で出した {len(guide["problems"])} 問の解説（{DATE}・難しい問題）</h1>'
        f'<p class="sub">評価日 {DATE}・集計 {esc(summary["generated_at"])}・'
        'tools/model-eval/build_problem_guide_hard.py が problem_guide_hard.json と summary.json から生成（手で書き換えない）</p>'
        f'<p class="sub">順位・時間・所見は元のレポートにあります: <a href="{esc(REPORT_NAME)}">{esc(REPORT_NAME)}</a></p>'
        f'<nav aria-label="目次"><ol>{toc}</ol><div class="toc-groups">{groups}</div></nav>'
        f'{body}</main></body></html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="既定 results/2026-10-18/summary.json")
    parser.add_argument("--guide", default=str(GUIDE_PATH), help="解説の本文（既定 suites/problem_guide_hard.json）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="出力先（既定 Documents/AIモデル評価_出題内容_2026-10-18.html）")
    args = parser.parse_args(argv)
    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    guide = json.loads(Path(args.guide).read_text(encoding="utf-8"))
    errors = validate_guide(guide)
    if errors:
        print("解説が原文と食い違っている（HTML は作らない）:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    frozen_path = summary_path.parent / "frozen.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8")) if frozen_path.exists() else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(guide, summary, frozen), encoding="utf-8")
    print(f"{out} を書いた（{out.stat().st_size:,} バイト）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
