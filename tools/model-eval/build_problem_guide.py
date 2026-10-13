#!/usr/bin/env python3
"""評価レポートで出した 16 問の「出題内容の解説書」を、1 ファイルで完結する HTML にする（外部参照なし）。

  build_problem_guide.py                          # suites/problem_guide.json と results/2026-10-08/summary.json
                                                  #   → Documents/AIモデル評価_出題内容_2026-10-08.html
  build_problem_guide.py --out work/guide.html    # 出力先を変える
  build_problem_guide.py --summary work/smoke/summary.json --guide suites/problem_guide.json

入力:
- suites/problem_guide.json: 問題ごとの解説（やること・具体例・難しさ・採点の仕方・用語）。手で書く。
- 各問題の原文: TestData/数学難問-三次元空間-TEST.md、suites/coding/、suites/extra/（折りたたんで載せる。needle は長いので抜粋）。
- results/<日付>/summary.json: モデルごと・問題ごとの点（「この問題の結果」の色つきのマス）。excluded のモデルは出さない。

解説の本文と原文が食い違っていないかは、読み込みのときに検査する（隠しテストの件数、採点の条件、期待値、具体例の文字列）。
食い違いがあれば、HTML を作らずに一覧を出して終了コード 1 で止まる。HTML は手で書き換えない。

色: 問題の種類ごとに 5 色（3D 数学・コーディング・指示に従う力・資料からの検索・JSON の取り出し）。見出しの帯・カードの左の線・
目次の印に使う。種類の名前は必ず文字でも出す。正解・誤り・答えなしの色は元のレポート（build_report.py）と同じ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from build_report import (  # noqa: E402 - 元のレポートの部品（見た目・色・点のマスの色づけ）を再利用する
    COLOR_NA, GRADE_SYMBOLS, MATH3D_PROBLEM, STYLE, _ink_on, _mix, cell_fill, cell_texts, cell_tip, esc, fmt_pct,
    grade_legend,
)
from evallib import common  # noqa: E402

GUIDE_PATH = common.SUITES_DIR / "problem_guide.json"
DEFAULT_OUT = common.REPO_DIR / "Documents" / f"AIモデル評価_出題内容_{common.DEFAULT_DATE}.html"
MATH3D_ANSWER_DOC = common.REPO_DIR / "Documents" / "3D問題_実施モデル一覧_2026-10-08.md"
SURFACE = "#fcfcfb"

# 問題の種類の色。dataviz スキルの検証済みの 8 色（青・オレンジ・アクア・黄・マゼンタ・緑・紫・赤）から、緑・アクア・赤を除いた 5 色を
# 選び、隣り合う並び（この順）がすべての検査を通る順に並べた（validate_palette.js --mode light: 隣接の最悪 CVD ΔE 19.9、通常視覚 ΔE 28.1）。
# 黄とマゼンタは明るい面で 3:1 を下回る（WARN）ので、種類の名前を必ず文字でも出す（色だけで区別させない）。
# 緑と赤は「正解」「誤り」の色（COLOR_OK・COLOR_NG）と紛れるので使わない。オレンジは誤りの赤と ΔE 13.2 と近いが、使う場所が
# 見出し・左の線・目次の印で、結果のマス（大きな色の面と点の文字）とは離れている。
CATEGORY_COLORS = {
    "math3d": "#eb6834",  # オレンジ
    "coding": "#2a78d6",  # 青
    "inst": "#eda100",    # 黄
    "needle": "#6250d6",  # 紫
    "json": "#e87ba4",    # マゼンタ
}
CATEGORY_ORDER = tuple(CATEGORY_COLORS)
# カテゴリ → summary.json の suites の鍵
CATEGORY_SUITE = {"math3d": "math3d", "coding": "coding", "inst": "extra", "needle": "extra", "json": "extra"}
# 具体例の枠の見出し（左, 右）。指示追従は答えの見本ではなく、条件と採点の確かめ方を並べる
EXAMPLE_LABELS = {
    "math3d": ("条件", "答え"),
    "coding": ("入力", "期待する答え"),
    "inst": ("問題文の条件", "採点で確かめること"),
    "needle": ("資料の中の 1 文", "期待する答え"),
    "json": ("文章の一部", "期待する値"),
}
REQUIRED_KEYS = ("id", "title", "category", "one_line", "task", "example", "difficulty", "measures", "grading", "terms")
EXPECTED_IDS = ("math3d",) + common.CODING_ITEMS + common.EXTRA_ITEMS
# 原文の抜粋（needle は長いので、冒頭と末尾だけ載せる）
NEEDLE_HEAD_CHARS = 600
NEEDLE_TAIL_CHARS = 400


# ------------------------------------------------------------------------------------------------ 原文と検査


def item_category(item: str) -> str:
    """問 ID から種類（math3d / coding / inst / needle / json）を引く。"""

    if item == "math3d":
        return "math3d"
    if item in common.CODING_ITEMS:
        return "coding"
    for kind, items in common.EXTRA_KINDS.items():
        if item in items:
            return kind
    raise ValueError(f"unknown item: {item}")


def item_files(item: str) -> list[Path]:
    """具体例の文字列が出てくるべき原文のファイル（問題文と、採点の答え・正解の表）。"""

    if item == "math3d":
        return [MATH3D_PROBLEM, MATH3D_ANSWER_DOC]
    if item in common.CODING_ITEMS:
        return [common.item_dir("coding", item) / "prompt.md"]
    directory = common.item_dir("extra", item)
    return [directory / "prompt.md", directory / "answer.json"]


def source_text(item: str) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in item_files(item))


def problem_text(item: str) -> str:
    """AI に送った問題文の全文（コーディングは共通の指示つき）。"""

    if item == "math3d":
        return MATH3D_PROBLEM.read_text(encoding="utf-8").strip()
    return common.build_prompt("coding" if item in common.CODING_ITEMS else "extra", item)


def count_hidden_cases(item: str) -> int:
    """隠しテスト tests.py の case_ 関数の数（1 ケース = 1 つの関数）。"""

    text = (common.item_dir("coding", item) / "tests.py").read_text(encoding="utf-8")
    return len(re.findall(r"^def case_", text, flags=re.MULTILINE))


def extra_answer(item: str) -> dict[str, Any]:
    return common.read_json(common.item_dir("extra", item) / "answer.json")


def needle_position(item: str) -> dict[str, Any]:
    """needle の資料の長さと、合言葉の文の位置（資料の節を 1 行ずつ数える）。"""

    answer = extra_answer(item)
    prompt = (common.item_dir("extra", item) / "prompt.md").read_text(encoding="utf-8")
    body = prompt.split('"""\n', 1)[1].split('\n"""', 1)[0]
    lines = body.split("\n")
    index = next(position for position, line in enumerate(lines) if answer["answer"] in line)
    return {"line_no": index + 1, "line_total": len(lines), "chars": len(body), "depth": answer["depth"],
            "word": answer["answer"]}


def validate_guide(guide: dict[str, Any]) -> list[str]:
    """解説（problem_guide.json）が原文と食い違っていないかの検査。問題の一覧を返す（空なら問題なし）。"""

    errors: list[str] = []
    categories = guide.get("categories") or {}
    for category in CATEGORY_ORDER:
        if not (categories.get(category) or {}).get("label"):
            errors.append(f"categories.{category}.label が無い")
    problems = guide.get("problems") or []
    ids = [problem.get("id") for problem in problems]
    if ids != list(EXPECTED_IDS):
        errors.append(f"問題の ID と順序が違う: {ids}（期待 {list(EXPECTED_IDS)}）")
    for problem in problems:
        item = problem.get("id", "?")
        for key in REQUIRED_KEYS:
            if not problem.get(key):
                errors.append(f"{item}: 必須の鍵 {key} が無い（または空）")
        if item not in EXPECTED_IDS:
            continue
        if problem.get("category") != item_category(item):
            errors.append(f"{item}: category が {problem.get('category')}（期待 {item_category(item)}）")
        if not (problem.get("grading") or {}).get("summary"):
            errors.append(f"{item}: grading.summary が無い")
        text = source_text(item)
        for number, example in enumerate(problem.get("example") or [], start=1):
            for key in ("input", "output"):
                if example.get(key) not in text:
                    errors.append(f"{item}: 具体例 {number} の {key} が原文に無い: {example.get(key)!r}")
        errors.extend(_validate_grading(problem))
        if item == "math3d":
            errors.extend(_validate_math3d(problem))
    return errors


def _validate_grading(problem: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    item = problem["id"]
    grading = problem.get("grading") or {}
    if item in common.CODING_ITEMS:
        actual = count_hidden_cases(item)
        listed = sum(entry["n"] for entry in grading.get("cases") or [])
        if grading.get("case_total") != actual:
            errors.append(f"{item}: case_total {grading.get('case_total')} が tests.py の case_ の数 {actual} と違う")
        if listed != actual:
            errors.append(f"{item}: cases の n の合計 {listed} が tests.py の case_ の数 {actual} と違う")
    elif item in common.EXTRA_KINDS["inst"]:
        labels = [check["label"] for check in extra_answer(item)["checks"]]
        if grading.get("items") != labels:
            errors.append(f"{item}: grading.items が answer.json の条件の一覧と違う")
    elif item in common.EXTRA_KINDS["json"]:
        expected = extra_answer(item)["expected"]
        fields = {entry["key"]: entry["expected"] for entry in grading.get("fields") or []}
        if fields != expected or [entry["key"] for entry in grading.get("fields") or []] != list(expected):
            errors.append(f"{item}: grading.fields が answer.json の expected と違う")
    elif item in common.EXTRA_KINDS["needle"]:
        depth_percent = f"{round(extra_answer(item)['depth'] * 100)}%"
        if depth_percent not in problem.get("one_line", "") or depth_percent not in "".join(problem.get("difficulty") or []):
            errors.append(f"{item}: 合言葉の位置 {depth_percent} が one_line か difficulty に書かれていない")
    return errors


def _validate_math3d(problem: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    answer_doc = MATH3D_ANSWER_DOC.read_text(encoding="utf-8")
    parts = problem.get("parts") or []
    if [part.get("key") for part in parts] != ["q1", "q2", "q3", "q4"]:
        errors.append("math3d: parts の鍵が q1〜q4 ではない")
    for part in parts:
        # 正解は 3D 問題の一覧の表（正解の節）の文字列そのまま
        if f"| {part.get('label')} | {part.get('answer')} |" not in answer_doc:
            errors.append(f"math3d: {part.get('label')} の正解が {MATH3D_ANSWER_DOC.name} の表と違う")
    return errors


# ------------------------------------------------------------------------------------------------ 部品


EXTRA_STYLE = """
.sub a{color:inherit}
.lead-text{font-size:1.02rem;margin:8px 0 4px}
.toc-groups{display:flex;flex-wrap:wrap;gap:10px 18px;margin:8px 0}
.toc-group{flex:1 1 230px}.toc-group ul{margin:4px 0 0;padding-left:20px}.toc-group li{margin:1px 0}
.chip-cat{display:inline-flex;align-items:center;gap:6px;padding:2px 10px 2px 8px;border:1px solid var(--cat);border-radius:12px;
background:var(--surface);color:var(--text-primary);font-size:.85rem;font-weight:600;white-space:nowrap}
.dot{display:inline-block;width:12px;height:12px;border-radius:3px;background:var(--cat)}
.exam-cards{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.exam{flex:1 1 300px;background:var(--surface-2);border-radius:8px;padding:12px 16px;border-top:6px solid var(--cat)}
.exam.multi{border-top-color:var(--grid)}
.exam h3{margin:6px 0 4px}.exam p{margin:4px 0}.exam .chips{display:flex;flex-wrap:wrap;gap:4px 6px}
.exam dl{margin:6px 0 0;font-size:.88rem}.exam dt{font-weight:600;color:var(--text-secondary);margin-top:6px}
.exam dd{margin:0}
.k{color:var(--text-secondary);font-weight:600}
.card{margin:20px 0 32px;border:1px solid var(--grid);border-left:8px solid var(--cat);border-radius:8px;padding:0 16px 14px}
.card>header{margin:0 -16px 10px;padding:10px 16px;background:var(--band);border-radius:0 7px 0 0;display:flex;flex-wrap:wrap;
align-items:center;gap:6px 12px}
.card>header h3{margin:0;font-size:1.15rem}
.card h4{font-size:.95rem;margin:16px 0 4px;color:var(--text-secondary)}
.card h4::before{content:"";display:inline-block;width:4px;height:.9em;margin-right:6px;vertical-align:-1px;background:var(--cat);
border-radius:2px}
.card p{margin:4px 0}.card ul{margin:4px 0;padding-left:22px}.card li{margin:2px 0}
p.one-line{font-weight:600;font-size:1.02rem;margin:6px 0}
.example{display:grid;grid-template-columns:1fr auto 1fr;gap:6px 10px;align-items:start;margin:8px 0 2px}
.example>div{min-width:0}
.example .ex-label{font-size:.8rem;color:var(--text-secondary);font-weight:600}
.example pre{margin:2px 0 0;font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;overflow-wrap:anywhere}
.example .ex-arrow{align-self:center;font-size:1.2rem;color:var(--text-secondary);padding-top:16px}
.ex-note{margin:2px 0 10px;color:var(--text-secondary);font-size:.88rem}
@media (max-width:640px){.example{grid-template-columns:1fr}.example .ex-arrow{display:none}}
dl.terms{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:4px 0;font-size:.9rem}
dl.terms dt{font-weight:600}dl.terms dd{margin:0;color:var(--text-secondary)}
.results{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:6px;margin:6px 0}
.res{min-width:0}.res-cell{border-radius:6px;padding:6px 4px;min-height:46px;text-align:center;display:flex;flex-direction:column;
justify-content:center}
.res-main{font-weight:700;font-size:1rem}.res-sub{font-size:.72rem;font-weight:600}
.res-name{margin-top:2px;font-size:.78rem;color:var(--text-secondary);text-align:center;overflow-wrap:anywhere}
.tally{margin:2px 0 4px;font-size:.88rem;color:var(--text-secondary)}
.chips-run{display:inline-flex;gap:3px}
.situation{margin:6px 0}
svg.figure{display:block;max-width:100%;height:auto;margin:6px 0;background:var(--surface-2);border-radius:6px}
svg.figure text{font-size:13px;fill:var(--text-primary)}svg.figure .sub-text{fill:var(--text-secondary);font-size:11.5px}
.kind-intro{margin:22px 0 0;padding:8px 12px;background:var(--surface-2);border-radius:6px}
.kind-intro p{margin:4px 0 0}
details>pre{max-height:520px;overflow:auto}
@media print{.card{break-inside:avoid-page}}
"""


def category_style(guide: dict[str, Any]) -> str:
    """種類ごとの色の変数（--cat は線・印、--band は見出しの帯の薄い色）。"""

    return "".join(f".cat-{category}{{--cat:{color};--band:{_mix(SURFACE, color, 0.16)}}}"
                   for category, color in CATEGORY_COLORS.items())


def chip(guide: dict[str, Any], category: str) -> str:
    """種類の印。色の四角と、種類の名前の文字（色だけに頼らない）。"""

    return (f'<span class="chip-cat cat-{category}"><i class="dot"></i>'
            f'{esc(guide["categories"][category]["label"])}</span>')


def heading_text(problem: dict[str, Any]) -> str:
    """カードの見出し。問 ID は元のレポートの表の見出しと同じ表記（C1〜C6、inst1 など）にする。"""

    if problem["id"] == "math3d":
        return problem["title"]  # 種類の印（3D 数学）が見出しの横に付くので、題名だけにする
    label = problem["id"].upper() if problem["id"] in common.CODING_ITEMS else problem["id"]
    return f"{label} {problem['title']}"


def bullet_list(lines: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>"


def terms_block(terms: list[dict[str, str]]) -> str:
    return ('<dl class="terms">'
            + "".join(f"<dt>{esc(term['term'])}</dt><dd>{esc(term['explain'])}</dd>" for term in terms) + "</dl>")


def example_block(problem: dict[str, Any]) -> str:
    left, right = EXAMPLE_LABELS[problem["category"]]
    parts = []
    for example in problem["example"]:
        parts.append(f'<div class="example"><div><div class="ex-label">{esc(left)}</div><pre>{esc(example["input"])}</pre></div>'
                     '<div class="ex-arrow" aria-hidden="true">→</div>'
                     f'<div><div class="ex-label">{esc(right)}</div><pre>{esc(example["output"])}</pre></div></div>')
        if example.get("note"):
            parts.append(f'<p class="ex-note">{esc(example["note"])}</p>')
    return "".join(parts)


def staircase_svg() -> str:
    """3D 数学の図。O→A→B→C の 3 本の線分を、斜め上から見た絵で示す（x・y・z の向きの矢印つき）。"""

    # 画面の座標: x の向き = 右下、y の向き = 右上、z の向き = 真上（1 辺の長さ 1 を 62 に対応させる）
    point_o = (96, 118)
    point_a = (point_o[0] + 62, point_o[1] + 34)
    point_b = (point_a[0] + 62, point_a[1] - 34)
    point_c = (point_b[0], point_b[1] - 62)
    # (線分の名前, 始点, 終点, 名前を置くずれ, 文字の揃え)
    segments = (("OA → V1", point_o, point_a, (-6, 18), "end"), ("AB → V2", point_a, point_b, (10, 18), "start"),
                ("BC → V3", point_b, point_c, (-10, 4), "end"))
    points = (("O (0,0,0)", point_o, (-10, 5), "end"), ("A (1,0,0)", point_a, (0, 22), "middle"),
              ("B (1,1,0)", point_b, (10, 18), "start"), ("C (1,1,1)", point_c, (10, 5), "start"))
    parts = ['<svg class="figure" viewBox="0 0 330 185" width="330" height="185" role="img" '
             'aria-label="点 O から A、B、C へ、x の向き、y の向き、z の向きに長さ 1 ずつ進む、階段のような 3 本の線分">']
    # 軸の向き（左下）
    axis_origin = (28, 150)
    for label, (shift_x, shift_y), anchor in (("x", (30, 17), "start"), ("y", (30, -17), "start"), ("z", (0, -34), "middle")):
        end_x, end_y = axis_origin[0] + shift_x, axis_origin[1] + shift_y
        parts.append(f'<line x1="{axis_origin[0]}" y1="{axis_origin[1]}" x2="{end_x}" y2="{end_y}" stroke="#76756f" '
                     'stroke-width="1.5"/>')
        label_x, label_y = (end_x + 6, end_y + 4) if anchor == "start" else (end_x, end_y - 5)
        parts.append(f'<text class="sub-text" x="{label_x}" y="{label_y}" text-anchor="{anchor}">{label}</text>')
    # 3 本の線分（V1・V2・V3 のもとになる線）と、その名前
    for name, first, second, offset, anchor in segments:
        parts.append(f'<line x1="{first[0]}" y1="{first[1]}" x2="{second[0]}" y2="{second[1]}" stroke="#52514e" '
                     'stroke-width="5" stroke-linecap="round"/>')
        label_x = (first[0] + second[0]) / 2 + offset[0]
        label_y = (first[1] + second[1]) / 2 + offset[1]
        parts.append(f'<text class="sub-text" x="{label_x:.0f}" y="{label_y:.0f}" text-anchor="{anchor}">{esc(name)}</text>')
    # 4 つの点とその座標
    for name, point, offset, anchor in points:
        parts.append(f'<circle cx="{point[0]}" cy="{point[1]}" r="5" fill="#0b0b0b"/>')
        parts.append(f'<text x="{point[0] + offset[0]}" y="{point[1] + offset[1]}" text-anchor="{anchor}">{esc(name)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------------------------------------ 結果のマス


def result_cell(summary: dict[str, Any], problem: dict[str, Any], model: dict[str, Any]) -> dict[str, Any] | None:
    suite = summary["suites"].get(CATEGORY_SUITE[problem["category"]]) or {}
    entry = (suite.get("models") or {}).get(model["key"]) or {}
    return (entry.get("items") or {}).get(problem["id"])


def tally_text(cells: list[dict[str, Any] | None]) -> str:
    full = sum(1 for cell in cells if cell and cell.get("cell") == "scored" and float(cell.get("score") or 0) >= 1.0)
    partial = sum(1 for cell in cells if cell and cell.get("cell") == "scored" and 0 < float(cell.get("score") or 0) < 1.0)
    zero = sum(1 for cell in cells if cell and (cell.get("cell") == "no_answer"
                                                 or (cell.get("cell") == "scored" and float(cell.get("score") or 0) <= 0)))
    unrecorded = len(cells) - full - partial - zero
    pieces = [f"満点 {full}"] + [f"{name} {count}" for name, count in
                                (("部分点", partial), ("0 点・答えなし", zero), ("飛ばし・記録なし", unrecorded)) if count]
    return f"{len(cells)} モデル中、" + "・".join(pieces)


def results_grid(summary: dict[str, Any], problem: dict[str, Any]) -> str:
    models = summary["models"]
    cells = [result_cell(summary, problem, model) for model in models]
    boxes = []
    for model, cell in zip(models, cells):
        if cell is None:
            fill, main, sub, tip = COLOR_NA, "記録なし", "", f"記録なし\n{model['label']} / {problem['id']}"
        else:
            fill = cell_fill(cell)
            main, sub = cell_texts(cell)
            tip = cell_tip(cell, model["label"], problem["id"])
        ink = _ink_on(fill)
        sub_html = f'<span class="res-sub">{esc(sub)}</span>' if sub else ""
        boxes.append(f'<div class="res" role="listitem" title="{esc(tip)}">'
                     f'<div class="res-cell" style="background:{fill};color:{ink}"><span class="res-main">{esc(main)}</span>'
                     f'{sub_html}</div><div class="res-name">{esc(model["label"])}</div></div>')
    return (f'<p class="tally">{esc(tally_text(cells))}。</p>'
            f'<div class="results" role="list" aria-label="モデルごとの結果">{"".join(boxes)}</div>')


def math3d_results(summary: dict[str, Any], problem: dict[str, Any]) -> str:
    """3D 数学の結果。モデルごと・小問ごとに、能力に使った回の ○×— を並べる（参考の回は除く）。"""

    suite = summary["suites"]["math3d"]
    keys = [part["key"] for part in problem["parts"]]
    rows = []
    totals = {key: [0, 0] for key in keys}  # [正解, 回数]
    for model in summary["models"]:
        runs = [run for run in (suite["models"].get(model["key"]) or {}).get("runs") or [] if run.get("used")]
        if not runs:
            rows.append(f'<tr><td>{esc(model["label"])}</td><td colspan="{len(keys) + 1}" class="muted">記録なし</td></tr>')
            continue
        cells = []
        for key in keys:
            chips = []
            for run in runs:
                value = (run.get("grade") or {}).get(key)
                symbol, color, label = GRADE_SYMBOLS[value]
                chips.append(f'<span class="chip" style="background:{color}" aria-label="{label}" '
                             f'title="{esc(label)}">{symbol}</span>')
                totals[key][1] += 1
                totals[key][0] += 1 if value is True else 0
            cells.append(f'<td class="center"><span class="chips-run">{"".join(chips)}</span></td>')
        rows.append(f'<tr><td>{esc(model["label"])}</td>{"".join(cells)}<td class="num">{len(runs)} 回</td></tr>')
    total_cells = "".join(f'<td class="center strong">{done} / {count}</td>' for done, count in totals.values())
    rows.append(f'<tr><th>全モデルの合計（正解 / 回数）</th>{total_cells}<td></td></tr>')
    headers = "".join(f"<th>{esc(part['label'])}</th>" for part in problem["parts"])
    return ('<table class="data"><thead><tr><th>モデル</th>' + headers + '<th>回数</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<p class="caption">○ 正解・× 誤り・— 答えなし。1 つのマスに複数の印があるのは、複数回解かせたとき（左から古い順）。'
            '能力に使っていない参考の回は除いてあります。時間と順位は元のレポートにあります。</p>')


# ------------------------------------------------------------------------------------------------ カード


def grading_block(problem: dict[str, Any]) -> str:
    grading = problem["grading"]
    parts = [f'<p>{esc(grading["summary"])}</p>']
    if grading.get("cases"):
        parts.append(f'<p class="k">ケースの種類（合計 {grading["case_total"]} ケース）</p><ul>'
                     + "".join(f'<li>{esc(entry["kind"])}（{entry["n"]} ケース）</li>' for entry in grading["cases"]) + "</ul>")
    if grading.get("items"):
        parts.append(f'<p class="k">{esc(grading.get("items_title", "確かめる条件"))}</p>{bullet_list(grading["items"])}')
    if grading.get("fields"):
        rows = "".join(f'<tr><td><code>{esc(entry["key"])}</code></td>'
                       f'<td><code>{esc(json.dumps(entry["expected"], ensure_ascii=False))}</code></td>'
                       f'<td>{esc(entry.get("note", ""))}</td></tr>' for entry in grading["fields"])
        parts.append('<table class="data"><thead><tr><th>鍵</th><th>正解</th><th>気をつける点</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table>')
    if problem["category"] == "needle":
        position = needle_position(problem["id"])
        parts.append(f'<p class="caption">資料は全 {position["line_total"]} 節、{position["chars"]:,} 文字。合言葉の文は '
                     f'{position["line_no"]} 番目（先頭から約 {position["depth"] * 100:.0f}% の位置）に 1 つだけあります。'
                     f'正解は「{esc(position["word"])}」です。</p>')
    return "".join(parts)


def original_block(problem: dict[str, Any]) -> str:
    text = problem_text(problem["id"])
    if problem["category"] == "needle":
        head, tail = text[:NEEDLE_HEAD_CHARS], text[-NEEDLE_TAIL_CHARS:]
        shown = (f"{head}\n…（中略。問題文は全部で {len(text):,} 文字。資料は {needle_position(problem['id'])['chars']:,} 文字）…\n{tail}")
        note = f"問題文は全 {len(text):,} 文字です。長いので、冒頭 {NEEDLE_HEAD_CHARS} 字と末尾 {NEEDLE_TAIL_CHARS} 字だけを載せます。"
    else:
        shown = text
        note = ("AI に送った問題文の全文です。コーディングは、共通の指示（PREAMBLE）と、問題ごとの文を空行でつなぎます。"
                if problem["category"] == "coding" else "AI に送った問題文の全文です。")
    return f'<details><summary>問題文の原文（{esc(note)}）</summary><pre>{esc(shown)}</pre></details>'


def problem_card(guide: dict[str, Any], summary: dict[str, Any], problem: dict[str, Any]) -> str:
    category = problem["category"]
    body = [f'<p class="one-line">{esc(problem["one_line"])}</p>',
            f'<h4>やること</h4><p>{esc(problem["task"])}</p>']
    if problem["id"] == "math3d":
        body.append('<h4>問題の状況</h4><div class="situation">'
                    + "".join(f"<p>{esc(line)}</p>" for line in problem["situation"]) + staircase_svg() + "</div>")
        rows = "".join(f'<tr><td class="strong">{esc(part["label"])}</td><td>{esc(part["ask"])}</td>'
                       f'<td>{esc(part["answer"])}</td></tr>' for part in problem["parts"])
        body.append('<h4>小問と正解</h4><table class="data"><thead><tr><th>小問</th><th>何を答えるか</th><th>正解</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>')
    body.append(f'<h4>具体例</h4>{example_block(problem)}')
    body.append(f'<h4>何が難しいか</h4>{bullet_list(problem["difficulty"])}')
    body.append(f'<h4>何の力を見るか</h4><p>{esc(problem["measures"])}</p>')
    body.append(f'<h4>採点の仕方</h4>{grading_block(problem)}')
    body.append(f'<h4>用語</h4>{terms_block(problem["terms"])}')
    result = math3d_results(summary, problem) if problem["id"] == "math3d" else results_grid(summary, problem)
    body.append(f'<h4>この問題の結果</h4>{result}')
    body.append(original_block(problem))
    return (f'<article class="card cat-{category}" id="p-{problem["id"]}"><header>{chip(guide, category)}'
            f'<h3>{esc(heading_text(problem))}</h3></header>{"".join(body)}</article>')


# ------------------------------------------------------------------------------------------------ 節


def limits_lines(summary: dict[str, Any], suite_key: str) -> list[str]:
    limits = summary["limits"].get(suite_key)
    if not limits:
        return []
    return [f"生成の上限: {limits['max_tokens']:,} トークン",
            f"思考の予算: {limits['reasoning_budget_tokens']:,} トークン（Strata だけ）",
            f"1 回の要求の時間: {limits['request_timeout_s'] // 60} 分まで"]


def section_overview(guide: dict[str, Any], summary: dict[str, Any]) -> str:
    overview = guide["overview"]
    cards = []
    for exam in overview["exams"]:
        suite = exam["suite"]
        categories = [category for category in CATEGORY_ORDER if CATEGORY_SUITE[category] == suite]
        chips = "".join(chip(guide, category) for category in categories)
        limits = limits_lines(summary, suite)
        limit_html = ("<dt>制限</dt><dd>" + "<br>".join(esc(line) for line in limits) + "</dd>") if limits else ""
        note_html = f"<dt>条件</dt><dd>{esc(exam['limits_note'])}</dd>" if exam.get("limits_note") else ""
        css = f"cat-{categories[0]}" if len(categories) == 1 else "multi"
        cards.append(f'<div class="exam {css}" style="--cat:{CATEGORY_COLORS[categories[0]]}">'
                     f'<div class="chips">{chips}</div><h3>{esc(exam["name"])}</h3>'
                     f'<p>{esc(exam["why"])}</p><dl><dt>問題数</dt><dd>{esc(exam["count_text"])}</dd>'
                     f'<dt>点の付け方</dt><dd>{esc(exam["points"])}</dd>'
                     f'{limit_html}{note_html}</div>')
    limit_terms = terms_block(overview["limit_terms"])
    stall = summary.get("stall_timeout_s")
    budget = summary.get("model_time_budget_s")
    time_caption = (f'<p class="caption">この実験の値: {stall} 秒のあいだ何も届かなければ打ち切り（stall）、'
                    f'1 つのモデルの累計時間が {budget // 60} 分を超えたら残りの問を飛ばしました。</p>') if stall and budget else ""
    formulas = "".join(f"<li>{esc(text)}</li>" for text in summary["formulas"].values())
    color_rows = "".join(
        f'<li>{chip(guide, category)} {esc(guide["categories"][category]["intro"])}</li>' for category in CATEGORY_ORDER)
    return (f'<p class="lead-text">{esc(overview["lead"])}</p>'
            f'<div class="exam-cards">{"".join(cards)}</div>'
            f'<h3>制限の意味</h3>{limit_terms}{time_caption}'
            f'<h3>総合順位の式</h3><p>{esc(overview["scoring"])}</p><ul class="notes formulas">{formulas}</ul>'
            f'{terms_block(overview["terms"])}'
            f'<h3>色の見方</h3><p>{esc(overview["color_note"])}</p><ul class="notes colors">{color_rows}</ul>'
            f'<p>{esc(overview["result_note"])}</p>{grade_legend()}')


def section_problems(guide: dict[str, Any], summary: dict[str, Any], categories: tuple[str, ...]) -> str:
    parts = []
    for category in categories:
        problems = [problem for problem in guide["problems"] if problem["category"] == category]
        if len(categories) > 1:
            # 追加の 3 試験は、種類ごとにまとめの見出しを付ける
            parts.append(f'<div class="kind-intro cat-{category}">{chip(guide, category)}'
                         f'<p>{esc(guide["categories"][category]["intro"])}</p></div>')
        parts.extend(problem_card(guide, summary, problem) for problem in problems)
    return "".join(parts)


def section_appendix(guide: dict[str, Any], summary: dict[str, Any]) -> str:
    date = summary["date"]
    rows = [
        ("問題文", "TestData/数学難問-三次元空間-TEST.md、tools/model-eval/suites/coding/PREAMBLE.md と c1〜c6/prompt.md、"
                "tools/model-eval/suites/extra/<問>/prompt.md"),
        ("隠しテストと採点用ファイル", "tools/model-eval/suites/coding/c1〜c6/tests.py、tools/model-eval/suites/extra/<問>/answer.json、"
                              "採点器 tools/model-eval/suites/extra/grade_extra.py"),
        ("3D 数学の正解", "Documents/3D問題_実施モデル一覧_2026-10-08.md"),
        ("点の記録", f"tools/model-eval/results/{date}/summary.json"),
        ("この解説の本文", "tools/model-eval/suites/problem_guide.json（作り直すのは tools/model-eval/build_problem_guide.py）"),
    ]
    for archive in summary.get("archives") or []:
        rows.append((f"保管（{archive['name']}）", f"{archive['path']}（順位には使っていない）"))
    table = "".join(f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td></tr>" for name, path in rows)
    return (f'<h3>データの場所</h3><table class="data kv"><tbody>{table}</tbody></table>'
            f'<p>{esc(guide["appendix"]["closing"])}</p>')


def section_v1(guide: dict[str, Any], summary: dict[str, Any]) -> str:
    labels = {model["key"]: model["label"] for model in summary["models"]}
    lines = []
    for archive in summary.get("archives") or []:
        coding = (archive.get("suites") or {}).get("coding") or {}
        for key, entry in coding.items():
            lines.append(f"{labels.get(key, key)}: {entry['n_items']} 問中 {entry['n_all_passed']} 問が全部合格"
                         f"（能力 {fmt_pct(entry['ability'])}）")
    record = ('<p class="k">易しい版の記録（summary.json の archives）</p>' + bullet_list(lines)) if lines else ""
    return f'<p>{esc(guide["appendix"]["v1"])}</p>{record}'


def build_html(guide: dict[str, Any], summary: dict[str, Any]) -> str:
    report_link = f"AIモデル評価_{summary['date']}.html"
    counts = {category: sum(1 for problem in guide["problems"] if problem["category"] == category) for category in CATEGORY_ORDER}
    total = len(guide["problems"])
    sections = [
        ("s0", "1. 全体像（3 つの試験）", section_overview(guide, summary)),
        ("s1", f"2. 3D 数学（{counts['math3d']} 問）", section_problems(guide, summary, ("math3d",))),
        ("s2", f"3. コーディング（{counts['coding']} 問）", section_problems(guide, summary, ("coding",))),
        ("s3", f"4. 追加の 3 試験（{counts['inst'] + counts['needle'] + counts['json']} 問）",
         section_problems(guide, summary, ("inst", "needle", "json"))),
        ("s4", "5. 補足: 最初に出した易しい版", section_v1(guide, summary)),
        ("s5", "6. 生データの場所", section_appendix(guide, summary)),
    ]
    toc_sections = "".join(f'<li><a href="#{anchor}">{esc(title)}</a></li>' for anchor, title, _body in sections)
    groups = []
    for category in CATEGORY_ORDER:
        links = "".join(f'<li><a href="#p-{problem["id"]}">{esc(heading_text(problem))}</a></li>'
                        for problem in guide["problems"] if problem["category"] == category)
        groups.append(f'<div class="toc-group cat-{category}">{chip(guide, category)}<ul>{links}</ul></div>')
    body = "".join(f'<section id="{anchor}"><h2>{esc(title)}</h2>{content}</section>' for anchor, title, content in sections)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>AI モデル評価 {esc(summary["date"])} 出題内容の解説</title>'
        f'<style>{STYLE}{EXTRA_STYLE}{category_style(guide)}</style></head>'
        '<body class="viz-root"><main>'
        f'<h1>評価で出した {total} 問の解説（出題内容）</h1>'
        f'<p class="sub">評価日 {esc(summary["date"])}・集計 {esc(summary["generated_at"])}・'
        'tools/model-eval/build_problem_guide.py が problem_guide.json と summary.json から生成（手で書き換えない）</p>'
        f'<p class="sub">結果・順位・所見は元のレポートにあります: <a href="{esc(report_link)}">{esc(report_link)}</a></p>'
        f'<nav aria-label="目次"><ol>{toc_sections}</ol><div class="toc-groups">{"".join(groups)}</div></nav>'
        f'{body}</main></body></html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", default=None, help=f"既定 results/{common.DEFAULT_DATE}/summary.json")
    parser.add_argument("--guide", default=str(GUIDE_PATH), help="解説の本文（既定 suites/problem_guide.json）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="出力先（既定 Documents/AIモデル評価_出題内容_<日付>.html）")
    args = parser.parse_args(argv)
    summary_path = Path(args.summary) if args.summary else common.results_dir_for(None) / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    guide = json.loads(Path(args.guide).read_text(encoding="utf-8"))
    errors = validate_guide(guide)
    if errors:
        print("解説が原文と食い違っている（HTML は作らない）:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(guide, summary), encoding="utf-8")
    print(f"{out} を書いた（{out.stat().st_size:,} バイト）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
