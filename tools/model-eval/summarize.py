#!/usr/bin/env python3
"""results/<日付>/ の記録を集めて summary.json を作る（build_report.py の入力）。

  summarize.py                               # results/2026-10-08/summary.json を書く
  summarize.py --results-dir work/smoke --out work/smoke/summary.json
  summarize.py --results-dir results/2026-10-18 --suites coding_v3,math --no-math3d   # 2026-10-18 の難問 9 問

読むもの:
- math3d_local.json（ローカル 8 種の 3D。Coder は 2026-10-09 に流した 2 回。ほかはDocuments/3D問題_実施モデル一覧_2026-10-08.md から写した値）
- local/<slug>/<suite>/<問>-run1.json（run_eval.py run の記録）
- claude/<sonnet|opus>/<math3d|coding|extra>/<問>-run<n>.json（メインが保存し、grade-claude が採点した記録）
- archive-*/（作り直す前の試験の記録。点数だけを archives にまとめ、順位には使わない）

式は evallib/scoring.py（能力・速度点・総合）。足りない記録は status "missing" として 0 点に数え、missing に並べる。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import targets as targets_module  # noqa: E402
from evallib import common, scoring  # noqa: E402

MATH3D_KEYS = ("q1", "q2", "q3", "q4")
SUITE_LABELS = {"math3d": "頭の良さ（3D 数学）", "coding": "コーディング 6 問", "extra": "追加の 3 試験",
                "coding_v3": "難しいコーディング 6 問", "math": "数学 3 問", "hard": "全 9 問（コーディング 6 + 数学 3）"}
# Sonnet と Opus を比べる 2 つの Claude
CLAUDE_PAIR = ("sonnet", "opus")
# 1 問の記録を表に出すときの区分（色分けに使う）
CELL_SCORED = "scored"        # 答えがあり採点した（点数で緑の濃淡・0 点なら赤）
CELL_NO_ANSWER = "no_answer"  # 答えなし・上限・時間切れ・stall・エラー（灰）
CELL_SKIPPED = "skipped"      # 累計時間の上限で飛ばした（灰）
CELL_MISSING = "missing"      # 記録が無い（灰）

# Strata が思考の予算（reasoning_budget_tokens）に届いたとき、思考の最後に差し込む文
# （tools/strata/vendor/Strata/serve/server.py の REASONING_WRAP_UP）。思考にこれがあれば、答えは予算で打ち切られたあとに書かれた
REASONING_WRAP_UP_MARK = "I have thought about this long enough; time to give my answer."
# 同じ行の繰り返しを数える行の最短の字数。「}」「Good.」のような短い行は、ループでなくても何度も出るので数えない
REPEAT_LINE_MIN_CHARS = 20


def thinking_stats(thinking: str) -> dict[str, Any] | None:
    """思考の中身の目安（所見の根拠として HTML に出す）。思考が無ければ None。

    - question_per_10k: 思考 1 万字あたりの「?」の数。仕様の読みを疑う問いかけの多さの目安
    - maybe_per_10k: 1 万字あたりの「maybe」の数（大文字小文字は区別しない）
    - repeated_line_pct: 20 字以上の行のうち、それより前に同じ行（前後の空白を除いて一致）が出ていた割合（%）。
      同じ文を繰り返すループの目安
    """

    if not thinking:
        return None
    chars = len(thinking)
    long_lines = [line.strip() for line in thinking.splitlines() if len(line.strip()) >= REPEAT_LINE_MIN_CHARS]
    seen: set[str] = set()
    repeated = 0
    for line in long_lines:
        if line in seen:
            repeated += 1
        seen.add(line)
    return {
        "chars": chars,
        "question_per_10k": thinking.count("?") / chars * 10000,
        "maybe_per_10k": len(re.findall("maybe", thinking, flags=re.IGNORECASE)) / chars * 10000,
        "repeated_line_pct": repeated / len(long_lines) * 100 if long_lines else 0.0,
    }


def _math3d_score(grade: dict[str, Any]) -> float:
    return sum(1 for key in MATH3D_KEYS if grade.get(key) is True) / len(MATH3D_KEYS)


def _valid_claude(record: dict[str, Any]) -> bool:
    return not record.get("tool_uses")


def _claude_tokens(record: dict[str, Any]) -> int | None:
    """Claude の usage（null 可）から出力トークン数を取る。output_tokens が無ければ total_tokens・subagent_tokens
    （Agent の結果の値。2026-10-18 の取り込みは subagent_tokens の名前で残した）。"""

    usage = record.get("usage")
    if not isinstance(usage, dict):
        return None
    for key in ("output_tokens", "total_tokens", "subagent_tokens"):
        if isinstance(usage.get(key), int):
            return usage[key]
    return None


EXCLUDED_FILE = "excluded.json"


def read_excluded(results_dir: Path) -> dict[str, str]:
    """results/<日付>/excluded.json（{"<targets.py の key>": "<理由>"}）。比較から外すモデル。無ければ空。

    外したモデルは順位・表・図に出さない（記録のファイルは消さない）。理由は summary.json の excluded に残す。
    """

    path = results_dir / EXCLUDED_FILE
    if not path.exists():
        return {}
    excluded = common.read_json(path)
    unknown = sorted(set(excluded) - set(targets_module.BY_KEY))
    if unknown:
        raise SystemExit(f"{path}: targets.py に無い key: {', '.join(unknown)}")
    return {str(key): str(reason) for key, reason in excluded.items()}


def report_targets(results_dir: Path) -> tuple[targets_module.Target, ...]:
    """比較に載せるモデル（targets.py の並びから excluded.json のものを除いたもの）。"""

    excluded = read_excluded(results_dir)
    # 後から足したモデル（added）は、それより前の日付の評価には出さない（results/<日付> の名前で比べる）
    return tuple(target for target in targets_module.TARGETS
                 if target.key not in excluded and not (target.added and _is_date(results_dir.name)
                                                        and results_dir.name < target.added))


def _is_date(name: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", name))


def collect_math3d(results_dir: Path, claude_records: list[dict[str, Any]], missing: list[str]) -> dict[str, Any]:
    local_path = results_dir / "math3d_local.json"
    local = common.read_json(local_path) if local_path.exists() else {"runs": [], "model_notes": {}, "notes": []}
    if not local_path.exists():
        missing.append("math3d_local.json が無い")
    models: dict[str, dict[str, Any]] = {}
    for target in report_targets(results_dir):
        runs: list[dict[str, Any]] = []
        if target.backend == "claude":
            records = sorted((record for record in claude_records
                              if record.get("model") == target.key and record.get("suite") == "math3d"),
                             key=lambda record: record.get("run", 0))
            for record in records:
                grade = record.get("grade")
                graded = isinstance(grade, dict) and all(key in grade for key in MATH3D_KEYS)
                runs.append({
                    "label": f"run{record.get('run')}", "grade": grade if graded else None,
                    "score": _math3d_score(grade) if graded else None, "wall_s": record.get("wall_s"),
                    "tokens": _claude_tokens(record),
                    "tok_s": None, "used": _valid_claude(record) and graded,
                    "note": "" if _valid_claude(record) else "ツールを使ったので無効",
                    "source": "claude",
                })
                if not graded:
                    missing.append(f"claude/{target.key}/math3d/{record.get('item')}-run{record.get('run')} の採点が未記入")
        else:
            for run in local.get("runs", []):
                if run.get("target") != target.key:
                    continue
                runs.append({"label": run.get("date", "")[5:] + ("" if run.get("used") else "（参考）"),
                             "grade": run.get("grade"), "score": _math3d_score(run.get("grade") or {}),
                             "wall_s": run.get("wall_s"), "tokens": run.get("tokens"), "tok_s": run.get("tok_s"),
                             "used": bool(run.get("used")), "note": run.get("note", ""), "env": run.get("env", ""),
                             "source": "local-md"})
        used = [run for run in runs if run["used"]]
        if not used:
            missing.append(f"math3d: {target.label} の回が無い")
        models[target.key] = {
            "runs": runs,
            "n_runs": len(used),
            "ability": scoring.mean(run["score"] for run in used) if used else None,
            "time_s": scoring.median(run["wall_s"] for run in used),
            "tok_s": scoring.median(run["tok_s"] for run in used),
            "note": (local.get("model_notes") or {}).get(target.key, ""),
        }
    return {"label": SUITE_LABELS["math3d"], "items": list(MATH3D_KEYS), "answer_key": local.get("answer_key", {}),
            "notes": local.get("notes", []), "models": models}


def _cell_from_local(record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {"cell": CELL_MISSING, "score": 0.0, "status": "missing", "time_s": None}
    grade = record.get("grade") or {}
    status = record.get("status")
    if status == common.STATUS_SKIPPED:
        cell = CELL_SKIPPED
    elif grade.get("no_answer"):
        cell = CELL_NO_ANSWER
    else:
        cell = CELL_SCORED
    # 時間: ロードを除く壁時計。飛ばした問とエラーは時間の中央値に入れない
    time_s = record.get("wall_excl_load_s") if status not in (common.STATUS_SKIPPED, common.STATUS_ERROR) else None
    thinking = record.get("thinking") or ""
    return {"cell": cell, "score": float(grade.get("score") or 0.0), "all_passed": bool(grade.get("all_passed")),
            "status": status, "reason": grade.get("reason"), "time_s": time_s,
            "tokens": record.get("completion_tokens"), "thinking_tokens_est": record.get("thinking_tokens_est"),
            "tok_s": record.get("server_decode_tok_s"), "finish": record.get("finish"),
            # サーバーのエラー文（HTML のツールチップに出す。長いものは切る）
            "error": (record.get("error") or "")[:300] or None,
            "budget_cut": REASONING_WRAP_UP_MARK in thinking,
            "thinking_stats": thinking_stats(thinking),
            # 0 点の理由を表で文字にするため（コードが Python として読めない・禁止の import や呼び出し）。
            # 思考中に停止トークンが出て本文が空だった回（status eos_in_thinking）は、grade.reason が eos_in_thinking の答えなし（0 点）
            "syntax_error": bool(grade.get("syntax_error")), "violations": len(grade.get("violations") or []),
            "failed_cases": _failed_cases(grade)}


def _failed_cases(grade: dict[str, Any]) -> list[str]:
    """落ちた隠しテストのケース名（コーディング）か、誤った小問（数学）。"""

    if grade.get("kind") == "math":
        return [f"({part['key']})" for part in grade.get("parts") or [] if not part.get("ok")]
    return [case["name"] for case in grade.get("cases") or [] if not case.get("ok")]


def _cell_from_claude(records: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [record for record in records if _valid_claude(record)]
    if not valid:
        return {"cell": CELL_MISSING, "score": 0.0, "status": "missing" if not records else "invalid_tool_use",
                "time_s": None}
    graded = [record for record in valid if isinstance(record.get("grade"), dict)]
    if not graded:
        return {"cell": CELL_MISSING, "score": 0.0, "status": "ungraded", "time_s": None}
    scores = [float(record["grade"].get("score") or 0.0) for record in graded]
    times = [record["wall_s"] / max(1, int(record.get("batch_size") or 1))
             for record in graded if record.get("wall_s") is not None]
    no_answer = all(record["grade"].get("no_answer") for record in graded)
    tokens = [_claude_tokens(record) for record in graded]
    graded = sorted(graded, key=lambda record: record.get("run", 0))
    run_details = [{"run": record.get("run"), "score": float(record["grade"].get("score") or 0.0),
                    "all_passed": bool(record["grade"].get("all_passed")), "wall_s": record.get("wall_s"),
                    "tokens": _claude_tokens(record), "failed_cases": _failed_cases(record["grade"])}
                   for record in graded]
    return {"cell": CELL_NO_ANSWER if no_answer else CELL_SCORED, "score": sum(scores) / len(scores),
            "all_passed": all(record["grade"].get("all_passed") for record in graded), "status": "ok",
            "reason": graded[0]["grade"].get("reason"), "time_s": scoring.median(times),
            "tokens": scoring.median(token for token in tokens if token is not None) if tokens else None,
            "thinking_tokens_est": None, "tok_s": None, "runs": len(graded), "run_details": run_details,
            "min": min(scores), "max": max(scores),
            "n_all_passed_runs": sum(1 for record in graded if record["grade"].get("all_passed"))}


def collect_suite(suite: str, results_dir: Path, claude_records: list[dict[str, Any]],
                  missing: list[str]) -> dict[str, Any]:
    items = list(common.SUITE_ITEMS[suite])
    models: dict[str, dict[str, Any]] = {}
    for target in report_targets(results_dir):
        cells: dict[str, dict[str, Any]] = {}
        for item in items:
            if target.backend == "claude":
                records = [record for record in claude_records if record.get("model") == target.key
                           and record.get("suite") == suite and record.get("item") == item]
                cell = _cell_from_claude(records)
            else:
                path = common.local_record_path(results_dir, target.slug, suite, item)
                cell = _cell_from_local(common.read_json(path) if path.exists() else None)
            if cell["cell"] == CELL_MISSING:
                missing.append(f"{suite}: {target.label} の {item}（{cell['status']}）")
            cells[item] = cell
        times = [cell["time_s"] for cell in cells.values()]
        # 1 問も記録が無いモデルは、0 点ではなく「記録なし」（順位に入れない）
        nothing = all(cell["cell"] == CELL_MISSING for cell in cells.values())
        entry = {
            "items": cells,
            "ability": None if nothing else scoring.mean(cell["score"] for cell in cells.values()),
            "time_s": scoring.median(times),
            "total_time_s": sum(time for time in times if time is not None) or None,
            "tok_s": scoring.median(cell.get("tok_s") for cell in cells.values()),
            "n_answered": sum(1 for cell in cells.values() if cell["cell"] == CELL_SCORED),
            "n_all_passed": sum(1 for cell in cells.values() if cell.get("all_passed")),
            "tokens_total": sum(cell.get("tokens") or 0 for cell in cells.values()) or None,
            "thinking_tokens_est_total": sum(cell.get("thinking_tokens_est") or 0 for cell in cells.values()) or None,
            "n_budget_cut": sum(1 for cell in cells.values() if cell.get("budget_cut")),
        }
        if suite == "extra":
            entry["kind_scores"] = {kind: scoring.mean(cells[item]["score"] for item in kind_items)
                                    for kind, kind_items in common.EXTRA_KINDS.items()}
        models[target.key] = entry
    result = {"label": SUITE_LABELS[suite], "items": items, "models": models}
    if suite == "extra":
        result["kinds"] = {kind: list(kind_items) for kind, kind_items in common.EXTRA_KINDS.items()}
        result["kind_labels"] = dict(common.EXTRA_KIND_LABELS)
    return result


def add_rankings(suite_summary: dict[str, Any]) -> None:
    models = suite_summary["models"]
    speeds = scoring.speed_scores({key: entry.get("time_s") for key, entry in models.items()})
    for key, entry in models.items():
        entry["speed"] = speeds[key]
        entry["overall"] = scoring.overall(entry.get("ability"), speeds[key])
    ranks = scoring.rank({key: entry["overall"] for key, entry in models.items()})
    for key, entry in models.items():
        entry["rank"] = ranks[key]
    times = [entry["time_s"] for entry in models.values() if entry.get("time_s")]
    suite_summary["time_range_s"] = [min(times), max(times)] if times else None


def collect_archives(results_dir: Path) -> list[dict[str, Any]]:
    """results/<日付>/archive-*/ に退避した記録を、試験とモデルごとの点数だけにまとめる（順位には使わない）。

    退避の形は本番と同じ（local/<slug>/<suite>/<問>-run1.json と claude/<model>/<suite>/<問>-run<n>.json）。
    """

    archives: list[dict[str, Any]] = []
    for archive in sorted(path for path in results_dir.glob("archive-*") if path.is_dir()):
        suites: dict[str, dict[str, Any]] = {}
        for target in report_targets(results_dir):
            base = archive / ("claude" if target.backend == "claude" else "local") / target.slug
            for suite_dir in sorted(path for path in base.glob("*") if path.is_dir()):
                grades = [common.read_json(path).get("grade") for path in sorted(suite_dir.glob("*-run*.json"))]
                grades = [grade for grade in grades if isinstance(grade, dict)]
                if not grades:
                    continue
                suites.setdefault(suite_dir.name, {})[target.key] = {
                    "n_items": len(grades),
                    "n_all_passed": sum(1 for grade in grades if grade.get("all_passed")),
                    "ability": scoring.mean(float(grade.get("score") or 0.0) for grade in grades),
                }
        archives.append({"name": archive.name, "path": f"tools/model-eval/results/{results_dir.name}/{archive.name}/",
                         "suites": suites})
    return archives


def combine_suites(suites: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """いくつかの試験をまとめた 1 つの順位（能力 = 全部の問の点の平均、時間 = 全部の問の時間の中央値）。"""

    items: list[str] = []
    for name in names:
        items.extend(suites[name]["items"])
    models: dict[str, dict[str, Any]] = {}
    for key in suites[names[0]]["models"]:
        cells = {}
        for name in names:
            cells.update(suites[name]["models"][key]["items"])
        nothing = all(cell["cell"] == CELL_MISSING for cell in cells.values())
        times = [cell["time_s"] for cell in cells.values()]
        models[key] = {
            "items": cells,
            "ability": None if nothing else scoring.mean(cell["score"] for cell in cells.values()),
            "time_s": scoring.median(times),
            "total_time_s": sum(time for time in times if time is not None) or None,
            "tok_s": scoring.median(cell.get("tok_s") for cell in cells.values()),
            "n_answered": sum(1 for cell in cells.values() if cell["cell"] == CELL_SCORED),
            "n_all_passed": sum(1 for cell in cells.values() if cell.get("all_passed")),
            "n_skipped": sum(1 for cell in cells.values() if cell["cell"] == CELL_SKIPPED),
        }
    return {"label": SUITE_LABELS["hard"], "items": items, "models": models}


def judge_pair(first: list[float], second: list[float]) -> str:
    """2 つのモデルの回ごとの点を比べる（cond_compare.py と同じ規則: 一方の最小 > 他方の最大なら差あり）。"""

    if not first or not second:
        return "比べられない"
    if min(first) > max(second):
        return "first"
    if min(second) > max(first):
        return "second"
    if min(first) == max(first) == min(second) == max(second):
        return "同じ"
    return "判定できない"


def claude_comparison(suites: dict[str, Any], names: tuple[str, ...], first: str = "sonnet",
                      second: str = "opus") -> dict[str, Any] | None:
    """2 つの Claude の問ごとの比べ（各回の点・最小〜最大・判定・落ちたケース）と、回ごとの合計点の比べ。

    判定は "first" / "second"（どちらが上か）を、呼び出し側でモデルの key に読み替える。
    """

    rows = []
    totals: dict[str, dict[int, float]] = {first: {}, second: {}}
    for name in names:
        suite = suites[name]
        if first not in suite["models"] or second not in suite["models"]:
            return None
        for item in suite["items"]:
            entry: dict[str, Any] = {"suite": name, "item": item}
            for model in (first, second):
                cell = suite["models"][model]["items"][item]
                details = cell.get("run_details") or []
                entry[model] = {"scores": [detail["score"] for detail in details],
                                "mean": cell["score"] if details else None,
                                "times": [detail["wall_s"] for detail in details],
                                "failed_cases": sorted({case for detail in details for case in detail["failed_cases"]}),
                                "n_all_passed_runs": cell.get("n_all_passed_runs", 0)}
                for detail in details:
                    totals[model][detail["run"]] = totals[model].get(detail["run"], 0.0) + detail["score"]
            verdict = judge_pair(entry[second]["scores"], entry[first]["scores"])
            entry["verdict"] = {"first": second, "second": first}.get(verdict, verdict)
            rows.append(entry)
    if not any(row[first]["scores"] or row[second]["scores"] for row in rows):
        return None
    total_scores = {model: [totals[model][run] for run in sorted(totals[model])] for model in (first, second)}
    verdict = judge_pair(total_scores[second], total_scores[first])
    return {"pair": [first, second], "rows": rows, "run_totals": total_scores,
            "total_verdict": {"first": second, "second": first}.get(verdict, verdict),
            "rule": "一方の全部の回の最小 > 他方の全部の回の最大 のときだけ「差あり」。それ以外は「判定できない」（全部同じ点なら「同じ」）"}


def claude_effort_table(suites: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Claude の各モデル（effort 違い）の、全 9 問の能力・回ごとの合計点・1 回の時間の中央値・出力の量。"""

    rows = []
    for effort, *models in targets_module.CLAUDE_EFFORT_PAIRS:
        for key in models:
            cells = [suites[name]["models"][key]["items"][item] for name in names if key in suites[name]["models"]
                     for item in suites[name]["items"]]
            details = [detail for cell in cells for detail in cell.get("run_details") or []]
            if not details:
                continue
            per_run: dict[int, float] = {}
            for detail in details:
                per_run[detail["run"]] = per_run.get(detail["run"], 0.0) + detail["score"]
            rows.append({"key": key, "label": targets_module.BY_KEY[key].label, "effort": effort,
                         "n_runs": len(details), "ability": scoring.mean(detail["score"] for detail in details),
                         "run_totals": [per_run[run] for run in sorted(per_run)],
                         "n_all_passed": sum(1 for detail in details if detail["all_passed"]),
                         "time_median_s": scoring.median(detail["wall_s"] for detail in details),
                         "time_total_s": sum(detail["wall_s"] or 0 for detail in details),
                         "tokens_median": scoring.median(detail["tokens"] for detail in details if detail["tokens"])})
    return rows


