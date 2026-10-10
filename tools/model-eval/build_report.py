#!/usr/bin/env python3
"""summary.json から 1 ファイルで完結する HTML を作る（外部 CDN なし、CSS と SVG をファイル内に書く）。

  build_report.py                                    # results/2026-10-08/summary.json → Documents/AIモデル評価_2026-10-08.html
  build_report.py --summary work/smoke/summary.json --out work/smoke/report.html

所見（節 5）は results/<日付>/findings.json（{"facts": [...], "opinions": [...]}）があれば載せる。無ければ空欄の注記を出す。
HTML は手で書き換えない。直すときは summary.json か findings.json か、このスクリプトを直して作り直す。

色（計画の方針 7）: 正解 #1a7f37、誤り #c0392b、答えなし #8a8f98、部分点は緑の濃淡。
系統は Claude #1f59bb・Ollama #086c61・Strata #7044bb（既存の HTML と同じ）。1〜3 位は金・銀・銅のバッジ。
系統の色は凡例と表でも名前を併記し、色だけで区別させない。採点のマスも、点数と状態（上限・エラー・予算での打ち切り）を
文字で併記する（赤と緑は色覚の型によって見分けにくい）。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from evallib import common  # noqa: E402
from summarize import REASONING_WRAP_UP_MARK, REPEAT_LINE_MIN_CHARS  # noqa: E402

FAMILY_COLORS = {"claude": "#1f59bb", "ollama": "#086c61", "strata": "#7044bb"}
FAMILY_LABELS = {"claude": "Claude（API）", "ollama": "Ollama（この機体）", "strata": "Strata（この機体）"}
COLOR_OK = "#1a7f37"
COLOR_NG = "#c0392b"
COLOR_NA = "#8a8f98"
# 部分点の濃淡の明るい端（0 点に近い部分点）。暗い端は COLOR_OK
COLOR_PARTIAL_LIGHT = "#d3ecd9"
MEDAL_COLORS = {1: "#c9a227", 2: "#9aa1a9", 3: "#b0703c"}
GRADE_SYMBOLS = {True: ("○", COLOR_OK, "正解"), False: ("×", COLOR_NG, "誤り"), None: ("—", COLOR_NA, "答えなし")}

# 記録の状態（status）を色だけでなく文字でも示すための短い名前と説明（ヒートマップの下段・ツールチップ・一覧）。
# 赤と緑は色覚の型によって見分けにくいので、点数と状態は必ず文字でも出す
STATUS_LABELS = {"length": "上限", "timeout": "時間切れ", "stall": "無応答", "error": "エラー",
                 "eos_in_thinking": "思考中停止"}
STATUS_DESCRIPTIONS = {"length": "生成の上限トークンに届いた", "timeout": "1 要求の時間上限に届いた",
                       "stall": "一定時間なにも届かず打ち切った", "error": "サーバーがエラーを返した",
                       "eos_in_thinking": "思考の途中で停止トークンが出て、本文が空のまま終わった（0 点・答えなし）"}
# Strata が思考を予算で打ち切ったあとの答え（summarize.py の budget_cut）の印
BUDGET_CUT_LABEL = "打切"
# 答えはあるが 0 点になった理由の印（禁止の import・呼び出しで実行しなかった / コードが Python として読めない）
VIOLATION_LABEL = "禁止"
SYNTAX_ERROR_LABEL = "文法誤り"
# 答えなしで状態が ok のとき（採点器の reason）の下段の文字
NO_ANSWER_REASON_LABELS = {"本文が無い": "本文なし", "コードが無い": "コードなし"}
# results/<日付>/archive-*/ の説明（summary.json の archives）。無い名前は汎用の文にする
ARCHIVE_NOTES = {
    "archive-coding-v1-easy": "易しい版 v1 のコーディング。天井効果で差が出なかったので、難しい版 v2（いまの 6 問）に替えた。"
                              "順位には使っていない。",
}
THINKING_EST_NOTE = ("思考のトークン数は推定。どの API も直接は出さないので、出力トークン × 思考の文字数 ÷ (思考 + 本文の文字数) "
                     "で出した。")

DEFAULT_OUT = common.REPO_DIR / "Documents" / f"AIモデル評価_{common.DEFAULT_DATE}.html"
MATH3D_PROBLEM = common.REPO_DIR / "TestData" / "数学難問-三次元空間-TEST.md"

esc = html.escape


# ------------------------------------------------------------------------------------------------ 書式


def fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def fmt_score(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    if seconds < 3600:
        minutes, rest = divmod(round(seconds), 60)
        return f"{minutes} 分 {rest} 秒" if rest else f"{minutes} 分"
    hours, rest = divmod(round(seconds), 3600)
    return f"{hours} 時間 {rest // 60} 分"


def fmt_int(value: Any) -> str:
    return "—" if value is None else f"{int(value):,}"


def fmt_rate(value: Any) -> str:
    return "不明" if value is None else f"{float(value):.1f}"


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _mix(light: str, dark: str, ratio: float) -> str:
    first, second = _hex_to_rgb(light), _hex_to_rgb(dark)
    mixed = (round(a + (b - a) * ratio) for a, b in zip(first, second))
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def _ink_on(fill: str) -> str:
    """塗りの上に置く文字の色（相対輝度で白か墨）。"""

    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _hex_to_rgb(fill))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#ffffff" if luminance < 0.4 else "#0b0b0b"


def cell_fill(cell: dict[str, Any]) -> str:
    """ヒートマップの 1 マスの色。答えなし・飛ばし・記録なしは灰、0 点は赤、満点は緑、部分点は緑の濃淡。"""

    if cell.get("cell") != "scored":
        return COLOR_NA
    score = float(cell.get("score") or 0.0)
    if score >= 1.0:
        return COLOR_OK
    if score <= 0.0:
        return COLOR_NG
    return _mix(COLOR_PARTIAL_LIGHT, COLOR_OK, score)


def cell_texts(cell: dict[str, Any]) -> tuple[str, str]:
    """ヒートマップの 1 マスの文字（上段, 下段）。

    上段は点数か「答えなし」など。下段は状態（上限・エラー・時間切れ・無応答）と、思考を予算で打ち切ったあとの答え
    （打切）を文字で示す。色だけに頼らない（灰は「答えなし」と「記録なし」で同じ色なので、文字で分ける）。
    """

    kind = cell.get("cell")
    if kind == "skipped":
        return "飛ばし", ""
    if kind == "missing":
        return "なし", ""
    marks = [STATUS_LABELS[cell["status"]]] if cell.get("status") in STATUS_LABELS else []
    if cell.get("budget_cut"):
        marks.append(BUDGET_CUT_LABEL)
    if kind == "scored":
        if cell.get("violations"):
            marks.append(VIOLATION_LABEL)
        elif cell.get("syntax_error"):
            marks.append(SYNTAX_ERROR_LABEL)
        return fmt_pct(cell.get("score")), "・".join(marks)
    if not marks and cell.get("reason") in NO_ANSWER_REASON_LABELS:
        marks.append(NO_ANSWER_REASON_LABELS[cell["reason"]])
    return "答えなし", "・".join(marks)


def cell_tip(cell: dict[str, Any], model_label: str, item_label: str) -> str:
    main, sub = cell_texts(cell)
    lines = [main + (f"（{sub}）" if sub else ""), f"{model_label} / {item_label}"]
    status = cell.get("status")
    if status and status != "ok":
        lines.append(f"状態: {status}" + (f"（{STATUS_DESCRIPTIONS[status]}）" if status in STATUS_DESCRIPTIONS else ""))
    if cell.get("error"):
        lines.append(f"エラー: {cell['error'][:160]}")
    if cell.get("budget_cut"):
        lines.append("思考が予算に届いて打ち切られたあとの答え")
    if cell.get("reason"):
        lines.append(f"理由: {cell['reason']}")
    if cell.get("time_s") is not None:
        lines.append(f"時間: {fmt_time(cell['time_s'])}")
    if cell.get("tokens") is not None:
        lines.append(f"出力: {fmt_int(cell['tokens'])} トークン")
    if cell.get("thinking_tokens_est") is not None:
        lines.append(f"うち思考（推定）: {fmt_int(cell['thinking_tokens_est'])} トークン")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ 図（SVG）


def _bar_path(x: float, y: float, width: float, height: float, radius: float = 4.0) -> str:
    """基線側は角、先端だけ 4px の丸みの横棒。"""

    if width <= 0:
        return ""
    radius = min(radius, width, height / 2)
    return (f"M{x:.1f},{y:.1f} h{width - radius:.1f} a{radius},{radius} 0 0 1 {radius},{radius} "
            f"v{height - 2 * radius:.1f} a{radius},{radius} 0 0 1 {-radius},{radius} h{-(width - radius):.1f} z")


def hbar_chart(rows: list[dict[str, Any]], *, title: str, ticks: list[tuple[float, str]],
               scale, value_label, label_width: int = 250, plot_width: int = 430) -> str:
    """横棒。rows: {label, family, value, tip}。scale(value) は 0〜1 の位置。value が None なら「記録なし」。"""

    row_height, bar_height, top, bottom = 30, 16, 12, 30
    height = top + row_height * len(rows) + bottom
    width = label_width + plot_width + 90
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="{esc(title)}">']
    for position, label in ticks:
        x = label_width + scale(position) * plot_width
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{height - bottom + 4}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{height - bottom + 18}" text-anchor="middle">{esc(label)}</text>')
    parts.append(f'<line class="axis" x1="{label_width}" y1="{top - 4}" x2="{label_width}" y2="{height - bottom + 4}"/>')
    for index, row in enumerate(rows):
        y = top + index * row_height
        center = y + row_height / 2
        parts.append(f'<text class="label" x="{label_width - 10}" y="{center + 4:.1f}" text-anchor="end">'
                     f'{esc(row["label"])}</text>')
        value = row.get("value")
        if value is None:
            parts.append(f'<text class="muted" x="{label_width + 8}" y="{center + 4:.1f}">記録なし</text>')
            continue
        bar_width = max(0.0, scale(value)) * plot_width
        color = FAMILY_COLORS.get(row.get("family"), COLOR_NA)
        tip = esc(row.get("tip") or "")
        parts.append(f'<g class="mark" tabindex="0" data-tip="{tip}">'
                     f'<rect class="hit" x="{label_width}" y="{y + 2}" width="{plot_width}" height="{row_height - 4}"/>'
                     f'<path d="{_bar_path(label_width, center - bar_height / 2, max(bar_width, 1.5), bar_height)}" '
                     f'fill="{color}"/></g>')
        parts.append(f'<text class="value" x="{label_width + bar_width + 6:.1f}" y="{center + 4:.1f}">'
                     f'{esc(value_label(value))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _log_axis(times: list[float]) -> tuple[float, float, list[tuple[float, str]]]:
    candidates = [(10, "10 秒"), (30, "30 秒"), (60, "1 分"), (120, "2 分"), (300, "5 分"), (600, "10 分"),
                  (1200, "20 分"), (1800, "30 分"), (3600, "1 時間"), (7200, "2 時間"), (14400, "4 時間")]
    low = min(times) / 1.4
    high = max(times) * 1.25
    ticks = [(value, label) for value, label in candidates if low <= value <= high]
    return low, high, ticks


def time_bar_chart(rows: list[dict[str, Any]], *, title: str) -> str:
    times = [row["value"] for row in rows if row.get("value")]
    if not times:
        return '<p class="muted">時間の記録がない。</p>'
    low, high, ticks = _log_axis(times)

    def scale(value: float) -> float:
        return (math.log(value) - math.log(low)) / (math.log(high) - math.log(low))

    return hbar_chart(rows, title=title, ticks=ticks, scale=scale, value_label=fmt_time)


def _overlap(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    return width * height if width > 0 and height > 0 else 0.0


# 点の名前を置く候補（点からのずれ dx, dy と文字の揃え）。右・左・上・下を先に試し、だめなら上下へ 14px ずつ離す
LABEL_CANDIDATES = [(10, 4, "start"), (-10, 4, "end"), (0, -12, "middle"), (0, 20, "middle")] + [
    candidate for step in (1, 2, 3) for candidate in (
        (10, 4 - 14 * step, "start"), (10, 4 + 14 * step, "start"), (-10, 4 - 14 * step, "end"),
        (-10, 4 + 14 * step, "end"), (0, -12 - 14 * step, "middle"), (0, 20 + 14 * step, "middle"))]


def place_labels(points: list[tuple[float, float, str]], bounds: tuple[float, float, float, float],
                 char_width: float = 7.2) -> list[tuple[float, float, str, bool]]:
    """散布図の点の名前の位置を決める（x, y, text-anchor, 引き出し線が要るか）。

    ほかの名前・ほかの点・描く範囲（bounds = 左, 上, 右, 下）と重ならない最初の候補を選ぶ。どれも重なるときは、
    重なりの面積が最も小さい候補にする。込み合った点（近くに点が多いもの）から先に置く。
    """

    point_boxes = [(x - 8, y - 8, x + 8, y + 8) for x, y, _text in points]
    crowd = [sum(1 for other_x, other_y, _ in points if abs(other_x - x) < 90 and abs(other_y - y) < 30)
             for x, y, _text in points]
    order = sorted(range(len(points)), key=lambda index: -crowd[index])
    placed: list[tuple[float, float, float, float]] = []
    result: list[tuple[float, float, str, bool] | None] = [None] * len(points)
    for index in order:
        x, y, text = points[index]
        text_width = char_width * len(text) + 4
        best = None
        for rank, (dx, dy, anchor) in enumerate(LABEL_CANDIDATES):
            if anchor == "start":
                box = (x + dx, y + dy - 11, x + dx + text_width, y + dy + 3)
            elif anchor == "end":
                box = (x + dx - text_width, y + dy - 11, x + dx, y + dy + 3)
            else:
                box = (x - text_width / 2, y + dy - 11, x + text_width / 2, y + dy + 3)
            outside = (max(0.0, bounds[0] - box[0]) + max(0.0, box[2] - bounds[2])
                       + max(0.0, bounds[1] - box[1]) + max(0.0, box[3] - bounds[3]))
            penalty = (outside * 1000 + sum(_overlap(box, other) for other in placed)
                       + sum(_overlap(box, other) for other in point_boxes))
            if best is None or penalty < best[0]:
                best = (penalty, rank, box, dx, dy, anchor)
            if penalty == 0:
                break
        _penalty, rank, box, dx, dy, anchor = best
        placed.append(box)
        # 右・左・上・下の 4 つ以外（離して置いた名前）は、どの点の名前か分かるよう引き出し線を引く
        result[index] = (x + dx, y + dy, anchor, rank >= 4)
    return [entry for entry in result if entry is not None]


def scatter_chart(points: list[dict[str, Any]], *, title: str) -> str:
    """能力（縦、0〜100%）× 時間（横、対数）。点の名前は、ほかの名前・点・枠と重ならない位置に置く。"""

    usable = [point for point in points if point.get("time") and point.get("ability") is not None]
    if not usable:
        return '<p class="muted">散布図に載せる記録がない。</p>'
    # 上の余白は 100% の点の上に名前を置ける広さ、右の余白は右端の点の名前を左に回せば足りる広さ
    width, height = 720, 410
    left, right, top, bottom = 60, 30, 46, 50
    plot_width, plot_height = width - left - right, height - top - bottom
    low, high, ticks = _log_axis([point["time"] for point in usable])

    def x_of(value: float) -> float:
        return left + (math.log(value) - math.log(low)) / (math.log(high) - math.log(low)) * plot_width

    def y_of(value: float) -> float:
        return top + (1 - value) * plot_height

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="{esc(title)}">']
    for value in (0, 0.25, 0.5, 0.75, 1.0):
        y = y_of(value)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{value * 100:.0f}%</text>')
    for value, label in ticks:
        x = x_of(value)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{height - bottom + 18}" text-anchor="middle">{esc(label)}</text>')
    parts.append(f'<text class="axis-title" x="{left + plot_width / 2:.1f}" y="{height - 8}" text-anchor="middle">'
                 f'時間（対数。左ほど速い）</text>')
    parts.append(f'<text class="axis-title" x="14" y="{top + plot_height / 2:.1f}" text-anchor="middle" '
                 f'transform="rotate(-90 14 {top + plot_height / 2:.1f})">能力</text>')
    coordinates = [(x_of(point["time"]), y_of(point["ability"]), point["short"]) for point in usable]
    positions = place_labels(coordinates, (left + 2, 2, width - 4, height - bottom - 2))
    labels: list[str] = []
    for point, (x, y, text), (label_x, label_y, anchor, leader) in zip(usable, coordinates, positions):
        color = FAMILY_COLORS.get(point.get("family"), COLOR_NA)
        tip = esc(point.get("tip") or "")
        parts.append(f'<g class="mark" tabindex="0" data-tip="{tip}"><circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="12"/>'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}" stroke="var(--surface)" stroke-width="2"/></g>')
        if leader:
            # 引き出し線は名前の縦の中ほど（基線の 4px 上）まで
            parts.insert(1, f'<line class="leader" x1="{x:.1f}" y1="{y:.1f}" x2="{label_x:.1f}" y2="{label_y - 4:.1f}"/>')
        labels.append(f'<text class="point-label" x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="{anchor}">'
                      f'{esc(text)}</text>')
    parts.extend(labels)
    parts.append("</svg>")
    return "".join(parts)


def heatmap(models: list[dict[str, Any]], items: list[str], cells: dict[str, dict[str, dict[str, Any]]],
            *, title: str, item_labels: dict[str, str] | None = None) -> str:
    # 高さ 36: 上段の点数と下段の状態（上限・エラー・打切）の 2 行が入る
    cell_width, cell_height, gap, label_width, header = 64, 36, 2, 250, 30
    width = label_width + len(items) * (cell_width + gap) + 10
    height = header + len(models) * (cell_height + gap) + 6
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="{esc(title)}">']
    for column, item in enumerate(items):
        x = label_width + column * (cell_width + gap) + cell_width / 2
        parts.append(f'<text class="tick" x="{x:.1f}" y="{header - 10}" text-anchor="middle">'
                     f'{esc((item_labels or {}).get(item, item))}</text>')
    for row, model in enumerate(models):
        y = header + row * (cell_height + gap)
        parts.append(f'<rect x="{label_width - 16}" y="{y + cell_height / 2 - 5:.1f}" width="10" height="10" rx="2" '
                     f'fill="{FAMILY_COLORS.get(model["family"], COLOR_NA)}"/>')
        parts.append(f'<text class="label" x="{label_width - 22}" y="{y + cell_height / 2 + 4:.1f}" text-anchor="end">'
                     f'{esc(model["label"])}</text>')
        for column, item in enumerate(items):
            cell = cells.get(model["key"], {}).get(item) or {"cell": "missing", "score": 0.0}
            x = label_width + column * (cell_width + gap)
            fill = cell_fill(cell)
            ink = _ink_on(fill)
            main, sub = cell_texts(cell)
            tip = cell_tip(cell, model["label"], (item_labels or {}).get(item, item))
            center_x = x + cell_width / 2
            if sub:
                texts = (f'<text class="cell-text" x="{center_x}" y="{y + 15}" text-anchor="middle" fill="{ink}">'
                         f'{esc(main)}</text><text class="cell-sub" x="{center_x}" y="{y + 29}" text-anchor="middle" '
                         f'fill="{ink}">{esc(sub)}</text>')
            else:
                texts = (f'<text class="cell-text" x="{center_x}" y="{y + cell_height / 2 + 4:.1f}" text-anchor="middle" '
                         f'fill="{ink}">{esc(main)}</text>')
            parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(tip)}">'
                         f'<rect x="{x}" y="{y}" width="{cell_width}" height="{cell_height}" rx="3" fill="{fill}"/>'
                         f'{texts}</g>')
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------------------------------------ 表と部品


def family_legend() -> str:
    items = "".join(f'<span class="legend-item"><span class="swatch" style="background:{color}"></span>'
                    f'{esc(FAMILY_LABELS[family])}</span>' for family, color in FAMILY_COLORS.items())
    return f'<div class="legend" aria-label="系統の凡例">{items}</div>'


def grade_legend() -> str:
    entries = [(COLOR_OK, "正解・全部合格"), (_mix(COLOR_PARTIAL_LIGHT, COLOR_OK, 0.5), "部分点（濃いほど高い）"),
               (COLOR_NG, "誤り・0 点"), (COLOR_NA, "答えなし・飛ばし・記録なし")]
    items = "".join(f'<span class="legend-item"><span class="swatch" style="background:{color}"></span>{esc(label)}</span>'
                    for color, label in entries)
    marks = [f"{label} = {STATUS_DESCRIPTIONS[status]}" for status, label in STATUS_LABELS.items()]
    marks.append(f"{BUDGET_CUT_LABEL} = 思考が予算に届いて打ち切られたあとの答え（Strata）")
    marks.append("本文なし／コードなし = 答えの本文やコードのブロックが無かった")
    marks.append(f"{VIOLATION_LABEL} = 禁止の import・呼び出しがあり実行せず 0 点")
    marks.append(f"{SYNTAX_ERROR_LABEL} = 答えのコードが Python として読めない")
    return (f'<div class="legend" aria-label="採点の凡例">{items}</div>'
            f'<p class="caption">マスの下段の文字（状態）: {esc("、".join(marks))}。2 つ当てはまるときは「・」でつなぐ。</p>')


def medal(rank: int | None) -> str:
    if rank is None:
        return '<span class="muted">—</span>'
    color = MEDAL_COLORS.get(rank)
    if color:
        return f'<span class="medal" style="background:{color}" aria-label="{rank} 位">{rank}</span>'
    return f'<span class="rank">{rank}</span>'


def model_cell(model: dict[str, Any]) -> str:
    return (f'<span class="swatch" style="background:{FAMILY_COLORS.get(model["family"], COLOR_NA)}"></span>'
            f'{esc(model["label"])}')


def ranking_table(models: list[dict[str, Any]], suite: dict[str, Any], *, time_label: str) -> str:
    entries = suite["models"]
    ordered = sorted(models, key=lambda model: (entries[model["key"]].get("rank") is None,
                                                entries[model["key"]].get("rank") or 0))
    rows = []
    for model in ordered:
        entry = entries[model["key"]]
        rows.append(
            f'<tr><td class="num">{medal(entry.get("rank"))}</td><td>{model_cell(model)}</td>'
            f'<td>{esc(FAMILY_LABELS[model["family"]])}</td>'
            f'<td class="num">{fmt_pct(entry.get("ability"))}</td><td class="num">{fmt_time(entry.get("time_s"))}</td>'
            f'<td class="num">{fmt_score(entry.get("speed"))}</td><td class="num strong">{fmt_score(entry.get("overall"))}</td>'
            f'<td class="num">{fmt_rate(entry.get("tok_s"))}</td></tr>')
    return ('<table class="data"><thead><tr><th>順位</th><th>モデル</th><th>系統</th><th>能力</th>'
            f'<th>{esc(time_label)}</th><th>速度点</th><th>総合</th><th>tok/s（参考）</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def math3d_table(models: list[dict[str, Any]], suite: dict[str, Any]) -> str:
    rows = []
    for model in models:
        entry = suite["models"][model["key"]]
        runs = entry.get("runs") or []
        if not runs:
            rows.append(f'<tr><td>{model_cell(model)}</td><td colspan="9" class="muted">記録なし</td></tr>')
            continue
        for index, run in enumerate(runs):
            grade = run.get("grade") or {}
            cells = []
            for key in suite["items"]:
                symbol, color, label = GRADE_SYMBOLS[grade.get(key) if grade else None]
                cells.append(f'<td class="center"><span class="chip" style="background:{color}" '
                             f'aria-label="{label}">{symbol}</span></td>')
            used = "" if run.get("used") else ' class="unused"'
            name = model_cell(model) if index == 0 else ""
            rows.append(f'<tr{used}><td>{name}</td><td>{esc(run.get("label", ""))}</td>{"".join(cells)}'
                        f'<td class="num">{fmt_pct(run.get("score"))}</td><td class="num">{fmt_time(run.get("wall_s"))}</td>'
                        f'<td class="num">{fmt_int(run.get("tokens"))}</td><td class="num">{fmt_rate(run.get("tok_s"))}</td>'
                        f'<td class="note">{esc(run.get("note") or run.get("env") or "")}</td></tr>')
    return ('<table class="data"><thead><tr><th>モデル</th><th>回</th><th>(1)</th><th>(2)</th><th>(3)</th><th>(4)</th>'
            '<th>正答率</th><th>時間</th><th>出力トークン</th><th>tok/s</th><th>注記</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<p class="caption">灰色の行（参考）は能力の計算に使っていない回。○ 正解・× 誤り・— 答えなし。</p>')


def suite_rows(models, suite, *, key: str, tip_extra=None) -> list[dict[str, Any]]:
    rows = []
    for model in models:
        entry = suite["models"][model["key"]]
        value = entry.get(key)
        tip_lines = [fmt_pct(value) if key == "ability" else fmt_time(value), model["label"]]
        if tip_extra:
            tip_lines.extend(tip_extra(entry))
        rows.append({"label": model["label"], "family": model["family"], "value": value,
                     "tip": "\n".join(tip_lines)})
    return rows


# 散布図の点の名前（短く。正式な名前はツールチップと表にある）
SCATTER_SHORT_LABELS = {"sonnet": "Sonnet5.5", "opus": "Opus5.5", "qwen3.8-flash-next:IQ4_XS": "IQ4_XS",
                        "strata-flash-next:IQ3_S": "RVN IQ3_S", "strata-official:IQ3_XXS": "official IQ3_XXS"}


def scatter_points(models, suite) -> list[dict[str, Any]]:
    points = []
    for model in models:
        entry = suite["models"][model["key"]]
        short = SCATTER_SHORT_LABELS.get(model["key"], model["label"])
        points.append({"short": short, "family": model["family"], "time": entry.get("time_s"),
                       "ability": entry.get("ability"),
                       "tip": f"能力 {fmt_pct(entry.get('ability'))}・{fmt_time(entry.get('time_s'))}\n{model['label']}"})
    return points


def _labels(models: list[dict[str, Any]]) -> str:
    return "・".join(model["label"] for model in models)


SUITE_SHORT_NAMES = {"coding": "コーディング", "extra": "追加の 3 試験"}


# 作り直す前の版を保管した試験の、いまの版の言い方（天井効果の注記で、易しい版ではなく難しい版の結果だと分かるように）
ARCHIVE_SCOPES = {"archive-coding-v1-easy": ("coding", "難しい版（v2）のコーディングでも")}


def suite_scope(summary: dict[str, Any], suite_key: str) -> str:
    """天井効果の注記に入れる試験の言い方。"""

    for archive in summary.get("archives") or []:
        scope = ARCHIVE_SCOPES.get(archive["name"])
        if scope and scope[0] == suite_key:
            return scope[1]
    return f"{SUITE_SHORT_NAMES[suite_key]}の"


def ceiling_models(models: list[dict[str, Any]], suite: dict[str, Any]) -> list[dict[str, Any]]:
    """全問で全部合格したモデル（天井効果。この試験ではそのモデルどうしの能力の差が測れない）。"""

    return [model for model in models
            if suite["models"][model["key"]]["items"]
            and all(cell.get("all_passed") for cell in suite["models"][model["key"]]["items"].values())]


def ceiling_note(models: list[dict[str, Any]], suite: dict[str, Any], scope: str) -> str | None:
    """scope は試験の名前（例「難しい版（v2）のコーディングでも」）。概要の節でもどの試験の話か分かるように入れる。"""

    top = ceiling_models(models, suite)
    if not top:
        return None
    count = len(suite["items"])
    return (f"天井効果: {_labels(top)} は{scope} {count} 問すべてで全部合格した（能力 100%）。"
            f"{'この ' + str(len(top)) + ' つ' if len(top) > 1 else 'このモデル'}の順位の差は速さだけで、"
            "能力の差はこの試験では測れていない。")


def budget_cut_note(models: list[dict[str, Any]], suite: dict[str, Any], budget: int, item_labels,
                    suite_name: str) -> str | None:
    """思考が予算に届いて打ち切られた問（Strata）の注記。全問なら「どの問題も」とまとめる。suite_name は「コーディング」など。"""

    whole, partial = [], []
    for model in models:
        cells = suite["models"][model["key"]]["items"]
        cut = [item for item in suite["items"] if (cells.get(item) or {}).get("budget_cut")]
        if not cut:
            continue
        if len(cut) == len(suite["items"]):
            whole.append(model)
        else:
            partial.append(f"{model['label']} の {'・'.join((item_labels or {}).get(item, item) for item in cut)}")
    if not whole and not partial:
        return None
    lines = []
    if whole:
        lines.append(f"{_labels(whole)} の{suite_name}の答えは、どの問題も思考が予算 {budget:,} トークンで"
                     "打ち切られたあとのもの。")
    if partial:
        lines.append(f"{suite_name}で思考が予算 {budget:,} トークンで打ち切られたあとの答え: {'、'.join(partial)}。")
    lines.append(f"Strata は予算に届くと思考の最後に「{REASONING_WRAP_UP_MARK}」を差し込み、答えを書かせる"
                 f"（マスの下段の「{BUDGET_CUT_LABEL}」）。")
    return "".join(lines)


def status_list(models: list[dict[str, Any]], suite: dict[str, Any], item_labels) -> str:
    """状態が ok でない問（上限・エラー・時間切れ・無応答）を文字で並べる。色が見分けられなくても読めるように。"""

    lines = []
    for model in models:
        cells = suite["models"][model["key"]]["items"]
        for item in suite["items"]:
            cell = cells.get(item) or {}
            status = cell.get("status")
            if status not in STATUS_LABELS:
                continue
            answer = f"答えあり・{fmt_pct(cell.get('score'))}" if cell.get("cell") == "scored" else "答えなし・0 点"
            lines.append(f"{model['label']} の {(item_labels or {}).get(item, item)}: {STATUS_LABELS[status]}"
                         f"（{STATUS_DESCRIPTIONS[status]}）。{answer}")
    if not lines:
        return ""
    return ('<p class="caption">状態が ok でない問:</p><ul class="notes">'
            + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>")


def _range(values: list[float], digits: int, unit: str = "") -> str:
    if not values:
        return "—"
    low, high = min(values), max(values)
    if round(low, digits) == round(high, digits):
        return f"{low:.{digits}f}{unit}"
    return f"{low:.{digits}f}〜{high:.{digits}f}{unit}"


def thinking_table(models: list[dict[str, Any]], suite: dict[str, Any]) -> str:
    """ローカルのモデルの思考の量と中身（問ごとの値の最小〜最大）。Claude は思考を返さないので載せない。"""

    rows = []
    for model in models:
        if model["backend"] == "claude":
            continue
        entry = suite["models"][model["key"]]
        stats = [cell["thinking_stats"] for cell in entry["items"].values() if cell.get("thinking_stats")]
        rows.append(
            f'<tr><td>{model_cell(model)}</td><td class="num">{fmt_int(entry.get("tokens_total"))}</td>'
            f'<td class="num">{fmt_int(entry.get("thinking_tokens_est_total"))}</td>'
            f'<td class="num">{entry.get("n_budget_cut", 0)} / {len(entry["items"])}</td>'
            f'<td class="num">{_range([stat["question_per_10k"] for stat in stats], 1)}</td>'
            f'<td class="num">{_range([stat["maybe_per_10k"] for stat in stats], 1)}</td>'
            f'<td class="num">{_range([stat["repeated_line_pct"] for stat in stats], 1, "%")}</td></tr>')
    return ('<table class="data"><thead><tr><th>モデル</th><th>出力トークン（合計）</th><th>うち思考（推定・合計）</th>'
            '<th>予算で打切</th><th>「?」/ 1 万字</th><th>「maybe」/ 1 万字</th><th>同じ行の再出現</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            f'<p class="caption">{esc(THINKING_EST_NOTE)}「?」と「maybe」（大文字小文字を区別しない）は思考 1 万字あたりの数、'
            f'同じ行の再出現は {REPEAT_LINE_MIN_CHARS} 字以上の行のうち、それより前に同じ行が出ていた割合。どれも問ごとの値の'
            '最小〜最大。「?」と「maybe」が多いのは仕様の読みを疑い続ける型、再出現が多いのは同じ文を繰り返す型の目安。'
            'Claude は思考を返さないので載せない。</p>')


def archive_block(summary: dict[str, Any], models: list[dict[str, Any]], suite_key: str) -> str:
    """作り直す前の試験（archive-*）の点数。順位には使っていないことを明記する。"""

    parts = []
    for archive in summary.get("archives") or []:
        results = (archive.get("suites") or {}).get(suite_key)
        if not results:
            continue
        note = ARCHIVE_NOTES.get(archive["name"], "作り直す前の試験の記録。順位には使っていない。")
        rows = "".join(
            f'<tr><td>{model_cell(model)}</td><td class="num">{results[model["key"]]["n_items"]}</td>'
            f'<td class="num">{results[model["key"]]["n_all_passed"]}</td>'
            f'<td class="num">{fmt_pct(results[model["key"]]["ability"])}</td></tr>'
            for model in models if model["key"] in results)
        parts.append(f'<details><summary>{esc(note)}（記録は {esc(archive["path"])}）</summary>'
                     '<table class="data"><thead><tr><th>モデル</th><th>流した問</th><th>全部合格</th><th>能力</th></tr>'
                     f'</thead><tbody>{rows}</tbody></table></details>')
    return "".join(parts)


def archive_notes(summary: dict[str, Any], suite_key: str) -> list[str]:
    return [f"{ARCHIVE_NOTES.get(archive['name'], '作り直す前の試験の記録。順位には使っていない。')}"
            f"記録は {archive['path']} に保管してある。"
            for archive in summary.get("archives") or [] if (archive.get("suites") or {}).get(suite_key)]


# ------------------------------------------------------------------------------------------------ 節


def section_overview(summary: dict[str, Any], models: list[dict[str, Any]]) -> str:
    tiles = []
    by_key = {model["key"]: model for model in models}
    for suite_key in ("math3d", "coding", "extra"):
        suite = summary["suites"][suite_key]
        winners = [key for key, entry in suite["models"].items() if entry.get("rank") == 1]
        names = "、".join(by_key[key]["label"] for key in winners) or "—"
        overall_values = [entry["overall"] for entry in suite["models"].values() if entry.get("overall") is not None]
        best = f"総合 {max(overall_values):.3f}" if overall_values else "記録なし"
        tiles.append(f'<div class="tile"><div class="tile-label">{esc(suite["label"])}の総合 1 位</div>'
                     f'<div class="tile-value">{esc(names)}</div><div class="tile-sub">{esc(best)}</div></div>')
    limits = summary["limits"]
    coding = summary["suites"]["coding"]
    coding_labels = {item: item.upper() for item in coding["items"]}
    notes = [
        "試行の回数は少ない。3D は 1〜3 回（Claude は 3 回）、コーディングと追加の試験は各問 1 回。サンプリングありなので、"
        "同じモデルでも回によって結果が変わりうる。",
        "ローカルの 3D は既存の記録（Documents/3D問題_実施モデル一覧_2026-10-08.md）を使い、Claude だけ今回 3 回流した。",
        "strata-flash-coder:IQ1_M (Coder) は 2026-10-09 に追加で計測した。条件はほかの Strata と同じ。3D は公式版と同じ条件"
        "（effort high・思考の予算なし・生成の上限 65,536 トークン・temperature 1.0）で 2 回流した。",
        "Claude の時間は Agent の duration（Agent の所要時間。API の待ちと通信を含む）。機体の中で動くローカルの時間とは"
        "意味が違う。Claude の tok/s は不明。",
        f"ローカルの生成の上限: コーディング {limits['coding']['max_tokens']:,}・追加 {limits['extra']['max_tokens']:,} トークン"
        f"（Strata の思考予算 {limits['coding']['reasoning_budget_tokens']:,} / {limits['extra']['reasoning_budget_tokens']:,}）。"
        "上限で答えが出なかった問は 0 点。",
        f"1 つのモデルの累計時間が {summary['model_time_budget_s'] // 60} 分を超えたら、残りの問を飛ばした（灰色）。",
        "tok/s は参考の列。順位は能力と時間（対数）だけで決める（下の式）。",
        THINKING_EST_NOTE,
    ]
    # コーディングの読み方に効く注記（天井効果・Strata の予算での打ち切り・作り直す前の版）。詳しくは節 3
    notes.extend(note for note in (
        ceiling_note(models, coding, suite_scope(summary, "coding")),
        budget_cut_note(models, coding, limits["coding"]["reasoning_budget_tokens"], coding_labels, "コーディング"),
    ) if note)
    notes.extend(archive_notes(summary, "coding"))
    # 比較から外したモデル（results/<日付>/excluded.json）。読み手が最初に気づくよう、注記の先頭に置く
    notes[0:0] = [f"{entry['label']} は比較の対象から外した（{entry['reason']}）。計測の記録は "
                  f"tools/model-eval/results/{summary['date']}/ に残してある。"
                  for entry in summary.get("excluded") or []]
    notes.append("状態が error（エラー）・length（上限）などの問は、表のマスの下段に文字でも示す（色だけで区別させない）。")
    if summary.get("missing"):
        notes.append(f"足りない記録が {len(summary['missing'])} 件ある（付録の一覧）。")
    return (f'<div class="tiles">{"".join(tiles)}</div><ul class="notes">'
            + "".join(f"<li>{esc(note)}</li>" for note in notes) + "</ul>"
            + f'<h3>順位の式</h3>{formula_block(summary)}')


def formula_block(summary: dict[str, Any]) -> str:
    formulas = "".join(f"<li>{esc(text)}</li>" for text in summary["formulas"].values())
    return (f'<ul class="notes formulas">{formulas}</ul>'
            '<p class="caption">時間 T: 3D は全問に答えるまでの時間の中央値、コーディングと追加は 1 問あたりの時間の中央値。'
            'Ollama はロード時間を除く。Claude は Agent の duration（複数問をまとめて頼んだ回は問の数で割る）。'
            '時間の幅が広い（数秒〜1 時間）ので、速度点は対数で比べる。時間の上限で飛ばした問とエラーの問は、時間の中央値に入れない。</p>')


def section_targets(summary: dict[str, Any], models: list[dict[str, Any]]) -> str:
    rows = "".join(f'<tr><td>{model_cell(model)}</td><td>{esc(FAMILY_LABELS[model["family"]])}</td>'
                   f'<td>{esc(model.get("notes") or "")}</td></tr>' for model in models)
    limits = summary["limits"]
    conditions = [
        ("thinking", "すべての試験であり。Ollama は think:true、Strata は reasoning_effort high、Claude は effort xhigh"),
        ("サンプリング", "各サーバーの既定（Ollama は各 Modelfile）。Strata だけ temperature 1.0 / top_p 0.95 / top_k 20 を送る"),
        ("コーディング", f"6 問 × 1 回。上限 {limits['coding']['max_tokens']:,} トークン・1 要求 "
                     f"{limits['coding']['request_timeout_s'] // 60} 分。隠しテストの合格率で採点"),
        ("追加の試験", f"3 種 × 3 問 × 1 回。上限 {limits['extra']['max_tokens']:,} トークン・1 要求 "
                   f"{limits['extra']['request_timeout_s'] // 60} 分"),
        ("打ち切り", f"{summary['stall_timeout_s']} 秒のあいだ何も届かなければ stall として打ち切り（0 点）"),
        ("Claude", "メインが Agent ツールで起動（ツールやコードの実行は使わせない）。採点はローカルと同じ隠しテスト・採点器"),
    ]
    condition_rows = "".join(f"<tr><th>{esc(name)}</th><td>{esc(text)}</td></tr>" for name, text in conditions)
    return (family_legend() + '<table class="data"><thead><tr><th>モデル</th><th>系統</th><th>注記</th></tr></thead>'
            f'<tbody>{rows}</tbody></table><h3>条件</h3><table class="data kv"><tbody>{condition_rows}</tbody></table>')


def section_math3d(summary: dict[str, Any], models: list[dict[str, Any]]) -> str:
    suite = summary["suites"]["math3d"]
    notes = "".join(f"<li>{esc(model['label'])}: {esc(suite['models'][model['key']]['note'])}</li>"
                    for model in models if suite["models"][model["key"]].get("note"))
    ability = hbar_chart(suite_rows(models, suite, key="ability",
                                    tip_extra=lambda entry: [f"回数 {entry.get('n_runs')}"]),
                         title="3D の能力", ticks=[(value, f"{value * 100:.0f}%") for value in (0, .25, .5, .75, 1)],
                         scale=lambda value: value, value_label=fmt_pct)
    times = time_bar_chart(suite_rows(models, suite, key="time_s"), title="3D の時間（中央値・対数）")
    return (
        '<h3>採点（○×—）</h3>' + math3d_table(models, suite)
        + (f'<ul class="notes">{notes}</ul>' if notes else "")
        + f'<h3>能力（正答率の平均）</h3>{family_legend()}{ability}'
        + f'<h3>全問に答えるまでの時間（中央値・対数の目盛り）</h3>{times}'
        + '<p class="caption">ローカルの時間は既存の記録の値（Open WebUI 経由の回はロード時間を含む可能性がある）。'
          'Claude は Agent の duration。</p>'
        + f'<h3>能力 × 時間</h3>{scatter_chart(scatter_points(models, suite), title="3D の能力と時間")}'
        + '<h3>総合順位</h3>' + ranking_table(models, suite, time_label="時間 T（中央値）")
    )


def section_scored_suite(summary: dict[str, Any], models: list[dict[str, Any]], suite_key: str) -> str:
    suite = summary["suites"][suite_key]
    cells = {key: entry["items"] for key, entry in suite["models"].items()}
    labels = {item: item.upper() for item in suite["items"]} if suite_key == "coding" else None
    budget = summary["limits"][suite_key]["reasoning_budget_tokens"]
    # 読み方の注記（天井効果・予算での打ち切り・作り直す前の版）。どれも記録から決まり、当てはまらなければ出さない
    notes = [note for note in (ceiling_note(models, suite, suite_scope(summary, suite_key)),
                               budget_cut_note(models, suite, budget, labels, SUITE_SHORT_NAMES[suite_key])) if note]
    notes.extend(archive_notes(summary, suite_key))
    parts = []
    if notes:
        parts.append('<ul class="notes callout">' + "".join(f"<li>{esc(note)}</li>" for note in notes) + "</ul>")
    parts.append(f'<h3>モデル × 問の点数</h3>{grade_legend()}'
                 + heatmap(models, suite["items"], cells, title=f"{suite['label']}の点数", item_labels=labels)
                 + status_list(models, suite, labels))
    if suite_key == "coding":
        parts.append(f'<h3>思考の量と中身（ローカル）</h3>{thinking_table(models, suite)}')
        parts.append(archive_block(summary, models, suite_key))
    if suite_key == "extra":
        kind_rows = []
        for model in models:
            scores = suite["models"][model["key"]].get("kind_scores") or {}
            kind_rows.append(f"<tr><td>{model_cell(model)}</td>"
                             + "".join(f'<td class="num">{fmt_pct(scores.get(kind))}</td>' for kind in suite["kinds"])
                             + f'<td class="num strong">{fmt_pct(suite["models"][model["key"]].get("ability"))}</td></tr>')
        headers = "".join(f"<th>{esc(suite['kind_labels'][kind])}</th>" for kind in suite["kinds"])
        parts.append(f'<h3>種類ごとの平均</h3><table class="data"><thead><tr><th>モデル</th>{headers}<th>全体</th></tr>'
                     f'</thead><tbody>{"".join(kind_rows)}</tbody></table>')
    ability = hbar_chart(
        suite_rows(models, suite, key="ability",
                   tip_extra=lambda entry: [f"全部合格 {entry.get('n_all_passed')} 問・答えあり {entry.get('n_answered')} 問"]),
        title=f"{suite['label']}の能力", ticks=[(value, f"{value * 100:.0f}%") for value in (0, .25, .5, .75, 1)],
        scale=lambda value: value, value_label=fmt_pct)
    parts.append(f'<h3>能力（問ごとの点数の平均）</h3>{family_legend()}{ability}')
    parts.append('<h3>1 問あたりの時間（中央値・対数の目盛り）</h3>'
                 + time_bar_chart(suite_rows(models, suite, key="time_s"), title=f"{suite['label']}の時間"))
    parts.append(f'<h3>能力 × 時間</h3>{scatter_chart(scatter_points(models, suite), title=suite["label"])}')
    parts.append('<h3>総合順位</h3>' + ranking_table(models, suite, time_label="1 問の時間 T（中央値）"))
    return "".join(parts)


def section_findings(findings: dict[str, Any] | None) -> str:
    if not findings:
        return '<p class="muted">所見はまだ書かれていない（results/&lt;日付&gt;/findings.json に facts と opinions を書いて作り直す）。</p>'
    facts = "".join(f"<li>{esc(line)}</li>" for line in findings.get("facts", []))
    opinions = "".join(f"<li>{esc(line)}</li>" for line in findings.get("opinions", []))
    return f'<h3>事実</h3><ul class="notes">{facts}</ul><h3>意見（解釈）</h3><ul class="notes">{opinions}</ul>'


def section_appendix(summary: dict[str, Any]) -> str:
    data_paths = [
        ("ローカルの記録", f"tools/model-eval/results/{summary['date']}/local/<モデル>/<試験>/<問>-run1.json"),
        ("Claude の記録", f"tools/model-eval/results/{summary['date']}/claude/<sonnet|opus>/<試験>/<問>-run<n>.json"),
        ("3D の既存記録", f"tools/model-eval/results/{summary['date']}/math3d_local.json（出典 Documents/3D問題_実施モデル一覧_2026-10-08.md）"),
        ("集計", f"tools/model-eval/results/{summary['date']}/summary.json"),
        ("問題と隠しテスト", "tools/model-eval/suites/"),
    ]
    # 作り直す前の版（順位に使っていない）の保管場所
    data_paths.extend((f"保管（{archive['name']}）", f"{archive['path']}（順位には使っていない）")
                      for archive in summary.get("archives") or [])
    path_rows = "".join(f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td></tr>" for name, path in data_paths)
    problems = []
    if MATH3D_PROBLEM.exists():
        problems.append(("3D 数学（TestData/数学難問-三次元空間-TEST.md）", MATH3D_PROBLEM.read_text(encoding="utf-8")))
    for item in common.CODING_ITEMS:
        problems.append((f"コーディング {item.upper()}（共通の指示 + 問題）", common.build_prompt("coding", item)))
    for kind, items in common.EXTRA_KINDS.items():
        for item in items:
            text = common.build_prompt("extra", item)
            if kind == "needle":
                head, _, tail = text.partition('"""\n')
                body, _, question = tail.partition('\n"""')
                text = f'{head}"""\n{body[:300]}…（中略。資料は全部で {len(body):,} 文字）\n"""{question}'
            problems.append((f"追加 {common.EXTRA_KIND_LABELS[kind]} {item}", text))
    details = "".join(f"<details><summary>{esc(name)}</summary><pre>{esc(text)}</pre></details>" for name, text in problems)
    missing = "".join(f"<li>{esc(line)}</li>" for line in summary.get("missing", []))
    invalid = "".join(f"<li>{esc(line)}</li>" for line in summary.get("claude_invalid_runs", []))
    return (f'<h3>式</h3>{formula_block(summary)}'
            f'<h3>生データの場所</h3><table class="data kv"><tbody>{path_rows}</tbody></table>'
            + (f'<h3>足りない記録</h3><ul class="notes">{missing}</ul>' if missing else "")
            + (f'<h3>無効にした Claude の回（ツールを使った）</h3><ul class="notes">{invalid}</ul>' if invalid else "")
            + f'<h3>問題文</h3>{details}')


