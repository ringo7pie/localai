"""パス・試験の一覧・問題文の組み立て・記録の読み書き（run_eval.py / summarize.py / build_report.py が共有する）。"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterator

TOOL_DIR = Path(__file__).resolve().parent.parent
SUITES_DIR = TOOL_DIR / "suites"
RESULTS_ROOT = TOOL_DIR / "results"
WORK_DIR = TOOL_DIR / "work"
REPO_DIR = TOOL_DIR.parent.parent

# 評価の日付。run_local.sh も同じ値を渡す（日をまたいでも結果の置き場が割れないよう固定する）
DEFAULT_DATE = "2026-10-08"

CODING_ITEMS = ("c1", "c2", "c3", "c4", "c5", "c6")
EXTRA_KINDS = {
    "inst": ("inst1", "inst2", "inst3"),
    "needle": ("needle1", "needle2", "needle3"),
    "json": ("json1", "json2", "json3"),
}
EXTRA_ITEMS = tuple(item for items in EXTRA_KINDS.values() for item in items)
SUITE_ITEMS = {"coding": CODING_ITEMS, "extra": EXTRA_ITEMS}
EXTRA_KIND_LABELS = {"inst": "日本語の指示に従う", "needle": "長い資料からの検索", "json": "JSON の構造化出力"}

# 試験ごとの上限（計画の方針 2）。Ollama の num_predict = Strata の max_tokens
SUITE_LIMITS = {
    "coding": {"max_tokens": 32768, "reasoning_budget_tokens": 24576, "request_timeout_s": 40 * 60},
    "extra": {"max_tokens": 8192, "reasoning_budget_tokens": 6144, "request_timeout_s": 20 * 60},
}
# 何も届かないまま、この秒数が過ぎたら打ち切る（stall）
STALL_TIMEOUT_S = 300
# 1 つのモデルの累計時間（壁時計、ロードを除く）の上限。超えたら残りを skipped_time_budget にする
MODEL_TIME_BUDGET_S = 100 * 60

# 記録の status。FINAL は再開のときに飛ばす（--retry-errors は error だけ、--retry-skipped は skipped だけ流し直す）
STATUS_OK = "ok"
STATUS_LENGTH = "length"
STATUS_TIMEOUT = "timeout"
STATUS_STALL = "stall"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped_time_budget"
# 思考の途中で停止トークンが出て、本文が空のまま終わった（finish が stop・本文が空・思考あり）。error ではない
STATUS_EOS_IN_THINKING = "eos_in_thinking"
FINAL_STATUSES = {STATUS_OK, STATUS_LENGTH, STATUS_TIMEOUT, STATUS_STALL, STATUS_SKIPPED, STATUS_EOS_IN_THINKING}
# 問題文の言語。ja は PREAMBLE.md と prompt.md、en は PREAMBLE.en.md と prompt.en.md（コーディングだけ）
PROMPT_LANGS = ("ja", "en")
DEFAULT_PROMPT_LANG = "ja"

# Claude に渡すときだけ足す一文（計画の方針 5。メインが Agent の指示文の最後に付ける）
CLAUDE_SUFFIX = "ツールやコードの実行は使わず、答えだけを返してください。"


def item_dir(suite: str, item: str) -> Path:
    return SUITES_DIR / suite / item


def build_prompt(suite: str, item: str, lang: str = DEFAULT_PROMPT_LANG) -> str:
    """ローカルのモデルに user メッセージとして送る全文。system メッセージは使わない。

    - coding: suites/coding/PREAMBLE.md の全文 + 空行 + suites/coding/<item>/prompt.md の全文
      （lang="en" なら PREAMBLE.en.md と prompt.en.md。日本語版の忠実な英訳）
    - extra:  suites/extra/<item>/prompt.md の全文（前置きなし。英語版は無い）
    前後の空白は落としてからつなぐ。
    """

    if lang not in PROMPT_LANGS:
        raise ValueError(f"unknown prompt lang: {lang}（候補: {', '.join(PROMPT_LANGS)}）")
    if lang == "en" and suite != "coding":
        raise ValueError(f"{suite} には英語版の問題文が無い（英語版は coding だけ）")
    suffix = ".en.md" if lang == "en" else ".md"
    body_path = item_dir(suite, item) / f"prompt{suffix}"
    if not body_path.is_file():
        raise FileNotFoundError(f"{lang} の問題文が無い: {body_path}")
    body = body_path.read_text(encoding="utf-8").strip()
    if suite == "coding":
        preamble_path = SUITES_DIR / "coding" / f"PREAMBLE{suffix}"
        if not preamble_path.is_file():
            raise FileNotFoundError(f"{lang} の共通の指示が無い: {preamble_path}")
        preamble = preamble_path.read_text(encoding="utf-8").strip()
        return f"{preamble}\n\n{body}"
    if suite == "extra":
        return body
    raise ValueError(f"unknown suite: {suite}")


def results_dir_for(date: str | None = None) -> Path:
    return RESULTS_ROOT / (date or DEFAULT_DATE)


def local_record_path(results_dir: Path, slug: str, suite: str, item: str, run: int = 1) -> Path:
    return results_dir / "local" / slug / suite / f"{item}-run{run}.json"


def attempt_record_path(path: Path, attempt: int) -> Path:
    """やり直した問の 1 回目の記録の置き場（c4-run1.json → c4-run1.attempt1.json）。"""

    return path.with_name(f"{path.stem}.attempt{attempt}{path.suffix}")


def is_attempt_record(path: Path) -> bool:
    return ".attempt" in path.stem


def record_is_eos_in_thinking(record: dict[str, Any]) -> bool:
    """思考中に停止トークンが出て本文が空だった記録か。

    新しい記録は status が eos_in_thinking。この状態を足す前の記録は status が ok のまま、
    finish が stop・本文が空・思考ありで残っているので、同じものとして数える。
    """

    status = record.get("status")
    if status == STATUS_EOS_IN_THINKING:
        return True
    return (status == STATUS_OK and record.get("finish") == "stop" and not (record.get("content") or "").strip()
            and bool((record.get("thinking") or "").strip()))


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    """同じディレクトリの一時ファイルに書いてから置き換える（途中で止まっても壊れた JSON を残さない）。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def iter_local_records(results_dir: Path, slug: str) -> Iterator[tuple[Path, dict[str, Any]]]:
    base = results_dir / "local" / slug
    if not base.is_dir():
        return
    for path in sorted(base.glob("*/*-run*.json")):
        if is_attempt_record(path):
            continue  # やり直した問の 1 回目（.attemptN.json）は、問の数にも採点にも入れない
        yield path, read_json(path)


def iter_attempt_records(results_dir: Path, slug: str) -> Iterator[tuple[Path, dict[str, Any]]]:
    """やり直した問の 1 回目の記録（累計時間に足すため）。"""

    base = results_dir / "local" / slug
    if not base.is_dir():
        return
    for path in sorted(base.glob("*/*-run*.attempt*.json")):
        yield path, read_json(path)


def iter_claude_records(results_dir: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    base = results_dir / "claude"
    if not base.is_dir():
        return
    for path in sorted(base.glob("*/*/*-run*.json")):
        yield path, read_json(path)