def read_schedule(results_dir: Path) -> dict[str, Any] | None:
    path = results_dir / "progress.json"
    if not path.exists():
        return None
    state = common.read_json(path)
    return {"t0": state.get("t0"), "total_hours": state.get("total_hours"), "phases": state.get("phases"),
            "deadline_lifted_at": state.get("deadline_lifted_at"), "deadline_note": state.get("deadline_note"),
            "local_history": (state.get("lanes") or {}).get("local", {}).get("history")}


def model_budgets(results_dir: Path) -> dict[str, list[float]]:
    """meta.json の起動ごとの argv から、モデルごとに渡した --time-budget-min（違う値を渡した順に。例 [70, 100000]）。"""

    budgets: dict[str, list[float]] = {}
    for target in report_targets(results_dir):
        path = results_dir / "local" / target.slug / "meta.json"
        if not path.exists():
            continue
        for session in common.read_json(path).get("sessions") or []:
            argv = session.get("argv") or []
            if "--time-budget-min" in argv:
                value = float(argv[argv.index("--time-budget-min") + 1])
                values = budgets.setdefault(target.key, [])
                if not values or values[-1] != value:
                    values.append(value)
    return budgets


# 時間の上限で飛ばされた記録を、上限なしで流し直す前に写しておく置き場（2026-10-18 の評価で使った）
BUDGET_SKIPPED_DIR = "skipped-budget70"