# ------------------------------------------------------------------------------------------------ 組み立て


STYLE = """
.viz-root{color-scheme:light;--surface:#fcfcfb;--surface-2:#f3f3f1;--grid:#e6e5e1;--axis:#bdbcb6;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#76756f;}
body{margin:0;background:var(--surface);color:var(--text-primary);
font-family:"Noto Sans JP","Hiragino Sans","Yu Gothic UI",system-ui,sans-serif;line-height:1.6}
main{max-width:1080px;margin:0 auto;padding:24px 20px 80px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.3rem;margin:40px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--grid)}
h3{font-size:1.05rem;margin:24px 0 8px}
.sub,.caption,.muted{color:var(--text-secondary)}.caption{font-size:.85rem;margin:4px 0 0}.muted{color:var(--text-muted)}
nav ol{display:flex;flex-wrap:wrap;gap:4px 16px;padding-left:20px;margin:8px 0}
.tiles{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.tile{flex:1 1 220px;background:var(--surface-2);border-radius:8px;padding:12px 16px}
.tile-label{font-size:.85rem;color:var(--text-secondary)}.tile-value{font-size:1.25rem;font-weight:600}
.tile-sub{font-size:.85rem;color:var(--text-muted)}
.notes li{margin:2px 0}
table.data{border-collapse:collapse;width:100%;margin:8px 0;font-size:.9rem}
table.data th,table.data td{border-bottom:1px solid var(--grid);padding:5px 8px;text-align:left;vertical-align:middle}
table.data thead th{color:var(--text-secondary);font-weight:600;background:var(--surface-2)}
table.kv th{width:9em;color:var(--text-secondary);font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td.center{text-align:center}
td.strong{font-weight:700}td.note{color:var(--text-secondary);font-size:.85rem}
tr.unused td{color:var(--text-muted);background:var(--surface-2)}
.swatch{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:baseline}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:.85rem;color:var(--text-secondary);margin:4px 0 8px}
.chip{display:inline-block;min-width:22px;border-radius:4px;color:#fff;font-weight:700;text-align:center;line-height:22px}
.medal{display:inline-block;width:24px;height:24px;border-radius:12px;color:#fff;font-weight:700;text-align:center;line-height:24px}
.rank{display:inline-block;width:24px;text-align:center}
svg.chart{display:block;max-width:100%;height:auto;margin:4px 0;font-size:12px}
svg .grid{stroke:var(--grid);stroke-width:1}svg .axis{stroke:var(--axis);stroke-width:1}
svg .tick,svg .axis-title{fill:var(--text-secondary)}svg .label{fill:var(--text-primary)}
svg .value,svg .point-label{fill:var(--text-secondary)}svg .leader{stroke:var(--axis);stroke-width:1}svg .muted{fill:var(--text-muted)}
svg .cell-text{font-size:11px;font-weight:600;pointer-events:none}
svg .cell-sub{font-size:9.5px;font-weight:600;pointer-events:none}
ul.callout{background:var(--surface-2);border-radius:8px;padding:8px 12px 8px 28px}
svg .hit{fill:transparent}svg .mark{cursor:default;outline:none}
svg .mark:hover>path,svg .mark:focus>path,svg .mark:hover>rect:not(.hit),svg .mark:focus>rect:not(.hit),
svg .mark:hover>circle:not(.hit),svg .mark:focus>circle:not(.hit){filter:brightness(1.15)}
svg .mark:focus>rect:not(.hit),svg .mark:focus>circle:not(.hit){stroke:var(--text-primary);stroke-width:1.5}
details{margin:6px 0}summary{cursor:pointer;color:var(--text-secondary)}
pre{white-space:pre-wrap;background:var(--surface-2);padding:10px;border-radius:6px;font-size:.82rem}
#tip{position:fixed;pointer-events:none;background:#fff;border:1px solid var(--grid);border-radius:6px;padding:6px 10px;
box-shadow:0 2px 8px rgba(0,0,0,.12);font-size:.82rem;color:var(--text-secondary);max-width:320px;z-index:10}
#tip .tip-value{color:var(--text-primary);font-weight:700;font-size:.95rem}
@media print{#tip{display:none}}
"""

