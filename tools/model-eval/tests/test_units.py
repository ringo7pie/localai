"""tools/model-eval の単体試験（GPU もネットも使わない。サンドボックスの子プロセスは起動する）。

  uvx --with pytest pytest tools/model-eval/tests -q

範囲: コードの取り出し、静的な走査、サンドボックス（参照解の全合格・違反の検出・時間切れ・メモリ）、追加 3 試験の採点器、
ランキングの式、Ollama / Strata のストリームの読み取り（偽のサーバー）、run_eval.py の run / grade-claude、
summarize.py と build_report.py の生成のスモーク、KV キャッシュの比べ（cond_compare.py の判定・集計・HTML・engine ログの読み取り、
run_kv_compare.sh の --dry-run）、コーディング性能の調査（run_eval.py の上限の上書き・英語の問題文・思考中停止のやり直し、
cond_compare.py の条件の集計と判定・HTML、run_fix_compare.sh の --dry-run と偽の systemctl での本流）。
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

import build_report
import cond_compare
import kv_compare
import run_eval
import summarize
import targets as targets_module
from evallib import clients, common, sandbox, scoring
from suites.extra import grade_extra, make_needle

TOOL_DIR = Path(__file__).resolve().parent.parent
CODING_DIR = TOOL_DIR / "suites" / "coding"
EXTRA_DIR = TOOL_DIR / "suites" / "extra"
# サンドボックスの仕組みの試験に使う小さな問題（旧 C1 の括弧の対応）。本番の問題とは切り離す
SANDBOX_FIXTURE = TOOL_DIR / "tests" / "fixtures" / "sandbox-item"


def reference_code(item: str) -> str:
    return (CODING_DIR / item / "reference.py").read_text(encoding="utf-8")


def fenced(code: str, tag: str = "python") -> str:
    return f"説明です。\n```{tag}\n{code}\n```\n"


# ------------------------------------------------------------------------------------------------ 問題文


def test_build_prompt_coding_has_preamble_and_problem():
    text = common.build_prompt("coding", "c1")
    preamble = (CODING_DIR / "PREAMBLE.md").read_text(encoding="utf-8").strip()
    body = (CODING_DIR / "c1" / "prompt.md").read_text(encoding="utf-8").strip()
    assert text == f"{preamble}\n\n{body}"
    assert "split_words" in text and "標準ライブラリだけ" in text


def test_build_prompt_extra_has_no_preamble():
    text = common.build_prompt("extra", "json1")
    assert text == (EXTRA_DIR / "json1" / "prompt.md").read_text(encoding="utf-8").strip()


def test_every_item_has_files():
    for item in common.CODING_ITEMS:
        for name in ("prompt.md", "tests.py", "reference.py"):
            assert (CODING_DIR / item / name).is_file(), f"{item}/{name}"
    for item in common.EXTRA_ITEMS:
        for name in ("prompt.md", "answer.json"):
            assert (EXTRA_DIR / item / name).is_file(), f"{item}/{name}"


def test_needle_files_match_generator():
    assert make_needle.main(["--check"]) == 0
    for item_id, word, depth, _seed in make_needle.NEEDLES:
        prompt = (EXTRA_DIR / item_id / "prompt.md").read_text(encoding="utf-8")
        assert prompt.count(word) == 1
        document = prompt.split('"""')[1]
        # 合言葉の位置が、資料の長さに対して決めた割合の近くにある
        assert abs(document.index(word) / len(document) - depth) < 0.05
        assert 7500 < len(document) < 9500


# ------------------------------------------------------------------------------------------------ コードの取り出し


def test_extract_last_python_block():
    text = "```python\nx = 1\n```\n途中\n```python\ndef f():\n    return 2\n```\n"
    code, how = sandbox.extract_code(text)
    assert how == "python_block" and "return 2" in code and "x = 1" not in code


def test_extract_prefers_python_over_later_plain_block():
    text = "```python\ndef f():\n    return 1\n```\n```\n実行例\n```\n"
    code, how = sandbox.extract_code(text)
    assert how == "python_block" and "return 1" in code


def test_extract_any_block_and_def_body_and_none():
    assert sandbox.extract_code("```\ndef g():\n    pass\n```")[1] == "any_block"
    code, how = sandbox.extract_code("def h():\n    return 3\n")
    assert how == "def_body" and "return 3" in code
    assert sandbox.extract_code("答えられません。") == (None, "none")


def test_extract_unterminated_block():
    code, how = sandbox.extract_code("```python\ndef k():\n    return 4\n")
    assert how == "python_block" and "return 4" in code


# ------------------------------------------------------------------------------------------------ 静的な走査


@pytest.mark.parametrize("code", [
    "import socket",
    "import urllib.request",
    "from subprocess import run",
    "from http import client",
    "import os\nos.system('ls')",
    "import os\nos.execv('/bin/ls', [])",
    "from os import system",
    "x = __import__('socket')",
    "import importlib\nimportlib.import_module(name)",
    "import ctypes",
    "import multiprocessing.pool",
])
def test_static_scan_violations(code):
    assert sandbox.static_scan(code)["violations"], code


def test_static_scan_allows_normal_code():
    scan = sandbox.static_scan("import re\nimport collections\nP = re.compile(r'x')\ndef f():\n    return open('a')")
    assert scan["violations"] == [] and scan["warnings"] == ["call open"]


def test_static_scan_problem_forbidden_calls():
    assert sandbox.static_scan("def evaluate(s):\n    return eval(s)", ("eval", "exec", "compile"))["violations"]
    assert sandbox.static_scan("f = eval", ("eval",))["violations"]
    assert sandbox.static_scan("import builtins\nbuiltins.exec('1')", ("exec",))["violations"]
    # re.compile は禁止の compile ではない
    assert not sandbox.static_scan("import re\nre.compile('a')", ("eval", "exec", "compile"))["violations"]


def test_static_scan_problem_forbidden_modules():
    # C4 の json、C5 の re のように、問題ごとにモジュール自体を禁止する。import のあらゆる形を見つける
    forbidden = ("json", "json.loads")
    for code in ("import json\ndef parse_json(t):\n    return json.loads(t)",
                 "import json as j\ndef parse_json(t):\n    return j.loads(t)",
                 "from json import loads\ndef parse_json(t):\n    return loads(t)",
                 "from json.decoder import JSONDecoder",
                 "import importlib\nm = importlib.import_module('json')"):
        assert sandbox.static_scan(code, forbidden)["violations"], code
    assert not sandbox.static_scan("import re\ndef parse_json(t):\n    return re.match('x', t)", forbidden)["violations"]
    assert not sandbox.static_scan("import json", ("eval",))["violations"]


def test_static_scan_syntax_error():
    assert sandbox.static_scan("def (:")["syntax_error"]


def test_read_forbidden_calls():
    assert sandbox.read_forbidden_calls(CODING_DIR / "c4" / "tests.py")[:2] == ("json", "json.loads")
    assert sandbox.read_forbidden_calls(CODING_DIR / "c5" / "tests.py")[:2] == ("re", "re.compile")
    assert sandbox.read_forbidden_calls(CODING_DIR / "c1" / "tests.py") == ()


def test_denied_modules_match_harness():
    tree = ast.parse((CODING_DIR / "harness.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DENIED_MODULES":
            harness_set = set(ast.literal_eval(node.value.args[0]))
            break
    else:
        pytest.fail("harness.py に DENIED_MODULES が無い")
    assert harness_set == set(sandbox.DENIED_MODULES)


# ------------------------------------------------------------------------------------------------ サンドボックス


@pytest.mark.parametrize("item", common.CODING_ITEMS)
def test_reference_solutions_pass_all_hidden_tests(item, work_tmp):
    grade = sandbox.grade_coding(fenced(reference_code(item)), CODING_DIR / item, work_tmp / item)
    failed = [case for case in grade.get("cases", []) if not case["ok"]]
    assert grade["all_passed"], failed
    assert grade["score"] == 1.0 and 15 <= grade["total"] <= 30


def test_wrong_solution_gets_partial_score(work_tmp):
    # 再帰で書いた is_balanced は深いケースで落ちる。< > を括弧に数える誤りも混ぜる
    code = (
        "def is_balanced(text):\n"
        "    pairs = {')': '(', ']': '[', '}': '{', '>': '<'}\n"
        "    def walk(index, stack):\n"
        "        if index == len(text):\n"
        "            return not stack\n"
        "        char = text[index]\n"
        "        if char in '([{<':\n"
        "            return walk(index + 1, stack + [char])\n"
        "        if char in pairs:\n"
        "            if not stack or stack[-1] != pairs[char]:\n"
        "                return False\n"
        "            return walk(index + 1, stack[:-1])\n"
        "        return walk(index + 1, stack)\n"
        "    return walk(0, [])\n"
    )
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    failed = {case["name"] for case in grade["cases"] if not case["ok"]}
    assert {"case_deep_ok", "case_angle_ignored"} <= failed
    assert 0 < grade["score"] < 1 and not grade["all_passed"]


def test_violation_is_not_executed(work_tmp):
    code = "import socket\ndef is_balanced(text):\n    return True\n"
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    assert grade["score"] == 0.0 and grade["violations"] == ["import socket"]
    assert not (work_tmp / "solution.py").exists()


def test_runtime_import_guard_blocks_dynamic_import(work_tmp):
    # 静的な走査をすり抜ける書き方でも、実行中の meta path で拒む
    code = ("loader = getattr(__import__('importlib'), 'import_module')\n"
            "net = loader('so' + 'cket')\n"
            "def is_balanced(text):\n    return True\n")
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    assert grade["score"] == 0.0
    assert "not allowed" in (grade["import_error"] or "")


def test_runtime_blocks_file_write_and_fork(work_tmp):
    code = ("import os\n"
            "def is_balanced(text):\n"
            "    if text == '':\n"
            "        open('written.txt', 'w').write('x')\n"
            "    if text == '(':\n"
            "        getattr(os, 'fo' + 'rk')()\n"
            "    return text.count('(') == text.count(')')\n")
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    errors = {case["name"]: case["error"] for case in grade["cases"]}
    assert "PermissionError" in errors["case_empty"]
    assert "PermissionError" in errors["case_single_open"]
    assert not (work_tmp / "written.txt").exists()


def test_infinite_loop_case_times_out_but_others_count(work_tmp):
    code = ("def is_balanced(text):\n"
            "    while text == '':\n"
            "        pass\n"
            "    stack = []\n"
            "    pairs = {')': '(', ']': '[', '}': '{'}\n"
            "    for char in text:\n"
            "        if char in '([{':\n"
            "            stack.append(char)\n"
            "        elif char in pairs:\n"
            "            if not stack or stack.pop() != pairs[char]:\n"
            "                return False\n"
            "    return not stack\n")
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    errors = {case["name"]: case["error"] for case in grade["cases"]}
    assert errors["case_empty"].startswith("timeout")
    assert grade["passed"] == grade["total"] - 1


def test_memory_limit(work_tmp):
    code = "BIG = bytearray(3 * 1024 ** 3)\ndef is_balanced(text):\n    return True\n"
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    assert grade["score"] == 0.0 and "MemoryError" in (grade["import_error"] or "")


def test_no_code_is_no_answer(work_tmp):
    grade = sandbox.grade_coding("わかりません", SANDBOX_FIXTURE, work_tmp)
    assert grade["no_answer"] and grade["score"] == 0.0


def test_print_in_solution_does_not_break_protocol(work_tmp):
    code = 'print("{\\"done\\": true}")\n' + (SANDBOX_FIXTURE / "reference.py").read_text(encoding="utf-8")
    grade = sandbox.grade_coding(fenced(code), SANDBOX_FIXTURE, work_tmp)
    assert grade["all_passed"]


# ------------------------------------------------------------------------------------------------ 追加 3 試験


def inst_answer(item: str) -> dict:
    return json.loads((EXTRA_DIR / item / "answer.json").read_text(encoding="utf-8"))


def test_inst1_ideal_and_broken_answers():
    ideal = "- 本を読みます。\n- 映画を観ます。\n- 料理をします。\n- 部屋を片付けます。\n- 昼寝をします。\n以上"
    grade = grade_extra.grade_inst(ideal, inst_answer("inst1"))
    assert grade["score"] == 1.0, grade
    broken = "雨の日のおすすめです。\n- 本を読みます\n- DVD で映画を観ます。\n- 料理をします。\n- 昼寝です。\n以上です。"
    grade = grade_extra.grade_inst(broken, inst_answer("inst1"))
    results = {check["id"]: check["ok"] for check in grade["checks"]}
    assert results == {"bullet_count": False, "max_line_chars": True, "bullet_endings": False,
                       "last_line": False, "no_latin": False}


def test_inst2_ideal_answer_and_digit_check():
    ideal = ("注意点は次のとおりです。\n- 使い回しをしません。\n- 定期的に見直します。\n- 人に教えません。\n"
             "- 長く複雑にします。\n以上")
    assert grade_extra.grade_inst(ideal, inst_answer("inst2"))["score"] == 1.0
    with_digit = ideal.replace("長く", "１２文字以上の長さに")
    results = {check["id"]: check["ok"] for check in grade_extra.grade_inst(with_digit, inst_answer("inst2"))["checks"]}
    assert results["no_digits"] is False and results["bullet_block"] is True


def test_inst3_ideal_answer_and_list_marks():
    ideal = ("朝ごはんを食べると頭が働きます。\n朝ごはんで体温が上がります。\n朝ごはんは生活の調子を整えます。")
    assert grade_extra.grade_inst(ideal, inst_answer("inst3"))["score"] == 1.0
    numbered = "\n".join(f"{index}. {line}" for index, line in enumerate(ideal.splitlines(), 1))
    results = {check["id"]: check["ok"] for check in grade_extra.grade_inst(numbered, inst_answer("inst3"))["checks"]}
    assert results["line_count"] is False


@pytest.mark.parametrize("content,expected", [
    ("月影ポプラ", 1.0),
    ("「月影ポプラ」", 1.0),
    ("**月影ポプラ**。", 1.0),
    ("  月影ポプラ\n", 1.0),
    ("合言葉は月影ポプラです。", 0.0),
    ("月影ポプラー", 0.0),
])
def test_needle_grading(content, expected):
    answer = json.loads((EXTRA_DIR / "needle1" / "answer.json").read_text(encoding="utf-8"))
    assert grade_extra.grade_needle(content, answer)["score"] == expected


def test_json_grading_modes_and_types():
    expected = json.loads((EXTRA_DIR / "json2" / "answer.json").read_text(encoding="utf-8"))
    perfect = json.dumps(expected["expected"], ensure_ascii=False)
    assert grade_extra.grade_json(perfect, expected)["parse_mode"] == "strict"
    assert grade_extra.grade_json(f"```json\n{perfect}\n```", expected)["score"] == 1.0
    embedded = grade_extra.grade_json(f"結果です: {perfect} 以上", expected)
    assert embedded["parse_mode"] == "embedded" and embedded["score"] == 1.0
    wrong = dict(expected["expected"], participants="3", has_allergy="true", phone="０９０-１２３４-５６７８", note="x")
    graded = grade_extra.grade_json(json.dumps(wrong, ensure_ascii=False), expected)
    # 数と真偽値を文字列で返したら不一致。全角の電話番号は NFKC で一致
    assert graded["matched"] == 4 and graded["extra_keys"] == ["note"]
    assert grade_extra.grade_json("JSON ではありません", expected)["score"] == 0.0


def test_grade_extra_no_content():
    grade = grade_extra.grade_extra("  ", EXTRA_DIR / "json1")
    assert grade["no_answer"] and grade["score"] == 0.0


def test_json_expected_answers_follow_the_texts():
    # 期待値の取り違えを防ぐ: 日付・人数などが問題文の記述と合っているか
    assert "10 月 24 日（土）" in (EXTRA_DIR / "json2" / "prompt.md").read_text(encoding="utf-8")
    import datetime
    assert datetime.date(2026, 10, 24).weekday() == 5
    assert json.loads((EXTRA_DIR / "json3" / "answer.json").read_text(encoding="utf-8"))["expected"]["affected_users"] == 5


# ------------------------------------------------------------------------------------------------ 式


def test_speed_scores_log_scale():
    scores = scoring.speed_scores({"fast": 108.0, "slow": 3700.0, "mid": math.sqrt(108.0 * 3700.0), "none": None})
    assert scores["fast"] == pytest.approx(1.0) and scores["slow"] == pytest.approx(0.0)
    assert scores["mid"] == pytest.approx(0.5) and scores["none"] is None
    assert scoring.speed_scores({"only": 10.0}) == {"only": 1.0}


def test_overall_and_rank():
    assert scoring.overall(1.0, 0.5) == pytest.approx(0.85)
    assert scoring.overall(0.5, None) == pytest.approx(0.35)
    assert scoring.overall(None, 1.0) is None
    assert scoring.rank({"a": 0.9, "b": 0.8, "c": 0.9, "d": None}) == {"a": 1, "b": 3, "c": 1, "d": None}


def test_thinking_estimate():
    assert clients.estimate_thinking_tokens(1000, 300, 100) == 750
    assert clients.estimate_thinking_tokens(1000, 0, 100) == 0
    assert clients.estimate_thinking_tokens(None, 10, 10) is None


# ------------------------------------------------------------------------------------------------ ストリームの読み取り


def ollama_script(lines_delay: float = 0.0, extra_sleep: float = 0.0, content: str = "```python\nx = 1\n```"):
    def script(handler, method, path, body):
        if method == "GET" and path == "/api/tags":
            return handler.send_json({"models": [{"name": "fake:model"}]})
        if method == "GET" and path == "/api/version":
            return handler.send_json({"version": "0.0-test"})
        if method == "GET" and path == "/api/ps":
            return handler.send_json({"models": []})
        if method == "POST" and path == "/api/chat":
            assert body["stream"] is True and body["think"] is True and "num_ctx" not in body["options"]
            handler.start_stream()
            handler.write_line(json.dumps({"message": {"role": "assistant", "content": "", "thinking": "考える"},
                                           "done": False}))
            time.sleep(extra_sleep)
            for _ in range(int(lines_delay and 20)):
                handler.write_line(json.dumps({"message": {"thinking": "まだ"}, "done": False}))
                time.sleep(lines_delay)
            handler.write_line(json.dumps({"message": {"content": content}, "done": False}))
            handler.write_line(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop",
                                           "prompt_eval_count": 50, "prompt_eval_duration": 100_000_000,
                                           "eval_count": 40, "eval_duration": 2_000_000_000,
                                           "load_duration": 500_000_000, "total_duration": 3_000_000_000}))
            return None
        return handler.send_json({"error": "not found"}, status=404)

    return script


def test_chat_ollama_success(fake_server):
    url = fake_server(ollama_script())
    payload = {"model": "fake:model", "messages": [], "stream": True, "think": True, "options": {"num_predict": 10}}
    result = clients.chat_ollama(url, payload, stall_s=5, deadline_s=30)
    assert result["status"] == "ok" and result["finish"] == "stop"
    assert result["thinking"] == "考える" and "x = 1" in result["content"]
    assert result["completion_tokens"] == 40 and result["server_decode_tok_s"] == 20.0
    assert result["load_s"] == 0.5 and result["ttft_s"] is not None and result["t_first_content_s"] is not None
    assert 0 < result["thinking_tokens_est"] < 40


def test_chat_ollama_stall(fake_server):
    url = fake_server(ollama_script(extra_sleep=2.0))
    payload = {"model": "fake:model", "messages": [], "stream": True, "think": True, "options": {}}
    result = clients.chat_ollama(url, payload, stall_s=0.5, deadline_s=30)
    assert result["status"] == "stall" and result["thinking"] == "考える" and result["content"] == ""
    assert result["delta_chunks"] == 1 and result["completion_tokens"] is None


