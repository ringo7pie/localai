"""2026-10-18 の評価（難しいコーディング 6 問 coding_v3・数学 3 問 math・進捗の表示・締切）の試験。

GPU もモデルも使わない。サンドボックスの子プロセスは起動する。一時ファイルは work/pytest/ の下（conftest.work_tmp）。
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

import progress as progress_cli
import run_eval
import targets as targets_module
from evallib import common, progress, sandbox
from suites.math import grade_math

TOOL_DIR = Path(__file__).resolve().parent.parent
V3_DIR = TOOL_DIR / "suites" / "coding_v3"
MATH_DIR = TOOL_DIR / "suites" / "math"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def item_module(item: str, name: str):
    return load(f"{item}_{name}", V3_DIR / item / f"{name}.py")


# ------------------------------------------------------------------------------------------------ 問題の形


def test_hard_order_covers_each_item_once():
    expected = {("coding_v3", item) for item in common.CODING_V3_ITEMS} | {("math", item) for item in common.MATH_ITEMS}
    assert len(common.HARD_ORDER) == 9 and set(common.HARD_ORDER) == expected
    assert run_eval.selected_items("hard", None, None) == list(common.HARD_ORDER)
    assert run_eval.selected_items("hard", "h2,m3", None) == [("math", "m3"), ("coding_v3", "h2")]


@pytest.mark.parametrize("item", common.CODING_V3_ITEMS)
def test_coding_v3_files_and_prompt(item):
    folder = V3_DIR / item
    for name in ("prompt.md", "tests.py", "reference.py", "oracle.py"):
        assert (folder / name).is_file(), name
    text = common.build_prompt("coding_v3", item)
    assert text.startswith("次の仕様を満たす Python 3.12 のコード") and f"## 問題 {item.upper()}" in text


@pytest.mark.parametrize("item", common.MATH_ITEMS)
def test_math_prompt_has_answer_format(item):
    text = common.build_prompt("math", item)
    assert text.startswith(f"## 問題 {item.upper()}") and text.rstrip().endswith("単位や説明は付けない。")
    assert "答え(a): <値>" in text


# ------------------------------------------------------------------------------------------------ 参照解と隠しテスト


@pytest.mark.parametrize("item", common.CODING_V3_ITEMS)
def test_reference_passes_all_hidden_tests(item, work_tmp):
    code = (V3_DIR / item / "reference.py").read_text(encoding="utf-8")
    grade = sandbox.grade_coding(f"```python\n{code}\n```", V3_DIR / item, work_tmp / item)
    failed = [case for case in grade.get("cases", []) if not case["ok"]]
    assert grade["all_passed"], failed
    assert 15 <= grade["total"] <= 30
    assert grade["seconds"] < 5


def test_h4_reference_matches_brute_force():
    ref, oracle = item_module("h4", "reference"), item_module("h4", "oracle")
    rng = random.Random(4)
    for _ in range(600):
        den = rng.choice((1, -1)) * rng.randint(1, 300)
        args = (rng.randint(-2000, 2000), den, rng.randint(1, 80), rng.choice((-1, 0, 1)))
        assert ref.best_rational(*args) == oracle.best_rational_brute(*args), args


def test_h4_large_bounds_are_farey_neighbours():
    ref = item_module("h4", "reference")
    rng = random.Random(5)
    for _ in range(300):
        num, den, limit = rng.randint(-10 ** 30, 10 ** 30), rng.randint(1, 10 ** 30), rng.randint(1, 10 ** 25)
        low, high = ref.best_rational(num, den, limit, -1), ref.best_rational(num, den, limit, 1)
        assert low[0] * den <= num * low[1] and num * high[1] <= high[0] * den
        if low != high:
            assert high[0] * low[1] - low[0] * high[1] == 1 and low[1] + high[1] > limit


def test_h1_reference_matches_brute_force():
    ref, oracle = item_module("h1", "reference"), item_module("h1", "oracle")
    rng = random.Random(1)

    def outcome(fn, pts):
        try:
            return fn(pts)
        except ValueError:
            return "VE"

    for _ in range(400):
        coord = rng.choice((1, 2, 3))
        pts = [(rng.randint(-coord, coord), rng.randint(0, coord), rng.randint(0, coord)) for _ in range(rng.randint(1, 10))]
        assert outcome(ref.hull3d, pts) == outcome(oracle.hull3d_brute, pts), pts


def test_h6_reference_matches_oracles():
    ref, oracle = item_module("h6", "reference"), item_module("h6", "oracle")
    rng = random.Random(6)
    for _ in range(300):
        rows, cols = rng.randint(1, 4), rng.randint(1, 5)
        board = ["".join("#" if rng.random() < 0.15 else "." for _ in range(cols)) for _ in range(rows)]
        assert ref.count_tilings(board) == oracle.count_tilings_brute(board), board
    for rows, cols in ((5, 6), (6, 5), (4, 8)):
        board = ["." * cols] * rows
        assert ref.count_tilings(board) == oracle.count_tilings_memo(board)


def test_h3_reference_matches_oracle_on_random_programs():
    ref, oracle = item_module("h3", "reference"), item_module("h3", "oracle")
    gen = item_module("h3", "gen_programs")

    def outcome(fn, src):
        try:
            return fn(src)
        except (SyntaxError, NameError, TypeError) as exc:
            return type(exc).__name__

    for src in gen.programs(17, 400):
        assert outcome(ref.infer, src) == outcome(oracle.infer_oracle, src), src


def test_h3_hidden_programs_are_the_generated_ones():
    tests = load("h3_tests_for_check", V3_DIR / "h3" / "tests.py")
    gen = item_module("h3", "gen_programs")
    assert tests.PROGRAMS == gen.programs(7, 400)


def test_h5_reference_matches_oracle():
    ref, oracle = item_module("h5", "reference"), item_module("h5", "oracle")
    gen = item_module("h5", "gen_patterns")

    def outcome(fn, *args):
        try:
            return fn(*args)
        except ValueError:
            return "VE"

    patterns, alphabets = gen.patterns(23, 300), gen.alphabets(24, 300)
    for pattern, alphabet in zip(patterns, alphabets):
        assert outcome(ref.min_dfa_size, pattern, alphabet) == outcome(oracle.min_dfa_size_oracle, pattern, alphabet)
    for i in range(0, 120, 2):
        first, second, alphabet = patterns[i], patterns[i] + "|" + patterns[i + 1], alphabets[i]
        got = outcome(ref.distinguish, first, second, alphabet)
        want = outcome(oracle.distinguish_oracle, first, second, alphabet, 5)
        assert got == want or (isinstance(got, str) and got != "VE" and len(got) > 5 and want is None)


def test_h5_hidden_patterns_are_the_generated_ones():
    tests = load("h5_tests_for_check", V3_DIR / "h5" / "tests.py")
    gen = item_module("h5", "gen_patterns")
    assert tests.PATTERNS == gen.patterns(21, 300) and tests.ALPHABETS == gen.alphabets(22, 300)


def test_h2_reference_matches_oracles():
    ref, oracle = item_module("h2", "reference"), item_module("h2", "oracle")
    rng = random.Random(8)
    for _ in range(300):
        alpha = rng.choice(("ab", "abc", "abcdef"))
        a = [rng.choice(alpha) for _ in range(rng.randint(0, 9))]
        b = [rng.choice(alpha) for _ in range(rng.randint(0, 9))]
        assert ref.shortest_edit_script(a, b) == oracle.ses_enumerate(a, b) == oracle.ses_table(a, b), (a, b)


# ------------------------------------------------------------------------------------------------ 数学


@pytest.mark.parametrize("item", common.MATH_ITEMS)
def test_math_answers_match_reference_and_numeric_check(item):
    ref = load(f"{item}_math_reference", MATH_DIR / item / "reference.py")
    answer = json.loads((MATH_DIR / item / "answer.json").read_text(encoding="utf-8"))
    values = ref.answers()
    assert [part["key"] for part in answer["parts"]] == list(values)
    for part in answer["parts"]:
        assert part["value"] == pytest.approx(values[part["key"]], rel=1e-12)
        # 作成時の大きなモンテカルロ（verify_numeric.py）との差が標準誤差の 3 倍以内
        assert abs(part["monte_carlo"] - part["value"]) <= 3 * part["monte_carlo_std_error"] + 1e-9
    numeric = ref.numeric_check()
    for key, value in values.items():
        tolerance = 0.06 if (item, key) in (("m1", "b"), ("m2", "b"), ("m2", "c")) else 0.02
        assert numeric[key] == pytest.approx(value, rel=tolerance), (key, numeric[key], value)


def test_math_closed_forms():
    m3 = load("m3_math_reference", MATH_DIR / "m3" / "reference.py").answers()
    assert m3["a"] == pytest.approx(1 - math.pi / 6) and m3["b"] == pytest.approx(0.488 - 0.028 * math.pi)
    m1 = load("m1_math_reference", MATH_DIR / "m1" / "reference.py").answers()
    expected = math.sqrt(2) / 12 + math.sqrt(3) * 0.6 + 3 * (math.pi - math.acos(1 / 3)) * 0.36 + 4 / 3 * math.pi * 0.216
    assert m1["a"] == pytest.approx(expected)


@pytest.mark.parametrize("text,value", [
    ("4.12534", 4.12534), ("2π - 8/3", 2 * math.pi - 8 / 3), ("\\frac{\\sqrt{2}}{12}", math.sqrt(2) / 12),
    ("$1 - \\frac{\\pi}{6}$", 1 - math.pi / 6), ("2√3", 2 * math.sqrt(3)), ("1e-5", 1e-5),
    ("3(π-acos(1/3))", 3 * (math.pi - math.acos(1 / 3))), ("1−π/6 ≈ 0.4764", 0.4764), ("0.6^3", 0.216),
    ("−0.0238", -0.0238),
])
def test_grade_math_evaluates_expressions(text, value):
    assert grade_math.evaluate(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["import os", "__import__('os')", "2**1000", "open('x')", "4.1（約）", ""])
def test_grade_math_rejects_unsafe_or_unreadable(text):
    assert grade_math.evaluate(text) is None


def test_grade_math_scores_parts_and_last_line_wins():
    content = "考え方\n**答え(a):** 1\n答え（b）： 0.488 - 0.028*pi\n答え(c): 0.466171\n答え(a): 1 - pi/6\n"
    grade = grade_math.grade_math(content, MATH_DIR / "m3")
    assert grade["score"] == 1.0 and grade["all_passed"]
    wrong = grade_math.grade_math("答え(a): 1 - pi/6\n答え(b): 0.4\n", MATH_DIR / "m3")
    assert wrong["passed"] == 1 and not wrong["all_passed"]
    none = grade_math.grade_math("答えは分からない", MATH_DIR / "m3")
    assert none["score"] == 0 and none["no_answer"]


def test_run_eval_grades_math_and_coding_v3(work_tmp):
    grade = run_eval.grade_answer("math", "m1", "答え(a): 4.12534\n答え(b): 13.1342", "ok", work_tmp)
    assert grade["kind"] == "math" and grade["all_passed"]
    code = (V3_DIR / "h4" / "reference.py").read_text(encoding="utf-8")
    grade = run_eval.grade_answer("coding_v3", "h4", f"```python\n{code}\n```", "ok", work_tmp / "h4")
    assert grade["kind"] == "coding" and grade["all_passed"]


# ------------------------------------------------------------------------------------------------ 締切と進捗


@pytest.fixture
def offline_target(monkeypatch, work_tmp):
    target = targets_module.Target(key="fake:model", label="fake", family="ollama", backend="ollama",
                                   slug="fake-model", model="fake:model", base_url="http://127.0.0.1:9")
    monkeypatch.setattr(run_eval.targets_module, "get", lambda key: target)
    monkeypatch.setattr(run_eval, "gpu_snapshot", lambda: None)
    monkeypatch.setattr(run_eval, "preflight", lambda *_args, **_kwargs: {"checked_at": common.now_iso()})
    monkeypatch.setattr(common, "WORK_DIR", work_tmp / "work")
    return target


def test_run_past_deadline_skips_everything_and_writes_progress(offline_target, work_tmp):
    results = work_tmp / "results"
    state = work_tmp / "progress.json"
    past = (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=1)).isoformat(timespec="seconds")
    argv = ["run", "--target", "fake:model", "--suite", "hard", "--results-dir", str(results), "--no-preload",
            "--deadline", past, "--progress", str(state)]
    assert run_eval.main(argv) == 0
    for suite, item in common.HARD_ORDER:
        record = json.loads((results / "local" / "fake-model" / suite / f"{item}-run1.json").read_text("utf-8"))
        assert record["status"] == common.STATUS_SKIPPED and "締切" in record["error"]
        assert record["grade"]["score"] == 0.0
    lane = json.loads(state.read_text(encoding="utf-8"))["lanes"]["local"]
    assert lane["done"] == 9 and lane["total"] == 9 and lane["target"] == "fake:model"


@pytest.fixture
def jst():
    """進捗の表示は、実行した機体の現地時刻で時刻を出す（意図した動作）。

    時刻の文字列（「10-18 16:15」など）を比べる試験は、現地時刻が UTC の CI の機体でも同じになるよう、
    日本時間（UTC+9）に固定して走らせる。POSIX 形式の TZ なので tzdata が無い機体でも動く。
    """
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "JST-9"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


def fixed_state(t0: datetime.datetime) -> dict:
    state = progress.empty_state()
    state["t0"] = progress.iso(t0)
    state["phases"][0]["started_at"] = progress.iso(t0)
    state["phases"][0]["finished_at"] = progress.iso(t0 + datetime.timedelta(minutes=100))
    state["phases"][1]["started_at"] = progress.iso(t0 + datetime.timedelta(minutes=100))
    state["lanes"]["local"] = {"target": "qwen3.8:27b", "model_index": 3, "model_count": 9, "budget_min": 70,
                               "base_budget_min": 70, "spent_min": 20, "item": "h3", "suite": "coding_v3",
                               "item_started_at": progress.iso(t0 + datetime.timedelta(minutes=290)),
                               "done": 3, "total": 9, "status": "running"}
    state["lanes"]["claude"] = {"total": 54, "active": [{"model": "opus", "item": "h2", "run": 2,
                                                         "started_at": progress.iso(t0 + datetime.timedelta(minutes=297))}]}
    return state


def test_progress_view_remaining_times():
    t0 = datetime.datetime(2026, 10, 18, 15, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    now = t0 + datetime.timedelta(minutes=300)
    view = progress.build_view(fixed_state(t0), at=now)
    assert view["elapsed_total_min"] == pytest.approx(300)
    assert view["remaining_total_min"] == pytest.approx(18 * 60 - 300)
    p0, p1 = view["phases"][0], view["phases"][1]
    assert p0["state"] == "done" and p0["elapsed_min"] == pytest.approx(100)
    assert p1["state"] == "running" and p1["elapsed_min"] == pytest.approx(200)
    # いまのモデルの残り: 70 - 20 - 10（この問の経過）= 40、後のモデル 6 × (70 + 5) = 450
    assert p1["remaining_models_min"] == pytest.approx(490)
    assert p1["remaining_min"] == pytest.approx(490)
    assert view["claude"]["active"][0]["elapsed_min"] == pytest.approx(3)
    text = progress.render(view)
    for needle in ("qwen3.8:27b（3/9 モデル目）", "問 h3", "opus h2 run2", "[全行程] 経過 5:00 / 18:00", "期限まで残り 13:00",
                   "P1  進行中", "P0  終了"):
        assert needle in text, needle


def test_progress_deadline_caps_local_remaining():
    t0 = datetime.datetime(2026, 10, 18, 15, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    state = fixed_state(t0)
    state["lanes"]["local"]["deadline"] = progress.iso(t0 + datetime.timedelta(minutes=400))
    view = progress.build_view(state, at=t0 + datetime.timedelta(minutes=300))
    assert view["phases"][1]["remaining_models_min"] == pytest.approx(100)


def test_progress_cli_init_phase_lane_claude_show(work_tmp, capsys):
    state = work_tmp / "p.json"
    base = ["--state", str(state)]
    assert progress_cli.main(base + ["init", "--t0", "2026-10-18T15:40:41+09:00"]) == 0
    with pytest.raises(SystemExit):
        progress_cli.main(base + ["init"])
    assert progress_cli.main(base + ["phase", "start", "P2"]) == 0
    assert progress_cli.main(base + ["lane", "local", "--set", "target=gemma4:e4b", "model_index=1", "model_count=9",
                                     "budget_min=70", "item="]) == 0
    assert progress_cli.main(base + ["claude", "start", "--model", "sonnet", "--item", "h1", "--run", "1"]) == 0
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["lanes"]["local"]["model_index"] == 1 and "item" not in data["lanes"]["local"]
    assert data["lanes"]["claude"]["active"][0]["model"] == "sonnet"
    assert progress_cli.main(base + ["claude", "end", "--model", "sonnet", "--item", "h1", "--run", "1"]) == 0
    capsys.readouterr()
    assert progress_cli.main(base + ["show", "--json"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["claude"]["active"] == [] and view["phases"][2]["state"] == "running"


def test_progress_unlimited_budget_estimates_from_items():
    t0 = datetime.datetime(2026, 10, 18, 15, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    state = fixed_state(t0)
    # 上限なし: 6 問記録済みで累計 78 分 → 1 問 13 分。いまの問は 10 分経過 → 残り 3 分 + 残り 2 問 × 13 = 29。
    # 後のモデルの 5 問 × est_item_min 20 = 100、後のモデル 1 つ × 切替 5。計 134
    state["lanes"]["local"].update(budget_min=100000, base_budget_min=100000, model_index=1, model_count=2,
                                   spent_min=78, done=6, total=9, items_after=5, est_item_min=20)
    view = progress.build_view(state, at=t0 + datetime.timedelta(minutes=300))
    assert view["phases"][1]["remaining_models_min"] == pytest.approx(134)
    text = progress.render(view)
    assert "上限なし" in text and "残りの問と 1 問の見込みから" in text
    # まだ記録の無いモデル（done 0）は est_item_min で見込む。問の送信の前（読み込み中）は全部の問を数える
    state["lanes"]["local"].update(spent_min=0, done=0, total=3, items_after=0, model_count=1)
    state["lanes"]["local"].pop("item_started_at")
    view = progress.build_view(state, at=t0 + datetime.timedelta(minutes=300))
    assert view["phases"][1]["remaining_models_min"] == pytest.approx(60)


def test_progress_added_phase_and_lifted_deadline(work_tmp, capsys, jst):
    state = work_tmp / "p.json"
    base = ["--state", str(state)]
    assert progress_cli.main(base + ["init", "--t0", "2026-10-18T15:40:41+09:00"]) == 0
    assert progress_cli.main(base + ["phase", "add", "P1b", "--label", "流し直し", "--planned-min", "160",
                                     "--depends", "P1", "--before", "P3", "--lane", "local"]) == 0
    with pytest.raises(ValueError):
        progress_cli.main(base + ["phase", "add", "P1b", "--label", "x", "--planned-min", "1"])
    with pytest.raises(KeyError):
        progress_cli.main(base + ["phase", "add", "P9", "--label", "x", "--planned-min", "1", "--depends", "PX"])
    data = json.loads(state.read_text(encoding="utf-8"))
    assert [phase["id"] for phase in data["phases"]] == ["P0", "P1", "P2", "P1b", "P3"]
    assert data["phases"][-1]["depends"] == ["P1", "P2", "P1b"]
    assert progress_cli.main(base + ["deadline", "lift", "--note", "ユーザーの指示"]) == 0
    t0 = progress.parse_time("2026-10-18T15:40:41+09:00")
    loaded = progress.load(state)
    for index, minutes in ((0, (0, 100)), (2, (100, 200))):
        loaded["phases"][index]["started_at"] = progress.iso(t0 + datetime.timedelta(minutes=minutes[0]))
        loaded["phases"][index]["finished_at"] = progress.iso(t0 + datetime.timedelta(minutes=minutes[1]))
    loaded["phases"][1]["started_at"] = progress.iso(t0 + datetime.timedelta(minutes=100))
    loaded["phases"][1]["finished_at"] = progress.iso(t0 + datetime.timedelta(minutes=500))
    view = progress.build_view(loaded, at=t0 + datetime.timedelta(minutes=510))
    p1b, p3 = view["phases"][3], view["phases"][4]
    assert p1b["id"] == "P1b" and p1b["state"] == "waiting"
    # P1b は P1 の終了（500 分）より後の今（510 分）から 160 分、P3 はその後
    assert progress.parse_time(p3["planned_start_at"]) == t0 + datetime.timedelta(minutes=670)
    text = progress.render(view)
    assert "期限なし（当初の期限 10-19 09:40 は" in text and "ユーザーの指示" in text and "期限まで残り" not in text
    assert progress_cli.main(base + ["deadline", "restore"]) == 0
    assert "期限まで残り" in progress.render(progress.build_view(progress.load(state)))


def test_run_local_dry_run_lists_order_and_budget(work_tmp):
    env = dict(os.environ, ORDER="gemma4:e4b,strata-official:IQ3_XXS,qwen3.8-flash-next:IQ4_XS", SUITE="hard",
               RUN_DATE="pytest-dry-run", BUDGET_MIN="70",
               DEADLINE=(datetime.datetime.now().astimezone() + datetime.timedelta(hours=2)).isoformat(timespec="seconds"))
    out = subprocess.run([str(TOOL_DIR / "run_local.sh"), "--dry-run"], env=env, capture_output=True, text=True,
                         check=True).stdout
    lines = [line for line in out.splitlines() if line.startswith("  ")]
    assert [line.split()[1].split("（")[0] for line in lines] == ["gemma4:e4b", "strata-official:IQ3_XXS", "qwen3.8-flash-next:IQ4_XS"]
    assert "unit strata-official" in lines[1]
    # 締切まで 2 時間・3 モデル: (120 - 15) / 3 = 35 分に詰まる
    assert "上限 35.0 分" in lines[0] or "上限 34.9 分" in lines[0]
    assert not (TOOL_DIR / "results" / "pytest-dry-run").exists()


# ------------------------------------------------------------------------------------------------ 集計と HTML


def test_summarize_and_build_report_hard(work_tmp, monkeypatch):
    import summarize
    import build_report_hard
    from html.parser import HTMLParser

    monkeypatch.setattr(common, "WORK_DIR", work_tmp / "work")
    results = work_tmp / "results"
    h4 = (V3_DIR / "h4" / "reference.py").read_text(encoding="utf-8")
    for model, scores in (("sonnet", ("4.12534", "1")), ("opus", ("4.12534", "13.1342"))):
        for run in (1, 2, 3):
            common.write_json(results / "claude" / model / "math" / f"m1-run{run}.json",
                              {"model": model, "suite": "math", "item": "m1", "run": run, "wall_s": 30.0,
                               "content": f"答え(a): {scores[0]}\n答え(b): {scores[1]}", "usage": None, "tool_uses": 0,
                               "grade": None})
            common.write_json(results / "claude" / model / "coding_v3" / f"h4-run{run}.json",
                              {"model": model, "suite": "coding_v3", "item": "h4", "run": run, "wall_s": 60.0,
                               "content": f"```python\n{h4}\n```", "usage": None, "tool_uses": 0, "grade": None})
    assert run_eval.main(["grade-claude", "--results-dir", str(results)]) == 0
    summary = summarize.summarize(results, ("coding_v3", "math"), include_math3d=False)
    compare = summary["claude_comparison"]
    m1 = next(row for row in compare["rows"] if row["item"] == "m1")
    assert m1["sonnet"]["scores"] == [0.5, 0.5, 0.5] and m1["opus"]["scores"] == [1.0, 1.0, 1.0]
    assert m1["verdict"] == "opus" and m1["sonnet"]["failed_cases"] == ["(b)"]
    h4_row = next(row for row in compare["rows"] if row["item"] == "h4")
    assert h4_row["verdict"] == "同じ"
    assert compare["total_verdict"] == "opus" and compare["run_totals"]["opus"] == [2.0, 2.0, 2.0]
    assert "hard" in summary["suites"] and summary["suites"]["hard"]["items"][:6] == list(common.CODING_V3_ITEMS)
    html_text = build_report_hard.build_html(summary, {"facts": ["事実 1"], "opinions": ["意見 1"]})

    class Counter(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sections = 0
            self.svgs = 0
            self.external = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            self.sections += tag == "section"
            self.svgs += tag == "svg"
            for key in ("src", "href"):
                if attrs.get(key, "").startswith(("http:", "https:", "//")):
                    self.external.append(attrs[key])

    counter = Counter()
    counter.feed(html_text)
    assert counter.sections == 9 and counter.svgs >= 9 and not counter.external
    assert "Sonnet と Opus の差" in html_text and "Opus が上" in html_text and "事実 1" in html_text


def test_budget_reruns_and_budget_text(work_tmp):
    import build_report_hard
    import summarize

    assert build_report_hard.budget_text({"a": [70.0, 100000.0]}, "a") == "70 分 → 上限なし"
    assert build_report_hard.budget_text({"a": 70.0}, "a") == "70 分"
    assert build_report_hard.budget_text({}, "a") == "—"
    results = work_tmp / "2026-10-18"
    target = targets_module.BY_KEY["qwen3.8:27b"]
    common.write_json(results / summarize.BUDGET_SKIPPED_DIR / target.slug / "coding_v3" / "h2-run1.json",
                      {"status": "skipped_time_budget", "error": "累計 79.4 分が上限 70.0 分を超えた"})
    common.write_json(results / "local" / target.slug / "coding_v3" / "h2-run1.json",
                      {"status": "ok", "wall_s": 747.0, "grade": {"score": 1.0}})
    common.write_json(results / "local" / target.slug / "meta.json",
                      {"sessions": [{"argv": ["run", "--time-budget-min", "70.0"]},
                                    {"argv": ["run", "--time-budget-min", "70.0"]},
                                    {"argv": ["run", "--time-budget-min", "100000"]}]})
    reruns = summarize.budget_reruns(results)
    assert len(reruns) == 1 and reruns[0]["key"] == "qwen3.8:27b" and reruns[0]["score_gained"] == 1.0
    assert reruns[0]["items"][0] == {"suite": "coding_v3", "item": "h2", "skipped_reason": "累計 79.4 分が上限 70.0 分を超えた",
                                     "final_status": "ok", "final_score": 1.0, "final_wall_s": 747.0}
    assert summarize.model_budgets(results)["qwen3.8:27b"] == [70.0, 100000.0]


def test_progress_fmt_hm_has_no_negative_zero():
    assert progress.fmt_hm(-0.001) == "0:00"
    assert progress.fmt_hm(-61) == "-1:01"
    assert progress.fmt_hm(None) == "—"


def test_progress_all_phases_done_says_finished(jst):
    t0 = datetime.datetime(2026, 10, 18, 15, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    state = fixed_state(t0)
    for index, phase in enumerate(state["phases"]):
        phase["started_at"] = progress.iso(t0 + datetime.timedelta(minutes=index * 10))
        phase["finished_at"] = progress.iso(t0 + datetime.timedelta(minutes=index * 10 + 5))
    text = progress.render(progress.build_view(state, at=t0 + datetime.timedelta(minutes=100)))
    assert "全工程終了（10-18 16:15）" in text and "見込みの残り" not in text


def test_problem_guide_hard_validates_and_builds(work_tmp):
    import copy

    import build_problem_guide_hard as guide_builder

    guide = json.loads(guide_builder.GUIDE_PATH.read_text(encoding="utf-8"))
    assert guide_builder.validate_guide(guide) == []
    broken = copy.deepcopy(guide)
    broken["problems"][0]["example"][0]["input"] = "hull3d([])"
    broken["problems"][1]["grading"]["case_total"] = 99
    broken["problems"][6]["parts"] = broken["problems"][6]["parts"][:1]
    errors = guide_builder.validate_guide(broken)
    assert any("h1: 具体例 1 の input" in line for line in errors)
    assert any("h2: case_total 99" in line for line in errors)
    assert any("m1: parts の鍵" in line for line in errors)
    summary = work_tmp / "summary.json"
    summary.write_text(json.dumps({"generated_at": "2026-10-19T00:00:00+09:00", "models": [], "suites": {}}), encoding="utf-8")
    out = work_tmp / "guide.html"
    assert guide_builder.main(["--summary", str(summary), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    for item in common.CODING_V3_ITEMS + common.MATH_ITEMS:
        assert f'id="p-{item}"' in text
    assert text.count("<svg") == 6 and "http" not in text.split("<main>")[0]