SCRIPT = """
(function(){
  var tip=document.getElementById('tip');
  function show(element,x,y){
    tip.textContent='';
    element.getAttribute('data-tip').split('\\n').forEach(function(line,index){
      var row=document.createElement('div');row.textContent=line;if(index===0){row.className='tip-value';}tip.appendChild(row);
    });
    tip.hidden=false;
    var width=tip.offsetWidth,height=tip.offsetHeight;
    var left=Math.min(x+14,window.innerWidth-width-8),top=y+14;
    if(top+height>window.innerHeight-8){top=y-height-14;}
    tip.style.left=left+'px';tip.style.top=top+'px';
  }
  function hide(){tip.hidden=true;}
  document.querySelectorAll('[data-tip]').forEach(function(element){
    element.addEventListener('pointermove',function(event){show(element,event.clientX,event.clientY);});
    element.addEventListener('pointerleave',hide);
    element.addEventListener('focus',function(){var box=element.getBoundingClientRect();show(element,box.right,box.top);});
    element.addEventListener('blur',hide);
  });
})();
"""


def build_html(summary: dict[str, Any], findings: dict[str, Any] | None = None) -> str:
    models = summary["models"]
    sections = [
        ("s0", "0. 概要と注意", section_overview(summary, models)),
        ("s1", "1. 対象と条件", section_targets(summary, models)),
        ("s2", "2. 頭の良さ（3D 数学）", section_math3d(summary, models)),
        ("s3", "3. コーディング（6 問・隠しテスト）", section_scored_suite(summary, models, "coding")),
        ("s4", "4. 追加の 3 試験（指示追従・長文検索・JSON）", section_scored_suite(summary, models, "extra")),
        ("s5", "5. 所見", section_findings(findings)),
        ("s6", "6. 付録（式・生データ・問題文）", section_appendix(summary)),
    ]
    toc = "".join(f'<li><a href="#{anchor}">{esc(title)}</a></li>' for anchor, title, _body in sections)
    body = "".join(f'<section id="{anchor}"><h2>{esc(title)}</h2>{content}</section>'
                   for anchor, title, content in sections)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>AI モデル評価 {esc(summary["date"])}</title><style>{STYLE}</style></head>'
        '<body class="viz-root"><main>'
        f'<h1>{len(summary["models"])} の AI の比較評価（3D 数学・コーディング・追加 3 試験）</h1>'
        f'<p class="sub">評価日 {esc(summary["date"])}・集計 {esc(summary["generated_at"])}・'
        'tools/model-eval/build_report.py が summary.json から生成（手で書き換えない）</p>'
        f'<nav aria-label="目次"><ol>{toc}</ol></nav>{body}</main>'
        f'<div id="tip" role="tooltip" hidden></div><script>{SCRIPT}</script></body></html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", default=None, help=f"既定 results/{common.DEFAULT_DATE}/summary.json")
    parser.add_argument("--findings", default=None, help="既定 summary と同じ場所の findings.json（無ければ空欄）")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    summary_path = Path(args.summary) if args.summary else common.results_dir_for(None) / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    findings_path = Path(args.findings) if args.findings else summary_path.parent / "findings.json"
    findings = json.loads(findings_path.read_text(encoding="utf-8")) if findings_path.exists() else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(summary, findings), encoding="utf-8")
    print(f"{out} を書いた（{out.stat().st_size:,} バイト）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
