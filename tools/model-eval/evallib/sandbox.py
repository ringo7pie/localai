"""コーディング問題の採点: 答えからコードを取り出し、静的に走査し、隠しテストを別プロセスで動かす。

実行の形（計画の方針 3）:
- `python3 -I -S -B suites/coding/harness.py <tests.py> <solution.py>` を work/ の下で起動する。/tmp は使わない。
- 資源の上限: 全体 10 秒（壁時計）、CPU 10 秒、アドレス空間 2 GiB、書けるファイル 1 MiB、子プロセスを作らない。
- 禁止モジュールの import は、静的な走査（実行前）と harness の meta path（実行中）の両方で拒む。
  静的な走査で違反が見つかったら実行せずに 0 点にする。

ネットの遮断は擬似的（AppArmor の制限で unshare -rn / bwrap が使えない）。README の「サンドボックス」を参照。
"""

from __future__ import annotations

import ast
import json
import os
import re
import resource
import subprocess
import time
from pathlib import Path
from typing import Any

# 採点に使う Python。ツール本体と同じく、システムの python3（3.12）に固定する
SANDBOX_PYTHON = "/usr/bin/python3"
HARNESS = Path(__file__).resolve().parent.parent / "suites" / "coding" / "harness.py"

WALL_TIMEOUT_S = 10
CPU_LIMIT_S = 10
# 2026-10-18 に 1 GiB から 2 GiB にした。512 MiB のスタックのスレッドで深い再帰を動かす答えが、1 GiB では
# malloc の arena の予約と配置の乱数しだいで「can't start new thread」になり、同じ答えの点が採点のたびに揺れた
# （20 回中 5 回落ちた。2 GiB では 20 回とも同じ）
ADDRESS_SPACE_BYTES = 2 << 30
FILE_SIZE_BYTES = 1 << 20