def test_chat_ollama_deadline(fake_server):
    url = fake_server(ollama_script(lines_delay=0.05))
    payload = {"model": "fake:model", "messages": [], "stream": True, "think": True, "options": {}}
    result = clients.chat_ollama(url, payload, stall_s=5, deadline_s=0.3)
    assert result["status"] == "timeout"


def test_chat_ollama_http_error(fake_server):
    url = fake_server(lambda handler, method, path, body: handler.send_json({"error": "model not found"}, status=404))
    result = clients.chat_ollama(url, {"model": "x", "messages": [], "stream": True}, stall_s=5, deadline_s=5)
    assert result["status"] == "error" and "404" in result["error"]


def strata_script(handler, method, path, body):
    if method == "GET" and path == "/v1/models":
        return handler.send_json({"data": [{"id": "strata-official:IQ3_XXS"}]})
    assert path == "/v1/chat/completions" and body["reasoning_effort"] == "high"
    assert body["reasoning_budget_tokens"] == 6144 and body["top_k"] == 20
    handler.start_stream("text/event-stream")
    handler.write_line(": ping")
    handler.write_line("")

    def data(obj):
        handler.write_line("data: " + json.dumps(obj, ensure_ascii=False))
        handler.write_line("")

    data({"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]})
    data({"choices": [{"index": 0, "delta": {"reasoning_content": "思考"}, "finish_reason": None}]})
    data({"choices": [{"index": 0, "delta": {"content": "月影ポプラ"}, "finish_reason": None}]})
    data({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 6400, "completion_tokens": 30},
          "timings": {"predicted_per_second": 58.2, "prompt_per_second": 900.0}})
    handler.write_line("data: [DONE]")
    return None


def test_chat_strata_success(fake_server):
    url = fake_server(strata_script) + "/v1"
    target = targets_module.get("strata-official:IQ3_XXS")
    payload = run_eval.build_payload(target, "extra", "質問", "15m")
    result = clients.chat_strata(url, payload, stall_s=5, deadline_s=30)
    assert result["status"] == "ok" and result["content"] == "月影ポプラ" and result["thinking"] == "思考"
    assert result["completion_tokens"] == 30 and result["server_decode_tok_s"] == 58.2


def test_build_payload_ollama_sends_no_sampling_or_num_ctx():
    payload = run_eval.build_payload(targets_module.get("gemma4:31b-it-qat"), "coding", "q", "15m")
    assert payload["options"] == {"num_predict": 32768} and payload["think"] is True
    assert "temperature" not in payload


# ------------------------------------------------------------------------------------------------ run_eval.py


@pytest.fixture
def fake_target(fake_server, monkeypatch, work_tmp):
    url = fake_server(ollama_script(content=fenced(reference_code("c1"))))
    target = targets_module.Target(key="fake:model", label="fake", family="ollama", backend="ollama",
                                   slug="fake-model", model="fake:model", base_url=url)
    monkeypatch.setattr(run_eval.targets_module, "get", lambda key: target)
    monkeypatch.setattr(run_eval, "gpu_snapshot", lambda: None)
    monkeypatch.setattr(common, "WORK_DIR", work_tmp / "work")
    return target


def test_run_writes_record_and_resumes(fake_target, work_tmp, capsys):
    results = work_tmp / "results"
    argv = ["run", "--target", "fake:model", "--suite", "coding", "--items", "c1", "--results-dir", str(results),
            "--no-preload"]
    assert run_eval.main(argv) == 0
    record = json.loads((results / "local" / "fake-model" / "coding" / "c1-run1.json").read_text(encoding="utf-8"))
    assert record["status"] == "ok" and record["grade"]["all_passed"]
    assert record["wall_excl_load_s"] == pytest.approx(record["wall_s"] - 0.5, abs=1e-3)
    assert record["request"]["options"] == {"num_predict": 32768}
    assert "PREAMBLE" not in record["prompt"] and "split_words" in record["prompt"]
    assert (results / "local" / "fake-model" / "meta.json").exists()
    capsys.readouterr()
    # 2 回目は飛ばす
    assert run_eval.main(argv) == 0
    assert "0 問を流す" in capsys.readouterr().out


def test_run_time_budget_skips(fake_target, work_tmp):
    results = work_tmp / "results"
    argv = ["run", "--target", "fake:model", "--suite", "extra", "--items", "json1,json2", "--results-dir",
            str(results), "--no-preload", "--time-budget-min", "0"]
    assert run_eval.main(argv) == 0
    for item in ("json1", "json2"):
        record = json.loads((results / "local" / "fake-model" / "extra" / f"{item}-run1.json").read_text("utf-8"))
        assert record["status"] == common.STATUS_SKIPPED and record["grade"]["score"] == 0.0


def write_claude(results: Path, model: str, suite: str, item: str, run: int, content: str, **extra) -> Path:
    record = {"model": model, "suite": suite, "item": item, "run": run, "content": content, "wall_s": 60.0,
              "usage": None, "tool_uses": 0, "grade": None}
    record.update(extra)
    path = results / "claude" / model / suite / f"{item}-run{run}.json"
    common.write_json(path, record)
    return path


def test_grade_claude(work_tmp, monkeypatch):
    monkeypatch.setattr(common, "WORK_DIR", work_tmp / "work")
    results = work_tmp / "results"
    coding = write_claude(results, "opus", "coding", "c3", 1, fenced(reference_code("c3")))
    expected = json.loads((EXTRA_DIR / "json1" / "answer.json").read_text(encoding="utf-8"))["expected"]
    extra = write_claude(results, "sonnet", "extra", "json1", 1, json.dumps(expected, ensure_ascii=False),
                         batch_size=3)
    math3d = write_claude(results, "opus", "math3d", "3d", 1, "答え", grade={"q1": True, "q2": True, "q3": False,
                                                                             "q4": None})
    assert run_eval.main(["grade-claude", "--results-dir", str(results)]) == 0
    assert json.loads(coding.read_text("utf-8"))["grade"]["all_passed"]
    assert json.loads(extra.read_text("utf-8"))["grade"]["score"] == 1.0
    assert json.loads(math3d.read_text("utf-8"))["grade"]["q1"] is True
    # 3D の採点が無い回と、ツールを使った回は要確認（終了コード 1）
    write_claude(results, "sonnet", "math3d", "3d", 1, "答え")
    write_claude(results, "sonnet", "coding", "c1", 1, fenced(reference_code("c1")), tool_uses=2)
    assert run_eval.main(["grade-claude", "--results-dir", str(results)]) == 1


# ------------------------------------------------------------------------------------------------ 集計と HTML


class _Counter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: dict[str, int] = {}
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags[tag] = self.tags.get(tag, 0) + 1

    def handle_data(self, data):
        self.text.append(data)


def synthetic_results(work_tmp: Path) -> Path:
    results = work_tmp / "results"
    results.mkdir(parents=True)
    shutil.copy(TOOL_DIR / "results" / "2026-10-08" / "math3d_local.json", results / "math3d_local.json")
    for model in ("sonnet", "opus"):
        for run in (1, 2, 3):
            write_claude(results, model, "math3d", "3d", run, "答え", wall_s=200.0 * run,
                         grade={"q1": True, "q2": True, "q3": True, "q4": run != 2})
        for item in common.CODING_ITEMS:
            write_claude(results, model, "coding", item, 1, "", wall_s=90.0,
                         grade={"kind": "coding", "score": 1.0, "all_passed": True})
        for item in common.EXTRA_ITEMS:
            write_claude(results, model, "extra", item, 1, "", wall_s=120.0, batch_size=3,
                         grade={"kind": "extra", "score": 0.5, "all_passed": False})
    target = targets_module.get("gemma4:e4b")
    for index, item in enumerate(common.CODING_ITEMS):
        status = common.STATUS_SKIPPED if index == 5 else common.STATUS_OK
        grade = ({"score": 0.0, "no_answer": True, "reason": status} if index == 5
                 else {"score": index / 5, "all_passed": index == 4})
        common.write_json(common.local_record_path(results, target.slug, "coding", item),
                          {"target": target.key, "suite": "coding", "item": item, "status": status,
                           "wall_excl_load_s": None if index == 5 else 30.0 + index, "completion_tokens": 1000,
                           "server_decode_tok_s": 90.0, "grade": grade})
    return results


def test_summarize_and_build_report(work_tmp):
    results = synthetic_results(work_tmp)
    summary = summarize.summarize(results)
    math3d = summary["suites"]["math3d"]["models"]
    assert math3d["opus"]["ability"] == pytest.approx((1 + 0.75 + 1) / 3)
    assert math3d["opus"]["time_s"] == 400.0
    assert math3d["gemma4:e4b"]["ability"] == pytest.approx((0.5 + 0.75 + 0.75) / 3)
    assert math3d["strata-flash-next:IQ3_S"]["n_runs"] == 2
    coding = summary["suites"]["coding"]["models"]
    assert coding["gemma4:e4b"]["ability"] == pytest.approx(sum(index / 5 for index in range(5)) / 6)
    assert coding["gemma4:e4b"]["items"]["c6"]["cell"] == summarize.CELL_SKIPPED
    assert coding["gemma4:e4b"]["time_s"] == 32.0
    assert summary["suites"]["extra"]["models"]["sonnet"]["time_s"] == 40.0
    assert coding["qwen3.8:27b"]["items"]["c1"]["cell"] == summarize.CELL_MISSING
    # 1 問も記録が無いモデルは 0 点ではなく「記録なし」で、順位に入らない
    assert coding["qwen3.8:27b"]["ability"] is None and coding["qwen3.8:27b"]["rank"] is None
    assert any("qwen3.8:27b" in line for line in summary["missing"])
    assert {entry["rank"] for entry in coding.values()} >= {1}

    html_text = build_report.build_html(summary, {"facts": ["事実の行"], "opinions": ["意見の行"]})
    counter = _Counter()
    counter.feed(html_text)
    text = "".join(counter.text)
    assert counter.tags.get("svg", 0) >= 11
    assert counter.tags.get("table", 0) >= 7
    assert "速度点 = (ln T_max − ln T)" in text and "総合 = 0.7 × 能力 + 0.3 × 速度点" in text
    assert "事実の行" in text and "意見の行" in text and "Claude の時間は Agent の duration" in text
    for section in range(7):
        assert f'id="s{section}"' in html_text
    assert "http://" not in html_text and "https://" not in html_text  # 外部の資源を読まない
    out = work_tmp / "report.html"
    assert build_report.main(["--summary", str(_write(work_tmp / "summary.json", summary)), "--out", str(out)]) == 0
    assert out.stat().st_size > 10000


def _write(path: Path, data) -> Path:
    common.write_json(path, data)
    return path


def test_thinking_stats():
    assert summarize.thinking_stats("") is None
    line = "Should the comment start a new word here?"  # 20 字以上の行
    stats = summarize.thinking_stats(f"{line}\nMaybe not.\n{line}\nok\n{line}\nmaybe so")
    chars = len(f"{line}\nMaybe not.\n{line}\nok\n{line}\nmaybe so")
    assert stats["question_per_10k"] == pytest.approx(3 / chars * 10000)
    assert stats["maybe_per_10k"] == pytest.approx(2 / chars * 10000)   # 大文字小文字を区別しない
    # 20 字以上の行は 3 本で、2 本目と 3 本目が前に出た行。短い行（ok・Maybe not.）は数えない
    assert stats["repeated_line_pct"] == pytest.approx(2 / 3 * 100)


def test_cell_texts_show_status_in_words():
    texts = build_report.cell_texts
    assert texts({"cell": "no_answer", "status": "error", "reason": "error"}) == ("答えなし", "エラー")
    assert texts({"cell": "no_answer", "status": "length", "reason": "length"}) == ("答えなし", "上限")
    assert texts({"cell": "no_answer", "status": "ok", "reason": "本文が無い"}) == ("答えなし", "本文なし")
    assert texts({"cell": "scored", "status": "length", "score": 0.2, "budget_cut": True}) == ("20%", "上限・打切")
    assert texts({"cell": "scored", "status": "ok", "score": 1.0}) == ("100%", "")
    assert texts({"cell": "skipped", "status": "skipped_time_budget"}) == ("飛ばし", "")
    assert texts({"cell": "scored", "status": "ok", "score": 0.0, "violations": 1}) == ("0%", "禁止")
    assert texts({"cell": "scored", "status": "ok", "score": 0.0, "syntax_error": True}) == ("0%", "文法誤り")


def test_report_notes_ceiling_budget_archive(work_tmp):
    """天井効果・Strata の予算での打ち切り・作り直す前の版・状態の文字が、記録から HTML に出る。"""

    results = synthetic_results(work_tmp)
    rvn = targets_module.get("strata-flash-next:IQ3_S")
    for index, item in enumerate(common.CODING_ITEMS):
        status = common.STATUS_LENGTH if index == 5 else common.STATUS_OK
        common.write_json(common.local_record_path(results, rvn.slug, "coding", item),
                          {"target": rvn.key, "suite": "coding", "item": item, "status": status,
                           "wall_excl_load_s": 500.0 + index, "completion_tokens": 26000,
                           "thinking": f"Is it this? maybe.\n\n{summarize.REASONING_WRAP_UP_MARK}\n",
                           "grade": {"score": 0.2, "all_passed": False}})
    ollama = targets_module.get("qwen3.8-flash-next:IQ4_XS")
    common.write_json(common.local_record_path(results, ollama.slug, "coding", "c1"),
                      {"target": ollama.key, "suite": "coding", "item": "c1", "status": common.STATUS_ERROR,
                       "error": "HTTP 500: CUDA error", "wall_excl_load_s": 40.0,
                       "grade": {"score": 0.0, "all_passed": False, "no_answer": True, "reason": "error"}})
    archived = results / "archive-coding-v1-easy" / "local" / "qwen3.8-27b" / "coding" / "c1-run1.json"
    common.write_json(archived, {"grade": {"score": 1.0, "all_passed": True}})

    summary = summarize.summarize(results)
    coding = summary["suites"]["coding"]["models"]
    assert coding[rvn.key]["n_budget_cut"] == 6
    assert coding[rvn.key]["items"]["c1"]["thinking_stats"]["question_per_10k"] > 0
    assert coding[ollama.key]["items"]["c1"]["time_s"] is None  # エラーの問は時間の中央値に入れない
    assert summary["archives"][0]["suites"]["coding"]["qwen3.8:27b"] == {"n_items": 1, "n_all_passed": 1,
                                                                        "ability": 1.0}
    html_text = build_report.build_html(summary, None)
    counter = _Counter()
    counter.feed(html_text)
    text = "".join(counter.text)
    # 保管した v1 があるので、いまの版は難しい版（v2）と書く
    assert "天井効果: Sonnet5.5-xHigh・Opus5.5-xHigh は難しい版（v2）のコーディングでも 6 問すべてで全部合格した" in text
    assert "strata-flash-next:IQ3_S (RVN) のコーディングの答えは、どの問題も" in text
    assert "どの問題も思考が予算 24,576 トークンで打ち切られたあとのもの" in text
    assert "archive-coding-v1-easy" in text and "順位には使っていない" in text
    assert "思考のトークン数は推定" in text
    assert "qwen3.8-flash-next:IQ4_XS の C1: エラー（サーバーがエラーを返した）。答えなし・0 点" in text
    assert "strata-flash-next:IQ3_S (RVN) の C6: 上限（生成の上限トークンに届いた）。答えあり・20%" in text
    assert "上限・打切" in text


def test_cell_colors():
    assert build_report.cell_fill({"cell": "scored", "score": 1.0}) == build_report.COLOR_OK
    assert build_report.cell_fill({"cell": "scored", "score": 0.0}) == build_report.COLOR_NG
    assert build_report.cell_fill({"cell": "no_answer", "score": 0.0}) == build_report.COLOR_NA
    partial = build_report.cell_fill({"cell": "scored", "score": 0.5})
    assert partial not in (build_report.COLOR_OK, build_report.COLOR_NG, build_report.COLOR_NA)
    assert build_report.fmt_time(108) == "1 分 48 秒" and build_report.fmt_time(3720) == "1 時間 2 分"


# ------------------------------------------------------------------------------------------------ KV キャッシュの比べ（cond_compare.py）


def test_judge_scores_four_outcomes():
    judge = cond_compare.judge_scores
    assert judge([0.2, 0.5, 0.4], [0.6, 0.9, 0.7]) == cond_compare.JUDGE_UP          # fp16 の最小 0.6 > int8 の最大 0.5
    assert judge([0.6, 0.9, 0.7], [0.2, 0.5, 0.4]) == cond_compare.JUDGE_DOWN        # fp16 の最大 0.5 < int8 の最小 0.6
    assert judge([0.2, 0.5], [0.5, 0.9]) == cond_compare.JUDGE_UNDECIDED             # 最小 = 最大のとき（同点）は上がったと言わない
    assert judge([0.1, 0.9], [0.4, 0.5]) == cond_compare.JUDGE_UNDECIDED             # 幅が入れ子
    assert judge([], [0.5]) == cond_compare.JUDGE_INCOMPARABLE
    assert judge([0.5], []) == cond_compare.JUDGE_INCOMPARABLE
    assert judge([], []) == cond_compare.JUDGE_INCOMPARABLE


ENGINE_LOG = """古い行
[strata] 2026-10-08 16:59:55 engine started: /x/strata --serve --max-context 131072 --kv int8 --resident-experts
strata generate: pre-filled 7433 of 7433 slots from the profile in 8.2 s
strata serve: decode expert cache hit rate: 50.0% (50 hits / 100 lookups); 1 more
[strata] 2026-10-09 12:00:00 engine started: /x/strata --serve --max-context 131072 --kv int8 --resident-experts --kv fp16
strata generate: expert cache 6000 slots
strata generate: pre-filled 5866 of 5866 slots from the profile in 6.0 s (2115 MB/s); slot 0 verified
strata serve: decode expert cache hit rate: 90.0% (900 hits / 1000 lookups); 5 more
strata serve: decode expert cache hit rate: 80.0% (400 hits / 500 lookups); 3 more
"""


def test_parse_engine_log_uses_the_last_start_line():
    engine = cond_compare.parse_engine_log(ENGINE_LOG)
    assert engine["started_line"].startswith("[strata] 2026-10-09 12:00:00 engine started:")
    assert engine["kv"] == "fp16"
    assert engine["slots"] == {"filled": 5866, "total": 5866}      # 前の起動の 7433 ではなく、最後の起動の枠
    assert len(engine["cache_hit_lines"]) == 2 and all("hit rate" in line for line in engine["cache_hit_lines"])
    stats = cond_compare.cache_hit_stats(engine["cache_hit_lines"])
    assert stats["lookups"] == 1500 and stats["pct"] == pytest.approx(1300 / 1500 * 100)
    assert cond_compare.cache_hit_stats([])["pct"] is None
    assert cond_compare.engine_context(engine["started_line"]) == 131072


def test_parse_engine_log_after_line_ignores_old_start_lines():
    lines = ENGINE_LOG.splitlines()
    # 起動の前に数えた行数より後ろに新しい起動行が無ければ、前の日の起動行を読まずに「無い」にする
    assert cond_compare.parse_engine_log(ENGINE_LOG, after_line=len(lines))["started_line"] is None
    # 起動行より前の行数を渡せば、その後ろの最後の起動行が取れる
    assert cond_compare.parse_engine_log(ENGINE_LOG, after_line=3)["kv"] == "fp16"
    # ログが作り直されて行数が減っていた（数えた行数 > 実際の行数）ときは先頭から見る
    assert cond_compare.parse_engine_log(ENGINE_LOG, after_line=1000)["kv"] == "fp16"
    assert cond_compare.parse_engine_log("")["started_line"] is None


def test_kv_matches_follows_the_last_kv_argument():
    int8_line = "[strata] x engine started: /x/strata --serve --kv int8 --resident-experts"
    fp16_line = int8_line + " --kv fp16"            # STRATA_EXTRA_ARGS は --kv int8 の後ろに足される
    assert cond_compare.engine_kv(int8_line) == "int8" and cond_compare.engine_kv(fp16_line) == "fp16"
    assert cond_compare.kv_matches(fp16_line, "fp16") and not cond_compare.kv_matches(fp16_line, "int8")
    assert cond_compare.kv_matches(int8_line, "int8") and not cond_compare.kv_matches(int8_line, "fp16")
    assert not cond_compare.kv_matches(None, "int8")
    assert cond_compare.engine_kv("engine started: --kv=fp16") == "fp16"


def test_check_kv_command_exit_codes(work_tmp, capsys):
    log_path = work_tmp / "engine.log"
    log_path.write_text(ENGINE_LOG, encoding="utf-8")
    assert cond_compare.main(["check-kv", "--log", str(log_path), "--kv", "fp16"]) == 0
    assert cond_compare.main(["check-kv", "--log", str(log_path), "--kv", "int8"]) == 1
    assert cond_compare.main(["check-kv", "--log", str(work_tmp / "none.log"), "--kv", "int8"]) == 1   # ログも起動行も無い
    assert "不一致" in capsys.readouterr().out


def test_read_cgroup_memory_from_fake_cgroup(work_tmp):
    group = work_tmp / "user.slice" / "strata.service"
    group.mkdir(parents=True)
    (group / "memory.peak").write_text("1234567\n", encoding="utf-8")
    # memory.current は無い → None
    peak, current = cond_compare.read_cgroup_memory("strata", cgroup_of=lambda unit: "/user.slice/strata.service",
                                                  cgroup_root=work_tmp)
    assert (peak, current) == (1234567, None)
    # unit が止まっていて ControlGroup が空 → どちらも None
    assert cond_compare.read_cgroup_memory("strata", cgroup_of=lambda unit: "", cgroup_root=work_tmp) == (None, None)


def write_kv_record(root: Path, kv: str, rep: int, slug: str, item: str, score: float, *, status: str = "ok",
                    tok_s: float = 80.0, wall: float = 400.0, cut: bool = True, all_passed: bool = False) -> None:
    target = targets_module.get(slug)
    path = common.local_record_path(cond_compare.rep_dir(root, kv, rep), target.slug, "coding", item)
    thinking = f"考え中\n{summarize.REASONING_WRAP_UP_MARK}\n" if cut else "考え中"
    common.write_json(path, {"target": target.key, "suite": "coding", "item": item, "status": status,
                             "wall_excl_load_s": wall, "completion_tokens": 27000, "thinking_tokens_est": 24500,
                             "server_decode_tok_s": tok_s, "thinking": thinking,
                             "grade": {"score": score, "all_passed": all_passed}})


def write_kv_server(root: Path, kv: str, slug: str, *, slots: int, status: str = "ok", start_s: float = 70.0,
                    peak_gib: float = 20.0) -> None:
    target = targets_module.get(slug)
    log_lines = ["strata serve: decode expert cache hit rate: 90.0% (900 hits / 1000 lookups); 5 more"]
    common.write_json(cond_compare.server_info_path(root, kv, target.slug), {
        "kv": kv, "target": target.key, "unit": target.unit, "slug": target.slug, "status": status, "reps": [2, 3],
        "start_s": start_s,
        "engine_started_line": "[strata] x engine started: /x/strata --max-context 131072 --kv int8"
                               + (" --kv fp16" if kv == "fp16" else ""),
        "slots": {"filled": slots, "total": slots}, "cache_hit_lines": log_lines, "vram_used_mib": 21000,
        "memory_peak_bytes": int(peak_gib * 1024 ** 3), "memory_current_bytes": int(peak_gib * 0.9 * 1024 ** 3)})


def synthetic_kv_root(work_tmp: Path) -> Path:
    """Coder は fp16 が全部高い（上がった）、公式の C4 は fp16 が全部低い（下がった）・C5 は幅が重なる、RVN は fp16 の記録が全く無い（比べられない）。"""

    root = work_tmp / "kv"
    coder, official, rvn = cond_compare.MODEL_KEYS
    for item in cond_compare.ITEMS:
        for rep, score in ((1, 0.10), (2, 0.20), (3, 0.30)):
            write_kv_record(root, "int8", rep, coder, item, score, tok_s=100.0, wall=400.0 + rep)
            write_kv_record(root, "int8", rep, official, item, score + (0.5 if item == "c4" else 0.0), tok_s=80.0)
            write_kv_record(root, "int8", rep, rvn, item, score, tok_s=50.0)
        for rep, score in ((1, 0.60), (2, 0.70), (3, 1.00)):
            write_kv_record(root, "fp16", rep, coder, item, score, tok_s=90.0, wall=440.0, all_passed=score >= 1.0)
        for rep, score in ((1, 0.15), (2, 0.50), (3, 0.25)):
            write_kv_record(root, "fp16", rep, official, item, score, tok_s=75.0, cut=False)
    # 公式の fp16 の rep3 の C5 は上限で終わった（状態 length）
    write_kv_record(root, "fp16", 3, official, "c5", 0.0, status="length", tok_s=75.0)
    write_kv_server(root, "int8", coder, slots=8138)
    write_kv_server(root, "fp16", coder, slots=6500, peak_gib=21.5)
    write_kv_server(root, "fp16", official, slots=6000, status="kv_mismatch")
    return root


def test_build_summary_aggregates_and_judges(work_tmp):
    root = synthetic_kv_root(work_tmp)
    summary = cond_compare.build_summary(root)
    coder, official, rvn = cond_compare.MODEL_KEYS
    c4_int8 = summary["results"][coder]["c4"]["int8"]
    assert c4_int8["scores"] == [0.1, 0.2, 0.3] and c4_int8["mean"] == pytest.approx(0.2)
    assert (c4_int8["min"], c4_int8["max"]) == (0.1, 0.3) and c4_int8["n_all_passed"] == 0
    assert c4_int8["tok_s_median"] == 100.0 and c4_int8["time_s_median"] == 402.0
    assert c4_int8["thinking_tokens_median"] == 24500 and c4_int8["n_budget_cut"] == 3
    c4_fp16 = summary["results"][coder]["c4"]["fp16"]
    assert c4_fp16["n_all_passed"] == 1 and c4_fp16["tok_s_median"] == 90.0 and c4_fp16["statuses"] == ["ok"] * 3
    assert summary["judgements"][coder]["c4"]["label"] == cond_compare.JUDGE_UP        # fp16 の最小 0.6 > int8 の最大 0.3
    assert summary["judgements"][official]["c4"]["label"] == cond_compare.JUDGE_DOWN        # fp16 の最大 0.5 < int8 の最小 0.6
    assert summary["judgements"][official]["c5"]["label"] == cond_compare.JUDGE_UNDECIDED
    assert summary["judgements"][rvn]["c4"]["label"] == cond_compare.JUDGE_INCOMPARABLE   # fp16 の記録が無い
    # 予算で打ち切られた回の数（公式の fp16 は思考に締めの文が無い）
    assert summary["results"][official]["c4"]["fp16"]["n_budget_cut"] == 0
    # 状態の一覧（length を含む）と、無い記録の status は missing
    assert summary["results"][official]["c5"]["fp16"]["statuses"] == ["ok", "ok", "length"]
    assert summary["results"][rvn]["c4"]["fp16"]["statuses"] == ["missing"] * 3
    assert summary["results"][rvn]["c4"]["fp16"]["n_records"] == 0 and summary["results"][rvn]["c4"]["fp16"]["mean"] is None
    # モデル × KV の型の中央値と起動の記録
    assert summary["pooled"][coder]["int8"]["tok_s_median"] == 100.0
    server = summary["servers"][coder]["fp16"]
    assert server["slots_filled"] == 6500 and server["engine_kv"] == "fp16" and server["context"] == 131072
    assert server["cache_hit_pct"] == pytest.approx(90.0) and server["start_s"] == 70.0
    assert server["memory_peak_bytes"] == int(21.5 * 1024 ** 3) and server["vram_used_mib"] == 21000
    assert summary["servers"][rvn]["int8"] is None
    assert any("kv_mismatch" in line for line in summary["missing"])          # 起動の結果が ok でない条件は足りない記録に出る
    assert any("RVN" in line and "記録が無い" in line for line in summary["missing"])
    # 速さと資源の差と比（fp16 − int8、fp16 ÷ int8）
    rows = {row["key"]: row for row in cond_compare.metric_rows(summary, coder)}
    assert rows["tok_s"]["diff"] == pytest.approx(-10.0) and rows["tok_s"]["ratio"] == pytest.approx(0.9)
    assert rows["slots"]["diff"] == 6500 - 8138
    assert rows["ram"]["fp16"] == pytest.approx(21.5)
    assert cond_compare.metric_rows(summary, rvn)[0]["diff"] is None             # RVN の fp16 は記録なし


def test_summarize_command_writes_summary_json(work_tmp, capsys):
    root = synthetic_kv_root(work_tmp)
    assert cond_compare.main(["summarize", "--kind", "kv", "--root", str(root)]) == 0
    written = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert written["judgements"][cond_compare.MODEL_KEYS[0]]["c5"]["label"] == cond_compare.JUDGE_UP
    assert "足りない記録" in capsys.readouterr().out


class _ExternalRefs(HTMLParser):
    """外部の資源を読む属性（src・href・action、style の url()）を集める。ページ内のリンク（#...）は外部ではない。"""

    def __init__(self):
        super().__init__()
        self.refs: list[str] = []
        self.tags: dict[str, int] = {}
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags[tag] = self.tags.get(tag, 0) + 1
        for name, value in attrs:
            if name in ("src", "href", "action", "xlink:href") and value and not value.startswith("#"):
                self.refs.append(value)

    def handle_data(self, data):
        self.text.append(data)


def test_kv_report_smoke_is_self_contained(work_tmp):
    root = synthetic_kv_root(work_tmp)
    summary = cond_compare.build_summary(root)
    html_text = cond_compare.build_kv_html(summary, {"summary": ["一行目", "二行目", "三行目", "四行目は出さない"],
                                                   "facts": ["事実の行"], "opinions": ["意見の行"]})
    parser = _ExternalRefs()
    parser.feed(html_text)
    text = "".join(parser.text)
    assert parser.refs == [] and "http://" not in html_text and "https://" not in html_text   # 外部の参照が無い
    assert "<link" not in html_text and "@import" not in html_text
    assert parser.tags.get("svg", 0) >= 4 and parser.tags.get("table", 0) >= 6   # 図は点の図・2 つの棒・模様の定義
    for section in range(7):
        assert f'id="s{section}"' in html_text
    assert "一行目" in text and "三行目" in text and "四行目は出さない" not in text
    assert "事実の行" in text and "意見の行" in text
    assert "上がった" in text and "下がった" in text and "差は判定できない" in text and "比べられない" in text
    assert "記録なし" in text                                                  # RVN の fp16 と起動の記録
    assert "fp16 の最小 &gt; int8 の最大" in html_text or "fp16 の最小 > int8 の最大" in text
    assert "int8（斜線" in text and "fp16（塗りつぶし" in text                  # 色だけでなく文字と模様で区別する
    assert f'fill="url(#{cond_compare.HATCH_ID})"' in html_text and f'id="{cond_compare.HATCH_ID}"' in html_text
    for color in (build_report.COLOR_OK, build_report.COLOR_NG, build_report.COLOR_NA, "#7044bb"):
        assert color in html_text
    assert "会話キャッシュ" in text and "別の日の既存の記録" in text
    out = work_tmp / "out" / "report.html"
    assert cond_compare.main(["report", "--kind", "kv", "--root", str(root), "--out", str(out)]) == 0
    assert out.stat().st_size > 10000


def test_kv_report_without_any_records_does_not_crash(work_tmp):
    root = work_tmp / "empty"
    root.mkdir()
    summary = cond_compare.build_summary(root)
    assert all(per_item[item]["label"] == cond_compare.JUDGE_INCOMPARABLE
               for per_item in summary["judgements"].values() for item in cond_compare.ITEMS)
    html_text = cond_compare.build_kv_html(summary, None)
    parser = _ExternalRefs()
    parser.feed(html_text)
    text = "".join(parser.text)
    assert "記録なし" in text and "所見はまだ書かれていない" in text and "3 行の結論は findings.json" in text
    assert parser.refs == []


def test_copy_int8_rep1_and_pending(work_tmp):
    source = work_tmp / "source"
    root = work_tmp / "kv"
    slug = targets_module.get(cond_compare.MODEL_KEYS[0]).slug
    for item in cond_compare.ITEMS:
        common.write_json(common.local_record_path(source, slug, "coding", item), {"status": "ok", "item": item})
    actions = cond_compare.copy_int8_rep1(root, source, [slug], dry_run=True)
    assert len(actions) == 2 and not (root / "int8").exists()                   # --dry-run は何も書かない
    cond_compare.copy_int8_rep1(root, source, [slug])
    for item in cond_compare.ITEMS:
        assert common.local_record_path(cond_compare.rep_dir(root, "int8", 1), slug, "coding", item).is_file()
    info = common.read_json(cond_compare.rep_dir(root, "int8", 1) / "source.json")
    assert "既存の記録の写し" in info["note"] and len(info["files"]) == 2 and info["files"][0]["from"].endswith("c4-run1.json")
    # 2 回目は写さない（既にある記録は上書きしない）
    marker = common.local_record_path(cond_compare.rep_dir(root, "int8", 1), slug, "coding", "c4")
    common.write_json(marker, {"status": "ok", "item": "c4", "edited": True})
    assert "既にある" in cond_compare.copy_int8_rep1(root, source, [slug])[0]
    assert common.read_json(marker)["edited"] is True
    assert len(common.read_json(cond_compare.rep_dir(root, "int8", 1) / "source.json")["files"]) == 2
    # まだ流していない問の数（run_eval.py run と同じ規則: 記録があれば飛ばす）
    assert cond_compare.count_pending(root, "int8", 1, slug) == 0
    assert cond_compare.count_pending(root, "int8", 2, slug) == 2
    common.write_json(common.local_record_path(cond_compare.rep_dir(root, "int8", 2), slug, "coding", "c4"), {"status": "ok"})
    assert cond_compare.count_pending(root, "int8", 2, slug) == 1
    common.write_json(common.local_record_path(cond_compare.rep_dir(root, "int8", 2), slug, "coding", "c5"), {"status": "error"})
    assert cond_compare.count_pending(root, "int8", 2, slug) == 0                  # error は既定では流し直さない
    assert cond_compare.count_pending(root, "int8", 2, slug, retry_errors=True) == 1


def test_server_info_command_writes_json(work_tmp, monkeypatch):
    monkeypatch.setattr(cond_compare, "read_cgroup_memory", lambda unit: (111, 99))
    monkeypatch.setattr(cond_compare, "read_vram_used_mib", lambda: 22000)
    log_path = work_tmp / "engine.log"
    log_path.write_text(ENGINE_LOG, encoding="utf-8")
    root = work_tmp / "kv"
    assert cond_compare.main(["server-info", "--root", str(root), "--kv", "fp16", "--target", cond_compare.MODEL_KEYS[1],
                            "--unit", "strata-official", "--engine-log", str(log_path), "--after-line", "0",
                            "--start-s", "75", "--status", "ok", "--reps", "1 2 3", "--vram-before", "16"]) == 0
    info = common.read_json(cond_compare.server_info_path(root, "fp16", "strata-official-IQ3_XXS"))
    assert info["status"] == "ok" and info["kv"] == "fp16" and info["reps"] == [1, 2, 3]
    assert info["slots"] == {"filled": 5866, "total": 5866} and len(info["cache_hit_lines"]) == 2
    assert info["engine_started_line"].endswith("--kv fp16")
    assert (info["vram_used_mib"], info["memory_peak_bytes"], info["memory_current_bytes"]) == (22000, 111, 99)
    assert info["start_s"] == 75.0 and info["vram_before_mib"] == 16
    # 起動に失敗した条件（起動行が無い）でも、null で書ける
    assert cond_compare.main(["server-info", "--root", str(root), "--kv", "int8", "--target", cond_compare.MODEL_KEYS[1],
                            "--unit", "strata-official", "--engine-log", str(work_tmp / "none.log"), "--status", "start_failed",
                            "--start-s", "300"]) == 0
    failed = common.read_json(cond_compare.server_info_path(root, "int8", "strata-official-IQ3_XXS"))
    assert failed["status"] == "start_failed" and failed["engine_started_line"] is None and failed["slots"] is None


def run_kv_script(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(["bash", str(TOOL_DIR / "run_kv_compare.sh"), *args], capture_output=True, text=True,
                          env=env, timeout=120, check=False)


def test_run_kv_compare_script_syntax_and_dry_run():
    assert subprocess.run(["bash", "-n", str(TOOL_DIR / "run_kv_compare.sh")], check=False).returncode == 0
    tag = "pytest-kv-dry"
    results = TOOL_DIR / "results" / tag
    assert not results.exists()
    completed = run_kv_script("--dry-run", env_extra={"RUN_TAG": tag})
    out = completed.stdout
    assert completed.returncode == 0, completed.stderr
    # 順番: Coder → 公式 → RVN。モデルごとに int8（rep2・rep3）→ fp16（rep1〜3）
    positions = [out.index(f"systemctl --user start {unit}") for unit in ("strata-coder", "strata-official")]
    assert positions == sorted(positions) and out.index("start strata-official") < out.rindex("start strata\n")
    assert out.count("systemctl --user start strata-coder") == 2 and out.count("--kv fp16\"") == 3
    assert out.split("[dry-run] 終わり")[0].count("systemctl --user unset-environment STRATA_EXTRA_ARGS") == 3
    assert "終わり: 全 Strata を止める → systemctl --user unset-environment STRATA_EXTRA_ARGS → show-environment" in out
    assert "run_eval.py run --target strata-flash-coder:IQ1_M --suite coding --items c4,c5" in out
    assert f"results/{tag}/int8/rep2" in out and f"results/{tag}/fp16/rep3" in out
    assert f"results/{tag}/int8/rep1 " not in out and "--time-budget-min 200" in out
    assert "strata-coder-engine.log" in out and "check-kv" in out and "server-info" in out
    assert "copy-int8-rep1" not in out and "results/2026-10-08/local/strata-coder-IQ1_M" in out   # 写す元の一覧
    assert not results.exists() and not (TOOL_DIR / "work" / f"run_kv_compare-{tag}.log").exists()   # dry-run は何も作らない


def test_run_kv_compare_script_filters_in_dry_run():
    env = {"RUN_TAG": "pytest-kv-dry", "ONLY_TARGETS": "strata-official:IQ3_XXS", "ONLY_KV": "fp16"}
    out = run_kv_script("--dry-run", env_extra=env).stdout
    assert "systemctl --user start strata-official" in out and "strata-coder" not in out and "unset-environment STRATA_EXTRA_ARGS\n" not in out.split("終わり")[0]
    assert out.count("--kv fp16") >= 2 and "条件 int8" not in out and "最初に int8 の rep1" not in out
    assert run_kv_script("--dry-run", env_extra={"ONLY_KV": "bf16"}).returncode == 2
    assert run_kv_script("--dry-run", env_extra={"ONLY_TARGETS": "nothing"}).returncode == 2
    assert run_kv_script("--no-such-option").returncode == 2


# ------------------------------------------------------------------------------------------------ run_kv_compare.sh の本流（偽の systemctl で。実機は起動しない）

STUB_SYSTEMCTL = r"""#!/usr/bin/env bash
# 偽の systemctl（試験用）。状態は $STUB_STATE の下のファイル、呼び出しは calls.log に残す
set -u
state="$STUB_STATE"
echo "systemctl $*" >> "$state/calls.log"
if [ "${1:-}" = "--user" ]; then shift; fi
command_name="${1:-}"; shift || true
engine_log_of() {
  case "$1" in
    strata-coder) echo strata-coder-engine.log ;;
    strata-official) echo strata-official-engine.log ;;
    *) echo strata-engine.log ;;
  esac
}
case "$command_name" in
  is-active)
    if [ "${1:-}" = "--quiet" ]; then shift; fi
    [ -f "$state/active-$1" ] ;;
  start)
    unit="$1"
    case ",${STUB_FAIL_START:-}," in *",$unit,"*) exit 1 ;; esac
    touch "$state/active-$unit"
    extra=""
    slots=8000
    if [ -f "$state/env-STRATA_EXTRA_ARGS" ]; then
      case ",${STUB_IGNORE_EXTRA_ARGS:-}," in
        *",$unit,"*) ;;
        *) extra="$(cat "$state/env-STRATA_EXTRA_ARGS")"; slots=6500 ;;
      esac
    fi
    log="$STUB_STRATA_LOGS/$(engine_log_of "$unit")"
    {
      echo "[strata] 2026-10-09 12:00:00 engine started: /x/strata --serve --max-context 131072 --kv int8 $extra"
      echo "strata generate: pre-filled $slots of $slots slots from the profile in 1.0 s"
    } >> "$log"
    ;;
  stop) rm -f "$state/active-$1" ;;
  set-environment)
    name="${1%%=*}"; value="${1#*=}"
    printf '%s' "$value" > "$state/env-$name" ;;
  unset-environment) rm -f "$state/env-$1" ;;
  show-environment)
    echo "PATH=/stub"
    for file in "$state"/env-*; do
      [ -e "$file" ] || continue
      echo "$(basename "$file" | sed 's/^env-//')=$(cat "$file")"
    done ;;
  show) echo "" ;;
  *) ;;
esac
"""

STUB_RUN_EVAL = """#!/usr/bin/env python3
# 偽の run_eval.py（試験用）: run の記録だけを書く
import os, sys
sys.path.insert(0, {tool_dir!r})
import targets
from evallib import common
from pathlib import Path

args = sys.argv[1:]
assert args[0] == "run", args
options = dict(zip(args[1::2], args[2::2]))
target = targets.get(options["--target"])
results_dir = Path(options["--results-dir"])
state = Path(os.environ["STUB_STATE"])
extra = (state / "env-STRATA_EXTRA_ARGS").read_text() if (state / "env-STRATA_EXTRA_ARGS").exists() else "none"
active = ",".join(sorted(path.name[len("active-"):] for path in state.glob("active-*")))
with open(state / "calls.log", "a") as calls:
    calls.write(f"run_eval target={{target.key}} dir={{results_dir}} kv_env={{extra}} active={{active}} budget={{options.get('--time-budget-min')}}\\n")
for item in options["--items"].split(","):
    path = common.local_record_path(results_dir, target.slug, "coding", item)
    if path.exists():
        continue
    common.write_json(path, {{"target": target.key, "suite": "coding", "item": item, "status": "ok", "wall_excl_load_s": 10.0,
                              "grade": {{"score": 0.5, "all_passed": False}}}})
"""


def build_kv_stub_env(work_tmp: Path, **extra_env: str) -> dict[str, str]:
    stub_bin = work_tmp / "stubbin"
    stub_bin.mkdir(exist_ok=True)
    (work_tmp / "state").mkdir(exist_ok=True)
    (work_tmp / "stratalogs").mkdir(exist_ok=True)
    scripts = {"systemctl": STUB_SYSTEMCTL,
               "journalctl": "#!/usr/bin/env bash\necho \"journal for $*\"\n",
               "nvidia-smi": "#!/usr/bin/env bash\ncase \"$*\" in *memory.total*) echo \"16 MiB, 24576 MiB\" ;; *) echo 16 ;; esac\n",
               "vram-policy.sh": "#!/usr/bin/env bash\necho \"policy=nouse (stub) $*\"\n",
               "run_eval_stub": STUB_RUN_EVAL.format(tool_dir=str(TOOL_DIR))}
    for name, body in scripts.items():
        path = stub_bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    source = work_tmp / "source"
    for key in cond_compare.MODEL_KEYS:
        for item in cond_compare.ITEMS:
            common.write_json(common.local_record_path(source, targets_module.get(key).slug, "coding", item),
                              {"target": key, "item": item, "status": "ok", "grade": {"score": 0.4, "all_passed": False}})
    env = dict(os.environ)
    env.update({"PATH": f"{stub_bin}:{env['PATH']}", "STUB_STATE": str(work_tmp / "state"),
                "STUB_STRATA_LOGS": str(work_tmp / "stratalogs"), "STRATA_LOGS": str(work_tmp / "stratalogs"),
                "RUN_EVAL_CMD": str(stub_bin / "run_eval_stub"), "VRAM_POLICY": str(stub_bin / "vram-policy.sh"),
                "RESULTS_BASE": str(work_tmp / "results"), "SOURCE_RESULTS": str(source),
                "LOG_DIR": str(work_tmp / "logs"), "RUN_TAG": "kvtest"})
    env.update(extra_env)
    return env


def run_kv_stubbed(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(TOOL_DIR / "run_kv_compare.sh")], capture_output=True, text=True, env=env,
                          timeout=180, check=False)


def kv_calls(work_tmp: Path) -> list[str]:
    path = work_tmp / "state" / "calls.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_run_kv_compare_full_flow_with_stubs(work_tmp):
    env = build_kv_stub_env(work_tmp)
    completed = run_kv_stubbed(env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = work_tmp / "results" / "kvtest"
    done = (root / "DONE").read_text(encoding="utf-8")
    assert "status=finished" in done and "environment=STRATA_EXTRA_ARGS なし" in done
    # 記録: int8 の rep1 は写し、rep2・rep3 と fp16 の rep1〜3 は流した（3 モデル × 5 回 × 2 問 + 写し 6 本）
    for key in cond_compare.MODEL_KEYS:
        slug = targets_module.get(key).slug
        for kv, reps in (("int8", (1, 2, 3)), ("fp16", (1, 2, 3))):
            for rep in reps:
                for item in cond_compare.ITEMS:
                    assert cond_compare.record_path(root, kv, rep, slug, item).is_file(), (slug, kv, rep, item)
        for kv, expected_slots in (("int8", 8000), ("fp16", 6500)):
            info = common.read_json(cond_compare.server_info_path(root, kv, slug))
            assert info["status"] == "ok" and info["slots"]["filled"] == expected_slots, (slug, kv, info)
            assert info["engine_started_line"].count("--kv fp16") == (1 if kv == "fp16" else 0)
            assert info["vram_before_mib"] == 16 and info["start_s"] is not None
    assert common.read_json(cond_compare.rep_dir(root, "int8", 1) / "source.json")["files"][0]["from"].endswith("-run1.json")
    # 流した順（起動の順）: Coder → 公式 → RVN。それぞれ int8 → fp16
    calls = kv_calls(work_tmp)
    starts = [line for line in calls if " start " in line]
    assert [line.split()[-1] for line in starts] == ["strata-coder"] * 2 + ["strata-official"] * 2 + ["strata"] * 2
    env_events = [line for line in calls if "set-environment" in line or " start " in line]
    first_fp16_start = next(index for index, line in enumerate(env_events) if "set-environment STRATA_EXTRA_ARGS=--kv fp16" in line)
    assert " start strata-coder" in env_events[first_fp16_start + 1]       # 起動の前に set-environment している
    runs = [line for line in calls if line.startswith("run_eval")]
    assert len(runs) == 15 and all("budget=200" in line for line in runs)
    for line in runs:                                                      # fp16 の回だけ STRATA_EXTRA_ARGS が付いている
        assert ("kv_env=--kv fp16" in line) == ("/fp16/" in line), line
    # 終わり: どの unit も止まっていて、STRATA_EXTRA_ARGS は残っていない
    assert not list((work_tmp / "state").glob("active-*")) and not (work_tmp / "state" / "env-STRATA_EXTRA_ARGS").exists()
    assert (work_tmp / "logs" / "run_kv_compare-kvtest.log").is_file()
    # 2 回目は記録済みなので、起動しない（途中から続けられる）
    (work_tmp / "state" / "calls.log").unlink()
    again = run_kv_stubbed(env)
    assert again.returncode == 0 and not [line for line in kv_calls(work_tmp) if " start " in line or line.startswith("run_eval")]
    assert "記録済み" in again.stdout
    # 集計と HTML まで通る
    summary = cond_compare.build_summary(root)
    assert summary["results"][cond_compare.MODEL_KEYS[0]]["c4"]["fp16"]["n_records"] == 3
    assert not summary["missing"]


def test_run_kv_compare_start_failure_and_kv_mismatch_are_recorded(work_tmp):
    coder, official, rvn = cond_compare.MODEL_KEYS
    env = build_kv_stub_env(work_tmp, STUB_FAIL_START="strata-official", STUB_IGNORE_EXTRA_ARGS="strata")
    completed = run_kv_stubbed(env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = work_tmp / "results" / "kvtest"
    # 起動に失敗した公式: journal を残し、start_failed と記録し、次へ進む
    for kv in cond_compare.KV_TYPES:
        info = common.read_json(cond_compare.server_info_path(root, kv, "strata-official-IQ3_XXS"))
        assert info["status"] == "start_failed" and info["slots"] is None
        assert list((root / kv).glob("journal-strata-official-IQ3_XXS-*.txt"))
    # RVN: int8 は ok、fp16 は起動行に --kv fp16 が無いので kv_mismatch（その条件は流さない）
    assert common.read_json(cond_compare.server_info_path(root, "int8", "strata-rvn-IQ3_S"))["status"] == "ok"
    mismatch = common.read_json(cond_compare.server_info_path(root, "fp16", "strata-rvn-IQ3_S"))
    assert mismatch["status"] == "kv_mismatch" and "--kv fp16" not in mismatch["engine_started_line"]
    assert not cond_compare.record_path(root, "fp16", 1, "strata-rvn-IQ3_S", "c4").exists()
    assert cond_compare.record_path(root, "fp16", 1, "strata-coder-IQ1_M", "c4").exists()      # Coder は流れた
    done = (root / "DONE").read_text(encoding="utf-8")
    assert "status=finished" in done and "status=start_failed" in done and "status=kv_mismatch" in done
    assert not (work_tmp / "state" / "env-STRATA_EXTRA_ARGS").exists() and not list((work_tmp / "state").glob("active-*"))
    summary = cond_compare.build_summary(root)
    assert any("start_failed" in line for line in summary["missing"]) and any("kv_mismatch" in line for line in summary["missing"])


def test_run_kv_compare_aborts_when_gpu_service_is_running_and_still_cleans_up(work_tmp):
    env = build_kv_stub_env(work_tmp)
    (work_tmp / "state" / "active-comfyui").touch()
    completed = run_kv_stubbed(env)
    assert completed.returncode == 1 and "GPU を取り合う" in completed.stdout
    root = work_tmp / "results" / "kvtest"
    assert "status=aborted" in (root / "DONE").read_text(encoding="utf-8")
    calls = kv_calls(work_tmp)
    assert not [line for line in calls if " start " in line or line.startswith("run_eval")]
    assert any("unset-environment STRATA_EXTRA_ARGS" in line for line in calls)      # 異常終了でも trap で外す


# ================================================================================================
# コーディング性能の調査（思考の上限の上書き・英語の問題文・思考中停止のやり直し・条件の集計・run_fix_compare.sh）
# ================================================================================================

# ------------------------------------------------------------------------------------------------ 上限の上書き（build_payload）


def test_build_payload_overrides_limits_for_strata():
    strata = targets_module.get("strata-official:IQ3_XXS")
    default = run_eval.build_payload(strata, "coding", "q", "15m")
    assert (default["max_tokens"], default["reasoning_budget_tokens"]) == (32768, 24576)      # 上書きしなければ今までどおり
    overridden = run_eval.build_payload(strata, "coding", "q", "15m", max_tokens=65536, reasoning_budget=0)
    assert overridden["max_tokens"] == 65536
    assert "reasoning_budget_tokens" in overridden and overridden["reasoning_budget_tokens"] == 0   # 0 のときも鍵を 0 で送る
    assert overridden["reasoning_effort"] == "high" and overridden["top_k"] == 20
    only_tokens = run_eval.build_payload(strata, "coding", "q", "15m", max_tokens=1000)
    assert (only_tokens["max_tokens"], only_tokens["reasoning_budget_tokens"]) == (1000, 24576)
    only_budget = run_eval.build_payload(strata, "extra", "q", "15m", reasoning_budget=100)
    assert (only_budget["max_tokens"], only_budget["reasoning_budget_tokens"]) == (8192, 100)


def test_build_payload_override_for_ollama_only_changes_num_predict():
    ollama = targets_module.get("gemma4:31b-it-qat")
    payload = run_eval.build_payload(ollama, "coding", "q", "15m", max_tokens=65536, reasoning_budget=0)
    assert payload["options"] == {"num_predict": 65536} and "reasoning_budget_tokens" not in payload
    assert payload["think"] is True


def test_sent_limits_records_what_was_sent():
    strata = targets_module.get("strata-official:IQ3_XXS")
    ollama = targets_module.get("gemma4:31b-it-qat")
    limits = run_eval.effective_limits("coding", 65536, 0)
    assert run_eval.sent_limits(strata, limits) == {"max_tokens": 65536, "reasoning_budget_tokens": 0, "request_timeout_s": 2400}
    # 思考の予算は Strata の要求にだけ付くので、Ollama の記録は None
    assert run_eval.sent_limits(ollama, limits)["reasoning_budget_tokens"] is None
    assert run_eval.sent_limits(strata, run_eval.effective_limits("coding"))["reasoning_budget_tokens"] == 24576


# ------------------------------------------------------------------------------------------------ 英語の問題文


def test_build_prompt_english_reads_en_files_and_japanese_is_unchanged():
    text = common.build_prompt("coding", "c4", "en")
    preamble = (CODING_DIR / "PREAMBLE.en.md").read_text(encoding="utf-8").strip()
    body = (CODING_DIR / "c4" / "prompt.en.md").read_text(encoding="utf-8").strip()
    assert text == f"{preamble}\n\n{body}"
    assert "parse_json(text: str) -> object" in text and "標準ライブラリ" not in text
    assert "regex_search(pattern: str, text: str) -> bool" in common.build_prompt("coding", "c5", "en")
    assert common.build_prompt("coding", "c4") == common.build_prompt("coding", "c4", "ja")
    assert common.build_prompt("coding", "c4").startswith("次の仕様を満たす Python 3.12 のコード")
    # 英語版の無い問・試験・言語は、分かる文言で失敗する
    with pytest.raises(FileNotFoundError, match="prompt.en.md"):
        common.build_prompt("coding", "c1", "en")
    with pytest.raises(ValueError, match="英語版"):
        common.build_prompt("extra", "json1", "en")
    with pytest.raises(ValueError, match="unknown prompt lang"):
        common.build_prompt("coding", "c4", "fr")


def test_show_prompt_command_has_prompt_lang(capsys):
    assert run_eval.main(["show-prompt", "--suite", "coding", "--item", "c5", "--prompt-lang", "en"]) == 0
    assert "Problem C5" in capsys.readouterr().out


@pytest.mark.parametrize("ja_name,en_name", [("PREAMBLE.md", "PREAMBLE.en.md"), ("c4/prompt.md", "c4/prompt.en.md"),
                                             ("c5/prompt.md", "c5/prompt.en.md")])
def test_english_prompts_keep_code_spans_and_structure(ja_name, en_name):
    japanese = (CODING_DIR / ja_name).read_text(encoding="utf-8")
    english = (CODING_DIR / en_name).read_text(encoding="utf-8")
    # バッククォートで囲んだコード片（関数名・引数・数値・例・例外名・禁止事項）が一致する。違うのは `float(その文字列)` の仮名の訳だけ
    spans_ja = Counter(span.replace("その文字列", "that string") for span in re.findall(r"`([^`]+)`", japanese))
    spans_en = Counter(re.findall(r"`([^`]+)`", english))
    assert spans_ja == spans_en

    def outline(text: str) -> list:
        # 見出し（#）と箇条書き（-）の並びと入れ子の深さ。本文の行と空行は種類だけ
        shape = []
        for line in text.splitlines():
            found = re.match(r"^(\s*)(#+|-)\s", line)
            shape.append((len(found.group(1)), found.group(2)) if found else ("text" if line.strip() else "blank"))
        return shape

    assert outline(japanese) == outline(english)


def test_english_prompts_keep_the_rules_that_decide_the_score():
    c4 = (CODING_DIR / "c4" / "prompt.en.md").read_text(encoding="utf-8")
    c5 = (CODING_DIR / "c5" / "prompt.en.md").read_text(encoding="utf-8")
    preamble = (CODING_DIR / "PREAMBLE.en.md").read_text(encoding="utf-8")
    assert "`json` module" in c4 and "scores 0" in c4 and "50,000" in c4 and "1,000,000" in c4
    assert "`re` module" in c5 and "scores 0" in c5 and "5,000" in c5 and "10,000" in c5
    assert "```python" in preamble and "Python 3.12" in preamble and preamble.count("\n- ") == 4


# ------------------------------------------------------------------------------------------------ 思考中の停止トークン（eos_in_thinking）


def finalize_status(finish, content, thinking):
    result = clients._empty_result()
    result["finish"] = finish
    return clients._finalize(result, 0.0, None, None, None, 1.0, [content], [thinking])["status"]


@pytest.mark.parametrize("finish,content,thinking,expected", [
    ("stop", "", "考え中", "eos_in_thinking"),
    ("stop", " \n\t", "考え中", "eos_in_thinking"),       # 空白だけの本文も空
    ("stop", "答え", "考え中", "ok"),
    ("stop", "", "", "ok"),                                # 思考も無いときは eos_in_thinking にしない
    ("length", "", "考え中", "length"),                    # 上限は length のまま
    ("length", "答え", "考え中", "length"),
])
def test_finalize_marks_eos_in_thinking(finish, content, thinking, expected):
    assert finalize_status(finish, content, thinking) == expected


def test_finalize_keeps_error_statuses_and_error_stays_none():
    result = clients._empty_result()
    result["finish"], result["status"] = "stop", "stall"
    assert clients._finalize(result, 0.0, None, None, None, 1.0, [""], ["考え中"])["status"] == "stall"
    eos = clients._finalize({**clients._empty_result(), "finish": "stop"}, 0.0, None, None, None, 1.0, [""], ["考え中"])
    assert eos["status"] == "eos_in_thinking" and eos["error"] is None


def test_eos_in_thinking_from_both_backends(fake_server):
    def ollama_eos(handler, method, path, body):
        handler.start_stream()
        handler.write_line(json.dumps({"message": {"thinking": "\\u0075 を書こうとして"}, "done": False}))
        handler.write_line(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 9}))

    def strata_eos(handler, method, path, body):
        handler.start_stream("text/event-stream")
        for obj in ({"choices": [{"index": 0, "delta": {"reasoning_content": "考え"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"completion_tokens": 7}}):
            handler.write_line("data: " + json.dumps(obj, ensure_ascii=False))
            handler.write_line("")
        handler.write_line("data: [DONE]")

    ollama = clients.chat_ollama(fake_server(ollama_eos), {"model": "m", "messages": [], "stream": True},
                                 stall_s=5, deadline_s=30)
    strata = clients.chat_strata(fake_server(strata_eos) + "/v1", {"model": "m", "messages": [], "stream": True},
                                 stall_s=5, deadline_s=30)
    for result in (ollama, strata):
        assert result["status"] == "eos_in_thinking" and result["content"] == "" and result["thinking"] and result["error"] is None


def test_eos_in_thinking_is_zero_points_no_answer_and_final(work_tmp):
    grade = run_eval.grade_answer("coding", "c4", "", "eos_in_thinking", work_tmp)
    assert grade["score"] == 0.0 and grade["no_answer"] and grade["all_passed"] is False and grade["reason"] == "eos_in_thinking"
    path = work_tmp / "c4-run1.json"
    common.write_json(path, {"status": "eos_in_thinking"})
    options = SimpleNamespace(redo=False, retry_errors=True, retry_skipped=True)
    assert not run_eval.should_run(path, options)                 # error ではないので --retry-errors でも流し直さない
    assert run_eval.should_run(path, SimpleNamespace(redo=True, retry_errors=False, retry_skipped=False))
    common.write_json(path, {"status": "error"})
    assert run_eval.should_run(path, options)
    # 集計でも答えなし・0 点として数え、状態の文字が出る
    cell = summarize._cell_from_local({"status": "eos_in_thinking", "grade": grade, "wall_excl_load_s": 30.0})
    assert cell["cell"] == summarize.CELL_NO_ANSWER and cell["score"] == 0.0 and cell["time_s"] == 30.0
    assert build_report.cell_texts(cell) == ("答えなし", "思考中停止")
    assert "eos_in_thinking" in build_report.STATUS_DESCRIPTIONS


def test_legacy_record_without_the_status_counts_as_eos():
    legacy = {"status": "ok", "finish": "stop", "content": "", "thinking": "考えて、止まった"}
    assert common.record_is_eos_in_thinking(legacy)
    assert common.record_is_eos_in_thinking({"status": "eos_in_thinking"})
    assert not common.record_is_eos_in_thinking({**legacy, "content": "答え"})
    assert not common.record_is_eos_in_thinking({**legacy, "finish": "length"})
    assert not common.record_is_eos_in_thinking({**legacy, "thinking": ""})


def test_attempt_record_path_and_listing(work_tmp):
    path = common.local_record_path(work_tmp, "slug", "coding", "c4")
    attempt = common.attempt_record_path(path, 1)
    assert attempt.name == "c4-run1.attempt1.json" and attempt.parent == path.parent
    common.write_json(path, {"item": "c4", "status": "ok", "wall_excl_load_s": 10.0})
    common.write_json(attempt, {"item": "c4", "status": "eos_in_thinking", "wall_excl_load_s": 5.0})
    # やり直した 1 回目は、問の数にも採点にも入れない
    assert [found.name for found, _record in common.iter_local_records(work_tmp, "slug")] == ["c4-run1.json"]
    assert [found.name for found, _record in common.iter_attempt_records(work_tmp, "slug")] == ["c4-run1.attempt1.json"]
    # 累計時間には両方を足す
    assert run_eval.used_seconds(work_tmp, SimpleNamespace(slug="slug")) == pytest.approx(15.0)


# ------------------------------------------------------------------------------------------------ run の本流（偽のサーバー）


def sequenced_ollama_script(outcomes: list[str], calls: list[dict], content: str):
    """/api/chat の呼び出しごとに outcomes を順に返す。"eos" は思考だけで停止、"ok" は本文あり。呼び出しの本体を calls に残す。"""

    def script(handler, method, path, body):
        if method == "GET" and path == "/api/tags":
            return handler.send_json({"models": [{"name": "fake:model"}]})
        if method == "GET" and path == "/api/version":
            return handler.send_json({"version": "0.0-test"})
        if method == "GET" and path == "/api/ps":
            return handler.send_json({"models": []})
        if method == "POST" and path == "/api/chat":
            outcome = outcomes[min(len(calls), len(outcomes) - 1)]
            calls.append(body)
            handler.start_stream()
            handler.write_line(json.dumps({"message": {"thinking": "考える"}, "done": False}))
            if outcome == "ok":
                handler.write_line(json.dumps({"message": {"content": content}, "done": False}))
            handler.write_line(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop",
                                           "eval_count": 40, "eval_duration": 2_000_000_000, "load_duration": 0}))
            return None
        return handler.send_json({"error": "not found"}, status=404)

    return script


def make_fake_ollama(fake_server, monkeypatch, work_tmp, outcomes, content):
    calls: list[dict] = []
    url = fake_server(sequenced_ollama_script(outcomes, calls, content))
    target = targets_module.Target(key="fake:model", label="fake", family="ollama", backend="ollama",
                                   slug="fake-model", model="fake:model", base_url=url)
    monkeypatch.setattr(run_eval.targets_module, "get", lambda key: target)
    monkeypatch.setattr(run_eval, "gpu_snapshot", lambda: None)
    monkeypatch.setattr(common, "WORK_DIR", work_tmp / "work")
    return target, calls


def run_c1(work_tmp, *extra):
    return run_eval.main(["run", "--target", "fake:model", "--suite", "coding", "--items", "c1", "--results-dir",
                          str(work_tmp / "results"), "--no-preload", *extra])


def read_c1(work_tmp, name="c1-run1.json"):
    return json.loads((work_tmp / "results" / "local" / "fake-model" / "coding" / name).read_text(encoding="utf-8"))


def test_run_retries_eos_in_thinking_once_and_keeps_the_first_attempt(fake_server, monkeypatch, work_tmp, capsys):
    _target, calls = make_fake_ollama(fake_server, monkeypatch, work_tmp, ["eos", "ok"], fenced(reference_code("c1")))
    assert run_c1(work_tmp) == 0
    assert len(calls) == 2
    record, first = read_c1(work_tmp), read_c1(work_tmp, "c1-run1.attempt1.json")
    assert record["status"] == "ok" and record["attempts"] == 2 and record["first_attempt_status"] == "eos_in_thinking"
    assert record["grade"]["all_passed"] and record["has_answer"]
    assert first["status"] == "eos_in_thinking" and first["attempts"] == 1 and first["grade"]["no_answer"]
    assert "思考中に停止トークン。1 回やり直す" in capsys.readouterr().out
    # 累計時間は両方の記録を足す
    both = run_eval.used_seconds(work_tmp / "results", SimpleNamespace(slug="fake-model"))
    assert both >= record["wall_excl_load_s"] + first["wall_excl_load_s"] - 1e-6
    # やり直した問は記録済みなので、もう一度実行しても流さない
    assert run_c1(work_tmp) == 0 and len(calls) == 2


def test_run_records_eos_twice_as_zero_points_and_never_retries_it(fake_server, monkeypatch, work_tmp, capsys):
    _target, calls = make_fake_ollama(fake_server, monkeypatch, work_tmp, ["eos"], fenced(reference_code("c1")))
    assert run_c1(work_tmp) == 0                                  # eos は error ではないので終了コードは 0
    assert len(calls) == 2
    record = read_c1(work_tmp)
    assert record["status"] == "eos_in_thinking" and record["attempts"] == 2 and record["first_attempt_status"] == "eos_in_thinking"
    assert record["grade"]["score"] == 0.0 and record["grade"]["no_answer"] and record["grade"]["reason"] == "eos_in_thinking"
    assert record["error"] is None and record["has_answer"] is False
    capsys.readouterr()
    assert run_c1(work_tmp) == 0 and "0 問を流す" in capsys.readouterr().out
    assert run_c1(work_tmp, "--retry-errors") == 0 and len(calls) == 2    # --retry-errors の対象にならない


def test_run_no_retry_eos_and_normal_record_has_no_attempt_file(fake_server, monkeypatch, work_tmp):
    _target, calls = make_fake_ollama(fake_server, monkeypatch, work_tmp, ["eos", "ok"], fenced(reference_code("c1")))
    assert run_c1(work_tmp, "--no-retry-eos") == 0
    assert len(calls) == 1
    record = read_c1(work_tmp)
    assert record["status"] == "eos_in_thinking" and record["attempts"] == 1 and "first_attempt_status" not in record
    assert not (work_tmp / "results" / "local" / "fake-model" / "coding" / "c1-run1.attempt1.json").exists()


def test_run_records_limits_and_prompt_lang_for_ollama(fake_server, monkeypatch, work_tmp):
    _target, calls = make_fake_ollama(fake_server, monkeypatch, work_tmp, ["ok"], fenced(reference_code("c4")))
    assert run_eval.main(["run", "--target", "fake:model", "--suite", "coding", "--items", "c4", "--results-dir",
                          str(work_tmp / "results"), "--no-preload", "--max-tokens", "4096", "--prompt-lang", "en"]) == 0
    assert calls[0]["options"] == {"num_predict": 4096}
    record = json.loads((work_tmp / "results" / "local" / "fake-model" / "coding" / "c4-run1.json").read_text(encoding="utf-8"))
    assert record["limits"] == {"max_tokens": 4096, "reasoning_budget_tokens": None, "request_timeout_s": 2400}
    assert record["prompt_lang"] == "en" and record["prompt"].startswith("Write Python 3.12 code")
    assert record["prompt"] == common.build_prompt("coding", "c4", "en")
    meta = json.loads((work_tmp / "results" / "local" / "fake-model" / "meta.json").read_text(encoding="utf-8"))
    assert meta["sessions"][0]["prompt_lang"] == "en" and meta["sessions"][0]["retry_eos"] is True


def test_run_sends_zero_reasoning_budget_and_records_it_for_strata(fake_server, monkeypatch, work_tmp):
    seen: list[dict] = []

    def script(handler, method, path, body):
        if method == "GET" and path == "/v1/models":
            return handler.send_json({"data": [{"id": "strata-official:IQ3_XXS"}]})
        seen.append(body)
        handler.start_stream("text/event-stream")
        for obj in ({"choices": [{"index": 0, "delta": {"reasoning_content": "考え"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {"content": fenced(reference_code("c1"))}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 30}}):
            handler.write_line("data: " + json.dumps(obj, ensure_ascii=False))
            handler.write_line("")
        handler.write_line("data: [DONE]")
        return None

    url = fake_server(script) + "/v1"
    target = targets_module.Target(key="strata-fake", label="fake", family="strata", backend="strata", slug="strata-fake",
                                   model="strata-official:IQ3_XXS", base_url=url, unit="strata-official")
    monkeypatch.setattr(run_eval.targets_module, "get", lambda key: target)
    monkeypatch.setattr(run_eval, "gpu_snapshot", lambda: None)
    monkeypatch.setattr(common, "WORK_DIR", work_tmp / "work")
    results = work_tmp / "results"
    assert run_eval.main(["run", "--target", "strata-fake", "--suite", "coding", "--items", "c1", "--results-dir", str(results),
                          "--reasoning-budget", "0", "--max-tokens", "65536"]) == 0
    assert seen[0]["reasoning_budget_tokens"] == 0 and seen[0]["max_tokens"] == 65536
    record = json.loads((results / "local" / "strata-fake" / "coding" / "c1-run1.json").read_text(encoding="utf-8"))
    assert record["limits"] == {"max_tokens": 65536, "reasoning_budget_tokens": 0, "request_timeout_s": 2400}
    assert record["request"]["reasoning_budget_tokens"] == 0 and record["prompt_lang"] == "ja" and record["attempts"] == 1


def test_run_dry_run_shows_overridden_limits_and_language(work_tmp, capsys):
    results = work_tmp / "results"
    argv = ["run", "--target", "strata-official:IQ3_XXS", "--suite", "coding", "--items", "c4,c5", "--results-dir",
            str(results), "--dry-run"]
    assert run_eval.main(argv + ["--reasoning-budget", "0", "--max-tokens", "65536", "--prompt-lang", "en"]) == 0
    out = capsys.readouterr().out
    assert "coding/c4" in out and "coding/c5" in out and "問題文 en" in out
    assert '"max_tokens": 65536' in out and '"reasoning_budget_tokens": 0' in out and "やり直し あり" in out
    assert not results.exists()                                   # dry-run は何も作らず、サーバーにもつながない
    assert run_eval.main(argv + ["--no-retry-eos"]) == 0
    out = capsys.readouterr().out
    assert "問題文 ja" in out and '"max_tokens": 32768' in out and '"reasoning_budget_tokens": 24576' in out and "やり直し なし" in out


def test_run_dry_run_also_shows_items_that_are_already_recorded(work_tmp, capsys):
    results = work_tmp / "results"
    common.write_json(common.local_record_path(results, "strata-official-IQ3_XXS", "coding", "c4"), {"status": "ok"})
    assert run_eval.main(["run", "--target", "strata-official:IQ3_XXS", "--suite", "coding", "--items", "c4", "--results-dir",
                          str(results), "--prompt-lang", "en", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "0 問を流す" in out and "記録済みで飛ばす" in out and "問題文 en" in out


def test_run_rejects_negative_limits():
    with pytest.raises(SystemExit):
        run_eval.main(["run", "--target", "strata-official:IQ3_XXS", "--suite", "coding", "--items", "c4",
                       "--max-tokens", "-1", "--dry-run"])


# ------------------------------------------------------------------------------------------------ cond_compare.py（fix: 終わり方の分類・条件の集計・基準との比べ）

FIX_CODER, FIX_OFFICIAL, FIX_RVN = cond_compare.MODEL_KEYS
CUT_MARK = summarize.REASONING_WRAP_UP_MARK


def end_record(status="ok", *, finish="stop", content="答え", thinking="考え中", tokens=20000, limits="default"):
    """classify_end に渡す記録（limits が "default" なら 65,536、None なら limits も request も無い古い記録）。"""

    record = {"status": status, "finish": finish, "content": content, "thinking": thinking, "completion_tokens": tokens}
    if limits == "default":
        record["limits"] = {"max_tokens": 65536, "reasoning_budget_tokens": 0}
    elif limits:
        record["limits"] = limits
    return record


@pytest.mark.parametrize("record,expected_end,expected_truncated", [
    # 思考を自分で終え、答えを書き切った
    (end_record(), "self_finished", False),
    # 予算で打ち切られたあと、答えを書いた（思考の末尾に Strata の打ち切り文）
    (end_record(thinking=f"考え\n{CUT_MARK}\n"), "budget_cut", False),
    # 答えを書いている途中で生成の上限に届いた
    (end_record("length", finish="length", tokens=65536), "answer_truncated", False),
    (end_record("length", finish="length", tokens=70000), "answer_truncated", False),                 # 上限を超える値でも
    # 予算で打ち切られたあとの答えが上限で切れた → budget_cut（truncated の印つき）
    (end_record("length", finish="length", tokens=65536, thinking=f"考え\n{CUT_MARK}\n"), "budget_cut", True),
    # 生成の上限まで考え続けて答えなし
    (end_record("length", finish="length", content="", tokens=65536), "no_answer_at_limit", False),
    (end_record("length", finish="length", content="  \n", tokens=65536), "no_answer_at_limit", False),   # 空白だけも空
    (end_record("length", finish="length", content="", tokens=None), "no_answer_at_limit", False),         # 値が無ければ上限に届いたとみなす
    # 同じ 1 トークンの繰り返しで打ち切り（status length なのに上限未満）
    (end_record("length", finish="length", content="", tokens=37935), "repeat_stop", False),
    (end_record("length", finish="length", tokens=37935), "repeat_stop", False),                          # 本文があっても上限未満なら繰り返し停止
    # 思考の途中で停止トークン（新しい記録と、古い記録の finish stop・本文が空・思考あり）
    (end_record("eos_in_thinking", content="", tokens=12380), "eos_in_thinking", False),
    (end_record("ok", content="", tokens=12248), "eos_in_thinking", False),
    # エラー系。本文が空で思考も無い ok は異常な記録なので error
    (end_record("error", content="", tokens=None), "error", False),
    (end_record("timeout", content=""), "error", False),
    (end_record("stall", content=""), "error", False),
    (end_record("ok", content="", thinking=""), "error", False),
    # 記録が無い・時間の上限で飛ばした
    (None, "missing", False),
    ({"status": "skipped_time_budget"}, "missing", False),
])
def test_classify_end(record, expected_end, expected_truncated):
    assert cond_compare.classify_end(record) == {"end": expected_end, "truncated": expected_truncated}


def test_classify_end_uses_the_limit_recorded_in_the_record():
    # limits が無い古い記録は 32,768 とみなす（request.max_tokens があればそちら）
    old = end_record("length", finish="length", content="", tokens=32768, limits=None)
    assert cond_compare.record_max_tokens(old) == 32768
    assert cond_compare.classify_end(old)["end"] == "no_answer_at_limit"
    assert cond_compare.classify_end({**old, "completion_tokens": 32767})["end"] == "repeat_stop"
    assert cond_compare.record_max_tokens({**old, "request": {"max_tokens": 16384}}) == 16384
    assert cond_compare.classify_end({**old, "request": {"max_tokens": 16384}, "completion_tokens": 20000})["end"] == "no_answer_at_limit"
    # 記録の limits が上限を決める（生成 32,768 の記録は 40,000 でなく 32,768 で上限）
    low = end_record("length", finish="length", content="", tokens=32768, limits={"max_tokens": 32768, "reasoning_budget_tokens": 0})
    assert cond_compare.classify_end(low)["end"] == "no_answer_at_limit"
    assert cond_compare.classify_end({**low, "limits": {"max_tokens": 65536}})["end"] == "repeat_stop"


def stat_run(rep, score, end, *, has_answer=True, truncated=False):
    """condition_stats に渡す 1 回分（_run_entry が作る項目のうち集計に使うもの）。"""

    return {"rep": rep, "status": "missing" if end == "missing" else "ok", "score": score, "end": end,
            "has_answer": has_answer, "truncated": truncated, "all_passed": False, "attempts": 1}


def test_condition_stats_counts_answers_and_ends():
    runs = [stat_run(1, 0.8, "self_finished"), stat_run(2, 0.0, "no_answer_at_limit", has_answer=False),
            stat_run(3, 0.5, "budget_cut", truncated=True)]
    stats = cond_compare.condition_stats(runs)
    assert stats["n_answered"] == 2 and stats["n_truncated"] == 1 and stats["n_records"] == 3
    assert stats["ends"]["self_finished"] == 1 and stats["ends"]["no_answer_at_limit"] == 1 and stats["ends"]["budget_cut"] == 1
    assert sum(stats["ends"].values()) == 3 and set(stats["ends"]) == set(cond_compare.END_STATES)
    # 記録の無い回は missing に数える（合計は runs の数）。答えが出た回数には入れない
    with_missing = cond_compare.condition_stats(runs + [cond_compare._run_entry(4, None)])
    assert with_missing["ends"]["missing"] == 1 and with_missing["n_records"] == 3 and with_missing["n_answered"] == 2
    assert sum(with_missing["ends"].values()) == 4


def test_compare_to_baseline_uses_the_same_rule_as_judge_scores():
    base = cond_compare.condition_stats([stat_run(1, 0.2, "self_finished"), stat_run(2, 0.3, "self_finished"),
                                         stat_run(3, 0.1, "self_finished")])

    def compared(*scores):
        return cond_compare.compare_to_baseline(base, cond_compare.condition_stats(
            [stat_run(index + 1, score, "self_finished") for index, score in enumerate(scores)]))

    up = compared(0.5, 0.6, 0.4)                          # 最小 0.4 > 基準の最大 0.3
    assert up["label"] == cond_compare.JUDGE_UP and up["diff"] == pytest.approx(0.5 - 0.2)
    assert compared(0.0, 0.1, 0.05)["label"] == cond_compare.JUDGE_UNDECIDED   # 最大 0.1 = 基準の最小 0.1（同点は下がったと言わない）
    assert compared(0.0, 0.05, 0.09)["label"] == cond_compare.JUDGE_DOWN       # 最大 0.09 < 基準の最小 0.1
    assert compared(0.3, 0.9, 0.9)["label"] == cond_compare.JUDGE_UNDECIDED    # 最小 0.3 = 基準の最大 0.3（同点は上がったと言わない）
    assert compared(0.1, 0.9)["label"] == cond_compare.JUDGE_UNDECIDED
    none = cond_compare.compare_to_baseline(base, cond_compare.condition_stats([]))
    assert none["label"] == cond_compare.JUDGE_INCOMPARABLE and none["diff"] is None
    assert cond_compare.compare_to_baseline(cond_compare.condition_stats([]), base)["label"] == cond_compare.JUDGE_INCOMPARABLE


def write_fix_record(root: Path, condition: str, rep: int, key: str, item: str, score: float, *, status: str = "ok",
                     cut: bool = False, finish: str = "stop", content: str = "答え", thinking: str = "考え中",
                     limits: dict | None = None, lang: str | None = None, attempts: int | None = None,
                     first: str | None = None, tok_s: float = 80.0, wall: float = 400.0,
                     thinking_tokens: int = 30000, all_passed: bool = False, tokens: int = 40000,
                     effort: str | None = None) -> None:
    target = targets_module.get(key)
    expected = cond_compare.FIX_EXPECTED[condition]
    path = common.local_record_path(cond_compare.rep_dir(root, condition, rep), target.slug, "coding", item)
    if cut:
        thinking = f"{thinking}\n{summarize.REASONING_WRAP_UP_MARK}\n"
    record = {"target": target.key, "suite": "coding", "item": item, "status": status, "finish": finish, "content": content,
              "thinking": thinking, "wall_excl_load_s": wall, "completion_tokens": tokens, "thinking_tokens_est": thinking_tokens,
              "server_decode_tok_s": tok_s, "prompt_lang": lang or expected["prompt_lang"],
              "limits": limits or {"max_tokens": expected["max_tokens"], "reasoning_budget_tokens": expected["reasoning_budget_tokens"],
                                   "request_timeout_s": 2400},
              "grade": {"score": score, "all_passed": all_passed}}
    if not content.strip() or status == "eos_in_thinking":
        record["grade"].update({"no_answer": True, "reason": status if status != "ok" else "本文が無い"})
    if effort:
        record["request"] = {"reasoning_effort": effort}
    if attempts:
        record["attempts"] = attempts
    if first:
        record["first_attempt_status"] = first
    common.write_json(path, record)


def synthetic_fix_root(work_tmp: Path) -> Path:
    """5 つの条件（基準 + 4 つ）。RVN は excluded.json で外す（RVN の記録は置いてある）。

    Coder: 上限なし（日本語）は思考中停止・上限まで答えなし・繰り返し停止などが混ざって上がらず、low（生成 32,768）の C4 は全部上限まで答えなしで下がり、
    low の C5 は上がる。英語は全部そろう。low-65k-ja は流していない。
    公式: 上限なし（日本語）の C4 は rep3 が無い（足りない記録）、英語は rep1・rep2 だけ（計画どおり）、low-ja は流していない、
    low-65k-ja は C4 の rep1 だけ（計測の途中）。
    """

    root = work_tmp / "fix"
    cond = cond_compare
    # ---- 基準（既存の記録の写し）。Coder の C5 rep1 は旧記録の思考中停止（status ok のまま本文が空）
    for rep in (1, 2, 3):
        write_fix_record(root, cond.COND_BASELINE, rep, FIX_CODER, "c4", 0.2, cut=True, thinking_tokens=24500)
        write_fix_record(root, cond.COND_BASELINE, rep, FIX_CODER, "c5", 0.1, cut=True)
        write_fix_record(root, cond.COND_BASELINE, rep, FIX_OFFICIAL, "c4", 0.5, cut=True, effort="high")
        write_fix_record(root, cond.COND_BASELINE, rep, FIX_OFFICIAL, "c5", 0.9, cut=True, effort="high")
        write_fix_record(root, cond.COND_BASELINE, rep, FIX_RVN, "c4", 0.1, cut=True)
        write_fix_record(root, cond.COND_BASELINE, rep, FIX_RVN, "c5", 0.0, cut=True)
    write_fix_record(root, cond.COND_BASELINE, 1, FIX_CODER, "c5", 0.0, content="", cut=True)       # 旧記録の思考中停止
    # ---- 上限なし（日本語）
    write_fix_record(root, cond.COND_NOBUDGET_JA, 1, FIX_CODER, "c4", 0.8, thinking_tokens=45000, all_passed=False)
    write_fix_record(root, cond.COND_NOBUDGET_JA, 2, FIX_CODER, "c4", 0.0, status="eos_in_thinking", content="",
                     attempts=2, first="eos_in_thinking", tokens=12000)
    write_fix_record(root, cond.COND_NOBUDGET_JA, 3, FIX_CODER, "c4", 0.9, thinking_tokens=45000, all_passed=True)
    write_fix_record(root, cond.COND_NOBUDGET_JA, 1, FIX_CODER, "c5", 0.1, status="length", finish="length", content="途中の答え", tokens=65536)
    write_fix_record(root, cond.COND_NOBUDGET_JA, 2, FIX_CODER, "c5", 0.0, status="length", finish="length", content="", tokens=65536)
    write_fix_record(root, cond.COND_NOBUDGET_JA, 3, FIX_CODER, "c5", 0.0, status="length", finish="length", content="", tokens=30000)
    for rep in (1, 2):
        write_fix_record(root, cond.COND_NOBUDGET_JA, rep, FIX_OFFICIAL, "c4", 0.9)
    # 公式の C4 rep3 は記録なし（足りない記録に出る）
    for rep, score in ((1, 0.9), (2, 0.9)):
        write_fix_record(root, cond.COND_NOBUDGET_JA, rep, FIX_OFFICIAL, "c5", score)
    write_fix_record(root, cond.COND_NOBUDGET_JA, 3, FIX_OFFICIAL, "c5", 0.0, status="length", finish="length", content="", tokens=65536)
    for item in ("c4", "c5"):
        for rep in (1, 2, 3):
            write_fix_record(root, cond.COND_NOBUDGET_JA, rep, FIX_RVN, item, 0.0, status="length", finish="length", content="")
    # ---- 上限なし（英語）。公式は rep1・rep2 だけ。Coder の C5 rep1 は上限が違う記録（警告に出る）
    for rep, score in ((1, 0.9), (2, 0.8), (3, 1.0)):
        write_fix_record(root, cond.COND_NOBUDGET_EN, rep, FIX_CODER, "c5", score)
    for rep, score in ((1, 0.8), (2, 0.6), (3, 0.7)):
        write_fix_record(root, cond.COND_NOBUDGET_EN, rep, FIX_CODER, "c4", score)
    write_fix_record(root, cond.COND_NOBUDGET_EN, 1, FIX_CODER, "c5", 0.9,
                     limits={"max_tokens": 65536, "reasoning_budget_tokens": 24576, "request_timeout_s": 2400})
    for rep in (1, 2):
        write_fix_record(root, cond.COND_NOBUDGET_EN, rep, FIX_OFFICIAL, "c4", 0.9)
        write_fix_record(root, cond.COND_NOBUDGET_EN, rep, FIX_OFFICIAL, "c5", 0.9)
    # ---- low（日本語・生成 32,768）。Coder の C4 は 3 回とも上限まで答えなし、C5 は 3 回とも答えが出る（rep3 は強さが high の記録 = 警告）
    for rep in (1, 2, 3):
        write_fix_record(root, cond.COND_LOW_JA, rep, FIX_CODER, "c4", 0.0, status="length", finish="length", content="",
                         tokens=32768, effort="low")
    for rep, score in ((1, 0.4), (2, 0.5), (3, 0.6)):
        write_fix_record(root, cond.COND_LOW_JA, rep, FIX_CODER, "c5", score, effort="low" if rep < 3 else "high", tokens=20000)
    # ---- low（日本語・生成 65,536）。公式の C4 rep1 だけ（計測の途中）。Coder は流していない
    write_fix_record(root, cond.COND_LOW_65K_JA, 1, FIX_OFFICIAL, "c4", 1.0, effort="low", all_passed=True)
    # ---- 外したモデルと、起動の記録・journal（Coder の上限なし日本語だけ。基準は起動していない）
    common.write_json(root / "excluded.json", {FIX_RVN: "利用者の指示で対象から外した"})
    common.write_json(cond_compare.server_info_path(root, cond.COND_NOBUDGET_JA, "strata-coder-IQ1_M"), {
        "condition": cond.COND_NOBUDGET_JA, "slug": "strata-coder-IQ1_M", "status": "ok", "reps": [1, 2, 3], "start_s": 70.0,
        "engine_started_line": "[strata] x engine started: /x/strata --max-context 131072 --kv int8",
        "slots": {"filled": 8000, "total": 8000},
        "cache_hit_lines": ["strata serve: decode expert cache hit rate: 90.0% (900 hits / 1000 lookups)"],
        "vram_used_mib": 21000, "memory_peak_bytes": 20 * 1024 ** 3})
    common.write_json(cond_compare.journal_counts_path(root, "strata-coder-IQ1_M"), {
        "slug": "strata-coder-IQ1_M", "unit": "strata-coder",
        "total": {"since": "x", "until": None, "counts": {"repeated_reasoning": 2, "thinking_budget_reached": 0,
                                                          "max_tokens_reached": 0, "lines": 500}},
        "arms": {"nobudget-ja": {"since": "x", "until": "y", "counts": {"repeated_reasoning": 1, "thinking_budget_reached": 0,
                                                                          "max_tokens_reached": 0, "lines": 300}}}})
    common.write_json(root / cond.COND_BASELINE / "source.json", {"note": cond.BASELINE_NOTE, "files": []})
    return root


def test_build_fix_summary_counts_ends_and_answers(work_tmp):
    root = synthetic_fix_root(work_tmp)
    summary = cond_compare.build_fix_summary(root)
    results, combined = summary["results"], summary["combined"]
    base, ja, en, low, low65 = cond_compare.FIX_CONDITIONS
    assert summary["conditions"] == [base, ja, en, low, low65] and summary["baseline"] == base
    assert summary["labels"][base] == "思考最大・上限 24,576（最初の評価）" and summary["labels"][low65] == "low・上限なし（生成 65,536）"
    # 上限なし（日本語）の Coder C4: 0.8 / 思考中停止（やり直しても空）/ 0.9
    coder_c4 = results[FIX_CODER]["c4"][ja]
    assert coder_c4["scores"] == [0.8, 0.0, 0.9] and coder_c4["mean"] == pytest.approx(1.7 / 3)
    assert coder_c4["statuses"] == ["ok", "eos_in_thinking", "ok"]
    assert coder_c4["n_self_finished"] == 2 and coder_c4["n_budget_cut"] == 0 and coder_c4["n_answered"] == 2
    assert coder_c4["n_eos"] == 2 and coder_c4["n_eos_final"] == 1 and coder_c4["n_retried"] == 1   # 1 回目も数える
    assert coder_c4["n_all_passed"] == 1 and coder_c4["thinking_tokens_median"] == 45000
    assert coder_c4["ends"] == {"self_finished": 2, "budget_cut": 0, "answer_truncated": 0, "no_answer_at_limit": 0,
                                "repeat_stop": 0, "eos_in_thinking": 1, "error": 0, "missing": 0}
    # 上限なし（日本語）の Coder C5: 途中で切れた答え（答えあり）・上限まで答えなし・繰り返しで停止（上限未満）
    coder_c5 = results[FIX_CODER]["c5"][ja]
    assert coder_c5["ends"]["answer_truncated"] == 1 and coder_c5["ends"]["no_answer_at_limit"] == 1 and coder_c5["ends"]["repeat_stop"] == 1
    assert coder_c5["n_answered"] == 1 and coder_c5["n_length"] == 3
    # 基準: 予算で打ち切られた回は budget_cut で「自分で思考を終えた」に数えない。旧記録の思考中停止（status ok のまま）も同じ状態に数える
    base_c4 = results[FIX_CODER]["c4"][base]
    assert base_c4["ends"]["budget_cut"] == 3 and base_c4["n_self_finished"] == 0 and base_c4["n_answered"] == 3
    base_c5 = results[FIX_CODER]["c5"][base]
    assert base_c5["statuses"][0] == "eos_in_thinking" and base_c5["runs"][0]["eos_legacy"] and base_c5["n_eos"] == 1
    assert base_c5["ends"]["eos_in_thinking"] == 1 and base_c5["ends"]["budget_cut"] == 2 and base_c5["n_answered"] == 2
    # C4・C5 をまとめた行（6 回）
    assert combined[FIX_CODER][ja]["n_records"] == 6 and combined[FIX_CODER][ja]["n_answered"] == 3
    assert combined[FIX_CODER][ja]["mean"] == pytest.approx((1.7 + 0.1) / 6)
    assert combined[FIX_CODER][base]["n_answered"] == 5 and sum(combined[FIX_CODER][base]["ends"].values()) == 6
    # 基準の答えが出た回数は旧記録の思考中停止を除く。速さの中央値もそろう
    assert combined[FIX_OFFICIAL][base]["n_answered"] == 6 and combined[FIX_OFFICIAL][base]["tok_s_median"] == 80.0


def test_build_fix_summary_baseline_comparisons(work_tmp):
    root = synthetic_fix_root(work_tmp)
    summary = cond_compare.build_fix_summary(root)
    base, ja, en, low, low65 = cond_compare.FIX_CONDITIONS
    comparisons = summary["comparisons"]
    assert base not in comparisons[FIX_CODER]["c4"]                       # 基準そのものは入れない
    # 上限なし（日本語）の Coder C4: [0.8, 0, 0.9] と基準 [0.2]*3 は幅が重なる → 判定できない（平均の差 +0.37）
    entry = comparisons[FIX_CODER]["c4"][ja]
    assert entry["label"] == cond_compare.JUDGE_UNDECIDED and entry["diff"] == pytest.approx(1.7 / 3 - 0.2)
    assert entry["baseline_range"] == [0.2, 0.2] and entry["range"] == [0.0, 0.9]
    # low-ja の Coder: C4 は全部 0 点（最大 0 < 基準の最小 0.2）→ 下がった、C5 は [0.4, 0.5, 0.6] vs 基準 [0, 0.1, 0.1]（最小 0.4 > 最大 0.1）→ 上がった
    assert comparisons[FIX_CODER]["c4"][low]["label"] == cond_compare.JUDGE_DOWN
    assert comparisons[FIX_CODER]["c4"][low]["diff"] == pytest.approx(-0.2)
    assert comparisons[FIX_CODER]["c5"][low]["label"] == cond_compare.JUDGE_UP
    assert comparisons[FIX_CODER]["c5"][low]["diff"] == pytest.approx(0.5 - 0.2 / 3)
    # まとめた行も同じ規則（6 回の点の最小・最大）。low-ja の Coder: 条件 [0,0,0,.4,.5,.6]、基準 [.2,.2,.2,0,.1,.1] → 判定できない
    assert comparisons[FIX_CODER][cond_compare.COMBINED][low]["label"] == cond_compare.JUDGE_UNDECIDED
    assert comparisons[FIX_CODER][cond_compare.COMBINED][low]["diff"] == pytest.approx(1.5 / 6 - 0.8 / 6)
    # 記録の無い（流していない）条件は比べられない。一部だけの条件は、ある記録だけで比べる
    assert comparisons[FIX_CODER]["c4"][low65]["label"] == cond_compare.JUDGE_INCOMPARABLE
    assert comparisons[FIX_CODER]["c4"][low65]["diff"] is None
    assert comparisons[FIX_OFFICIAL]["c5"][low65]["label"] == cond_compare.JUDGE_INCOMPARABLE
    assert comparisons[FIX_OFFICIAL]["c4"][low65]["label"] == cond_compare.JUDGE_UP        # 1.0 > 基準の最大 0.5（1 回だけ）
    assert comparisons[FIX_OFFICIAL][cond_compare.COMBINED][low]["label"] == cond_compare.JUDGE_INCOMPARABLE      # 公式の low-ja は流していない
    assert comparisons[FIX_OFFICIAL]["c4"][ja]["label"] == cond_compare.JUDGE_UP           # [0.9, 0.9] > 基準の最大 0.5
    # 平均の差は条件 − 基準
    assert comparisons[FIX_OFFICIAL]["c5"][ja]["diff"] == pytest.approx(1.8 / 3 - 0.9)


def test_build_fix_summary_excluded_not_run_missing_and_warnings(work_tmp):
    root = synthetic_fix_root(work_tmp)
    summary = cond_compare.build_fix_summary(root)
    base, ja, en, low, low65 = cond_compare.FIX_CONDITIONS
    # 外したモデルは集計・表・図・足りない記録のどこにも出ない（理由は excluded）
    assert [model["key"] for model in summary["models"]] == [FIX_CODER, FIX_OFFICIAL]
    assert summary["excluded"] == {FIX_RVN: "利用者の指示で対象から外した"}
    for section in ("results", "combined", "comparisons", "not_run", "servers", "journal_counts", "planned_reps"):
        assert FIX_RVN not in summary[section], section
    assert not any("strata-flash-next" in line or "RVN" in line for line in summary["missing"] + summary["warnings"])
    # 記録が 1 本も無い（モデル, 条件）は「流していない」で、足りない記録に数えない
    assert summary["not_run"][FIX_CODER] == {base: False, ja: False, en: False, low: False, low65: True}
    assert summary["not_run"][FIX_OFFICIAL] == {base: False, ja: False, en: False, low: True, low65: False}
    assert not any("low-65k-ja" in line and "strata-flash-coder" in line for line in summary["missing"])
    assert not any("low-ja" in line and "strata-official" in line for line in summary["missing"])
    # 一部だけあるときは、足りない回を警告する（公式の low-65k-ja は C4 rep1 だけ）
    low65_missing = [line for line in summary["missing"] if "low-65k-ja" in line]
    assert len(low65_missing) == 6 and any("C4（low-65k-ja・rep2）" in line for line in low65_missing)
    assert any("C5（low-65k-ja・rep1）" in line for line in low65_missing)
    assert any("起動の記録（low-65k-ja）server-strata-official-IQ3_XXS.json が無い" in line for line in low65_missing)
    assert any("strata-official:IQ3_XXS の C4（nobudget-ja・rep3）の記録が無い" in line for line in summary["missing"])
    # 計画に無い回（公式の英語 rep3）は足りない記録に数えない。起動の記録が無い条件（流したのに無い）は出る。基準は起動していないので出ない
    assert not any("nobudget-en・rep3" in line for line in summary["missing"])
    assert any("起動の記録（nobudget-ja）server-strata-official-IQ3_XXS.json が無い" in line for line in summary["missing"])
    assert not any("budget24k-ja）server" in line for line in summary["missing"])
    assert summary["planned_reps"][FIX_OFFICIAL][en] == [1, 2]
    # 期待と違う上限・思考の強さの記録は警告
    assert len(summary["warnings"]) == 2
    assert any("nobudget-en" in line and "24576" in line for line in summary["warnings"])
    assert any("low-ja" in line and "思考の強さ" in line and "high" in line for line in summary["warnings"])
    # 起動の記録と journal
    server = summary["servers"][FIX_CODER][ja]
    assert server["slots_filled"] == 8000 and server["cache_hit_pct"] == pytest.approx(90.0) and server["engine_kv"] == "int8"
    assert summary["servers"][FIX_CODER][base] is None
    counts = summary["journal_counts"][FIX_CODER]
    assert counts["total"]["counts"]["repeated_reasoning"] == 2 and counts["arms"]["nobudget-ja"]["counts"]["lines"] == 300
    assert summary["journal_counts"][FIX_OFFICIAL] is None
    # 送った上限・言語・思考の強さ（記録から読む）
    assert summary["limits_seen"][ja] == [{"max_tokens": 65536, "reasoning_budget_tokens": 0, "prompt_lang": "ja"}]
    assert {"max_tokens": 65536, "reasoning_budget_tokens": 24576, "prompt_lang": "en"} in summary["limits_seen"][en]
    assert summary["limits_seen"][low] == [{"max_tokens": 32768, "reasoning_budget_tokens": 0, "prompt_lang": "ja"}]
    assert summary["efforts_seen"][base] == ["high"] and summary["efforts_seen"][low] == ["low", "high"]
    assert summary["efforts_seen"][ja] == []                         # 記録に request が無いときは確かめない


def test_failed_start_is_reported_even_for_a_condition_without_records(work_tmp):
    root = work_tmp / "fix"
    common.write_json(cond_compare.server_info_path(root, cond_compare.COND_LOW_JA, "strata-coder-IQ1_M"),
                      {"slug": "strata-coder-IQ1_M", "status": "start_failed", "reps": []})
    summary = cond_compare.build_fix_summary(root)
    assert summary["not_run"][FIX_CODER][cond_compare.COND_LOW_JA] is True
    assert summary["missing"] == [f"{targets_module.get(FIX_CODER).label}（low-ja）の起動の結果: start_failed"]


def test_fix_summary_works_without_any_records_and_with_custom_conditions(work_tmp):
    empty = work_tmp / "empty"
    empty.mkdir()
    summary = cond_compare.build_fix_summary(empty)
    # 記録が 1 本も無い条件・モデルは全部「流していない」。足りない記録も警告も出ない
    assert not summary["missing"] and not summary["warnings"] and summary["excluded"] == {}
    assert len(summary["models"]) == 3 and len(summary["conditions"]) == 5
    assert all(flag for per_condition in summary["not_run"].values() for flag in per_condition.values())
    assert all(entry["label"] == cond_compare.JUDGE_INCOMPARABLE for per_model in summary["comparisons"].values()
               for per_scope in per_model.values() for entry in per_scope.values())
    # 条件名と数は任意（先頭が基準）。表示名は条件名のまま
    custom = cond_compare.build_fix_summary(empty, ["a", "b"], {"a": "条件 A"})
    assert custom["labels"] == {"a": "条件 A", "b": "b"} and custom["baseline"] == "a"
    assert list(custom["comparisons"][FIX_CODER]["c4"]) == ["b"]
    html_text = cond_compare.build_fix_html(custom, None)
    assert "条件 A" in html_text
    # 条件が 1 つだけ（比べる相手が無い）でも落ちない
    single = cond_compare.build_fix_summary(empty, ["only"])
    assert single["comparisons"][FIX_CODER]["c4"] == {} and "only" in cond_compare.build_fix_html(single, None)


def test_parse_conditions_and_labels():
    assert cond_compare.parse_conditions(None, None) == (list(cond_compare.FIX_CONDITIONS), {})
    assert cond_compare.FIX_CONDITIONS == ("budget24k-ja", "nobudget-ja", "nobudget-en", "low-ja", "low-65k-ja")
    # 既定の表示名（数字に挟まれた「,」＝ 24,576・32,768・65,536 の桁区切りでは割らない）
    default_labels = ("思考最大・上限 24,576（最初の評価）,思考最大・上限なし,思考最大・上限なし・英語,"
                      "low・上限なし（生成 32,768）,low・上限なし（生成 65,536）")
    conditions, labels = cond_compare.parse_conditions(",".join(cond_compare.FIX_CONDITIONS), default_labels)
    assert labels == {name: cond_compare.FIX_LABELS[name] for name in cond_compare.FIX_CONDITIONS}
    assert cond_compare.parse_conditions("x, y", None)[0] == ["x", "y"]
    with pytest.raises(SystemExit):
        cond_compare.parse_conditions("a,b", "only-one")
    with pytest.raises(SystemExit):
        cond_compare.parse_conditions("a,a", None)
    with pytest.raises(SystemExit):
        cond_compare.parse_conditions(" , ", None)


def test_summarize_command_for_fix_and_kv_shim(work_tmp, capsys):
    root = synthetic_fix_root(work_tmp)
    assert cond_compare.main(["summarize", "--root", str(root)]) == 0
    written = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert written["comparisons"][FIX_CODER]["c5"]["low-ja"]["label"] == cond_compare.JUDGE_UP
    assert written["labels"]["budget24k-ja"] == "思考最大・上限 24,576（最初の評価）" and "verdicts" not in written
    out = capsys.readouterr().out
    assert "足りない記録" in out and "!" in out                   # 警告の行
    # 任意の条件名
    assert cond_compare.main(["summarize", "--root", str(root), "--conditions", "budget24k-ja,nobudget-ja",
                              "--out", str(work_tmp / "two.json")]) == 0
    two = json.loads((work_tmp / "two.json").read_text(encoding="utf-8"))
    assert two["conditions"] == ["budget24k-ja", "nobudget-ja"] and list(two["comparisons"][FIX_CODER]["c4"]) == ["nobudget-ja"]
    # kv_compare.py は薄い互換の入口（KV の既定で動き、古い名前をそのまま使える）。KV の集計の形は変えていない
    assert kv_compare.judge_scores is cond_compare.judge_scores and kv_compare.build_summary is cond_compare.build_summary
    kv_root = synthetic_kv_root(work_tmp)
    assert kv_compare.main(["summarize", "--root", str(kv_root)]) == 0
    kv_summary = json.loads((kv_root / "summary.json").read_text(encoding="utf-8"))
    assert kv_summary["kv_types"] == ["int8", "fp16"] and set(kv_summary["judgements"]) == set(cond_compare.MODEL_KEYS)
    assert "not_run" not in kv_summary and "comparisons" not in kv_summary            # KV は流していない扱いを使わない（足りない記録は今までどおり）


FULL_FINDINGS = {"summary": ["一行目", "二行目", "三行目", "四行目も出す"], "facts": ["事実の行"], "opinions": ["意見の行"],
                 "evidence": ["上限に達した回数 45/49", {"text": "EOS 4/15", "source": "results/2026-10-08"}],
                 "recommendations": ["順位づけでは上限を付けない"], "caveats": ["追加の注意"]}
FULL_SETTINGS = [{"item": "思考の上限", "strata": "要求で 24,576", "ollama": "無し", "verdict": "不ぞろい"}]


def test_fix_report_smoke_is_self_contained(work_tmp):
    root = synthetic_fix_root(work_tmp)
    summary = cond_compare.build_fix_summary(root)
    html_text = cond_compare.build_fix_html(summary, {**FULL_FINDINGS, "settings": FULL_SETTINGS}, None)
    parser = _ExternalRefs()
    parser.feed(html_text)
    text = "".join(parser.text)
    assert parser.refs == [] and "http://" not in html_text and "https://" not in html_text      # 外部の参照が無い
    assert "<link" not in html_text and "@import" not in html_text
    # 図: 点の図 2（Coder・公式）+ 終わり方の積み上げ 1 + 思考の棒 1 + 模様の定義 2 + 凡例の小さな図
    assert parser.tags.get("svg", 0) >= 8 and parser.tags.get("table", 0) >= 9
    for section in range(8):
        assert f'id="s{section}"' in html_text
    # 全部記入した findings では「（未記入）」が出ない。結論は全行を箇条書きで出す
    assert "（未記入）" not in text
    for line in ("一行目", "三行目", "四行目も出す", "事実の行", "意見の行", "上限に達した回数 45/49", "EOS 4/15", "results/2026-10-08",
                 "順位づけでは上限を付けない", "追加の注意", "要求で 24,576", "不ぞろい"):
        assert line in text
    # 判定の 4 通りの文字と記号、流していない・外したモデル・状態の文字（色だけに頼らない）
    for word in ("上がった", "下がった", "差は判定できない", "比べられない", "▲", "▼", "＝", "？", "流していない"):
        assert word in text
    assert "外したモデル: RVN IQ3_S" in text and "利用者の指示で対象から外した" in text
    assert text.count("RVN IQ3_S") == 1                                                          # 外したモデルは注意の 1 行にだけ出る
    for word in ("答えが出た回数", "自己終了", "予算打切", "答え途中で上限", "上限まで答えなし", "繰り返し停止", "思考中停止", "やり直し済み",
                 "旧記録", "計画外", "journal の行数", "答えあり", "うち打切のあと途中切れ"):
        assert word in text
    for name in cond_compare.END_STATES[:-1]:
        assert name in text                                                                       # 凡例・分類の規則に終わり方の名前が出る
    for color in (build_report.COLOR_OK, build_report.COLOR_NG, build_report.COLOR_NA, "#7044bb", cond_compare.END_COLOR_AMBER):
        assert color in html_text
    assert 'patternTransform="rotate(45)"' in html_text and 'patternTransform="rotate(135)"' in html_text
    # 条件の定義の表（記録の limits・request から）と、条件の表示名
    for word in ("思考最大・上限 24,576（最初の評価）", "思考最大・上限なし・英語", "low・上限なし（生成 32,768）", "low・上限なし（生成 65,536）",
                 "24,576", "なし", "32,768", "65,536", "日本語", "英語", "high", "low", "Coder IQ1_M 流していない"):
        assert word in text
    # 固定の注意
    for word in ("試行は各条件", "別の日のもの", "生成の上限が条件で違う（32,768 と 65,536）", "Ollama のモデルは同じ問題を生成の上限 32,768・思考の上限なし"):
        assert word in text
    for word in ("条件の最小 &gt; 基準の最大", "終わり方の分類の規則", "生データの場所", "足りない記録・条件の食い違い"):
        assert word in html_text
    out = work_tmp / "out" / "report.html"
    settings_path = work_tmp / "settings.json"
    findings_path = work_tmp / "findings.json"
    settings_path.write_text(json.dumps(FULL_SETTINGS, ensure_ascii=False), encoding="utf-8")
    findings_path.write_text(json.dumps(FULL_FINDINGS, ensure_ascii=False), encoding="utf-8")
    assert cond_compare.main(["report", "--root", str(root), "--findings", str(findings_path), "--settings-table",
                              str(settings_path), "--out", str(out)]) == 0
    assert out.stat().st_size > 30000 and "要求で 24,576" in out.read_text(encoding="utf-8")
    # settings は findings.json の配列でも、--settings-table の JSON でも出る
    assert "要求で 24,576" in cond_compare.build_fix_html(summary, {**FULL_FINDINGS, "settings": FULL_SETTINGS}, None)
    assert "要求で 24,576" in cond_compare.build_fix_html(summary, FULL_FINDINGS, FULL_SETTINGS)


def test_fix_report_marks_missing_findings_as_unfilled(work_tmp):
    root = synthetic_fix_root(work_tmp)
    summary = cond_compare.build_fix_summary(root)
    for findings in (None, {}, {"summary": [], "evidence": None}):
        html_text = cond_compare.build_fix_html(summary, findings, None)
        text = "".join(_parse_text(html_text))
        # 結論・設定・証拠・推奨・所見の 5 つの節が「（未記入）」。注意の節は固定の文だけで出る
        assert text.count("（未記入）") >= 5
        for hint in ("summary（文の配列）", "settings 配列", "evidence（文の配列）", "recommendations（文の配列）", "facts と opinions"):
            assert hint in text
        for section in range(8):
            assert f'id="s{section}"' in html_text
    # 一部だけ書いたとき（事実だけ）は、書いた分が出て、残りだけ「（未記入）」
    partial = "".join(_parse_text(cond_compare.build_fix_html(summary, {"facts": ["事実だけ"]}, None)))
    assert "事実だけ" in partial and "意見（解釈）" in partial


def _parse_text(html_text: str) -> list[str]:
    parser = _ExternalRefs()
    parser.feed(html_text)
    return parser.text


def test_fix_report_without_any_records_does_not_crash(work_tmp):
    empty = work_tmp / "empty"
    empty.mkdir()
    summary = cond_compare.build_fix_summary(empty)
    html_text = cond_compare.build_fix_html(summary, None, None)
    parser = _ExternalRefs()
    parser.feed(html_text)
    text = "".join(parser.text)
    assert "流していない" in text and text.count("（未記入）") >= 5
    assert parser.refs == []
    out = work_tmp / "empty.html"
    assert cond_compare.main(["report", "--root", str(empty), "--out", str(out)]) == 0 and out.exists()


def test_fix_report_with_only_part_of_the_records_does_not_crash(work_tmp):
    """計測の途中（一部の条件に記録が一部だけ）でも、集計と HTML が作れて、記録の数が表に出る。"""

    root = work_tmp / "partial"
    write_fix_record(root, cond_compare.COND_BASELINE, 1, FIX_OFFICIAL, "c4", 0.5, cut=True)
    write_fix_record(root, cond_compare.COND_LOW_65K_JA, 1, FIX_OFFICIAL, "c4", 1.0, tokens=65536, status="length", finish="length")
    write_fix_record(root, cond_compare.COND_LOW_65K_JA, 2, FIX_OFFICIAL, "c5", 0.0, tokens=65536, status="length", finish="length", content="")
    summary = cond_compare.build_fix_summary(root)
    assert summary["combined"][FIX_OFFICIAL][cond_compare.COND_LOW_65K_JA]["n_records"] == 2
    assert summary["combined"][FIX_OFFICIAL][cond_compare.COND_LOW_65K_JA]["ends"]["missing"] == 4
    text = "".join(_parse_text(cond_compare.build_fix_html(summary, None, None)))
    assert "記録 2 / 6" in text and "記録 1 / 6" in text
    assert "公式 IQ3_XXS 2 / 6" in text


# ------------------------------------------------------------------------------------------------ cond_compare.py の小道具（基準の写し・journal・起動の記録）


def test_copy_baseline_copies_three_reps_and_writes_source(work_tmp):
    rep1_source, reps_source, root = work_tmp / "s1", work_tmp / "kv-int8", work_tmp / "fix"
    slug = targets_module.get(FIX_CODER).slug
    for item in cond_compare.ITEMS:
        common.write_json(common.local_record_path(rep1_source, slug, "coding", item), {"item": item, "from": "rep1"})
        for rep in (2, 3):
            common.write_json(common.local_record_path(reps_source / f"rep{rep}", slug, "coding", item), {"item": item, "from": f"rep{rep}"})
    actions = cond_compare.copy_baseline(root, "budget24k-ja", rep1_source, reps_source, [slug], dry_run=True)
    assert len(actions) == 6 and not (root / "budget24k-ja").exists()          # --dry-run は何も書かない
    cond_compare.copy_baseline(root, "budget24k-ja", rep1_source, reps_source, [slug])
    for rep in (1, 2, 3):
        for item in cond_compare.ITEMS:
            copied = common.read_json(common.local_record_path(cond_compare.rep_dir(root, "budget24k-ja", rep), slug, "coding", item))
            assert copied["from"] == f"rep{rep}"
    info = common.read_json(root / "budget24k-ja" / "source.json")
    assert len(info["files"]) == 6 and "24,576" in info["note"] and "32,768" in info["note"] and "日本語" in info["note"]
    assert info["limits"] == {"reasoning_budget_tokens": 24576, "max_tokens": 32768, "prompt_lang": "ja"}
    assert {entry["rep"] for entry in info["files"]} == {1, 2, 3} and info["files"][0]["from"].endswith("-run1.json")
    # 2 回目は写さない（既にある記録は上書きしない）
    marker = common.local_record_path(cond_compare.rep_dir(root, "budget24k-ja", 2), slug, "coding", "c4")
    common.write_json(marker, {"edited": True})
    assert all("既にある" in action for action in cond_compare.copy_baseline(root, "budget24k-ja", rep1_source, reps_source, [slug]))
    assert common.read_json(marker) == {"edited": True} and len(common.read_json(root / "budget24k-ja" / "source.json")["files"]) == 6
    # 元の記録が無いときは、その旨を返して続ける
    other = cond_compare.copy_baseline(root, "budget24k-ja", rep1_source, reps_source, ["no-such-slug"])
    assert len(other) == 6 and all("元の記録が無い" in action for action in other)


def test_copy_baseline_command_dry_run(work_tmp, capsys):
    assert cond_compare.main(["copy-baseline", "--root", str(work_tmp / "fix"), "--slug", "strata-coder-IQ1_M",
                              "--slug", "strata-official-IQ3_XXS", "--slug", "strata-rvn-IQ3_S", "--dry-run"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[dry-run]")]
    assert len(lines) == 18 and all("→" in line for line in lines)             # 写し元の実際の記録（3 モデル × 3 回 × 2 問）
    assert not (work_tmp / "fix").exists()


def test_count_journal_lines_and_journal_counts_command(work_tmp, monkeypatch, capsys):
    journal = ("2026-10-09T15:00:00+0900 h strata[1]: repeated reasoning detected; recovering\n"
               "2026-10-09T15:01:00+0900 h strata[1]: the reply reached max tokens\n"
               "2026-10-09T15:02:00+0900 h strata[1]: repeated reasoning detected\n"
               "2026-10-09T15:03:00+0900 h strata[1]: thinking budget reached\n"
               "2026-10-09T15:04:00+0900 h strata[1]: other line\n")
    counts = cond_compare.count_journal_lines(journal)
    assert counts == {"repeated_reasoning": 2, "thinking_budget_reached": 1, "max_tokens_reached": 1, "lines": 5}
    assert cond_compare.count_journal_lines("") == {"repeated_reasoning": 0, "thinking_budget_reached": 0,
                                                    "max_tokens_reached": 0, "lines": 0}
    journal_file = work_tmp / "journal.txt"
    journal_file.write_text(journal, encoding="utf-8")
    root = work_tmp / "fix"
    base = ["journal-counts", "--root", str(root), "--slug", "strata-coder-IQ1_M", "--unit", "strata-coder", "--since",
            "2026-10-09 15:00:00", "--journal-file", str(journal_file)]
    assert cond_compare.main(base + ["--arm", "nobudget-ja", "--until", "2026-10-09 16:00:00"]) == 0
    assert cond_compare.main(base) == 0
    data = common.read_json(cond_compare.journal_counts_path(root, "strata-coder-IQ1_M"))
    assert data["arms"]["nobudget-ja"]["counts"]["repeated_reasoning"] == 2 and data["arms"]["nobudget-ja"]["until"] == "2026-10-09 16:00:00"
    assert data["total"]["counts"]["lines"] == 5 and data["unit"] == "strata-coder" and "repeated_reasoning" in data["patterns"]
    # journalctl の呼び出し（--user -u UNIT --since ... -o short-iso）。読めなければ終了コード 1 で何も書かない
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout=journal, stderr="")

    monkeypatch.setattr(cond_compare.subprocess, "run", fake_run)
    assert cond_compare.main(["journal-counts", "--root", str(root), "--slug", "s2", "--unit", "strata", "--since", "2026-10-09 15:00:00",
                              "--until", "2026-10-09 17:00:00", "--arm", "nobudget-en"]) == 0
    assert seen["command"][:6] == ["journalctl", "--user", "-u", "strata", "--since", "2026-10-09 15:00:00"]
    assert "short-iso" in seen["command"] and seen["command"][seen["command"].index("--until") + 1] == "2026-10-09 17:00:00"
    monkeypatch.setattr(cond_compare, "read_journal", lambda unit, since, until=None: (_ for _ in ()).throw(OSError("no journal")))
    capsys.readouterr()
    assert cond_compare.main(["journal-counts", "--root", str(root), "--slug", "s3", "--unit", "strata", "--since", "x"]) == 1
    assert not cond_compare.journal_counts_path(root, "s3").exists()


def test_parse_engine_log_hits_after_line_picks_one_condition():
    # ENGINE_LOG の 0 始まりの行: 0 古い行 / 1 起動 / 2 枠 / 3 命中 / 4 起動（最後）/ 5 / 6 枠 / 7 命中 90% / 8 命中 80%
    everything = cond_compare.parse_engine_log(ENGINE_LOG)["cache_hit_lines"]
    assert len(everything) == 2
    last_only = cond_compare.parse_engine_log(ENGINE_LOG, hits_after_line=8)
    assert len(last_only["cache_hit_lines"]) == 1 and "80.0%" in last_only["cache_hit_lines"][0]
    assert last_only["started_line"].startswith("[strata] 2026-10-09 12:00:00") and last_only["slots"]["filled"] == 5866   # 起動行と枠は変わらない
    assert cond_compare.parse_engine_log(ENGINE_LOG, hits_after_line=9)["cache_hit_lines"] == []
    assert cond_compare.parse_engine_log(ENGINE_LOG, after_line=3, hits_after_line=8)["cache_hit_lines"] == last_only["cache_hit_lines"]


def test_server_info_command_accepts_any_condition_name(work_tmp, monkeypatch):
    monkeypatch.setattr(cond_compare, "read_cgroup_memory", lambda unit: (111, 99))
    monkeypatch.setattr(cond_compare, "read_vram_used_mib", lambda: 22000)
    log_path = work_tmp / "engine.log"
    log_path.write_text(ENGINE_LOG, encoding="utf-8")
    root = work_tmp / "fix"
    assert cond_compare.main(["server-info", "--root", str(root), "--cond", "nobudget-en", "--target", FIX_OFFICIAL,
                              "--unit", "strata-official", "--engine-log", str(log_path), "--hits-after-line", "8",
                              "--start-s", "75", "--status", "ok", "--reps", "1 2", "--vram-before", "16"]) == 0
    info = common.read_json(cond_compare.server_info_path(root, "nobudget-en", "strata-official-IQ3_XXS"))
    assert info["condition"] == "nobudget-en" and "kv" not in info and info["reps"] == [1, 2]
    assert len(info["cache_hit_lines"]) == 1 and info["slots"] == {"filled": 5866, "total": 5866}
    assert cond_compare.main(["pending", "--root", str(root), "--cond", "nobudget-en", "--rep", "1",
                              "--slug", "strata-official-IQ3_XXS"]) == 0
    assert cond_compare.count_pending(root, "nobudget-en", 1, "strata-official-IQ3_XXS") == 2


# ------------------------------------------------------------------------------------------------ run_fix_compare.sh


def run_fix_script(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(["bash", str(TOOL_DIR / "run_fix_compare.sh"), *args], capture_output=True, text=True,
                          env=env, timeout=120, check=False)


def test_run_fix_compare_script_syntax_and_dry_run():
    assert subprocess.run(["bash", "-n", str(TOOL_DIR / "run_fix_compare.sh")], check=False).returncode == 0
    tag = "pytest-fix-dry"
    results = TOOL_DIR / "results" / tag
    assert not results.exists()
    completed = run_fix_script("--dry-run", env_extra={"RUN_TAG": tag})
    out = completed.stdout
    assert completed.returncode == 0, completed.stderr
    # 最初に基準の写し元 18 本（3 モデル × rep1〜3 × C4・C5）。rep1 は 2026-10-08、rep2・rep3 は KV の比べの int8
    copies = [line for line in out.splitlines() if "budget24k-ja/rep" in line and "→" in line]
    assert len(copies) == 18
    assert sum("results/2026-10-08/local/" in line for line in copies) == 6
    assert sum("results/2026-10-09-kv/int8/rep2/local/" in line for line in copies) == 6
    assert sum("results/2026-10-09-kv/int8/rep3/local/" in line for line in copies) == 6
    # 順番: Coder → 公式 → RVN。モデルごとに起動は 1 回
    assert re.findall(r"systemctl --user start (\S+)", out) == ["strata-coder", "strata-official", "strata"]
    assert re.findall(r"systemctl --user stop (\S+)", out) == ["strata-coder", "strata-official", "strata"]
    # 命令: 思考の上限なし・生成 65,536・1 モデルの累計 400 分。英語は B だけ（Coder 3 回・公式 2 回）
    runs = [line for line in out.splitlines() if "run_eval.py run --target" in line]
    assert len(runs) == 14 and all("--reasoning-budget 0 --max-tokens 65536 --time-budget-min 400" in line for line in runs)
    assert all("--suite coding --items c4,c5" in line for line in runs)
    assert sum("--prompt-lang en" in line for line in runs) == 5 and sum("nobudget-en" in line for line in runs) == 5
    assert all(("--prompt-lang en" in line) == ("/nobudget-en/" in line) for line in runs)
    assert f"results/{tag}/nobudget-ja/rep3" in out and f"results/{tag}/nobudget-en/rep2" in out
    assert f"results/{tag}/nobudget-en/rep3 " in "".join(line for line in runs if "strata-flash-coder" in line)
    assert not any("strata-official" in line and "nobudget-en/rep3" in line for line in runs)       # 公式の英語は 2 回
    assert not any("strata-flash-next" in line and "nobudget-en" in line for line in runs)           # RVN は英語を流さない
    # Coder → 公式 → RVN の順の命令
    order = [re.search(r"--target (\S+)", line).group(1) for line in runs]
    assert order == ["strata-flash-coder:IQ1_M"] * 6 + ["strata-official:IQ3_XXS"] * 5 + ["strata-flash-next:IQ3_S"] * 3
    # KV の型は切り替えない。journal・起動の記録も命令に出る
    assert "systemctl --user set-environment" not in out and "systemctl --user unset-environment" not in out
    assert out.count("journal-counts") == 8 and out.count("server-info") == 5
    assert not results.exists() and not (TOOL_DIR / "work" / f"run_fix_compare-{tag}.log").exists()   # dry-run は何も作らない


def test_run_fix_compare_script_filters_and_rejects_bad_input():
    env = {"RUN_TAG": "pytest-fix-dry", "ONLY_TARGETS": "strata-official:IQ3_XXS", "ONLY_ARMS": "nobudget-en"}
    out = run_fix_script("--dry-run", env_extra=env).stdout
    assert re.findall(r"systemctl --user start (\S+)", out) == ["strata-official"]
    runs = [line for line in out.splitlines() if "run_eval.py run --target" in line]
    assert len(runs) == 2 and all("/nobudget-en/" in line and "--prompt-lang en" in line for line in runs)
    assert "nobudget-ja（" not in out and sum("budget24k-ja/rep" in line and "→" in line for line in out.splitlines()) == 6
    both = run_fix_script("--dry-run", env_extra={**env, "ONLY_ARMS": "nobudget-ja,nobudget-en"}).stdout
    assert sum("run_eval.py run --target" in line for line in both.splitlines()) == 5
    assert run_fix_script("--dry-run", env_extra={"ONLY_ARMS": "budget24k-ja"}).returncode == 2       # 基準は流せない
    assert run_fix_script("--dry-run", env_extra={"ONLY_TARGETS": "nothing"}).returncode == 2
    assert run_fix_script("--no-such-option").returncode == 2
    assert "ONLY_ARMS" in run_fix_script("--help").stdout


# 偽の run_eval.py（fix 用）: 記録に limits・言語を書き、エンジンのログに命中率の行を足す（日本語は 90%、英語は 50%）
STUB_RUN_EVAL_FIX = """#!/usr/bin/env python3
import os, sys
sys.path.insert(0, __TOOL_DIR__)
import targets
from evallib import common
from pathlib import Path

args = sys.argv[1:]
assert args[0] == "run", args
options = dict(zip(args[1::2], args[2::2]))
target = targets.get(options["--target"])
results_dir = Path(options["--results-dir"])
state = Path(os.environ["STUB_STATE"])
active = ",".join(sorted(path.name[len("active-"):] for path in state.glob("active-*")))
lang = options.get("--prompt-lang", "ja")
with open(state / "calls.log", "a") as calls:
    calls.write(f"run_eval target={target.key} dir={results_dir} lang={lang} budget={options.get('--reasoning-budget')} "
                f"max={options.get('--max-tokens')} limit_min={options.get('--time-budget-min')} active={active}\\n")
logs = {"strata-coder": "strata-coder-engine.log", "strata-official": "strata-official-engine.log"}
with open(Path(os.environ["STUB_STRATA_LOGS"]) / logs.get(target.unit, "strata-engine.log"), "a") as engine_log:
    hits = 90 if lang == "ja" else 50
    engine_log.write(f"strata serve: decode expert cache hit rate: {hits}.0% ({hits} hits / 100 lookups)\\n")
for item in options["--items"].split(","):
    path = common.local_record_path(results_dir, target.slug, "coding", item)
    if path.exists():
        continue
    common.write_json(path, {"target": target.key, "suite": "coding", "item": item, "status": "ok", "finish": "stop", "content": "答え",
                             "thinking": "考え", "wall_excl_load_s": 10.0, "prompt_lang": lang,
                             "limits": {"max_tokens": int(options["--max-tokens"]),
                                        "reasoning_budget_tokens": int(options["--reasoning-budget"]), "request_timeout_s": 2400},
                             "grade": {"score": 0.5, "all_passed": False}})
""".replace("__TOOL_DIR__", repr(str(TOOL_DIR)))

STUB_JOURNALCTL_FIX = """#!/usr/bin/env bash
# 偽の journalctl（試験用）: ループの回復 2 行・思考の予算 1 行・ほかの行 1 行を返す
echo "2026-10-09T15:00:00+0900 h strata[1]: repeated reasoning detected; recovering"
echo "2026-10-09T15:00:01+0900 h strata[1]: repeated reasoning detected"
echo "2026-10-09T15:00:02+0900 h strata[1]: thinking budget reached"
echo "2026-10-09T15:00:03+0900 h strata[1]: other line for $*"
"""


def build_fix_stub_env(work_tmp: Path, **extra_env: str) -> dict[str, str]:
    env = build_kv_stub_env(work_tmp)
    stub_bin = work_tmp / "stubbin"
    for name, body in (("run_eval_stub", STUB_RUN_EVAL_FIX), ("journalctl", STUB_JOURNALCTL_FIX)):
        (stub_bin / name).write_text(body, encoding="utf-8")
        (stub_bin / name).chmod(0o755)
    # 基準の写し元: rep1 は SOURCE_RESULTS（build_kv_stub_env が作る）、rep2・rep3 は KV の比べの int8。どれも request に上限を持つ
    kv_source = work_tmp / "kvsource"
    old_request = {"max_tokens": 32768, "reasoning_budget_tokens": 24576}
    for key in cond_compare.MODEL_KEYS:
        slug = targets_module.get(key).slug
        for item in cond_compare.ITEMS:
            for base in [Path(env["SOURCE_RESULTS"])] + [kv_source / f"rep{rep}" for rep in (2, 3)]:
                common.write_json(common.local_record_path(base, slug, "coding", item),
                                  {"target": key, "item": item, "status": "ok", "request": old_request, "thinking": "考え",
                                   "grade": {"score": 0.4, "all_passed": False}})
    env.update({"SOURCE_KV_RESULTS": str(kv_source), "RUN_TAG": "fixtest"})
    env.update(extra_env)
    return env


def run_fix_stubbed(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(TOOL_DIR / "run_fix_compare.sh")], capture_output=True, text=True, env=env,
                          timeout=180, check=False)


def test_run_fix_compare_full_flow_with_stubs(work_tmp):
    env = build_fix_stub_env(work_tmp)
    completed = run_fix_stubbed(env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = work_tmp / "results" / "fixtest"
    done = (root / "DONE").read_text(encoding="utf-8")
    assert "status=finished" in done and "environment=STRATA_EXTRA_ARGS なし" in done
    # 基準 18 本と source.json、A・B の記録（Coder は A・B とも 3 回、公式は A 3 回・B 2 回、RVN は A 3 回）
    coder, official, rvn = cond_compare.MODEL_KEYS
    expected_reps = {coder: {"nobudget-ja": (1, 2, 3), "nobudget-en": (1, 2, 3)},
                     official: {"nobudget-ja": (1, 2, 3), "nobudget-en": (1, 2)}, rvn: {"nobudget-ja": (1, 2, 3), "nobudget-en": ()}}
    for key in cond_compare.MODEL_KEYS:
        slug = targets_module.get(key).slug
        for rep in (1, 2, 3):
            for item in cond_compare.ITEMS:
                assert cond_compare.record_path(root, "budget24k-ja", rep, slug, item).is_file(), (slug, rep, item)
        for arm in ("nobudget-ja", "nobudget-en"):
            for rep in (1, 2, 3):
                for item in cond_compare.ITEMS:
                    assert cond_compare.record_path(root, arm, rep, slug, item).exists() == (rep in expected_reps[key][arm]), (slug, arm, rep)
    assert len(common.read_json(root / "budget24k-ja" / "source.json")["files"]) == 18
    # 流した順（起動の順）: Coder → 公式 → RVN。起動は 1 回ずつ。KV の型の切り替え（set-environment）は 1 度もしない
    calls = kv_calls(work_tmp)
    assert [line.split()[-1] for line in calls if " start " in line] == ["strata-coder", "strata-official", "strata"]
    assert not [line for line in calls if "set-environment" in line]
    runs = [line for line in calls if line.startswith("run_eval")]
    assert len(runs) == 14 and all("budget=0 max=65536 limit_min=400" in line for line in runs)
    assert all(("lang=en" in line) == ("/nobudget-en/" in line) for line in runs)
    assert [re.search(r"target=(\S+)", line).group(1) for line in runs] == [coder] * 6 + [official] * 5 + [rvn] * 3
    for line in runs:                                                      # 流している間は、そのモデルの unit だけが起動している
        target_key = re.search(r"target=(\S+)", line).group(1)
        assert line.endswith(f"active={targets_module.get(target_key).unit}"), line
    # 条件 × モデルごとの起動の記録。命中率はその条件を流した間の行だけ（日本語 90%・英語 50%）
    for key in cond_compare.MODEL_KEYS:
        slug = targets_module.get(key).slug
        for arm in ("nobudget-ja", "nobudget-en"):
            path = cond_compare.server_info_path(root, arm, slug)
            assert path.exists() == bool(expected_reps[key][arm]), (slug, arm)
            if path.exists():
                info = common.read_json(path)
                assert info["status"] == "ok" and info["condition"] == arm and "kv" not in info and info["slots"]["filled"] == 8000
                assert info["reps"] == list(expected_reps[key][arm]) and info["vram_before_mib"] == 16
                stats = cond_compare.cache_hit_stats(info["cache_hit_lines"])
                assert stats["pct"] == pytest.approx(90.0 if arm == "nobudget-ja" else 50.0)
                assert stats["lines"] == len(expected_reps[key][arm])
                assert "--kv int8" in info["engine_started_line"] and "--kv fp16" not in info["engine_started_line"]
    # journal の行数: モデルごとに 1 ファイル（起動から停止までと、条件ごと）
    for key in cond_compare.MODEL_KEYS:
        data = common.read_json(cond_compare.journal_counts_path(root, targets_module.get(key).slug))
        assert data["total"]["counts"]["repeated_reasoning"] == 2 and data["total"]["counts"]["thinking_budget_reached"] == 1
        assert set(data["arms"]) == {arm for arm, reps in expected_reps[key].items() if reps}
    # 終わり: どの unit も止まっている
    assert not list((work_tmp / "state").glob("active-*"))
    assert (work_tmp / "logs" / "run_fix_compare-fixtest.log").is_file()
    # 集計まで通る（足りない記録・警告なし）
    summary = cond_compare.build_fix_summary(root)
    assert not summary["missing"] and not summary["warnings"]
    assert summary["servers"][coder]["nobudget-en"]["cache_hit_pct"] == pytest.approx(50.0)
    assert summary["limits_seen"]["nobudget-en"] == [{"max_tokens": 65536, "reasoning_budget_tokens": 0, "prompt_lang": "en"}]
    # 2 回目は記録済みなので、起動しない（途中から続けられる）
    (work_tmp / "state" / "calls.log").unlink()
    again = run_fix_stubbed(env)
    assert again.returncode == 0 and not [line for line in kv_calls(work_tmp) if " start " in line or line.startswith("run_eval")]
    assert "記録済み" in again.stdout


def test_run_fix_compare_only_filters_run_a_subset(work_tmp):
    env = build_fix_stub_env(work_tmp, ONLY_TARGETS="strata-official:IQ3_XXS", ONLY_ARMS="nobudget-en")
    assert run_fix_stubbed(env).returncode == 0
    root = work_tmp / "results" / "fixtest"
    calls = kv_calls(work_tmp)
    assert [line.split()[-1] for line in calls if " start " in line] == ["strata-official"]
    runs = [line for line in calls if line.startswith("run_eval")]
    assert len(runs) == 2 and all("/nobudget-en/" in line and "lang=en" in line for line in runs)
    slug = targets_module.get(cond_compare.MODEL_KEYS[1]).slug
    assert cond_compare.record_path(root, "budget24k-ja", 1, slug, "c4").is_file()          # 基準は選んだモデルの分だけ写す
    assert not cond_compare.record_path(root, "budget24k-ja", 1, targets_module.get(cond_compare.MODEL_KEYS[0]).slug, "c4").exists()
    assert not (root / "nobudget-ja").exists()


def test_run_fix_compare_start_failure_is_recorded_and_next_model_runs(work_tmp):
    env = build_fix_stub_env(work_tmp, STUB_FAIL_START="strata-official")
    completed = run_fix_stubbed(env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = work_tmp / "results" / "fixtest"
    slug = "strata-official-IQ3_XXS"
    for arm in ("nobudget-ja", "nobudget-en"):
        info = common.read_json(cond_compare.server_info_path(root, arm, slug))
        assert info["status"] == "start_failed" and info["slots"] is None
    assert list(root.glob(f"journal-start-failed-{slug}-*.txt"))
    assert cond_compare.record_path(root, "nobudget-ja", 1, "strata-coder-IQ1_M", "c4").exists()      # Coder は流れた
    assert cond_compare.record_path(root, "nobudget-ja", 1, "strata-rvn-IQ3_S", "c4").exists()         # RVN も流れた
    assert not cond_compare.record_path(root, "nobudget-ja", 1, slug, "c4").exists()
    done = (root / "DONE").read_text(encoding="utf-8")
    assert "status=finished" in done and "status=start_failed" in done
    summary = cond_compare.build_fix_summary(root)
    assert any("start_failed" in line for line in summary["missing"])


def test_run_fix_compare_aborts_when_gpu_service_is_running_and_still_cleans_up(work_tmp):
    env = build_fix_stub_env(work_tmp)
    (work_tmp / "state" / "active-comfyui").touch()
    completed = run_fix_stubbed(env)
    assert completed.returncode == 1 and "GPU を取り合う" in completed.stdout
    root = work_tmp / "results" / "fixtest"
    assert "status=aborted" in (root / "DONE").read_text(encoding="utf-8")
    calls = kv_calls(work_tmp)
    assert not [line for line in calls if " start " in line or line.startswith("run_eval")]
    assert not [line for line in calls if "set-environment" in line]


def test_run_fix_compare_refuses_to_run_with_a_leftover_kv_override(work_tmp):
    env = build_fix_stub_env(work_tmp)
    (work_tmp / "state" / "env-STRATA_EXTRA_ARGS").write_text("--kv fp16", encoding="utf-8")
    completed = run_fix_stubbed(env)
    assert completed.returncode == 1 and "STRATA_EXTRA_ARGS が残っている" in completed.stdout
    root = work_tmp / "results" / "fixtest"
    assert "status=aborted" in (root / "DONE").read_text(encoding="utf-8")
    calls = kv_calls(work_tmp)
    assert not [line for line in calls if " start " in line or line.startswith("run_eval")]
    assert not [line for line in calls if "set-environment" in line]       # 外すのは利用者。このスクリプトは環境を変えない
    assert (work_tmp / "state" / "env-STRATA_EXTRA_ARGS").exists()
    assert not (root / "budget24k-ja").exists()                            # 基準も写さない
