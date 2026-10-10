"""追加の 3 試験の採点器（標準ライブラリのみ）。各問の answer.json の kind で分ける。

- inst（日本語の指示に従う力）: answer.json の checks を 1 つずつ確かめ、満たした割合を点数にする。
- needle（長い資料からの検索）: 答えの前後の飾り（空白・かぎかっこ・引用符・** ・末尾の句点）だけを外し、
  合言葉と完全に一致したら 1 点。
- json（構造化出力）: 本文を JSON として読み（全体 → ```json ブロック → 最初の { から最後の } の順に試す）、
  6 項目の一致率を点数にする。文字列は NFKC で正規化して前後の空白を除いて比べ、整数・真偽値は型も見る。

どの採点も本文（content）だけを見る。thinking は見ない。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

_LATIN = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")
_DIGIT = re.compile(r"[0-9０-９]")
_BULLET = re.compile(r"^- \S")
# 行頭の箇条書きの記号や番号（inst3 の「付けない」の判定）
_LIST_MARK = re.compile(r"^\s*(?:[-*・•●◦▪+]|[0-9０-９]+[.)．、）]|[（(][0-9０-９]+[)）]|[①-⑳])")


def _lines(content: str) -> list[str]:
    """空の行を除いた行の一覧。行末の空白は落とす（行頭は落とさない。箇条書きの判定に使うため）。"""

    return [line.rstrip() for line in (content or "").splitlines() if line.strip()]


def _check_inst(check: dict[str, Any], lines: list[str], content: str) -> bool:
    kind = check["type"]
    bullets = [line for line in lines if _BULLET.match(line)]
    if kind == "bullet_count":
        return len(bullets) == check["count"]
    if kind == "max_line_chars":
        return bool(lines) and all(len(line) <= check["limit"] for line in lines)
    if kind == "bullet_endings":
        return bool(bullets) and all(line.endswith(tuple(check["endings"])) for line in bullets)
    if kind == "line_endings":
        return bool(lines) and all(line.endswith(tuple(check["endings"])) for line in lines)
    if kind == "last_line_equals":
        return bool(lines) and lines[-1].strip() == check["text"]
    if kind == "first_line_equals":
        return bool(lines) and lines[0].strip() == check["text"]
    if kind == "no_latin":
        return bool(lines) and not _LATIN.search(content)
    if kind == "no_digits":
        return bool(lines) and not _DIGIT.search(content)
    if kind == "must_include":
        return all(word in content for word in check["words"])
    if kind == "each_line_includes":
        return bool(lines) and all(check["word"] in line for line in lines)
    if kind == "bullet_block":
        start = check["start_line"] - 1
        block = lines[start:start + check["count"]]
        return (len(block) == check["count"] and all(_BULLET.match(line) for line in block)
                and len(bullets) == check["count"])
    if kind == "line_count_plain":
        return len(lines) == check["count"] and not any(_LIST_MARK.match(line) for line in lines)
    raise ValueError(f"unknown check type: {kind}")


def grade_inst(content: str, answer: dict[str, Any]) -> dict[str, Any]:
    lines = _lines(content)
    results = [{"id": check["id"], "label": check["label"], "ok": _check_inst(check, lines, content or "")}
               for check in answer["checks"]]
    passed = sum(1 for result in results if result["ok"])
    return {"kind": "inst", "score": round(passed / len(results), 4), "passed": passed, "total": len(results),
            "all_passed": passed == len(results), "checks": results}


def normalize_needle_answer(content: str) -> str:
    """答えの飾りだけを外す。中身の言い換えは許さない（完全一致の採点）。"""

    lines = _lines(content)
    text = lines[-1].strip() if len(lines) == 1 else (content or "").strip()
    previous = None
    while previous != text:
        previous = text
        text = text.strip().strip("*").strip()
        for opening, closing in (("「", "」"), ("『", "』"), ('"', '"'), ("'", "'"), ("“", "”"), ("`", "`")):
            if text.startswith(opening) and text.endswith(closing) and len(text) >= 2:
                text = text[len(opening):len(text) - len(closing)]
        text = text.rstrip("。.")
    return text


def grade_needle(content: str, answer: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_needle_answer(content)
    exact = normalized == answer["answer"]
    return {"kind": "needle", "score": 1.0 if exact else 0.0, "all_passed": exact, "normalized": normalized[:200],
            "expected": answer["answer"], "contains": answer["answer"] in (content or ""),
            "depth": answer.get("depth")}


def parse_json_answer(content: str) -> tuple[Any, str]:
    """本文から JSON を読む。戻り値は (値, 読み方)。読めなければ (None, "unparsable")。"""

    text = (content or "").strip()
    try:
        return json.loads(text), "strict"
    except json.JSONDecodeError:
        pass
    blocks = re.findall(r"```[ \t]*(?:json|JSON)?[^\n]*\n(.*?)\n?[ \t]*```", text, re.DOTALL)
    for block in reversed(blocks):
        try:
            return json.loads(block), "fenced"
        except json.JSONDecodeError:
            continue
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1]), "embedded"
        except json.JSONDecodeError:
            pass
    return None, "unparsable"


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if isinstance(expected, int):
        return isinstance(actual, int) and not isinstance(actual, bool) and actual == expected
    if isinstance(expected, str):
        return isinstance(actual, str) and \
            unicodedata.normalize("NFKC", actual).strip() == unicodedata.normalize("NFKC", expected).strip()
    return actual == expected


def grade_json(content: str, answer: dict[str, Any]) -> dict[str, Any]:
    expected = answer["expected"]
    value, mode = parse_json_answer(content)
    if not isinstance(value, dict):
        return {"kind": "json", "score": 0.0, "all_passed": False, "parse_mode": mode,
                "reason": "JSON オブジェクトとして読めない", "fields": {}}
    fields = {key: {"ok": _same_value(value.get(key), want), "got": value.get(key)} for key, want in expected.items()}
    matched = sum(1 for field in fields.values() if field["ok"])
    return {"kind": "json", "score": round(matched / len(expected), 4), "all_passed": matched == len(expected),
            "parse_mode": mode, "matched": matched, "total": len(expected), "fields": fields,
            "extra_keys": sorted(set(value) - set(expected))}


def grade_extra(content: str, item_dir: Path) -> dict[str, Any]:
    """1 問の答えを採点する。本文が空なら答えなしとして 0 点。"""

    answer = json.loads((item_dir / "answer.json").read_text(encoding="utf-8"))
    if not (content or "").strip():
        return {"kind": answer["kind"], "score": 0.0, "all_passed": False, "no_answer": True, "reason": "本文が無い"}
    if answer["kind"] == "inst":
        return grade_inst(content, answer)
    if answer["kind"] == "needle":
        return grade_needle(content, answer)
    if answer["kind"] == "json":
        return grade_json(content, answer)
    raise ValueError(f"unknown kind: {answer['kind']}")