# harness.py の DENIED_MODULES と同じ一覧（tests/test_units.py で一致を確かめる）
DENIED_MODULES = frozenset({
    "socket", "_socket", "ssl", "_ssl", "subprocess", "_posixsubprocess", "urllib", "http", "ftplib",
    "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "socketserver", "asyncio", "ctypes", "_ctypes",
    "multiprocessing", "_multiprocessing", "pty", "requests",
})
# 静的な走査で違反とする呼び出し（属性の連なりで比べる）
DENIED_CALLS = frozenset({
    "os.system", "os.popen", "os.fork", "os.forkpty", "os.kill", "os.killpg", "os.remove", "os.unlink",
    "os.rmdir", "os.removedirs", "os.rename", "os.replace", "os.posix_spawn", "os.posix_spawnp",
    "shutil.rmtree", "shutil.move",
})
DENIED_CALL_PREFIXES = ("os.exec", "os.spawn")
# 違反ではないが記録しておく呼び出し（ファイルや標準入力。実行中は harness が拒む）
WARN_CALLS = frozenset({"open", "input", "io.open", "breakpoint"})

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+.-]*)[^\n]*\n(.*?)(?:\n[ \t]*```|\Z)", re.DOTALL)
_PYTHON_TAGS = {"python", "py", "python3", "py3"}


def extract_code(text: str) -> tuple[str | None, str]:
    """答えの本文からコードを取り出す。戻り値は (コード, 取り出し方)。

    取り出し方: 最後の ```python ブロック → 最後の ``` ブロック → `def` を含む本文全体 → 無し。
    閉じていない最後のブロック（生成の上限で切れた場合）も、本文の終わりまでをブロックとして扱う。
    """

    blocks = [(match.group(1).lower(), match.group(2)) for match in _FENCE.finditer(text or "")]
    python_blocks = [body for tag, body in blocks if tag in _PYTHON_TAGS]
    if python_blocks:
        return python_blocks[-1], "python_block"
    if blocks:
        return blocks[-1][1], "any_block"
    if text and re.search(r"^\s*def\s", text, re.MULTILINE):
        return text, "def_body"
    return None, "none"


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def static_scan(code: str, forbidden_calls: tuple[str, ...] = ()) -> dict[str, Any]:
    """禁止 import と危険な呼び出しを探す。戻り値は {"violations": [...], "warnings": [...], "syntax_error": str|None}。

    forbidden_calls は問題ごとの禁止（C5 の eval / exec / compile）。名前でも属性でも（builtins.eval）見つける。
    """

    violations: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"violations": [], "warnings": [], "syntax_error": f"{exc.msg} (line {exc.lineno})"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in DENIED_MODULES:
                    violations.append(f"import {alias.name}")
                elif alias.name.split(".")[0] in forbidden_calls:
                    # 問題ごとに禁止したモジュール（C4 の json、C5 の re）。import json as j の形も見つける
                    violations.append(f"import {alias.name} (この問題では禁止)")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in DENIED_MODULES:
                violations.append(f"from {node.module} import ...")
            elif module in forbidden_calls:
                violations.append(f"from {node.module} import ... (この問題では禁止)")
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                if dotted in DENIED_CALLS or dotted.startswith(DENIED_CALL_PREFIXES):
                    violations.append(f"from {node.module} import {alias.name}")
                if alias.name in forbidden_calls and module == "builtins":
                    violations.append(f"from builtins import {alias.name}")
        elif isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name is None:
                continue
            short = name.split(".")[-1]
            if name in DENIED_CALLS or name.startswith(DENIED_CALL_PREFIXES):
                violations.append(f"call {name}")
            elif name in ("__import__", "importlib.import_module"):
                first = node.args[0] if node.args else None
                if not isinstance(first, ast.Constant) or str(first.value).split(".")[0] in DENIED_MODULES:
                    violations.append(f"call {name}")
                elif str(first.value).split(".")[0] in forbidden_calls:
                    violations.append(f"call {name} (この問題では禁止)")
            elif forbidden_calls and (name in forbidden_calls or (name.startswith("builtins.") and short in forbidden_calls)):
                violations.append(f"call {name} (この問題では禁止)")
            elif name in WARN_CALLS:
                warnings.append(f"call {name}")
        elif isinstance(node, ast.Name) and forbidden_calls and node.id in forbidden_calls and isinstance(node.ctx, ast.Load):
            # eval を変数に入れて呼ぶ形（f = eval）も禁止に数える。呼び出しとして既に数えたものとは重複してよい
            violations.append(f"name {node.id} (この問題では禁止)")
    # 同じ違反の重複を除く（順番は保つ）
    return {"violations": list(dict.fromkeys(violations)), "warnings": list(dict.fromkeys(warnings)),
            "syntax_error": None}


def read_forbidden_calls(tests_path: Path) -> tuple[str, ...]:
    """tests.py の FORBIDDEN_CALLS を、import せずに読む（ast.literal_eval）。"""

    tree = ast.parse(tests_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "FORBIDDEN_CALLS"
                                                for target in node.targets):
            return tuple(ast.literal_eval(node.value))
    return ()


def _limit_resources() -> None:
    """子プロセスの中（exec の直前）で資源の上限を掛ける。"""

    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_S, CPU_LIMIT_S + 1))
    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_BYTES, FILE_SIZE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # RLIMIT_NPROC は掛けない（2026-10-18 に外した）。0 にするとスレッドも作れず、深い再帰のために大きなスタックの
    # スレッドで動かす答え（問題文では禁じていない）が全部落ちた。子プロセスは静的な走査（subprocess・multiprocessing
    # などの import）と、harness.py の実行時の差し替え（os.fork・os.posix_spawn など）で止める
    os.setsid()


def run_hidden_tests(code: str, tests_path: Path, work_dir: Path) -> dict[str, Any]:
    """答えのコードを work_dir/solution.py に書き、harness で隠しテストを動かす。"""

    # 子プロセスの cwd は work_dir になるので、相対パスで渡されても絶対パスに直しておく
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    solution_path = work_dir / "solution.py"
    solution_path.write_text(code, encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(work_dir), "TMPDIR": str(work_dir)}
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [SANDBOX_PYTHON, "-I", "-S", "-B", str(HARNESS), str(tests_path.resolve()), str(solution_path)],
            cwd=work_dir, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=WALL_TIMEOUT_S,
            preexec_fn=_limit_resources, check=False,
        )
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr, returncode = exc.stdout or b"", exc.stderr or b"", None
    elapsed = time.monotonic() - started

    case_names: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    import_error = None
    finished = False
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "cases" in record:
            case_names = list(record["cases"])
        elif "import_error" in record:
            import_error = record["import_error"]
        elif "case" in record:
            results[record["case"]] = record
        elif record.get("done"):
            finished = True
    killed_reason = None
    if not finished:
        killed_reason = "wall_timeout" if timed_out else f"killed (returncode {returncode})"
    cases = []
    for name in case_names:
        if name in results:
            cases.append({"name": name, "ok": bool(results[name].get("ok")), "error": results[name].get("error")})
        else:
            cases.append({"name": name, "ok": False,
                          "error": import_error or f"not run: {killed_reason or 'unknown'}"})
    passed = sum(1 for case in cases if case["ok"])
    total = len(case_names)
    return {
        "passed": passed,
        "total": total,
        "cases": cases,
        "import_error": import_error,
        "finished": finished,
        "killed_reason": killed_reason,
        "returncode": returncode,
        "seconds": round(elapsed, 2),
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-800:],
    }


def grade_coding(content: str, item_dir: Path, work_dir: Path) -> dict[str, Any]:
    """1 問の答えを採点する。点数は合格したケースの割合（部分点）。"""

    tests_path = item_dir / "tests.py"
    code, extract = extract_code(content)
    grade: dict[str, Any] = {"kind": "coding", "extract": extract, "score": 0.0, "all_passed": False,
                             "passed": 0, "total": None, "violations": [], "warnings": []}
    if code is None or not code.strip():
        grade["no_answer"] = True
        grade["reason"] = "コードが無い"
        return grade
    scan = static_scan(code, read_forbidden_calls(tests_path))
    grade["violations"] = scan["violations"]
    grade["warnings"] = scan["warnings"]
    grade["syntax_error"] = scan["syntax_error"]
    if scan["violations"]:
        grade["reason"] = "禁止の import / 呼び出しがあるため実行せず 0 点"
        return grade
    outcome = run_hidden_tests(code, tests_path, work_dir)
    grade.update({key: outcome[key] for key in ("passed", "total", "cases", "import_error", "finished",
                                                "killed_reason", "returncode", "seconds", "stderr_tail")})
    total = outcome["total"] or 0
    grade["score"] = round(outcome["passed"] / total, 4) if total else 0.0
    grade["all_passed"] = bool(total) and outcome["passed"] == total
    if not total:
        grade["reason"] = "テストを読み込めなかった（harness の異常）"
    return grade