def budget_reruns(results_dir: Path) -> list[dict[str, Any]]:
    """時間の上限で飛ばされ、あとで上限なしで流し直した問（skipped-budget70/ に元の記録がある問）と、流し直した結果。"""

    root = results_dir / BUDGET_SKIPPED_DIR
    if not root.is_dir():
        return []
    by_slug = {target.slug: target for target in report_targets(results_dir)}
    out = []
    for slug_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        target = by_slug.get(slug_dir.name)
        if target is None:
            continue
        items = []
        for old_path in sorted(slug_dir.glob("*/*-run1.json")):
            suite = old_path.parent.name
            item = old_path.name.split("-run")[0]
            final_path = results_dir / "local" / slug_dir.name / suite / old_path.name
            final = common.read_json(final_path) if final_path.exists() else {}
            grade = final.get("grade") or {}
            items.append({"suite": suite, "item": item, "skipped_reason": common.read_json(old_path).get("error"),
                          "final_status": final.get("status", "missing"), "final_score": float(grade.get("score") or 0.0),
                          "final_wall_s": final.get("wall_s")})
        out.append({"key": target.key, "label": target.label, "items": items,
                    "score_gained": sum(entry["final_score"] for entry in items)})
    return out


def summarize(results_dir: Path, suite_names: tuple[str, ...] = ("coding", "extra"),
              include_math3d: bool = True) -> dict[str, Any]:
    missing: list[str] = []
    claude_records = [record for _path, record in common.iter_claude_records(results_dir)]
    suites: dict[str, Any] = {}
    if include_math3d:
        suites["math3d"] = collect_math3d(results_dir, claude_records, missing)
    for suite in suite_names:
        suites[suite] = collect_suite(suite, results_dir, claude_records, missing)
    if len(suite_names) > 1 and not include_math3d:
        suites["hard"] = combine_suites(suites, suite_names)
    for suite_summary in suites.values():
        add_rankings(suite_summary)
    invalid = [f"claude/{record.get('model')}/{record.get('suite')}/{record.get('item')}-run{record.get('run')}"
               for record in claude_records if not _valid_claude(record)]
    return {
        "date": results_dir.name,
        "generated_at": common.now_iso(),
        "results_dir": str(results_dir),
        "weights": {"ability": scoring.WEIGHT_ABILITY, "speed": scoring.WEIGHT_SPEED},
        "formulas": dict(scoring.FORMULA_TEXT),
        "limits": common.SUITE_LIMITS,
        "stall_timeout_s": common.STALL_TIMEOUT_S,
        "model_time_budget_s": common.MODEL_TIME_BUDGET_S,
        "models": [{"key": target.key, "label": target.label, "family": target.family, "backend": target.backend,
                    "slug": target.slug, "notes": target.notes} for target in report_targets(results_dir)],
        "excluded": [{"key": key, "label": targets_module.BY_KEY[key].label, "reason": reason}
                     for key, reason in read_excluded(results_dir).items()],
        "suites": suites,
        "claude_invalid_runs": invalid,
        "missing": missing,
        "archives": collect_archives(results_dir),
        "suite_names": list(suite_names),
        "claude_comparison": claude_comparison(suites, tuple(suite_names)),
        "claude_comparisons": [dict(comparison, effort=effort) for effort, first, second in targets_module.CLAUDE_EFFORT_PAIRS
                               if (comparison := claude_comparison(suites, tuple(suite_names), first, second))],
        "claude_efforts": claude_effort_table(suites, tuple(suite_names)),
        "schedule": read_schedule(results_dir),
        "model_budgets_min": model_budgets(results_dir),
        "budget_reruns": budget_reruns(results_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", default=None, help=f"既定 results/{common.DEFAULT_DATE}")
    parser.add_argument("--out", default=None, help="既定 <results-dir>/summary.json")
    parser.add_argument("--suites", default="coding,extra", help="集計する試験（カンマ区切り。2026-10-18 は coding_v3,math）")
    parser.add_argument("--no-math3d", action="store_true", help="3D 数学（math3d_local.json と Claude の 3D）を集計しない")
    args = parser.parse_args(argv)
    results_dir = Path(args.results_dir).resolve() if args.results_dir else common.results_dir_for(None)
    names = tuple(name.strip() for name in args.suites.split(",") if name.strip())
    unknown = [name for name in names if name not in common.SUITE_ITEMS]
    if unknown:
        raise SystemExit(f"知らない試験: {', '.join(unknown)}")
    summary = summarize(results_dir, names, include_math3d=not args.no_math3d)
    out = Path(args.out) if args.out else results_dir / "summary.json"
    common.write_json(out, summary)
    print(f"{out} を書いた。足りない記録 {len(summary['missing'])} 件")
    for line in summary["missing"][:40]:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
