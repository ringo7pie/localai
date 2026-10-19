"""数学の採点器（標準ライブラリのみ）。本文（content）の「答え(a): <値>」の行を小問ごとに拾い、answer.json の値と比べる。

- 行は `答え(a): ...`・`答え（a）：...`・`答え a: ...` などを受け付ける。同じ小問が何度あれば最後の行を使う。
- 値は小数か、許可した記号だけの式（+ - * / ** と括弧、pi・e、sqrt・acos・asin・atan・arccos・arcsin・arctan・
  log・ln・exp・cos・sin・tan）。π・√・×・·・^・−・全角の文字、よくある LaTeX（\\frac{}{}・\\sqrt{}・\\pi・\\cdot・
  \\left・\\right・\\arccos・\\arctan）、数と文字の間の省略された掛け算（2pi、3sqrt(2)、2(1+x)）も読む。
- 「=」や「≈」で区切られていれば最後の部分を読み、読めなければ最初の部分を読む。
- ast で許可したノードだけを評価する（関数呼び出しは上の名前だけ、べき指数の絶対値は 12 以下）。
- 相対誤差が rel_tol（小問ごと、既定 1e-5。有効数字 6 桁に正しく丸めた値は必ず入る）以内なら正解。点数は正解の小問の割合。thinking は見ない。
"""

from __future__ import annotations

import ast
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_REL_TOL = 1e-5
ANSWER_LINE = re.compile(r"答え\s*[\(（]?\s*([a-zA-Zａ-ｚ])\s*[\)）]?\s*[:：]\s*(.+)$")
FUNCTIONS = {
    "sqrt": math.sqrt, "acos": math.acos, "asin": math.asin, "atan": math.atan, "arccos": math.acos,
    "arcsin": math.asin, "arctan": math.atan, "log": math.log, "ln": math.log, "exp": math.exp,
    "cos": math.cos, "sin": math.sin, "tan": math.tan,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
MAX_EXPONENT = 12


def _latex_to_plain(text: str) -> str:
    text = text.replace("\\left", "").replace("\\right", "").replace("\\,", " ").replace("\\!", "")
    text = text.replace("\\cdot", "*").replace("\\times", "*").replace("\\pi", "pi")
    for name in ("arccos", "arcsin", "arctan", "sqrt", "cos", "sin", "tan", "ln", "log", "exp"):
        text = text.replace("\\" + name, name)
    # sqrt{x} → sqrt(x)、\frac{a}{b} → ((a)/(b))。内側から外すため繰り返す
    frac = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
    root = re.compile(r"sqrt\s*\{([^{}]*)\}")
    for _ in range(12):
        new = frac.sub(r"((\1)/(\2))", root.sub(r"sqrt(\1)", text))
        if new == text:
            break
        text = new
    return text.replace("{", "(").replace("}", ")")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip()
    text = text.strip("`$ ").rstrip("。.、,；;")
    text = _latex_to_plain(text)
    text = (text.replace("π", "pi").replace("×", "*").replace("·", "*").replace("⋅", "*").replace("−", "-")
            .replace("–", "-").replace("^", "**").replace("√", "sqrt"))
    # sqrt2 / sqrt 2.5 → sqrt(2) / sqrt(2.5)
    text = re.sub(r"sqrt\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", text)
    # 省略された掛け算: 数のあとの文字・括弧、閉じ括弧のあとの数・文字・括弧
    text = re.sub(r"(\d)\s*(?=(?![eE][+-]?\d)[A-Za-z(])", r"\1*", text)
    text = re.sub(r"\)\s*(?=[\dA-Za-z(])", ")*", text)
    # 名前と名前の間の空白（pi r など）は掛け算にしない（読めない式として扱う）
    return text


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in CONSTANTS:
        return CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if abs(right) > MAX_EXPONENT:
            raise ValueError("exponent too large")
        return left ** right
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS
            and len(node.args) == 1 and not node.keywords):
        return FUNCTIONS[node.func.id](_eval(node.args[0]))
    raise ValueError(f"使えない式: {ast.dump(node)[:80]}")


def evaluate(text: str) -> float | None:
    """値の文字列を数にする。読めなければ None。"""

    segments = [segment for segment in re.split(r"[=≈≒]", unicodedata.normalize("NFKC", text)) if segment.strip()]
    if not segments:
        return None
    for candidate in (segments[-1], segments[0]):
        try:
            value = _eval(ast.parse(normalize(candidate), mode="eval"))
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError, RecursionError):
            continue
        if isinstance(value, complex) or not math.isfinite(value):
            continue
        return value
    return None


def find_answers(content: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in (content or "").splitlines():
        cleaned = unicodedata.normalize("NFKC", line).strip().lstrip("-*#> ").replace("**", "")
        match = ANSWER_LINE.search(cleaned)
        if match:
            found[match.group(1).lower()] = match.group(2).strip()
    return found


def grade_math(content: str, item_dir: Path) -> dict[str, Any]:
    answer = json.loads((item_dir / "answer.json").read_text(encoding="utf-8"))
    found = find_answers(content)
    parts = []
    for part in answer["parts"]:
        key = part["key"]
        text = found.get(key)
        value = evaluate(text) if text is not None else None
        rel_tol = float(part.get("rel_tol", DEFAULT_REL_TOL))
        expected = float(part["value"])
        ok = value is not None and abs(value - expected) <= rel_tol * max(abs(expected), 1e-12)
        parts.append({"key": key, "text": text, "value": value, "expected": expected, "ok": ok,
                      "rel_error": (abs(value - expected) / max(abs(expected), 1e-12)) if value is not None else None})
    correct = sum(1 for part in parts if part["ok"])
    grade: dict[str, Any] = {"kind": "math", "score": round(correct / len(parts), 4), "all_passed": correct == len(parts),
                             "passed": correct, "total": len(parts), "parts": parts}
    if not found:
        grade["no_answer"] = True
        grade["reason"] = "答えの行が無い"
    return grade
