#!/usr/bin/env python3
"""2026-10-18 の評価（難しいコーディング 6 問・数学 3 問）の HTML を summary.json から作る。

  summarize.py --results-dir results/2026-10-18 --suites coding_v3,math --no-math3d
  build_report_hard.py                       # results/2026-10-18/summary.json → Documents/AIモデル評価_2026-10-18.html
  build_report_hard.py --summary work/x/summary.json --out work/x/report.html

表・図・色の部品は build_report.py のものを使う（1 ファイルで完結、外部参照なし）。所見は results/<日付>/findings.json
（facts・opinions）があれば載せる。HTML は手で書き換えない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import build_report as br  # noqa: E402
from evallib import common, progress  # noqa: E402

DATE = "2026-10-18"
DEFAULT_SUMMARY = common.RESULTS_ROOT / DATE / "summary.json"
DEFAULT_OUT = common.REPO_DIR / "Documents" / f"AIモデル評価_{DATE}.html"
SUITES = ("coding_v3", "math")
ITEM_TITLES = {
    "h1": "H1 3 次元凸包", "h2": "H2 最短の編集スクリプト", "h3": "H3 型推論", "h4": "H4 最良の有理近似",
    "h5": "H5 正規表現の最小 DFA", "h6": "H6 敷き詰めの数", "m1": "M1 正四面体のまわり", "m2": "M2 2 本の線分の差",
    "m3": "M3 立方体の中の点",
}
br.SUITE_SHORT_NAMES.update({"coding_v3": "難しいコーディング", "math": "数学", "hard": "全 9 問"})
esc = br.esc


def item_label(item: str) -> str:
    return item.upper()


def verdict_text(verdict: str, labels: dict[str, str] | None = None) -> str:
    if labels and verdict in labels:
        return f"{labels[verdict]} が上"
    return {"opus": "Opus が上", "sonnet": "Sonnet が上", "同じ": "同じ点", "判定できない": "差は判定できない",
            "比べられない": "比べられない"}.get(verdict, verdict)


def one_budget_text(value: float) -> str:
    return "上限なし" if value >= progress.UNLIMITED_BUDGET_MIN else f"{value:g} 分"


def budget_text(budgets: dict[str, Any], key: str) -> str:
    """モデルに渡した時間の上限。途中で変えたモデルは「70 分 → 上限なし」。古い summary（1 つの数）も読む。"""

    if key not in budgets:
        return "—"
    values = budgets[key] if isinstance(budgets[key], list) else [budgets[key]]
    return " → ".join(one_budget_text(float(value)) for value in values)


def scores_text(scores: list[float]) -> str:
    return "・".join(br.fmt_pct(score) for score in scores) if scores else "—"


# ------------------------------------------------------------------------------------------------ 節


def section_overview(summary: dict[str, Any], models: list[dict[str, Any]]) -> str:
    by_key = {model["key"]: model for model in models}
    tiles = []
    for suite_key in ("hard",) + SUITES:
        suite = summary["suites"][suite_key]
        winners = [key for key, entry in suite["models"].items() if entry.get("rank") == 1]
        names = "、".join(by_key[key]["label"] for key in winners) or "—"
        best = [entry["overall"] for entry in suite["models"].values() if entry.get("overall") is not None]
        tiles.append(f'<div class="tile"><div class="tile-label">{esc(suite["label"])}の総合 1 位</div>'
                     f'<div class="tile-value">{esc(names)}</div>'
                     f'<div class="tile-sub">{esc(f"総合 {max(best):.3f}" if best else "記録なし")}</div></div>')
    comparisons = summary.get("claude_comparisons") or ([dict(summary["claude_comparison"], effort="xhigh")]
                                                        if summary.get("claude_comparison") else [])
    for compare in comparisons:
        totals = compare["run_totals"]
        sonnet_key, opus_key = (key for key in totals)
        labels = {sonnet_key: "Sonnet", opus_key: "Opus"}
        tiles.append(f'<div class="tile"><div class="tile-label">Sonnet と Opus（effort {esc(compare["effort"])}、9 問の合計点）</div>'
                     f'<div class="tile-value">{esc(verdict_text(compare["total_verdict"], labels))}</div>'
                     f'<div class="tile-sub">Sonnet {esc(" / ".join(f"{value:.2f}" for value in totals[sonnet_key]))}・'
                     f'Opus {esc(" / ".join(f"{value:.2f}" for value in totals[opus_key]))}（回ごと、9 点満点）</div></div>')
    limits = summary["limits"]["coding_v3"]
    budgets = summary.get("model_budgets_min") or {}
    first_budgets = sorted({float(values[0] if isinstance(values, list) else values) for values in budgets.values()})
    reruns = summary.get("budget_reruns") or []
    rerun_text = "、".join(f"{entry['label']} {len(entry['items'])} 問" for entry in reruns)
    notes = [
        "前回（2026-10-08）は Sonnet と Opus がすべての試験で満点になり、能力の差が測れなかった。今回は差が付くように、"
        "長い仕様・計算量の要求・退化した入力を含む難しいコーディング 6 問と、数で採点する数学 3 問を新しく作った。",
        "試行の回数: Claude 8 種（Sonnet・Opus × effort xhigh・high・medium・low）は各問 3 回、ローカルは各問 1 回（利用者の決定）。"
        "サンプリングありなので、1 回の結果は揺れうる。",
        "Claude の時間は Agent の duration（API の待ちと通信を含む）。機体の中で動くローカルの時間とは意味が違う。",
        f"ローカルの生成の上限は {limits['max_tokens']:,} トークン（Strata の思考予算 {limits['reasoning_budget_tokens']:,}）、"
        f"1 要求 {limits['request_timeout_s'] // 60} 分。上限で答えが出なかった問は 0 点。",
        ("1 つのモデルの累計時間の上限は、はじめ "
         + ("、".join(f"{value:g}" for value in first_budgets) if first_budgets else "70")
         + " 分（全行程を 18 時間に収めるための締切から逆算）で流した。その後、利用者の指示で期限と上限を外し、上限で飛ばされた問"
         + (f"（{rerun_text}）" if rerun_text else "")
         + "を上限なしで流し直した。表の点は流し直した後のもの（70 分の時点の点は 6 節）。"
           "上限で飛ばした問が残っていれば灰色・0 点。"),
        "数学は「答え(a): 値」の行を機械で読み、相対誤差 1e-5 以内で正解（有効数字 6 桁に正しく丸めた値は必ず入る）。",
        br.THINKING_EST_NOTE,
    ]
    notes[0:0] = [f"{entry['label']} は比較の対象から外した（{entry['reason']}）。" for entry in summary.get("excluded") or []]
    for suite_key in SUITES:
        note = br.ceiling_note(models, summary["suites"][suite_key], br.SUITE_SHORT_NAMES[suite_key] + "の")
        if note:
            notes.append(note)
    if summary.get("missing"):
        notes.append(f"足りない記録が {len(summary['missing'])} 件ある（付録の一覧）。")
    return (f'<div class="tiles">{"".join(tiles)}</div><ul class="notes">'
            + "".join(f"<li>{esc(note)}</li>" for note in notes) + "</ul>"
            + f'<h3>順位の式</h3>{br.formula_block(summary)}')


def section_targets(summary: dict[str, Any], models: list[dict[str, Any]]) -> str:
    budgets = summary.get("model_budgets_min") or {}
    rows = "".join(f'<tr><td>{br.model_cell(model)}</td><td>{esc(br.FAMILY_LABELS[model["family"]])}</td>'
                   f'<td class="num">{esc(budget_text(budgets, model["key"]))}</td>'
                   f'<td>{esc(model.get("notes") or "")}</td></tr>' for model in models)
    limits = summary["limits"]["coding_v3"]
    conditions = [
        ("問題", "難しいコーディング 6 問（H1〜H6、隠しテスト 18〜28 ケース・部分点）と数学 3 問（M1〜M3、小問 2〜3 つ）。"
                 "流す順は H4 → M1 → H1 → H3 → M2 → H6 → M3 → H2 → H5（易しい順）"),
        ("thinking", "すべてあり。Ollama は think:true、Strata は reasoning_effort high、Claude は effort xhigh・high・medium・low"
                     "（モデルの名前の末尾）"),
        ("サンプリング", "各サーバーの既定（Ollama は各 Modelfile）。Strata だけ temperature 1.0 / top_p 0.95 / top_k 20 を送る"),
        ("上限", f"生成 {limits['max_tokens']:,} トークン・Strata の思考予算 {limits['reasoning_budget_tokens']:,}・1 要求 "
                 f"{limits['request_timeout_s'] // 60} 分・{summary['stall_timeout_s']} 秒なにも届かなければ打ち切り"),
        ("回数", "Claude は各問 3 回、ローカルは各問 1 回"),
        ("Claude", "メインが Agent ツールで起動。ツールは問題文の Read・答えの Write・結果の返却の 3 回だけ"
                   "（コードの実行・検索は使わせない。回数と名前を記録で確かめた）。採点はローカルと同じ"),
        ("採点", "コーディングは隠しテストの合格率（標準ライブラリ・1 ケース 3 秒・全体 10 秒・アドレス空間 2 GiB のサンドボックス）。"
                 "数学は答えの行の数を相対誤差 1e-5 で比べる"),
    ]
    condition_rows = "".join(f"<tr><th>{esc(name)}</th><td>{esc(text)}</td></tr>" for name, text in conditions)
    return (br.family_legend() + '<table class="data"><thead><tr><th>モデル</th><th>系統</th><th>時間の上限</th><th>注記</th>'
            f'</tr></thead><tbody>{rows}</tbody></table><h3>条件</h3><table class="data kv"><tbody>{condition_rows}</tbody></table>')


def comparison_block(compare: dict[str, Any]) -> str:
    first, second = compare["pair"]
    labels = {key: br.esc(key) for key in (first, second)}
    try:
        import targets as targets_module
        labels = {key: targets_module.BY_KEY[key].label for key in (first, second)}
    except (ImportError, KeyError):
        pass
    rows = []
    for row in compare["rows"]:
        one, two = row[first], row[second]
        split = sorted(set(one["failed_cases"]) ^ set(two["failed_cases"]))
        rows.append(
            f'<tr><td>{esc(ITEM_TITLES.get(row["item"], row["item"]))}</td>'
            f'<td class="num">{esc(scores_text(one["scores"]))}</td><td class="num">{br.fmt_pct(one["mean"])}</td>'
            f'<td class="num">{esc(scores_text(two["scores"]))}</td><td class="num">{br.fmt_pct(two["mean"])}</td>'
            f'<td class="strong">{esc(verdict_text(row["verdict"], labels))}</td>'
            f'<td class="note">{esc("、".join(split[:6]) + ("…" if len(split) > 6 else "") if split else "—")}</td></tr>')
    totals = compare["run_totals"]
    total_rows = "".join(
        f'<tr><td>{esc(labels[model])}</td><td class="num">{esc(" / ".join(f"{value:.3f}" for value in totals[model]))}</td>'
        f'<td class="num">{(min(totals[model]) if totals[model] else 0):.3f}〜{(max(totals[model]) if totals[model] else 0):.3f}</td></tr>'
        for model in (first, second))
    return (
        f'<table class="data"><thead><tr><th>問</th><th>{esc(labels[first])}（回ごと）</th><th>平均</th>'
        f'<th>{esc(labels[second])}（回ごと）</th><th>平均</th><th>判定</th><th>片方だけが落としたケース・小問</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '<table class="data"><thead><tr><th>モデル</th><th>9 問の合計点（回ごと・9 点満点）</th><th>最小〜最大</th></tr></thead>'
        f'<tbody>{total_rows}</tbody></table>'
        f'<p><strong>合計点の判定: {esc(verdict_text(compare["total_verdict"], labels))}</strong></p>')


def section_claude(summary: dict[str, Any]) -> str:
    comparisons = summary.get("claude_comparisons") or ([dict(summary["claude_comparison"], effort="xhigh")]
                                                        if summary.get("claude_comparison") else [])
    if not comparisons:
        return '<p class="muted">Claude の記録がそろっていない。</p>'
    parts = ['<p>同じ問を Sonnet と Opus に、effort（考える量の設定）ごとに 3 回ずつ解かせた。表の点は回ごとの点'
             f'（1 回目・2 回目・3 回目）。判定の規則: {esc(comparisons[0]["rule"])}。</p>']
    efforts = summary.get("claude_efforts") or []
    if efforts:
        rows = "".join(
            f'<tr><td>{esc(row["label"])}</td><td>{esc(row["effort"])}</td><td class="num">{br.fmt_pct(row["ability"])}</td>'
            f'<td class="num">{esc(" / ".join(f"{value:.2f}" for value in row["run_totals"]))}</td>'
            f'<td class="num">{row["n_all_passed"]} / {row["n_runs"]}</td>'
            f'<td class="num">{esc(br.fmt_time(row["time_median_s"]))}</td>'
            f'<td class="num">{esc(br.fmt_int(row["tokens_median"]))}</td></tr>' for row in efforts)
        parts.append('<h3>Claude 8 種の一覧（全 9 問 × 3 回）</h3>'
                     '<table class="data"><thead><tr><th>モデル</th><th>effort</th><th>能力（平均）</th>'
                     '<th>合計点（回ごと）</th><th>全部正解の回</th><th>1 回の時間（中央値）</th><th>トークン（中央値・参考）</th>'
                     f'</tr></thead><tbody>{rows}</tbody></table>'
                     '<p class="caption">時間は Agent の duration。トークンはサブエージェントの合計（問題文を読む分を含む）。</p>')
    for compare in comparisons:
        parts.append(f'<h3>effort {esc(compare["effort"])}: Sonnet と Opus</h3>' + comparison_block(compare))
    return "".join(parts)


def section_suite(summary: dict[str, Any], models: list[dict[str, Any]], suite_key: str) -> str:
    suite = summary["suites"][suite_key]
    cells = {key: entry["items"] for key, entry in suite["models"].items()}
    labels = {item: item_label(item) for item in suite["items"]}
    parts = [f'<h3>モデル × 問の点数</h3>{br.grade_legend()}'
             + br.heatmap(models, suite["items"], cells, title=f"{suite['label']}の点数", item_labels=labels)
             + '<p class="caption">Claude のマスは 3 回の平均。ローカルは 1 回。</p>'
             + br.status_list(models, suite, labels)]
    budget = summary["limits"][suite_key]["reasoning_budget_tokens"] if suite_key in summary["limits"] else None
    if budget:
        note = br.budget_cut_note(models, suite, budget, labels, br.SUITE_SHORT_NAMES[suite_key])
        if note:
            parts.append(f'<ul class="notes callout"><li>{esc(note)}</li></ul>')
    if suite_key != "hard":
        parts.append(f'<h3>思考の量と中身（ローカル）</h3>{br.thinking_table(models, suite)}')
    ability = br.hbar_chart(
        br.suite_rows(models, suite, key="ability",
                      tip_extra=lambda entry: [f"全部合格 {entry.get('n_all_passed')} 問・答えあり {entry.get('n_answered')} 問"]),
        title=f"{suite['label']}の能力", ticks=[(value, f"{value * 100:.0f}%") for value in (0, .25, .5, .75, 1)],
        scale=lambda value: value, value_label=br.fmt_pct)
    parts.append(f'<h3>能力（問ごとの点数の平均）</h3>{br.family_legend()}{ability}')
    parts.append('<h3>1 問あたりの時間（中央値・対数の目盛り）</h3>'
                 + br.time_bar_chart(br.suite_rows(models, suite, key="time_s"), title=f"{suite['label']}の時間"))
    parts.append(f'<h3>能力 × 時間</h3>{br.scatter_chart(br.scatter_points(models, suite), title=suite["label"])}')
    parts.append('<h3>総合順位</h3>' + br.ranking_table(models, suite, time_label="1 問の時間 T（中央値）"))
    return "".join(parts)


def section_schedule(summary: dict[str, Any], models: list[dict[str, Any]]) -> str:
    schedule = summary.get("schedule")
    parts = []
    if schedule:
        rows = []
        for phase in schedule.get("phases") or []:
            started, finished = phase.get("started_at"), phase.get("finished_at")
            actual = None
            if started and finished:
                actual = progress.minutes_between(progress.parse_time(started), progress.parse_time(finished))
            rows.append(f'<tr><td>{esc(phase["id"])}</td><td>{esc(phase["label"])}</td>'
                        f'<td class="num">{esc(br.fmt_time(phase["planned_min"] * 60))}</td>'
                        f'<td>{esc((started or "—")[5:16].replace("T", " "))}</td><td>{esc((finished or "—")[5:16].replace("T", " "))}</td>'
                        f'<td class="num">{esc(br.fmt_time(actual * 60) if actual is not None else "—")}</td></tr>')
        lifted = schedule.get("deadline_lifted_at")
        lifted_text = (f'（{lifted[5:16].replace("T", " ")} に外した。{schedule.get("deadline_note") or ""}）'
                       if lifted else "")
        parts.append(f'<p>全行程の開始 {esc((schedule.get("t0") or "")[:16].replace("T", " "))}、期限 '
                     f'{esc(str(schedule.get("total_hours")))} 時間{esc(lifted_text)}。工程の計画と実績（progress.json）:</p>'
                     '<table class="data"><thead><tr><th>工程</th><th>内容</th><th>計画</th><th>開始</th><th>終了</th><th>実績</th>'
                     f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')
    budgets = summary.get("model_budgets_min") or {}
    suite = summary["suites"]["hard"]
    rows = []
    for model in models:
        if model["backend"] == "claude":
            continue
        entry = suite["models"][model["key"]]
        rows.append(f'<tr><td>{br.model_cell(model)}</td>'
                    f'<td class="num">{esc(budget_text(budgets, model["key"]))}</td>'
                    f'<td class="num">{esc(br.fmt_time(entry.get("total_time_s")))}</td>'
                    f'<td class="num">{entry.get("n_answered", 0)} / {len(suite["items"])}</td>'
                    f'<td class="num">{entry.get("n_skipped", 0)}</td></tr>')
    parts.append('<h3>ローカルのモデルごとの時間</h3><table class="data"><thead><tr><th>モデル</th><th>上限</th>'
                 '<th>使った時間（ロードを除く合計）</th><th>答えた問</th><th>時間の上限で飛ばした問</th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table>'
                 '<p class="caption">累計は問を送る前に見るので、最後の 1 問は上限を越えて走りうる（前回と同じ規則）。'
                 '使った時間は表に載せた記録の合計で、思考中の停止で流し直した問の 1 回目の時間は入れていない'
                 '（上限の判定の累計には入れた）。</p>')
    reruns = summary.get("budget_reruns") or []
    if reruns:
        n_items = len(suite["items"])
        rows = []
        for entry in reruns:
            final = suite["models"].get(entry["key"], {})
            total_final = (final.get("ability") or 0.0) * n_items
            items_text = "、".join(f'{item_label(item["item"])} {br.fmt_pct(item["final_score"])}（{br.STATUS_LABELS.get(item["final_status"], "答えあり" if item["final_status"] == "ok" else item["final_status"])}）'
                                   for item in entry["items"])
            rows.append(f'<tr><td>{esc(entry["label"])}</td><td>{esc(items_text)}</td>'
                        f'<td class="num">{total_final - entry["score_gained"]:.2f}</td><td class="num">{total_final:.2f}</td></tr>')
        parts.append('<h3>時間の上限で飛ばされた問の流し直し（上限なし）</h3>'
                     '<table class="data"><thead><tr><th>モデル</th><th>流し直した問（点・終わり方）</th>'
                     f'<th>70 分の時点の合計点（{n_items} 点満点）</th><th>流し直した後の合計点</th></tr></thead>'
                     f'<tbody>{"".join(rows)}</tbody></table>'
                     '<p class="caption">はじめ 70 分の上限で飛ばされた問だけを、あとで上限なしで流した（ほかのモデルは上限内で全問を終えていた）。'
                     '飛ばされた元の記録は results/2026-10-18/skipped-budget70/ に残した。</p>')
    return "".join(parts)


def section_appendix(summary: dict[str, Any]) -> str:
    date = summary["date"]
    data_paths = [
        ("ローカルの記録", f"tools/model-eval/results/{date}/local/<モデル>/<coding_v3|math>/<問>-run1.json"),
        ("Claude の記録", f"tools/model-eval/results/{date}/claude/<sonnet|opus>/<coding_v3|math>/<問>-run<n>.json"),
        ("Claude の答えの原本", f"tools/model-eval/results/{date}/claude-raw/（受験側が Write で保存した本文）"),
        ("集計", f"tools/model-eval/results/{date}/summary.json"),
        ("工程の記録", f"tools/model-eval/results/{date}/progress.json"),
        ("凍結した問題の sha256", f"tools/model-eval/results/{date}/frozen.json"),
        ("問題・隠しテスト・参照解", "tools/model-eval/suites/coding_v3/、tools/model-eval/suites/math/"),
    ]
    path_rows = "".join(f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td></tr>" for name, path in data_paths)
    problems = [(f"{ITEM_TITLES[item]}（{suite}）", common.build_prompt(suite, item)) for suite, item in common.HARD_ORDER]
    details = "".join(f"<details><summary>{esc(name)}</summary><pre>{esc(text)}</pre></details>" for name, text in problems)
    missing = "".join(f"<li>{esc(line)}</li>" for line in summary.get("missing", []))
    invalid = "".join(f"<li>{esc(line)}</li>" for line in summary.get("claude_invalid_runs", []))
    return (f'<h3>式</h3>{br.formula_block(summary)}'
            f'<h3>生データの場所</h3><table class="data kv"><tbody>{path_rows}</tbody></table>'
            + (f'<h3>足りない記録</h3><ul class="notes">{missing}</ul>' if missing else "")
            + (f'<h3>無効にした Claude の回</h3><ul class="notes">{invalid}</ul>' if invalid else "")
            + '<h3>問題文（ローカルと Claude に同じ全文を渡した）</h3>'
            f'<p>問題ごとの分かりやすい解説（やること・具体例・何が難しいか・採点の仕方・図）は '
            f'<a href="AIモデル評価_出題内容_{esc(date)}.html">AIモデル評価_出題内容_{esc(date)}.html</a> にある。</p>{details}')


def build_html(summary: dict[str, Any], findings: dict[str, Any] | None = None) -> str:
    models = summary["models"]
    sections = [
        ("s0", "0. 概要と注意", section_overview(summary, models)),
        ("s1", "1. 対象と条件", section_targets(summary, models)),
        ("s2", "2. Sonnet と Opus の差", section_claude(summary)),
        ("s3", "3. 難しいコーディング 6 問（隠しテスト）", section_suite(summary, models, "coding_v3")),
        ("s4", "4. 数学 3 問（数で採点）", section_suite(summary, models, "math")),
        ("s5", "5. 全 9 問の総合", section_suite(summary, models, "hard")),
        ("s6", "6. 時間の実績", section_schedule(summary, models)),
        ("s7", "7. 所見", br.section_findings(findings)),
        ("s8", "8. 付録（式・生データ・問題文）", section_appendix(summary)),
    ]
    toc = "".join(f'<li><a href="#{anchor}">{esc(title)}</a></li>' for anchor, title, _body in sections)
    body = "".join(f'<section id="{anchor}"><h2>{esc(title)}</h2>{content}</section>' for anchor, title, content in sections)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>AI モデル評価 {esc(summary["date"])}</title><style>{br.STYLE}</style></head>'
        '<body class="viz-root"><main>'
        f'<h1>{len(models)} の AI の比較評価（難しいコーディング 6 問・数学 3 問）</h1>'
        f'<p class="sub">評価日 {esc(summary["date"])}・集計 {esc(summary["generated_at"])}・'
        'tools/model-eval/build_report_hard.py が summary.json から生成（手で書き換えない）</p>'
        f'<nav aria-label="目次"><ol>{toc}</ol></nav>{body}</main>'
        f'<div id="tip" role="tooltip" hidden></div><script>{br.SCRIPT}</script></body></html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--findings", default=None, help="既定 summary と同じ場所の findings.json（無ければ空欄）")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    summary_path = Path(args.summary)
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
