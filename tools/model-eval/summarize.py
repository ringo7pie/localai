#!/usr/bin/env python3
"""results/<日付>/ の記録を集めて summary.json を作る（build_report.py の入力）。

  summarize.py                               # results/2026-10-08/summary.json を書く
  summarize.py --results-dir work/smoke --out work/smoke/summary.json

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
SUITE_LABELS = {"math3d": "頭の良さ（3D 数学）", "coding": "コーディング 6 問", "extra": "追加の 3 試験"}
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
    """Claude の usage（null 可）から出力トークン数を取る。output_tokens が無ければ total_tokens（Agent の結果の値）。"""

    usage = record.get("usage")
    if not isinstance(usage, dict):
        return None
    for key in ("output_tokens", "total_tokens"):
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
    return tuple(target for target in targets_module.TARGETS if target.key not in excluded)


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
            "syntax_error": bool(grade.get("syntax_error")), "violations": len(grade.get("violations") or [])}


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
    return {"cell": CELL_NO_ANSWER if no_answer else CELL_SCORED, "score": sum(scores) / len(scores),
            "all_passed": all(record["grade"].get("all_passed") for record in graded), "status": "ok",
            "reason": graded[0]["grade"].get("reason"), "time_s": scoring.median(times),
            "tokens": scoring.median(token for token in tokens if token is not None) if tokens else None,
            "thinking_tokens_est": None, "tok_s": None, "runs": len(graded)}


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


def summarize(results_dir: Path) -> dict[str, Any]:
    missing: list[str] = []
    claude_records = [record for _path, record in common.iter_claude_records(results_dir)]
    suites = {"math3d": collect_math3d(results_dir, claude_records, missing)}
    for suite in ("coding", "extra"):
        suites[suite] = collect_suite(suite, results_dir, claude_records, missing)
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", default=None, help=f"既定 results/{common.DEFAULT_DATE}")
    parser.add_argument("--out", default=None, help="既定 <results-dir>/summary.json")
    args = parser.parse_args(argv)
    results_dir = Path(args.results_dir).resolve() if args.results_dir else common.results_dir_for(None)
    summary = summarize(results_dir)
    out = Path(args.out) if args.out else results_dir / "summary.json"
    common.write_json(out, summary)
    print(f"{out} を書いた。足りない記録 {len(summary['missing'])} 件")
    for line in summary["missing"][:40]:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
