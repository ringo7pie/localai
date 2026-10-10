"""コーディング問題の隠しテストを、答えのコードに対して 1 問ぶん動かす。

evallib/sandbox.py が `python3 -I -S -B harness.py <tests.py> <solution.py>` で起動する（作業ディレクトリは
work/ の下、資源の上限は起動側の preexec で掛ける）。結果は標準出力に 1 行 1 JSON で書く:

  {"cases": ["case_a", ...]}                 テストの一覧（答えを読み込む前に出す）
  {"import_error": "..."}                    答えの読み込みに失敗したとき
  {"case": "case_a", "ok": true, "error": null, "seconds": 0.01}
  {"done": true}

途中で落とされても（CPU 時間・メモリの上限）、出せた行までは起動側が拾う。

ネットとプロセスの遮断は擬似的なもの（AppArmor の制限で unshare / bwrap が使えないため）:
- 禁止モジュールの import を sys.meta_path で拒む
- open と os のプロセス・削除系の関数を差し替える
本物の隔離ではない。相手が悪意のないモデルの答えである前提で、事故（うっかりの通信・書き込み）を防ぐ。
"""

import builtins
import importlib.util
import io
import json
import os
import signal
import sys
import time

# 起動側（evallib/sandbox.py の DENIED_MODULES）と同じ一覧
DENIED_MODULES = frozenset({
    "socket", "_socket", "ssl", "_ssl", "subprocess", "_posixsubprocess", "urllib", "http", "ftplib",
    "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "socketserver", "asyncio", "ctypes", "_ctypes",
    "multiprocessing", "_multiprocessing", "pty", "requests",
})
# os の中で、プロセスを作る・外へ書く・消す関数。呼ぶと PermissionError にする
DENIED_OS_FUNCTIONS = (
    "system", "popen", "fork", "forkpty", "execv", "execve", "execl", "execle", "execlp", "execlpe", "execvp",
    "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "posix_spawn", "posix_spawnp", "kill", "killpg", "remove", "unlink", "rmdir", "removedirs", "rename",
    "renames", "replace", "truncate", "chmod", "chown", "symlink", "link", "mkdir", "makedirs",
)
# 1 ケースの時間上限（秒）。全体の上限（10 秒）は起動側が掛ける
CASE_TIMEOUT_S = 3.0

REAL_STDOUT = sys.stdout


def emit(record):
    REAL_STDOUT.write(json.dumps(record, ensure_ascii=False) + "\n")
    REAL_STDOUT.flush()


class CaseTimeout(BaseException):
    """1 ケースの時間切れ。答えのコードが Exception を広く捕まえても抜けられるよう BaseException にする。"""


class Checks:
    """tests.py が使う判定の補助。失敗は AssertionError で知らせる。"""

    @staticmethod
    def _short(value):
        text = repr(value)
        return text if len(text) <= 200 else text[:200] + "…"

    def eq(self, actual, expected):
        if actual != expected:
            raise AssertionError(f"expected {self._short(expected)}, got {self._short(actual)}")

    def close(self, actual, expected, tolerance=1e-9):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise AssertionError(f"expected a number close to {expected!r}, got {self._short(actual)}")
        if abs(actual - expected) > tolerance:
            raise AssertionError(f"expected {expected!r}, got {actual!r}")

    def raises(self, exception_type, function, *args):
        try:
            result = function(*args)
        except exception_type:
            return
        except CaseTimeout:
            raise
        except Exception as exc:  # 違う種類の例外は不合格
            raise AssertionError(
                f"{function.__name__}{self._short(args)}: expected {exception_type.__name__}, "
                f"got {type(exc).__name__}: {exc}"
            ) from None
        raise AssertionError(
            f"{function.__name__}{self._short(args)}: expected {exception_type.__name__}, "
            f"returned {self._short(result)}"
        )


class DenyImports:
    """禁止モジュールの import を拒む meta path finder。"""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in DENIED_MODULES:
            raise ImportError(f"import of {fullname!r} is not allowed in the sandbox")
        return None


class NullWriter(io.TextIOBase):
    """答えのコードの print を捨てる（結果の行と混ざらないように）。"""

    def write(self, text):
        return len(text)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def install_guards():
    for name in list(sys.modules):
        if name.split(".")[0] in DENIED_MODULES:
            del sys.modules[name]
    sys.meta_path.insert(0, DenyImports())

    def denied(*_args, **_kwargs):
        raise PermissionError("this operation is not allowed in the sandbox")

    builtins.open = denied
    io.open = denied
    for name in DENIED_OS_FUNCTIONS:
        if hasattr(os, name):
            setattr(os, name, denied)


def on_alarm(_signum, _frame):
    raise CaseTimeout()


def main(argv):
    tests_path, solution_path = argv[1], argv[2]
    tests = load_module("hidden_tests", tests_path)
    cases = list(tests.CASES)
    emit({"cases": [case.__name__ for case in cases]})

    install_guards()
    sys.stdout = NullWriter()
    sys.stdin = io.StringIO("")
    signal.signal(signal.SIGALRM, on_alarm)
    try:
        signal.setitimer(signal.ITIMER_REAL, CASE_TIMEOUT_S * 2)
        solution = load_module("solution", solution_path)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException as exc:  # 構文の誤り・import の拒否・読み込み時の時間切れなど
        signal.setitimer(signal.ITIMER_REAL, 0)
        emit({"import_error": f"{type(exc).__name__}: {exc}"[:500]})
        emit({"done": True})
        return 0

    checks = Checks()
    for case in cases:
        started = time.perf_counter()
        error = None
        try:
            signal.setitimer(signal.ITIMER_REAL, CASE_TIMEOUT_S)
            case(solution, checks)
        except CaseTimeout:
            error = f"timeout: {CASE_TIMEOUT_S} 秒を超えた"
        except RecursionError as exc:
            error = f"RecursionError: {exc}"[:500]
        except BaseException as exc:  # SystemExit も不合格として拾う
            error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        emit({"case": case.__name__, "ok": error is None, "error": error,
              "seconds": round(time.perf_counter() - started, 3)})
    emit({"done": True})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
