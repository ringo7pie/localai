#!/usr/bin/env python3
"""条件を変えて流した C4・C5 の記録を集めて比べる（Strata 3 種）。KV キャッシュの型の比べ（kv）と、コーディング性能の調査（fix）。

  cond_compare.py summarize [--root results/2026-10-09-fix] [--conditions a,b,c,...] [--labels 表示名,表示名,...]   # <root>/summary.json
  cond_compare.py report [--root ...] [--findings <root>/findings.json] [--settings-table JSON] [--out Documents/Strata_コーディング性能の調査_2026-10-09.html]
  cond_compare.py server-info --root R --cond ARM --target KEY --unit UNIT --engine-log LOG ...   # run_fix_compare.sh・run_kv_compare.sh が使う
  cond_compare.py journal-counts --root R --slug SLUG --unit UNIT --since ISO [--until ISO] [--arm ARM]   # journal の行を数えて書く
  cond_compare.py pending --root R --cond ARM --rep 2 --slug SLUG   # まだ流していない問の数
  cond_compare.py copy-baseline --root R --arm budget24k-ja --slug SLUG ...   # 基準（上限 24,576）の既存の記録を写す
  cond_compare.py check-kv / copy-int8-rep1 ...                     # run_kv_compare.sh が使う（KV の型の比べ）

kv_compare.py は同じ機能を KV の比べの既定（--kind kv、results/2026-10-09-kv）で呼ぶ薄い入口。

記録の置き場は <root>/<条件>/rep<1〜3>/local/<slug>/coding/<問>-run1.json（run_eval.py run --results-dir の下）。
<root>/<条件>/server-<slug>.json は条件ごと（条件 × モデル）の起動の記録、<root>/journal-counts-<slug>.json は
モデルの unit の journal の行数（run_fix_compare.sh が書く）。思考中の停止トークンでやり直した問の 1 回目は
<問>-run1.attempt1.json（集計では 2 回目の記録に first_attempt_status として入る）。

条件（fix の既定）: budget24k-ja（基準。思考の上限 24,576・生成 32,768・日本語。既存の記録の写し）、nobudget-ja（上限なし・生成 65,536・日本語）、
nobudget-en（上限なし・生成 65,536・英語の問題文）、low-ja（思考の強さ low・上限なし・生成 32,768）、low-65k-ja（low・上限なし・生成 65,536）。
--conditions は任意の数で、先頭が基準。ほかの条件は全部を基準と比べる（平均の差と、点の判定）。
results/<root>/excluded.json（{"key": "理由"}）のモデルは集計・表・図から外し、注意の節に理由を出す。
記録が 1 本も無い条件 × モデルは「流していない」扱い（足りない記録に数えない）。一部だけあるときは、足りない回を警告する。

終わり方（1 回ごとに 1 つに分類する。classify_end）: self_finished（思考を自分で終え、答えを書き切った）、budget_cut（思考が予算で打ち切られ、答えを書いた）、
answer_truncated（答えを書いている途中で生成の上限）、no_answer_at_limit（生成の上限まで考え続けて答えなし）、repeat_stop（同じ 1 トークンの繰り返しで打ち切り）、
eos_in_thinking（思考の途中で停止トークン）、error、missing。

点の判定（kv も fix も同じ）: 条件の最小 > 基準の最大 →「上がった」、条件の最大 < 基準の最小 →「下がった」、それ以外 →「差は判定できない」、
どちらかに記録が無ければ「比べられない」。平均は使わない（3 回では偶然と区別できない差は判定しない）。

HTML は 1 ファイルで完結する（外部の資源を読まない）。色・書式・図の部品は build_report.py のものを再利用する。
標準ライブラリのみ。/usr/bin/python3 で動く。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import build_report  # noqa: E402
import run_eval  # noqa: E402
import summarize  # noqa: E402
import targets as targets_module  # noqa: E402
from evallib import common, scoring  # noqa: E402

KV_TYPES = ("int8", "fp16")
REPS = (1, 2, 3)
ITEMS = ("c4", "c5")
# 流す順（速い順）と、表・図に出す短い名前
MODEL_KEYS = ("strata-flash-coder:IQ1_M", "strata-official:IQ3_XXS", "strata-flash-next:IQ3_S")
SHORT_NAMES = {"strata-flash-coder:IQ1_M": "Coder IQ1_M", "strata-official:IQ3_XXS": "公式 IQ3_XXS",
               "strata-flash-next:IQ3_S": "RVN IQ3_S"}
KV_TAG = "2026-10-09-kv"
KV_ROOT = common.RESULTS_ROOT / KV_TAG
KV_OUT = common.REPO_DIR / "Documents" / "Strata_KVキャッシュ比較_2026-10-09.html"
# コーディング性能の調査（fix）の置き場と HTML
FIX_TAG = "2026-10-09-fix"
FIX_ROOT = common.RESULTS_ROOT / FIX_TAG
FIX_OUT = common.REPO_DIR / "Documents" / "Strata_コーディング性能の調査_2026-10-09.html"
KIND_KV, KIND_FIX = "kv", "fix"
# fix の条件（腕）。名前は results/<RUN_TAG>/ の下のディレクトリ名。先頭が基準で、ほかの条件は全部を基準と比べる
COND_BASELINE = "budget24k-ja"
COND_NOBUDGET_JA = "nobudget-ja"
COND_NOBUDGET_EN = "nobudget-en"
COND_LOW_JA = "low-ja"
COND_LOW_65K_JA = "low-65k-ja"
FIX_CONDITIONS = (COND_BASELINE, COND_NOBUDGET_JA, COND_NOBUDGET_EN, COND_LOW_JA, COND_LOW_65K_JA)
FIX_LABELS = {COND_BASELINE: "思考最大・上限 24,576（最初の評価）", COND_NOBUDGET_JA: "思考最大・上限なし",
              COND_NOBUDGET_EN: "思考最大・上限なし・英語", COND_LOW_JA: "low・上限なし（生成 32,768）",
              COND_LOW_65K_JA: "low・上限なし（生成 65,536）"}
# 各条件の記録が送ったはずの上限と言語。違う記録があれば summary の warnings に出す
FIX_EXPECTED = {COND_BASELINE: {"max_tokens": 32768, "reasoning_budget_tokens": 24576, "prompt_lang": "ja"},
                COND_NOBUDGET_JA: {"max_tokens": 65536, "reasoning_budget_tokens": 0, "prompt_lang": "ja"},
                COND_NOBUDGET_EN: {"max_tokens": 65536, "reasoning_budget_tokens": 0, "prompt_lang": "en"},
                COND_LOW_JA: {"max_tokens": 32768, "reasoning_budget_tokens": 0, "prompt_lang": "ja"},
                COND_LOW_65K_JA: {"max_tokens": 65536, "reasoning_budget_tokens": 0, "prompt_lang": "ja"}}
# 各条件の記録が送ったはずの思考の強さ（request.reasoning_effort）。記録に無ければ確かめない
FIX_EXPECTED_EFFORT = {COND_BASELINE: "high", COND_NOBUDGET_JA: "high", COND_NOBUDGET_EN: "high",
                       COND_LOW_JA: "low", COND_LOW_65K_JA: "low"}
# 一部の回だけ流す計画の（モデル, 条件）: 計画に無い回の記録が無いのは足りない記録に数えない（表では「計画外」）。
# ここに無い組は REPS の全部を流す計画。記録が 1 本も無い（モデル, 条件）は、この表に関わらず「流していない」扱い
FIX_PLANNED_REPS = {(MODEL_KEYS[1], COND_NOBUDGET_EN): (1, 2), (MODEL_KEYS[2], COND_NOBUDGET_EN): ()}
# 基準の写し元（rep1 は 2026-10-08 の記録、rep2・rep3 は KV の比べの int8 の記録）と source.json の説明
BASELINE_NOTE = "既存の記録の写し。思考の上限 24,576・生成 32,768・日本語（この調査のために流したものではない）"
BASELINE_REP1_SOURCE = common.RESULTS_ROOT / "2026-10-08"
BASELINE_REPS_SOURCE = common.RESULTS_ROOT / KV_TAG / "int8"
# int8 の rep1 に写す元（RVN と公式は 2026-10-08 に計測。Coder は 2026-10-09 に計測したが、記録は同じ results/2026-10-08/ にある）
SOURCE_DIR = common.RESULTS_ROOT / "2026-10-08"
SOURCE_NOTE = "既存の記録の写し。RVN と公式は 2026-10-08、Coder は 2026-10-09 に計測"
# 条件（モデル × 条件）の起動の結果。ok 以外は server-<slug>.json の status に書く
SERVER_STATUSES = ("ok", "start_failed", "kv_mismatch", "server_died")
# journal の行の数え方（Strata の journal に出る文。ループの回復・思考の予算・生成の上限）
JOURNAL_PATTERNS = {"repeated_reasoning": "repeated reasoning detected",
                    "thinking_budget_reached": "thinking budget reached",
                    "max_tokens_reached": "the reply reached max tokens"}
# 計画に書いた文脈長（起動行の --max-context が読めればそちらを使う）。2026-10-18 に 131072 から広げた
# （tools/strata/stra/config.py の DEFAULT_MAX_CONTEXT と同じ値）
DEFAULT_CONTEXT = 262144

# 点の判定の結果（文字）
JUDGE_UP = "上がった"
JUDGE_DOWN = "下がった"
JUDGE_UNDECIDED = "差は判定できない"
JUDGE_INCOMPARABLE = "比べられない"
JUDGE_SYMBOLS = {JUDGE_UP: ("▲", build_report.COLOR_OK), JUDGE_DOWN: ("▼", build_report.COLOR_NG),
                 JUDGE_UNDECIDED: ("＝", build_report.COLOR_NA), JUDGE_INCOMPARABLE: ("？", build_report.COLOR_NA)}
# 終わり方（1 回の記録を 1 つに分類する。classify_end）。並びは棒グラフの積み上げ順（答えあり → 答えなし → エラー → 記録なし）
END_SELF_FINISHED, END_BUDGET_CUT, END_ANSWER_TRUNCATED = "self_finished", "budget_cut", "answer_truncated"
END_NO_ANSWER_AT_LIMIT, END_REPEAT_STOP, END_EOS_IN_THINKING = "no_answer_at_limit", "repeat_stop", "eos_in_thinking"
END_ERROR, END_MISSING = "error", "missing"
END_STATES = (END_SELF_FINISHED, END_BUDGET_CUT, END_ANSWER_TRUNCATED, END_NO_ANSWER_AT_LIMIT, END_REPEAT_STOP,
              END_EOS_IN_THINKING, END_ERROR, END_MISSING)
# 表の列・凡例の名前と説明（色だけでなく文字で示す）
END_LABELS = {END_SELF_FINISHED: "自分で終えた", END_BUDGET_CUT: "予算で打切", END_ANSWER_TRUNCATED: "答えの途中で上限",
              END_NO_ANSWER_AT_LIMIT: "上限まで考えて答えなし", END_REPEAT_STOP: "繰り返しで停止",
              END_EOS_IN_THINKING: "思考中停止", END_ERROR: "エラー", END_MISSING: "記録なし"}
END_NOTES = {END_SELF_FINISHED: "思考を自分で終え、答えを書き切った",
             END_BUDGET_CUT: "思考が予算で打ち切られ（Strata が締めの文を差し込み）、答えを書いた",
             END_ANSWER_TRUNCATED: "思考は終えたが、答えを書いている途中で生成の上限に届いた",
             END_NO_ANSWER_AT_LIMIT: "生成の上限まで考え続けて、答えが無い",
             END_REPEAT_STOP: "同じ 1 トークンの繰り返しで Strata が打ち切った（生成の上限には届いていない）",
             END_EOS_IN_THINKING: "思考の途中で停止トークンが出て、本文が空のまま終わった",
             END_ERROR: "サーバーのエラー・時間切れ・無応答など", END_MISSING: "記録が無い・飛ばした"}
# 点の表の各回の小さい文字
END_SHORT = {END_SELF_FINISHED: "自己終了", END_BUDGET_CUT: "予算打切", END_ANSWER_TRUNCATED: "答え途中で上限",
             END_NO_ANSWER_AT_LIMIT: "上限まで答えなし", END_REPEAT_STOP: "繰り返し停止",
             END_EOS_IN_THINKING: "思考中停止", END_ERROR: "エラー", END_MISSING: "記録なし"}
# 記録に limits も request.max_tokens も無い古い記録の生成の上限
OLD_RECORD_MAX_TOKENS = 32768
# 終わり方の色と模様。答えなしの 3 種は同じ灰で、模様（無地 / 45° / 135°）と文字で区別する。色は build_report.py の定数
# （正解の緑・答えなしの灰・誤りの赤）に琥珀を足した。琥珀の対比は 3:1 未満なので、棒の中の数字・凡例の文字・表で補う
END_COLOR_AMBER = "#c58b12"
END_STYLE = {END_SELF_FINISHED: (build_report.COLOR_OK, None), END_BUDGET_CUT: (build_report.COLOR_OK, "45"),
             END_ANSWER_TRUNCATED: (END_COLOR_AMBER, None), END_NO_ANSWER_AT_LIMIT: (build_report.COLOR_NA, None),
             END_REPEAT_STOP: (build_report.COLOR_NA, "45"), END_EOS_IN_THINKING: (build_report.COLOR_NA, "135"),
             END_ERROR: (build_report.COLOR_NG, None), END_MISSING: (None, None)}
COMBINED = "all"                     # C4・C5 をまとめた行の名前（comparisons の scope）

# 点の判定の式（fix の HTML にも出す。kv は JUDGE_FORMULA）
FIX_FORMULA = [
    "条件の最小 > 基準の最大 → 「上がった」（▲）",
    "条件の最大 < 基準の最小 → 「下がった」（▼）",
    "それ以外 → 「差は判定できない」（＝。3 回では偶然と区別できない）",
    "基準か条件に記録が 1 つも無いとき → 「比べられない」（？）",
]
JUDGE_FORMULA = [
    "fp16 の最小 > int8 の最大 → 「上がった」",
    "fp16 の最大 < int8 の最小 → 「下がった」",
    "それ以外 → 「差は判定できない」（3 回では偶然と区別できない）",
    "どちらかの条件に記録が 1 つも無いとき → 「比べられない」",
]

# 色（build_report.py の定数を使う）。int8 と fp16 は同じ Strata の紫で、模様（斜線 / 塗り）と文字で区別する
COLOR_STRATA = build_report.FAMILY_COLORS["strata"]
COLOR_STRATA_LIGHT = "#e9e1f6"
HATCH_ID = "kv-hatch"
KV_MARK_TEXT = {"int8": "int8（斜線・白抜きの丸）", "fp16": "fp16（塗りつぶし・塗りの丸）"}

# engine のログの行の読み取り
ENGINE_START_MARK = "engine started:"
SLOTS_PATTERN = re.compile(r"pre-filled (\d+) of (\d+) slots")
HIT_MARK = "decode expert cache hit rate:"
HIT_PATTERN = re.compile(r"decode expert cache hit rate: ([\d.]+)% \((\d+) hits / (\d+) lookups\)")
KV_ARG_PATTERN = re.compile(r"(?<!\S)--kv(?:\s+|=)(\S+)")
CONTEXT_ARG_PATTERN = re.compile(r"(?<!\S)--max-context(?:\s+|=)(\d+)")
CGROUP_ROOT = Path("/sys/fs/cgroup")


# ------------------------------------------------------------------------------------------------ 点の判定


def judge_scores(int8_scores: list[float], fp16_scores: list[float]) -> str:
    """int8 と fp16 の点の一覧から判定する（最小・最大だけを比べる。平均は使わない）。"""

    if not int8_scores or not fp16_scores:
        return JUDGE_INCOMPARABLE
    if min(fp16_scores) > max(int8_scores):
        return JUDGE_UP
    if max(fp16_scores) < min(int8_scores):
        return JUDGE_DOWN
    return JUDGE_UNDECIDED


# ------------------------------------------------------------------------------------------------ engine のログ


def engine_kv(started_line: str | None) -> str | None:
    """起動行の --kv の値。engine は後ろの指定で上書きする（STRATA_EXTRA_ARGS は --kv int8 の後ろに足される）ので最後のもの。"""

    if not started_line:
        return None
    matches = KV_ARG_PATTERN.findall(started_line)
    return matches[-1] if matches else None


def engine_context(started_line: str | None) -> int | None:
    if not started_line:
        return None
    matches = CONTEXT_ARG_PATTERN.findall(started_line)
    return int(matches[-1]) if matches else None


def kv_matches(started_line: str | None, expected: str) -> bool:
    """起動行の実効の --kv が期待どおりか。fp16 なら `--kv fp16` が最後、int8 なら `--kv int8` が最後（fp16 は無い）。"""

    return engine_kv(started_line) == expected


def parse_engine_log(text: str, after_line: int = 0, hits_after_line: int = 0) -> dict[str, Any]:
    """engine のログから、最後の起動行と、それより後ろの枠・キャッシュの命中率の行を取る。

    after_line: 起動の前に数えておいた行数。それより後ろの行だけを見る（起動に失敗して新しい起動行が無いとき、
    前の日の起動行を読み違えないため）。ログが作り直されて行数が減っていたら先頭から見る。
    枠は起動行の後ろにある最初の `pre-filled N of M slots`。
    hits_after_line: 命中率の行を、ログの先頭から数えてこの行数より後ろのものだけにする（1 回の起動で複数の条件を流すとき、
    条件の始めに数えた行数を渡して、その条件の分だけを取る）。0 なら起動行より後ろの全部。
    """

    all_lines = text.splitlines()
    if after_line > len(all_lines):
        after_line = 0
    lines = all_lines[after_line:]
    start_index = None
    for index, line in enumerate(lines):
        if ENGINE_START_MARK in line:
            start_index = index
    if start_index is None:
        return {"started_line": None, "kv": None, "slots": None, "cache_hit_lines": []}
    started_line = lines[start_index].strip()
    tail = lines[start_index + 1:]
    slots = None
    for line in tail:
        found = SLOTS_PATTERN.search(line)
        if found:
            slots = {"filled": int(found.group(1)), "total": int(found.group(2))}
            break
    # tail[0] はログ全体で after_line + start_index + 1 行目（0 始まりの添え字）
    first_tail_index = after_line + start_index + 1
    return {"started_line": started_line, "kv": engine_kv(started_line), "slots": slots,
            "cache_hit_lines": [line.strip() for offset, line in enumerate(tail)
                                if HIT_MARK in line and first_tail_index + offset >= hits_after_line]}


def cache_hit_stats(lines: list[str]) -> dict[str, Any]:
    """命中率の行を足し合わせる（ヒット数の合計 ÷ 照会数の合計）。読める行が無ければ None。"""

    hits = lookups = used = 0
    for line in lines:
        found = HIT_PATTERN.search(line)
        if found:
            hits += int(found.group(2))
            lookups += int(found.group(3))
            used += 1
    return {"pct": hits / lookups * 100 if lookups else None, "lookups": lookups, "lines": used}


# ------------------------------------------------------------------------------------------------ 起動の記録（server-<slug>.json）


def read_int_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def default_cgroup_of(unit: str) -> str:
    try:
        completed = subprocess.run(["systemctl", "--user", "show", unit, "-p", "ControlGroup", "--value"],
                                   capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def read_cgroup_memory(unit: str, *, cgroup_of=default_cgroup_of,
                       cgroup_root: Path = CGROUP_ROOT) -> tuple[int | None, int | None]:
    """unit の cgroup の memory.peak と memory.current（バイト）。unit が止まっていたり読めなければ None。"""

    group = cgroup_of(unit)
    if not group:
        return None, None
    base = cgroup_root / group.lstrip("/")
    return read_int_file(base / "memory.peak"), read_int_file(base / "memory.current")


def read_vram_used_mib() -> int | None:
    try:
        completed = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=20, check=False)
        return int(completed.stdout.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def build_server_info(*, kv: str, target: str, unit: str, slug: str, status: str, start_s: float | None,
                      engine: dict[str, Any], vram_used_mib: int | None, vram_before_mib: int | None,
                      memory_peak_bytes: int | None, memory_current_bytes: int | None,
                      reps: list[int]) -> dict[str, Any]:
    """kv は条件の名前（KV の比べでは int8 / fp16、fix では budget24k-ja などの腕）。KV の型のときだけ "kv" の鍵も書く。"""

    info = {"condition": kv, "target": target, "unit": unit, "slug": slug, "status": status, "reps": reps,
            "start_s": start_s, "engine_started_line": engine.get("started_line"), "slots": engine.get("slots"),
            "cache_hit_lines": engine.get("cache_hit_lines") or [], "vram_before_mib": vram_before_mib,
            "vram_used_mib": vram_used_mib, "memory_peak_bytes": memory_peak_bytes,
            "memory_current_bytes": memory_current_bytes, "written_at": common.now_iso()}
    if kv in KV_TYPES:
        info["kv"] = kv
    return info


def server_info_path(root: Path, kv: str, slug: str) -> Path:
    return root / kv / f"server-{slug}.json"


def cmd_server_info(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    target = targets_module.get(args.target)
    log_path = Path(args.engine_log)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    engine = parse_engine_log(text, args.after_line, args.hits_after_line)
    peak, current = read_cgroup_memory(args.unit)
    reps = [int(rep) for rep in args.reps.replace(",", " ").split()]
    info = build_server_info(kv=args.cond, target=target.key, unit=args.unit, slug=args.slug or target.slug,
                             status=args.status, start_s=args.start_s, engine=engine,
                             vram_used_mib=read_vram_used_mib(), vram_before_mib=args.vram_before,
                             memory_peak_bytes=peak, memory_current_bytes=current, reps=reps)
    path = server_info_path(root, args.cond, args.slug or target.slug)
    common.write_json(path, info)
    print(f"{path} を書いた（条件 {args.cond}、status={args.status}、枠 {info['slots']}、命中率の行 {len(info['cache_hit_lines'])} 本）")
    return 0


def cmd_check_kv(args: argparse.Namespace) -> int:
    """終了コード 0: 一致、1: 不一致（起動行が無い場合を含む）。"""

    log_path = Path(args.log)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    engine = parse_engine_log(text, args.after_line)
    if engine["started_line"] is None:
        print(f"{log_path} に新しい起動行（{ENGINE_START_MARK}）が無い")
        return 1
    actual = engine["kv"]
    ok = kv_matches(engine["started_line"], args.kv)
    print(f"起動行の --kv は {actual}（期待 {args.kv}）: {'一致' if ok else '不一致'}。枠 {engine['slots']}")
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ 記録の置き場


def rep_dir(root: Path, kv: str, rep: int) -> Path:
    return root / kv / f"rep{rep}"


def record_path(root: Path, kv: str, rep: int, slug: str, item: str) -> Path:
    return common.local_record_path(rep_dir(root, kv, rep), slug, "coding", item)


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(common.REPO_DIR))
    except ValueError:
        return str(path)


def count_pending(root: Path, kv: str, rep: int, slug: str, *, retry_errors: bool = False) -> int:
    """まだ流していない問（C4・C5）の数。数え方は run_eval.py run と同じ規則（should_run）。"""

    args = SimpleNamespace(redo=False, retry_errors=retry_errors, retry_skipped=False)
    return sum(1 for item in ITEMS if run_eval.should_run(record_path(root, kv, rep, slug, item), args))


def copy_int8_rep1(root: Path, source_dir: Path, slugs: list[str], *, dry_run: bool = False) -> list[str]:
    """既存の int8 の記録（C4・C5）を <root>/int8/rep1/ に写し、source.json に元のパスを書く。既にある記録は写さない。"""

    target_dir = rep_dir(root, "int8", 1)
    source_path = target_dir / "source.json"
    previous = common.read_json(source_path) if source_path.exists() else {}
    files = {entry["to"]: entry for entry in previous.get("files", [])}
    actions: list[str] = []
    for slug in slugs:
        for item in ITEMS:
            source = common.local_record_path(source_dir, slug, "coding", item)
            destination = common.local_record_path(target_dir, slug, "coding", item)
            label = f"{slug}/{item}"
            if destination.exists():
                actions.append(f"{label}: 既にある。写さない")
                files.setdefault(display_path(destination), {"slug": slug, "item": item, "from": display_path(source),
                                                              "to": display_path(destination), "note": "写す前からあった"})
            elif source.exists():
                actions.append(f"{label}: {display_path(source)} → {display_path(destination)}")
                if not dry_run:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    files[display_path(destination)] = {"slug": slug, "item": item, "from": display_path(source),
                                                        "to": display_path(destination), "copied_at": common.now_iso()}
            else:
                actions.append(f"{label}: 元の記録が無い（{display_path(source)}）")
    if not dry_run and files:
        common.write_json(source_path, {"note": SOURCE_NOTE, "source_dir": display_path(source_dir),
                                        "files": sorted(files.values(), key=lambda entry: entry["to"])})
    return actions


def baseline_source(rep1_source: Path, reps_source: Path, rep: int, slug: str, item: str) -> Path:
    """基準の rep の写し元。rep1 は <rep1_source>/local/…（2026-10-08）、rep2・rep3 は <reps_source>/rep<N>/local/…（KV の比べの int8）。"""

    base = rep1_source if rep == 1 else reps_source / f"rep{rep}"
    return common.local_record_path(base, slug, "coding", item)


def copy_baseline(root: Path, arm: str, rep1_source: Path, reps_source: Path, slugs: list[str], *,
                  dry_run: bool = False) -> list[str]:
    """基準（思考の上限 24,576・生成 32,768・日本語）の既存の記録を <root>/<arm>/rep<1〜3>/ に写し、<arm>/source.json に元のパスを書く。

    既にある記録は写さない（上書きしない）。写し元が無い記録は actions に書く。
    """

    arm_dir = root / arm
    source_path = arm_dir / "source.json"
    previous = common.read_json(source_path) if source_path.exists() else {}
    files = {entry["to"]: entry for entry in previous.get("files", [])}
    actions: list[str] = []
    for slug in slugs:
        for rep in REPS:
            for item in ITEMS:
                source = baseline_source(rep1_source, reps_source, rep, slug, item)
                destination = common.local_record_path(rep_dir(root, arm, rep), slug, "coding", item)
                label = f"{slug}/rep{rep}/{item}"
                if destination.exists():
                    actions.append(f"{label}: 既にある。写さない")
                    files.setdefault(display_path(destination), {"slug": slug, "rep": rep, "item": item,
                                                                  "from": display_path(source),
                                                                  "to": display_path(destination), "note": "写す前からあった"})
                elif source.exists():
                    actions.append(f"{label}: {display_path(source)} → {display_path(destination)}")
                    if not dry_run:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                        files[display_path(destination)] = {"slug": slug, "rep": rep, "item": item,
                                                            "from": display_path(source),
                                                            "to": display_path(destination), "copied_at": common.now_iso()}
                else:
                    actions.append(f"{label}: 元の記録が無い（{display_path(source)}）")
    if not dry_run and files:
        common.write_json(source_path, {"note": BASELINE_NOTE, "arm": arm,
                                        "limits": {"reasoning_budget_tokens": 24576, "max_tokens": 32768,
                                                   "prompt_lang": "ja"},
                                        "rep1_source": display_path(rep1_source), "reps_source": display_path(reps_source),
                                        "files": sorted(files.values(), key=lambda entry: entry["to"])})
    return actions


def count_journal_lines(text: str) -> dict[str, int]:
    """journal の本文から、JOURNAL_PATTERNS の文を含む行の数を数える。"""

    counts = {name: 0 for name in JOURNAL_PATTERNS}
    lines = text.splitlines()
    for line in lines:
        for name, needle in JOURNAL_PATTERNS.items():
            if needle in line:
                counts[name] += 1
    counts["lines"] = len(lines)
    return counts


def read_journal(unit: str, since: str, until: str | None = None) -> str:
    """journalctl --user -u UNIT --since SINCE [--until UNTIL] -o short-iso の出力。読めなければ空文字（呼び出し側が記録する）。"""

    command = ["journalctl", "--user", "-u", unit, "--since", since, "-o", "short-iso", "--no-pager"]
    if until:
        command += ["--until", until]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    if completed.returncode != 0:
        raise OSError(f"journalctl が終了コード {completed.returncode}: {completed.stderr.strip()[:200]}")
    return completed.stdout


def cmd_journal_counts(args: argparse.Namespace) -> int:
    """モデルの unit の journal を数えて <root>/journal-counts-<slug>.json に書く。--arm 付きはその条件の分、無しは起動からの全部。"""

    root = Path(args.root).resolve()
    if args.journal_file:
        text = Path(args.journal_file).read_text(encoding="utf-8", errors="replace")
    else:
        try:
            text = read_journal(args.unit, args.since, args.until)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"journal を読めない: {exc}", file=sys.stderr)
            return 1
    entry = {"since": args.since, "until": args.until, "counts": count_journal_lines(text)}
    path = journal_counts_path(root, args.slug)
    data = common.read_json(path) if path.exists() else {"slug": args.slug, "unit": args.unit, "arms": {}}
    data["unit"] = args.unit
    data["patterns"] = dict(JOURNAL_PATTERNS)
    if args.arm:
        data.setdefault("arms", {})[args.arm] = entry
    else:
        data["total"] = entry
    data["written_at"] = common.now_iso()
    common.write_json(path, data)
    print(f"{path} を書いた（{args.arm or 'total'}: {entry['counts']}）")
    return 0


# ------------------------------------------------------------------------------------------------ 集計


def record_limits(record: dict[str, Any]) -> dict[str, Any]:
    """記録が実際に送った上限と問題文の言語。新しい記録は limits と prompt_lang、古い記録は request から読む（言語は ja）。"""

    limits = record.get("limits")
    if isinstance(limits, dict):
        found = {"max_tokens": limits.get("max_tokens"), "reasoning_budget_tokens": limits.get("reasoning_budget_tokens")}
    else:
        request = record.get("request") or {}
        found = {"max_tokens": request.get("max_tokens"),
                 "reasoning_budget_tokens": request.get("reasoning_budget_tokens")}
    found["prompt_lang"] = record.get("prompt_lang") or "ja"
    return found


def record_max_tokens(record: dict[str, Any]) -> int:
    """記録が送った生成の上限（limits.max_tokens か request.max_tokens）。無い古い記録は 32,768 とみなす。"""

    value = record_limits(record).get("max_tokens")
    return value if isinstance(value, int) and value > 0 else OLD_RECORD_MAX_TOKENS


def classify_end(record: dict[str, Any] | None) -> dict[str, Any]:
    """1 回の記録の終わり方を 1 つに分類する（END_STATES）。{"end": 名前, "truncated": bool}。

    - 記録が無い・時間の上限で飛ばした: missing
    - 思考の途中で停止トークン（status eos_in_thinking。古い記録の finish stop・本文が空・思考ありも）: eos_in_thinking
    - status length（生成の上限に届いた。completion_tokens が上限以上。値が無ければ届いたとみなす）:
        本文あり → 思考に予算の打ち切り文があれば budget_cut（truncated: true）、なければ answer_truncated
        本文なし → no_answer_at_limit
      completion_tokens が上限未満なのに length は、同じ 1 トークンの繰り返しで Strata が打ち切った repeat_stop
    - status ok: 思考に予算の打ち切り文があれば budget_cut、なければ self_finished（本文が空の異常な記録は error）
    - それ以外（error・timeout・stall）: error
    """

    if record is None or record.get("status") == common.STATUS_SKIPPED:
        return {"end": END_MISSING, "truncated": False}
    if common.record_is_eos_in_thinking(record):
        return {"end": END_EOS_IN_THINKING, "truncated": False}
    status = record.get("status")
    has_content = bool((record.get("content") or "").strip())
    budget_cut = summarize.REASONING_WRAP_UP_MARK in (record.get("thinking") or "")
    if status == common.STATUS_LENGTH:
        tokens = record.get("completion_tokens")
        at_limit = not isinstance(tokens, (int, float)) or tokens >= record_max_tokens(record)
        if not at_limit:
            return {"end": END_REPEAT_STOP, "truncated": False}
        if not has_content:
            return {"end": END_NO_ANSWER_AT_LIMIT, "truncated": False}
        if budget_cut:
            return {"end": END_BUDGET_CUT, "truncated": True}
        return {"end": END_ANSWER_TRUNCATED, "truncated": False}
    if status == common.STATUS_OK and has_content:
        return {"end": END_BUDGET_CUT if budget_cut else END_SELF_FINISHED, "truncated": False}
    return {"end": END_ERROR, "truncated": False}


def _run_entry(rep: int, record: dict[str, Any] | None) -> dict[str, Any]:
    """1 回の記録を表に出す形にする。summarize.py の _cell_from_local に、回の番号と記録の有無・やり直し・上限・終わり方・答えの有無を足す。

    has_answer: 本文が空でなく、採点できた回（途中で切れた答えも数える）。end・truncated: classify_end の結果。
    effort: 記録の request.reasoning_effort（思考の強さ。無ければ None）。
    """

    if record is None:
        return {"rep": rep, "cell": summarize.CELL_MISSING, "status": "missing", "score": None, "all_passed": False,
                "time_s": None, "tokens": None, "thinking_tokens_est": None, "tok_s": None, "budget_cut": False,
                "attempts": 0, "first_attempt_status": None, "limits": None, "planned": True,
                "end": END_MISSING, "truncated": False, "has_answer": False, "effort": None}
    entry = summarize._cell_from_local(record)
    entry["rep"] = rep
    entry["attempts"] = int(record.get("attempts") or 1)
    entry["first_attempt_status"] = record.get("first_attempt_status")
    entry["limits"] = record_limits(record)
    ending = classify_end(record)
    entry["end"], entry["truncated"] = ending["end"], ending["truncated"]
    entry["has_answer"] = bool((record.get("content") or "").strip()) and entry["cell"] == summarize.CELL_SCORED
    entry["effort"] = (record.get("request") or {}).get("reasoning_effort")
    if entry["status"] == common.STATUS_OK and common.record_is_eos_in_thinking(record):
        # eos_in_thinking を足す前の記録（status は ok のまま、finish が stop・本文が空・思考あり）も同じ状態に数える
        entry["status"] = common.STATUS_EOS_IN_THINKING
        entry["eos_legacy"] = True
    return entry


def condition_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """1 条件（モデル × 問 × 条件）の 3 回分。記録のある回（飛ばした問を除く）の点を集める。エラーは 0 点に数える。

    n_self_finished: 予算の打ち切り文が無く、status が ok の回（自分で思考を終えて答えを書いた）。
    n_eos: 思考中の停止トークンの回数（やり直した 1 回目も数える）。n_eos_final: 最終の記録が eos_in_thinking の回数。
    n_length: 上限までに答えが無かった回（status length）。n_retried: やり直した（attempt1 がある）回。
    n_answered: 答えが出た回（本文が空でなく採点できた回。途中で切れた答えも数える）。n_truncated: 予算で打ち切られたあとの答えが上限で切れた回。
    ends: 終わり方（END_STATES）ごとの回数。記録の無い回も missing に数えるので、合計は runs の数になる。
    """

    counted = [run for run in runs if run["status"] not in ("missing", common.STATUS_SKIPPED)]
    scores = [float(run["score"] or 0.0) for run in counted]
    return {
        "runs": runs,
        "scores": scores,
        "n_records": len(counted),
        "mean": scoring.mean(scores),
        "min": min(scores) if scores else None,
        "max": max(scores) if scores else None,
        "n_all_passed": sum(1 for run in counted if run.get("all_passed")),
        "tok_s_median": scoring.median(run.get("tok_s") for run in counted),
        "time_s_median": scoring.median(run.get("time_s") for run in counted),
        "tokens_median": scoring.median(run.get("tokens") for run in counted),
        "thinking_tokens_median": scoring.median(run.get("thinking_tokens_est") for run in counted),
        "n_budget_cut": sum(1 for run in counted if run.get("budget_cut")),
        "n_self_finished": sum(1 for run in counted if run["status"] == common.STATUS_OK and not run.get("budget_cut")),
        "n_eos": sum((run.get("first_attempt_status") == common.STATUS_EOS_IN_THINKING)
                     + (run["status"] == common.STATUS_EOS_IN_THINKING) for run in counted),
        "n_eos_final": sum(1 for run in counted if run["status"] == common.STATUS_EOS_IN_THINKING),
        "n_retried": sum(1 for run in counted if (run.get("attempts") or 1) > 1),
        "n_length": sum(1 for run in counted if run["status"] == common.STATUS_LENGTH),
        "n_answered": sum(1 for run in counted if run.get("has_answer")),
        "n_truncated": sum(1 for run in counted if run.get("truncated")),
        "ends": {name: sum(1 for run in runs if run.get("end", END_MISSING) == name) for name in END_STATES},
        "statuses": [run["status"] for run in runs],
    }


def pooled_stats(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    """モデル × 条件で、C4・C5 の全部の回を合わせた中央値（速さの比べに使う）。"""

    runs = [run for condition in conditions for run in condition["runs"]
            if run["status"] not in ("missing", common.STATUS_SKIPPED)]
    return {
        "n_records": len(runs),
        "tok_s_median": scoring.median(run.get("tok_s") for run in runs),
        "time_s_median": scoring.median(run.get("time_s") for run in runs),
        "tokens_median": scoring.median(run.get("tokens") for run in runs),
        "thinking_tokens_median": scoring.median(run.get("thinking_tokens_est") for run in runs),
        "n_budget_cut": sum(1 for run in runs if run.get("budget_cut")),
    }


def load_server(root: Path, kv: str, slug: str) -> dict[str, Any] | None:
    """server-<slug>.json を読み、summary.json に入れる形（枠・命中率・VRAM・RAM・起動秒）にする。無ければ None。"""

    path = server_info_path(root, kv, slug)
    if not path.exists():
        return None
    info = common.read_json(path)
    stats = cache_hit_stats(info.get("cache_hit_lines") or [])
    slots = info.get("slots") or {}
    started = info.get("engine_started_line")
    return {"status": info.get("status"), "reps": info.get("reps"), "start_s": info.get("start_s"),
            "engine_started_line": started, "engine_kv": engine_kv(started), "context": engine_context(started),
            "slots_filled": slots.get("filled"), "slots_total": slots.get("total"),
            "cache_hit_pct": stats["pct"], "cache_hit_lookups": stats["lookups"], "cache_hit_lines": stats["lines"],
            "vram_before_mib": info.get("vram_before_mib"), "vram_used_mib": info.get("vram_used_mib"),
            "memory_peak_bytes": info.get("memory_peak_bytes"),
            "memory_current_bytes": info.get("memory_current_bytes"), "written_at": info.get("written_at")}


def journal_counts_path(root: Path, slug: str) -> Path:
    return root / f"journal-counts-{slug}.json"


def load_journal_counts(root: Path, slug: str) -> dict[str, Any] | None:
    path = journal_counts_path(root, slug)
    return common.read_json(path) if path.exists() else None


def collect_conditions(root: Path, conditions: tuple[str, ...] | list[str], *,
                       planned: dict[tuple[str, str], tuple[int, ...]] | None = None,
                       copied: set[str] | None = None, model_keys: tuple[str, ...] | list[str] = MODEL_KEYS,
                       unrun_ok: bool = False) -> dict[str, Any]:
    """条件 × モデル × 問の記録、モデル × 条件の起動の記録、journal の行数を集める（KV の比べも fix も共通）。

    planned: (モデルの key, 条件) → 流す計画の回。ここに無い組は REPS の全部。計画に無い回が無いのは「足りない記録」に数えない
    （表では「計画外」）。copied: 既存の記録を写しただけの条件（起動していない）。起動の記録が無いのは足りない記録に数えない。
    model_keys: 集めるモデル（fix は excluded.json のモデルを除く）。
    unrun_ok: True なら、記録が 1 本も無い（モデル, 条件）は「流していない」扱い（not_run が True。足りない記録にも数えない）。
    """

    copied = copied or set()

    results: dict[str, dict[str, dict[str, Any]]] = {}
    pooled: dict[str, dict[str, Any]] = {}
    servers: dict[str, dict[str, Any]] = {}
    journals: dict[str, Any] = {}
    not_run: dict[str, dict[str, bool]] = {}
    # （モデルの key, 条件, 文, 流していない組なら除く文か）。起動の失敗は流していない組でも残す
    missing_entries: list[tuple[str, str, str, bool]] = []
    models = []
    for key in model_keys:
        target = targets_module.get(key)
        models.append({"key": key, "label": target.label, "short": SHORT_NAMES.get(key, target.label),
                       "slug": target.slug, "unit": target.unit})
        results[key] = {}
        for item in ITEMS:
            results[key][item] = {}
            for condition in conditions:
                runs = []
                for rep in REPS:
                    path = record_path(root, condition, rep, target.slug, item)
                    record = common.read_json(path) if path.exists() else None
                    entry = _run_entry(rep, record)
                    if record is None:
                        if rep in (planned or {}).get((key, condition), REPS):
                            missing_entries.append((key, condition, f"{target.label} の {item.upper()}（{condition}・rep{rep}）の記録が無い", True))
                        else:
                            entry["planned"] = False
                    runs.append(entry)
                results[key][item][condition] = condition_stats(runs)
        pooled[key], servers[key], not_run[key] = {}, {}, {}
        for condition in conditions:
            pooled[key][condition] = pooled_stats([results[key][item][condition] for item in ITEMS])
            servers[key][condition] = load_server(root, condition, target.slug)
            not_run[key][condition] = unrun_ok and not any(results[key][item][condition]["n_records"] for item in ITEMS)
            server = servers[key][condition]
            if server is None:
                if condition not in copied and (planned or {}).get((key, condition), REPS):
                    missing_entries.append((key, condition, f"{target.label} の起動の記録（{condition}）server-{target.slug}.json が無い", True))
            elif server["status"] != "ok":
                missing_entries.append((key, condition, f"{target.label}（{condition}）の起動の結果: {server['status']}", False))
        journals[key] = load_journal_counts(root, target.slug)
    missing = [line for key, condition, line, droppable in missing_entries if not (droppable and not_run[key][condition])]
    return {"models": models, "results": results, "pooled": pooled, "servers": servers, "journal_counts": journals,
            "not_run": not_run, "missing": missing}


def build_summary(root: Path) -> dict[str, Any]:
    """KV の型の比べ（int8 と fp16）の集計。"""

    collected = collect_conditions(root, KV_TYPES)
    results = collected["results"]
    judgements: dict[str, dict[str, Any]] = {}
    for key in MODEL_KEYS:
        judgements[key] = {}
        for item in ITEMS:
            judgements[key][item] = {
                "label": judge_scores(results[key][item]["int8"]["scores"], results[key][item]["fp16"]["scores"]),
                "int8_range": [results[key][item]["int8"]["min"], results[key][item]["int8"]["max"]],
                "fp16_range": [results[key][item]["fp16"]["min"], results[key][item]["fp16"]["max"]]}
    source_path = rep_dir(root, "int8", 1) / "source.json"
    return {
        "date": root.name,
        "generated_at": common.now_iso(),
        "root": display_path(root),
        "kv_types": list(KV_TYPES),
        "reps": list(REPS),
        "items": list(ITEMS),
        "limits": common.SUITE_LIMITS["coding"],
        "sampling": dict(targets_module.STRATA_SAMPLING),
        "models": collected["models"],
        "results": results,
        "judgements": judgements,
        "pooled": collected["pooled"],
        "servers": collected["servers"],
        "int8_rep1_source": common.read_json(source_path) if source_path.exists() else None,
        "missing": collected["missing"],
    }


# ------------------------------------------------------------------------------------------------ fix の集計


def condition_limits(results: dict[str, Any], condition: str) -> list[dict[str, Any]]:
    """条件の記録が実際に送った上限と言語の一覧（重複を除く）。"""

    seen: list[dict[str, Any]] = []
    for per_item in results.values():
        for item_stats in per_item.values():
            for run in item_stats[condition]["runs"]:
                limits = run.get("limits")
                if limits and limits not in seen:
                    seen.append(limits)
    return seen


def condition_efforts(results: dict[str, Any], condition: str) -> list[str]:
    """条件の記録が送った思考の強さ（request.reasoning_effort）の一覧（重複を除く。記録に無いものは数えない）。"""

    seen: list[str] = []
    for per_item in results.values():
        for item_stats in per_item.values():
            for run in item_stats[condition]["runs"]:
                if run.get("effort") and run["effort"] not in seen:
                    seen.append(run["effort"])
    return seen


def compare_to_baseline(baseline: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    """基準の condition_stats と、ある条件の condition_stats の比べ。平均の差（条件 − 基準）と、点の一覧による判定（judge_scores）。"""

    both = bool(baseline["n_records"] and stats["n_records"])
    return {"label": judge_scores(baseline["scores"], stats["scores"]),
            "baseline_mean": baseline["mean"], "mean": stats["mean"],
            "diff": stats["mean"] - baseline["mean"] if both else None,
            "baseline_range": [baseline["min"], baseline["max"]], "range": [stats["min"], stats["max"]]}


def build_comparisons(results: dict[str, Any], combined: dict[str, Any], model_keys: list[str],
                      conditions: list[str]) -> dict[str, Any]:
    """条件ごと・モデル × 問ごとの基準との比べ。comparisons[モデルの key][問 か "all"][条件]。基準の条件は入れない。"""

    baseline = conditions[0]
    comparisons: dict[str, Any] = {}
    for key in model_keys:
        comparisons[key] = {}
        for item in ITEMS:
            comparisons[key][item] = {name: compare_to_baseline(results[key][item][baseline], results[key][item][name])
                                      for name in conditions[1:]}
        comparisons[key][COMBINED] = {name: compare_to_baseline(combined[key][baseline], combined[key][name])
                                      for name in conditions[1:]}
    return comparisons


def build_fix_summary(root: Path, conditions: list[str] | tuple[str, ...] = FIX_CONDITIONS,
                      labels: dict[str, str] | None = None) -> dict[str, Any]:
    """コーディング性能の調査（fix）の集計。条件 × モデル × 問の統計と、基準との比べ、起動の記録、journal の行数。

    先頭の条件が基準。excluded.json のモデルは集計から外す（理由は summary の excluded）。
    記録が 1 本も無い（モデル, 条件）は not_run（流していない）で、足りない記録に数えない。
    """

    conditions = list(conditions)
    labels = {name: (labels or {}).get(name) or FIX_LABELS.get(name) or name for name in conditions}
    excluded = summarize.read_excluded(root)
    model_keys = [key for key in MODEL_KEYS if key not in excluded]
    copied = {name for name in conditions if (root / name / "source.json").exists()}
    collected = collect_conditions(root, conditions, planned=FIX_PLANNED_REPS, copied=copied, model_keys=model_keys,
                                   unrun_ok=True)
    results = collected["results"]
    combined = {key: {name: condition_stats([run for item in ITEMS for run in results[key][item][name]["runs"]])
                      for name in conditions} for key in model_keys}
    warnings: list[str] = []
    limits_seen = {name: condition_limits(results, name) for name in conditions}
    efforts_seen = {name: condition_efforts(results, name) for name in conditions}
    for name in conditions:
        expected = FIX_EXPECTED.get(name)
        for seen in limits_seen[name]:
            if expected and any(seen.get(field) != value for field, value in expected.items()):
                warnings.append(f"条件 {name} に、期待と違う上限・言語の記録がある: {json.dumps(seen, ensure_ascii=False)}"
                                f"（期待 {json.dumps(expected, ensure_ascii=False)}）")
        expected_effort = FIX_EXPECTED_EFFORT.get(name)
        if expected_effort and any(effort != expected_effort for effort in efforts_seen[name]):
            warnings.append(f"条件 {name} に、期待と違う思考の強さの記録がある: {efforts_seen[name]}（期待 {expected_effort}）")
    sources = {}
    for name in conditions:
        source_path = root / name / "source.json"
        if source_path.exists():
            sources[name] = common.read_json(source_path)
    return {
        "kind": KIND_FIX,
        "date": root.name,
        "generated_at": common.now_iso(),
        "root": display_path(root),
        "conditions": conditions,
        "baseline": conditions[0],
        "labels": labels,
        "reps": list(REPS),
        "items": list(ITEMS),
        "sampling": dict(targets_module.STRATA_SAMPLING),
        "models": collected["models"],
        "excluded": excluded,
        "results": results,
        "combined": combined,
        "comparisons": build_comparisons(results, combined, model_keys, conditions),
        "not_run": collected["not_run"],
        "pooled": collected["pooled"],
        "servers": collected["servers"],
        "journal_counts": collected["journal_counts"],
        "limits_seen": limits_seen,
        "efforts_seen": efforts_seen,
        "sources": sources,
        "planned_reps": {key: {name: list(FIX_PLANNED_REPS.get((key, name), REPS)) for name in conditions}
                         for key in model_keys},
        "warnings": warnings,
        "missing": collected["missing"],
    }


def parse_conditions(conditions_arg: str | None, labels_arg: str | None) -> tuple[list[str], dict[str, str]]:
    """--conditions と --labels を読む。表示名の区切りは「,」だが、数字に挟まれた「,」（24,576 の桁区切り）では割らない。"""

    conditions = [name.strip() for name in conditions_arg.split(",") if name.strip()] if conditions_arg else list(FIX_CONDITIONS)
    if not conditions:
        raise SystemExit("--conditions が空")
    if len(set(conditions)) != len(conditions):
        raise SystemExit(f"--conditions に同じ名前がある: {conditions}")
    labels: dict[str, str] = {}
    if labels_arg:
        # 区切りの「,」だけで割る。数字に挟まれた「,」（24,576 の桁区切り）は表示名の一部として残す
        names = [name.strip() for name in re.split(r"(?<!\d),|,(?!\d)", labels_arg)]
        if len(names) != len(conditions):
            raise SystemExit(f"--labels は --conditions と同じ数（{len(conditions)}）にする: {labels_arg}")
        labels = dict(zip(conditions, names))
    return conditions, labels


def cmd_summarize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.kind == KIND_KV:
        summary = build_summary(root)
    else:
        conditions, labels = parse_conditions(args.conditions, args.labels)
        summary = build_fix_summary(root, conditions, labels)
    out = Path(args.out) if args.out else root / "summary.json"
    common.write_json(out, summary)
    print(f"{out} を書いた。足りない記録 {len(summary['missing'])} 件")
    for line in summary["missing"][:40]:
        print(f"  - {line}")
    for line in summary.get("warnings") or []:
        print(f"  ! {line}")
    return 0


# ------------------------------------------------------------------------------------------------ 速さと資源の比べ


# 速さと資源の表の行。get(pooled, server) は int8 と fp16 それぞれの値。digits は小数の桁、unit は単位
METRICS = (
    {"key": "tok_s", "label": "生成 tok/s（中央値）", "unit": "tok/s", "digits": 1,
     "get": lambda pooled, server: pooled.get("tok_s_median")},
    {"key": "time_s", "label": "1 問の時間（中央値）", "unit": "秒", "digits": 0,
     "get": lambda pooled, server: pooled.get("time_s_median")},
    {"key": "slots", "label": "GPU のエキスパートの枠", "unit": "枠", "digits": 0,
     "get": lambda pooled, server: (server or {}).get("slots_filled")},
    {"key": "hit", "label": "エキスパートのキャッシュ命中率", "unit": "%", "digits": 1, "diff_unit": "pt",
     "get": lambda pooled, server: (server or {}).get("cache_hit_pct")},
    {"key": "vram", "label": "VRAM 使用（実行中）", "unit": "MiB", "digits": 0,
     "get": lambda pooled, server: (server or {}).get("vram_used_mib")},
    {"key": "ram", "label": "RAM（cgroup の memory.peak）", "unit": "GiB", "digits": 2,
     "get": lambda pooled, server: (server or {}).get("memory_peak_bytes") / 1024 ** 3
     if (server or {}).get("memory_peak_bytes") is not None else None},
    {"key": "start_s", "label": "起動にかかった時間", "unit": "秒", "digits": 0,
     "get": lambda pooled, server: (server or {}).get("start_s")},
)


def metric_rows(summary: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """1 モデルの、速さと資源の int8 / fp16 の値・差（fp16 − int8）・比（fp16 ÷ int8）。"""

    rows = []
    for spec in METRICS:
        values = {kv: spec["get"](summary["pooled"][key][kv], summary["servers"][key][kv]) for kv in KV_TYPES}
        both = values["int8"] is not None and values["fp16"] is not None
        rows.append({"key": spec["key"], "label": spec["label"], "unit": spec["unit"], "digits": spec["digits"],
                     "diff_unit": spec.get("diff_unit", spec["unit"]),
                     "int8": values["int8"], "fp16": values["fp16"],
                     "diff": values["fp16"] - values["int8"] if both else None,
                     "ratio": values["fp16"] / values["int8"] if both and values["int8"] else None})
    return rows


# ------------------------------------------------------------------------------------------------ HTML の部品

esc = html.escape

KV_STYLE = """
.judge{display:inline-block;border-radius:4px;color:#fff;font-weight:700;padding:0 8px;line-height:24px;white-space:nowrap}
.swatch-int8{background:repeating-linear-gradient(45deg,#7044bb 0 2px,#e9e1f6 2px 6px);border:1px solid #7044bb;box-sizing:border-box}
.swatch-fp16{background:#7044bb;border:1px solid #7044bb;box-sizing:border-box}
.dot-int8,.dot-fp16{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;
border:2px solid #7044bb;box-sizing:border-box;vertical-align:baseline}
.dot-int8{background:#fcfcfb}.dot-fp16{background:#7044bb}
.state{margin-left:4px;font-size:.78rem;color:var(--text-muted)}
svg .mean{stroke:var(--text-primary);stroke-width:2}
svg .group-label{fill:var(--text-primary);font-weight:600}
code{font-size:.85rem}
"""

HATCH_DEFS = (f'<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
              f'<pattern id="{HATCH_ID}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
              f'<rect width="6" height="6" fill="{COLOR_STRATA_LIGHT}"/>'
              f'<line x1="0" y1="0" x2="0" y2="6" stroke="{COLOR_STRATA}" stroke-width="2.5"/></pattern></defs></svg>')


def kv_legend() -> str:
    """int8 と fp16 の凡例。色は同じ Strata の紫で、模様（斜線 / 塗り）と名前で区別する。"""

    items = (f'<span class="legend-item"><span class="swatch swatch-int8"></span>{esc(KV_MARK_TEXT["int8"])}</span>'
             f'<span class="legend-item"><span class="swatch swatch-fp16"></span>{esc(KV_MARK_TEXT["fp16"])}</span>'
             f'<span class="legend-item"><span class="swatch" style="background:{COLOR_STRATA}"></span>色は Strata の紫</span>')
    return f'<div class="legend" aria-label="KV の型の凡例">{items}</div>'


def fmt_number(value: float | None, digits: int = 1, unit: str = "") -> str:
    return "—" if value is None else f"{value:,.{digits}f}{(' ' + unit) if unit else ''}"


def fmt_signed(value: float | None, digits: int = 1, unit: str = "") -> str:
    return "—" if value is None else f"{value:+,.{digits}f}{(' ' + unit) if unit else ''}"


def fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"×{value:.2f}"


def model_label(model: dict[str, Any]) -> str:
    return (f'<span class="swatch" style="background:{COLOR_STRATA}"></span>{esc(model["short"])}')


def judge_chip(label: str) -> str:
    symbol, color = JUDGE_SYMBOLS[label]
    return f'<span class="judge" style="background:{color}">{symbol} {esc(label)}</span>'


def _nice_ticks(maximum: float, count: int = 5, unit: float = 1.0) -> tuple[float, list[float]]:
    """0 から maximum を超える最小のきりのよい値までの目盛り。unit は目盛りの単位（秒の図なら 60 で、分のきりのよい値になる）。"""

    if maximum <= 0:
        return unit, [0.0, unit]
    scaled = maximum / unit
    raw = scaled / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(factor * magnitude for factor in (1, 2, 2.5, 5, 10) if factor * magnitude >= raw)
    top = math.ceil(scaled / step) * step
    return top * unit, [index * step * unit for index in range(int(round(top / step)) + 1)]


def _bar_fill(row: dict[str, Any]) -> str:
    """棒の塗り。row["style"] が 0 なら斜線、1 なら塗りつぶし、2 なら薄い紫（色は同じ紫）。style が無ければ kv が int8 なら斜線、それ以外は塗りつぶし。"""

    style = row.get("style", 0 if row.get("kv") == "int8" else 1)
    return (f"url(#{HATCH_ID})", COLOR_STRATA, COLOR_STRATA_LIGHT)[style]


def kv_bar_chart(rows: list[dict[str, Any]], *, title: str, value_label, tick_label=None, tick_unit: float = 1.0,
                 label_width: int = 190, plot_width: int = 500) -> str:
    """横棒。rows: {label, kv か style, value, tip, new_group, none_text}。int8 は斜線、fp16 は塗りつぶし（色は同じ紫）。値が None なら「記録なし」（none_text で変える）。

    tick_label: 目盛りの文字（既定は value_label）。tick_unit: 目盛りの単位（秒の図は 60）。
    """

    values = [row["value"] for row in rows if row.get("value") is not None]
    if not values:
        return '<p class="muted">記録がない。</p>'
    tick_label = tick_label or value_label
    top_value, ticks = _nice_ticks(max(values) * 1.05, unit=tick_unit)
    row_height, bar_height, group_gap, top, bottom = 24, 14, 10, 8, 30
    positions, y = [], top
    for row in rows:
        if row.get("new_group") and positions:
            y += group_gap
        positions.append(y)
        y += row_height
    height = int(y + bottom)
    width = label_width + plot_width + 90

    def x_of(value: float) -> float:
        return label_width + value / top_value * plot_width

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="{esc(title)}">']
    for tick in ticks:
        x = x_of(tick)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{y + 2:.1f}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{y + 18:.1f}" text-anchor="middle">{esc(tick_label(tick))}</text>')
    parts.append(f'<line class="axis" x1="{label_width}" y1="{top - 4}" x2="{label_width}" y2="{y + 2:.1f}"/>')
    for row, row_y in zip(rows, positions):
        center = row_y + row_height / 2
        parts.append(f'<text class="label" x="{label_width - 10}" y="{center + 4:.1f}" text-anchor="end">{esc(row["label"])}</text>')
        value = row.get("value")
        if value is None:
            parts.append(f'<text class="muted" x="{label_width + 8}" y="{center + 4:.1f}">{esc(row.get("none_text") or "記録なし")}</text>')
            continue
        bar_width = max(x_of(value) - label_width, 1.5)
        fill = _bar_fill(row)
        parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(row.get("tip") or "")}">'
                     f'<rect class="hit" x="{label_width}" y="{row_y + 1}" width="{plot_width}" height="{row_height - 2}"/>'
                     f'<path d="{build_report._bar_path(label_width, center - bar_height / 2, bar_width, bar_height)}" '
                     f'fill="{fill}" stroke="{COLOR_STRATA}" stroke-width="1.5"/></g>')
        parts.append(f'<text class="value" x="{label_width + bar_width + 6:.1f}" y="{center + 4:.1f}">{esc(value_label(value))}</text>')
    parts.append("</svg>")
    return "".join(parts)


cond_bar_chart = kv_bar_chart       # fix の図でも同じ棒グラフを使う（rows に style を渡す）


def score_dot_chart(summary: dict[str, Any]) -> str:
    """1 回ごとの点を丸で打ち、平均を横線で示す。モデル × 問の 6 組、それぞれ int8（白抜き）と fp16（塗り）を並べる。"""

    models, items = summary["models"], summary["items"]
    group_width, slot_centers, dot_offsets = 165, (40, 120), (-14, 0, 14)
    left, top, plot_height, bottom = 56, 16, 220, 62
    width = left + group_width * len(models) * len(items) + 10
    height = top + plot_height + bottom

    def y_of(value: float) -> float:
        return top + (1 - value) * plot_height

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="1 回ごとの点と平均（モデル × 問 × KV の型）">']
    for value in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line class="grid" x1="{left}" y1="{y_of(value):.1f}" x2="{width - 10}" y2="{y_of(value):.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{y_of(value) + 4:.1f}" text-anchor="end">{value * 100:.0f}%</text>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top - 4}" x2="{left}" y2="{top + plot_height}"/>')
    labels: list[str] = []
    for model_index, model in enumerate(models):
        for item_index, item in enumerate(items):
            group_x = left + (model_index * len(items) + item_index) * group_width
            if item_index == 0 and model_index > 0:
                parts.append(f'<line class="axis" x1="{group_x}" y1="{top - 4}" x2="{group_x}" y2="{height - bottom + 38}"/>')
            labels.append(f'<text class="group-label" x="{group_x + group_width / 2:.1f}" y="{top + plot_height + 38}" '
                          f'text-anchor="middle">{esc(model["short"])} · {esc(item.upper())}</text>')
            for kv, center_offset in zip(KV_TYPES, slot_centers):
                center_x = group_x + center_offset
                condition = summary["results"][model["key"]][item][kv]
                labels.append(f'<text class="tick" x="{center_x}" y="{top + plot_height + 18}" text-anchor="middle">{kv}</text>')
                counted = [run for run in condition["runs"] if run["status"] not in ("missing", common.STATUS_SKIPPED)]
                if not counted:
                    labels.append(f'<text class="muted" x="{center_x}" y="{top + plot_height - 8}" text-anchor="middle">記録なし</text>')
                    continue
                for run in counted:
                    dot_x = center_x + dot_offsets[(run["rep"] - 1) % len(dot_offsets)]
                    main, sub = build_report.cell_texts(run)
                    tip = "\n".join([f"{kv} rep{run['rep']}: {main}" + (f"（{sub}）" if sub else ""),
                                     f"{model['short']} / {item.upper()}",
                                     f"全部合格: {'はい' if run.get('all_passed') else 'いいえ'}"])
                    fill = "var(--surface)" if kv == "int8" else COLOR_STRATA
                    stroke = COLOR_STRATA if kv == "int8" else "var(--surface)"
                    stroke_width = 2.2 if kv == "int8" else 1.5
                    parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(tip)}"><circle class="hit" cx="{dot_x}" '
                                 f'cy="{y_of(run["score"]):.1f}" r="10"/><circle cx="{dot_x}" cy="{y_of(run["score"]):.1f}" r="5.5" '
                                 f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/></g>')
                mean_y = y_of(condition["mean"])
                mean_tip = (f"{kv} の平均: {build_report.fmt_pct(condition['mean'])}\n{model['short']} / {item.upper()}\n"
                            f"最小〜最大: {build_report.fmt_pct(condition['min'])}〜{build_report.fmt_pct(condition['max'])}")
                parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(mean_tip)}"><line class="mean" '
                             f'x1="{center_x - 20}" y1="{mean_y:.1f}" x2="{center_x + 20}" y2="{mean_y:.1f}"/></g>')
                labels.append(f'<text class="value" x="{center_x + 24}" y="{mean_y + 4:.1f}">{build_report.fmt_pct(condition["mean"])}</text>')
    parts.extend(labels)
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------------------------------------ 節


def _run_cell(run: dict[str, Any]) -> str:
    if run["status"] == "missing":
        return '<td class="num muted">記録なし</td>'
    main, sub = build_report.cell_texts(run)
    return f'<td class="num">{esc(main)}' + (f'<span class="state">{esc(sub)}</span>' if sub else "") + "</td>"


def section_conclusion(summary: dict[str, Any], findings: dict[str, Any] | None) -> str:
    rows = []
    for model in summary["models"]:
        for item in summary["items"]:
            judgement = summary["judgements"][model["key"]][item]
            ranges = []
            for kv in KV_TYPES:
                low, high = judgement[f"{kv}_range"]
                ranges.append("—" if low is None else f"{build_report.fmt_pct(low)}〜{build_report.fmt_pct(high)}")
            rows.append(f'<tr><td>{model_label(model)}</td><td>{esc(item.upper())}</td>'
                        f'<td class="num">{ranges[0]}</td><td class="num">{ranges[1]}</td>'
                        f'<td>{judge_chip(judgement["label"])}</td></tr>')
    lines = (findings or {}).get("summary") or []
    summary_block = ("<ol class=\"notes\">" + "".join(f"<li>{esc(line)}</li>" for line in lines[:3]) + "</ol>" if lines else
                     '<p class="muted">3 行の結論は findings.json の summary に書くと、ここに出る。</p>')
    return (summary_block
            + '<h3>点の判定（モデル × 問）</h3>'
            + '<table class="data"><thead><tr><th>モデル</th><th>問</th><th>int8 の点（最小〜最大）</th>'
              '<th>fp16 の点（最小〜最大）</th><th>判定</th></tr></thead>'
            + f'<tbody>{"".join(rows)}</tbody></table>'
            + '<p class="caption">判定の式は節 6。▲ 上がった・▼ 下がった・＝ 差は判定できない・？ 比べられない（記号と文字で示す）。</p>')


def section_conditions(summary: dict[str, Any]) -> str:
    limits, sampling = summary["limits"], summary["sampling"]
    contexts = {server["context"] for per_kv in summary["servers"].values() for server in per_kv.values()
                if server and server.get("context")}
    context = f"{max(contexts):,}（起動行の --max-context）" if contexts else f"{DEFAULT_CONTEXT:,}（計画の値。起動の記録なし）"
    conditions = [
        ("変えた条件", "KV キャッシュの型だけ。int8（既存の設定。tools/strata が --kv int8 を固定で付ける）と fp16（STRATA_EXTRA_ARGS=\"--kv fp16\" を足す）"),
        ("同じにした条件", f"thinking は effort high、temperature {sampling['temperature']} / top_p {sampling['top_p']} / top_k {sampling['top_k']}、"
                          f"生成の上限 {limits['max_tokens']:,} トークン、思考の予算 {limits['reasoning_budget_tokens']:,} トークン、文脈長 {context}"),
        ("問と回数", f"コーディング {'・'.join(item.upper() for item in summary['items'])}（隠しテストの合格率で採点）を、各条件 {len(summary['reps'])} 回"),
        ("対象", "・".join(model["label"] for model in summary["models"])),
        ("流す順", "モデルごとに int8 で起動（rep2・rep3）→ 止める → fp16 で起動（rep1〜3）→ 止める。モデルの順は Coder → 公式 → RVN"),
    ]
    condition_rows = "".join(f"<tr><th>{esc(name)}</th><td>{esc(text)}</td></tr>" for name, text in conditions)
    start_rows = []
    for model in summary["models"]:
        for kv in KV_TYPES:
            server = summary["servers"][model["key"]][kv]
            if server is None:
                start_rows.append(f'<tr><td>{model_label(model)}</td><td>{kv}</td><td colspan="4" class="muted">起動の記録なし</td></tr>')
                continue
            start_rows.append(
                f'<tr><td>{model_label(model)}</td><td>{kv}</td><td>{esc(str(server.get("status")))}</td>'
                f'<td>{esc(str(server.get("engine_kv") or "—"))}</td>'
                f'<td class="num">{fmt_number(server.get("start_s"), 0, "秒")}</td>'
                f'<td class="num">{esc(", ".join(f"rep{rep}" for rep in server.get("reps") or []) or "—")}</td></tr>')
    started = "".join(
        f'<details><summary>{esc(model["short"])}（{kv}）の起動行</summary><pre>{esc(summary["servers"][model["key"]][kv]["engine_started_line"] or "")}</pre></details>'
        for model in summary["models"] for kv in KV_TYPES
        if summary["servers"][model["key"]][kv] and summary["servers"][model["key"]][kv].get("engine_started_line"))
    return (f'<table class="data kv"><tbody>{condition_rows}</tbody></table>'
            + '<h3>起動の結果（engine の最後の起動行の --kv を確かめた）</h3>'
            + '<table class="data"><thead><tr><th>モデル</th><th>KV の型</th><th>結果</th><th>起動行の --kv</th>'
              '<th>起動にかかった時間</th><th>この起動で流した回</th></tr></thead>'
            + f'<tbody>{"".join(start_rows)}</tbody></table>'
            + '<p class="caption">結果: ok / start_failed（起動に失敗。journal を残した）/ kv_mismatch（起動行の --kv が違うので中止）/ '
              'server_died（流している途中で止まった）。</p>' + started)


def section_scores(summary: dict[str, Any]) -> str:
    rows = []
    for model in summary["models"]:
        for item in summary["items"]:
            for kv in KV_TYPES:
                condition = summary["results"][model["key"]][item][kv]
                span = ("—" if condition["min"] is None else
                        f"{build_report.fmt_pct(condition['min'])}〜{build_report.fmt_pct(condition['max'])}")
                rows.append(
                    f'<tr><td>{model_label(model)}</td><td>{esc(item.upper())}</td><td>{kv}</td>'
                    + "".join(_run_cell(run) for run in condition["runs"])
                    + f'<td class="num strong">{build_report.fmt_pct(condition["mean"])}</td><td class="num">{span}</td>'
                      f'<td class="num">{condition["n_all_passed"]} / {condition["n_records"]}</td></tr>')
    headers = "".join(f"<th>{rep} 回目</th>" for rep in summary["reps"])
    return (f'<h3>1 回ごとの点と平均</h3>{kv_legend()}{score_dot_chart(summary)}'
            '<p class="caption">丸は 1 回ごとの点（左から 1・2・3 回目）、黒い横線とその右の数字は平均。丸の上に重ねたマウスで回と状態が出る。'
            '表に同じ数字がある。</p>'
            f'<h3>モデル × 問 × KV の型の表</h3><table class="data"><thead><tr><th>モデル</th><th>問</th><th>KV の型</th>{headers}'
            '<th>平均</th><th>最小〜最大</th><th>全部合格</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<p class="caption">各回の小さい文字は状態（上限・エラーなど）と、思考が予算で打ち切られたあとの答え（打切）。'
            'エラーの回も 0 点として平均に入れる。全部合格は「全部合格の回数 / 記録のある回数」。</p>')


def section_speed(summary: dict[str, Any]) -> str:
    table_rows, tok_rows, time_rows = [], [], []
    for model in summary["models"]:
        rows = metric_rows(summary, model["key"])
        for index, row in enumerate(rows):
            first = f'<td rowspan="{len(rows)}">{model_label(model)}</td>' if index == 0 else ""
            table_rows.append(
                f'<tr>{first}<td>{esc(row["label"])}</td>'
                f'<td class="num">{fmt_number(row["int8"], row["digits"], row["unit"])}</td>'
                f'<td class="num">{fmt_number(row["fp16"], row["digits"], row["unit"])}</td>'
                f'<td class="num strong">{fmt_signed(row["diff"], row["digits"], row["diff_unit"])}</td>'
                f'<td class="num">{fmt_ratio(row["ratio"])}</td></tr>')
        by_key = {row["key"]: row for row in rows}
        for kv in KV_TYPES:
            for target_rows, key, digits, unit in ((tok_rows, "tok_s", 1, "tok/s"), (time_rows, "time_s", 0, "秒")):
                value = by_key[key][kv]
                target_rows.append({"label": f"{model['short']} · {kv}", "kv": kv, "value": value,
                                    "new_group": kv == "int8",
                                    "tip": f"{fmt_number(value, digits, unit)}\n{model['short']} / {kv}"})
    return (f'<h3>表（中央値。差 = fp16 − int8、比 = fp16 ÷ int8）</h3>'
            '<table class="data"><thead><tr><th>モデル</th><th>項目</th><th>int8</th><th>fp16</th><th>差</th><th>比</th></tr></thead>'
            f'<tbody>{"".join(table_rows)}</tbody></table>'
            '<p class="caption">tok/s と 1 問の時間は、C4・C5 の全部の回を合わせた中央値。エラーと飛ばした問は時間に入れない。'
            '枠・命中率・VRAM・RAM・起動秒は条件ごとの起動の記録（server-&lt;slug&gt;.json）の値。命中率は起動後の全リクエストの'
            '「ヒット数の合計 ÷ 照会数の合計」。VRAM は流し終えた直後の nvidia-smi。RAM は unit の cgroup の memory.peak。</p>'
            f'<h3>生成 tok/s（中央値。大きいほど速い）</h3>{kv_legend()}'
            + kv_bar_chart(tok_rows, title="生成 tok/s の比べ", value_label=lambda value: f"{value:.1f}",
                           tick_label=lambda value: f"{value:g}")
            + '<h3>1 問の時間（中央値。短いほど速い）</h3>'
            + kv_bar_chart(time_rows, title="1 問の時間の比べ", value_label=build_report.fmt_time,
                           tick_label=lambda value: f"{value / 60:g} 分", tick_unit=60.0))


def section_thinking(summary: dict[str, Any]) -> str:
    rows = []
    for model in summary["models"]:
        for item in summary["items"]:
            for kv in KV_TYPES:
                condition = summary["results"][model["key"]][item][kv]
                rows.append(
                    f'<tr><td>{model_label(model)}</td><td>{esc(item.upper())}</td><td>{kv}</td>'
                    f'<td class="num">{condition["n_budget_cut"]} / {condition["n_records"]}</td>'
                    f'<td class="num">{build_report.fmt_int(condition["thinking_tokens_median"])}</td>'
                    f'<td class="num">{build_report.fmt_int(condition["tokens_median"])}</td>'
                    f'<td>{esc(" / ".join(condition["statuses"]))}</td></tr>')
    return ('<table class="data"><thead><tr><th>モデル</th><th>問</th><th>KV の型</th><th>予算で打切</th>'
            '<th>思考（推定）の中央値</th><th>出力トークンの中央値</th><th>状態（1〜3 回目）</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            f'<p class="caption">{esc(build_report.THINKING_EST_NOTE)}予算で打切は、思考が予算 '
            f'{summary["limits"]["reasoning_budget_tokens"]:,} トークンに届いて、Strata が思考の最後に締めの文を差し込んだ回数'
            '（「打切の回数 / 記録のある回数」）。状態は ok / length（上限）/ error / missing（記録なし）。</p>')


def section_findings(findings: dict[str, Any] | None, root_label: str) -> str:
    if not findings or not (findings.get("facts") or findings.get("opinions")):
        return (f'<p class="muted">所見はまだ書かれていない（{esc(root_label)}/findings.json に facts と opinions を書いて作り直す）。</p>')
    facts = "".join(f"<li>{esc(line)}</li>" for line in findings.get("facts", []))
    opinions = "".join(f"<li>{esc(line)}</li>" for line in findings.get("opinions", []))
    return f'<h3>事実</h3><ul class="notes">{facts}</ul><h3>意見（解釈）</h3><ul class="notes">{opinions}</ul>'


def section_notes(summary: dict[str, Any]) -> str:
    source = summary.get("int8_rep1_source")
    notes = [
        f"試行は各条件 {len(summary['reps'])} 回だけ。サンプリングありで、同じ条件でも回によって点が大きく変わりうる。"
        "3 回では偶然と区別できない差は、判定しない。",
        "int8 の rep1 は、この比べのために流したものではなく、別の日の既存の記録の写し（RVN と公式は 2026-10-08、Coder は 2026-10-09 に計測）。"
        "ほかの回とは機体の状態（温度・空きメモリ・起動のたびの枠の数）が違うかもしれない。"
        + (f"写した元は {source.get('source_dir')}（source.json）。" if source else "（source.json は無い）"),
        "同じ問題を続けて流すので、Strata の会話キャッシュで入力の読み込みだけ速くなりうる。答えは毎回サンプリングされるので点には影響せず、"
        "1 問の時間には入力の読み込み（数秒）を含むので、影響は小さい。",
        "fp16 の KV は int8 の約 2 倍の VRAM を使い（計画の見積もりでは約 3.25 GiB と約 1.68 GiB）、増えた分だけ GPU に置けるエキスパートの枠が減る。"
        "枠の数と命中率は起動のたびに engine のログから読んだ値。",
        "速さと資源は、1 回ごとの揺れが点より小さいので、中央値の差をそのまま報告する（判定の式は使わない）。",
        "起動に失敗した条件・起動行の --kv が違った条件・流す途中でサーバーが止まった条件は、起動の結果（節 1）と足りない記録に出る。",
    ]
    data_paths = [
        ("記録", f"{summary['root']}/<int8|fp16>/rep<1〜3>/local/<slug>/coding/<c4|c5>-run1.json"),
        ("起動の記録", f"{summary['root']}/<int8|fp16>/server-<slug>.json（journal-*.txt は起動の失敗時）"),
        ("int8 rep1 の元", f"{summary['root']}/int8/rep1/source.json"),
        ("集計", f"{summary['root']}/summary.json"),
        ("実行の記録", f"{summary['root']}/DONE と tools/model-eval/work/run_kv_compare-{summary['date']}.log"),
        ("問題と隠しテスト", "tools/model-eval/suites/coding/c4・c5"),
    ]
    path_rows = "".join(f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td></tr>" for name, path in data_paths)
    formula = "".join(f"<li>{esc(line)}</li>" for line in JUDGE_FORMULA)
    missing = "".join(f"<li>{esc(line)}</li>" for line in summary.get("missing", []))
    return ('<ul class="notes">' + "".join(f"<li>{esc(note)}</li>" for note in notes) + "</ul>"
            + f'<h3>点の判定の式</h3><ul class="notes formulas">{formula}</ul>'
            + '<p class="caption">最小と最大だけを比べる（平均は使わない）。3 回の幅が重なれば、差があるとは言わない。</p>'
            + f'<h3>生データの場所</h3><table class="data kv"><tbody>{path_rows}</tbody></table>'
            + (f'<h3>足りない記録・起動の問題</h3><ul class="notes">{missing}</ul>' if missing else ""))


def build_kv_html(summary: dict[str, Any], findings: dict[str, Any] | None = None) -> str:
    sections = [
        ("s0", "0. 結論", section_conclusion(summary, findings)),
        ("s1", "1. 条件（KV の型だけを変えた）", section_conditions(summary)),
        ("s2", "2. 点（モデル × 問 × KV の型）", section_scores(summary)),
        ("s3", "3. 速さと資源", section_speed(summary)),
        ("s4", "4. 思考（予算での打ち切り）", section_thinking(summary)),
        ("s5", "5. 所見", section_findings(findings, summary["root"])),
        ("s6", "6. 注意・判定の式・生データ", section_notes(summary)),
    ]
    toc = "".join(f'<li><a href="#{anchor}">{esc(title)}</a></li>' for anchor, title, _body in sections)
    body = "".join(f'<section id="{anchor}"><h2>{esc(title)}</h2>{content}</section>' for anchor, title, content in sections)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Strata の KV キャッシュ比較 {esc(summary["date"])}</title>'
        f'<style>{build_report.STYLE}{KV_STYLE}</style></head>'
        f'<body class="viz-root">{HATCH_DEFS}<main>'
        '<h1>Strata 3 種の KV キャッシュ比較（int8 と fp16・コーディング C4・C5）</h1>'
        f'<p class="sub">計測 {esc(summary["date"])}・集計 {esc(summary["generated_at"])}・'
        'tools/model-eval/kv_compare.py が記録から生成（手で書き換えない）</p>'
        f'<nav aria-label="目次"><ol>{toc}</ol></nav>{body}</main>'
        f'<div id="tip" role="tooltip" hidden></div><script>{build_report.SCRIPT}</script></body></html>\n'
    )


# ------------------------------------------------------------------------------------------------ fix の HTML

FIX_STYLE = KV_STYLE + """
.legend svg{vertical-align:middle;margin-right:4px}
table.wide{font-size:.82rem}
td.left{text-align:left}
svg .base-shade{fill:var(--surface-2)}
svg .seg-count{font-size:11px;font-weight:700;pointer-events:none}
"""
# 状態を文字で示す名前（色だけに頼らない）
STATE_TEXT = {common.STATUS_OK: "ok", common.STATUS_LENGTH: "length（生成の上限に届いた）",
              common.STATUS_EOS_IN_THINKING: "eos_in_thinking（思考中に停止トークン）", common.STATUS_ERROR: "error",
              common.STATUS_TIMEOUT: "timeout", common.STATUS_STALL: "stall", "missing": "記録なし"}
LANG_TEXT = {"ja": "日本語", "en": "英語"}
SURFACE_COLOR = "#fcfcfb"            # build_report.STYLE の --surface（文字の縁取りに使う）
UNFILLED = "（未記入）"
NOT_RUN_TEXT = "流していない"


def cond_label(summary: dict[str, Any], condition: str) -> str:
    return summary["labels"][condition]


def unfilled(hint: str) -> str:
    """findings.json の項目が無いときの表示。"""

    return f'<p class="muted">{UNFILLED}{esc(hint)}</p>'


def string_list(findings: dict[str, Any] | None, key: str) -> list[str]:
    value = (findings or {}).get(key) or []
    return [str(line) for line in value] if isinstance(value, list) else [str(value)]


def bullet_list(lines: list[str]) -> str:
    return '<ul class="notes">' + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>"


def fmt_ends(stats: dict[str, Any]) -> str:
    """終わり方の回数を文字にする（0 の項目は省く）。予算で打ち切られたあとの答えが上限で切れた回は、括弧で添える。"""

    parts = []
    for name in END_STATES:
        count = stats["ends"].get(name, 0)
        if not count:
            continue
        text = f"{END_LABELS[name]} {count}"
        if name == END_BUDGET_CUT and stats.get("n_truncated"):
            text += f"（うち答えが上限で途中切れ {stats['n_truncated']}）"
        parts.append(text)
    return "・".join(parts) or "—"


def run_marks(run: dict[str, Any]) -> list[str]:
    """点の表の各回の小さい文字: 終わり方・禁止や文法誤り・旧記録・やり直し済み。"""

    marks = []
    if run["status"] != "missing":
        marks.append(END_SHORT[run.get("end", END_ERROR)] + ("（打切のあと途中切れ）" if run.get("truncated") else ""))
    if run.get("violations"):
        marks.append(build_report.VIOLATION_LABEL)
    elif run.get("syntax_error"):
        marks.append(build_report.SYNTAX_ERROR_LABEL)
    if run.get("eos_legacy"):
        marks.append("旧記録")
    if (run.get("attempts") or 1) > 1:
        marks.append(f"やり直し済み（1 回目 {run.get('first_attempt_status')}）")
    return marks


def fix_run_cell(run: dict[str, Any]) -> str:
    if run["status"] == "missing":
        return f'<td class="num muted">{"記録なし" if run.get("planned", True) else "計画外"}</td>'
    main, _sub = build_report.cell_texts(run)
    marks = run_marks(run)
    return f'<td class="num">{esc(main)}' + (f'<span class="state">{esc("・".join(marks))}</span>' if marks else "") + "</td>"


def diff_text(comparison: dict[str, Any] | None) -> str:
    """基準との平均の差（パーセントポイント）。基準そのもの（comparison が None）は「基準」。"""

    if comparison is None:
        return "基準"
    return "—" if comparison["diff"] is None else fmt_signed(comparison["diff"] * 100, 0, "pt")


def comparison_of(summary: dict[str, Any], key: str, scope: str, condition: str) -> dict[str, Any] | None:
    """基準との比べ。基準の条件は None。"""

    return None if condition == summary["baseline"] else summary["comparisons"][key][scope][condition]


# ---- 条件の定義の表


def _unique_texts(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _tokens_text(value: Any, zero_text: str = "") -> str:
    if value is None:
        return "—"
    return zero_text if value == 0 and zero_text else f"{value:,}"


def records_text(summary: dict[str, Any], condition: str) -> str:
    """条件の記録の数（モデルごと）。記録が 1 本も無いモデルは「流していない」。"""

    total = len(summary["reps"]) * len(summary["items"])
    parts = []
    for model in summary["models"]:
        stats = summary["combined"][model["key"]][condition]
        if summary["not_run"][model["key"]][condition]:
            parts.append(f"{model['short']} {NOT_RUN_TEXT}")
        else:
            parts.append(f"{model['short']} {stats['n_records']}" + ("" if stats["n_records"] == total else f" / {total}"))
    return "・".join(parts)


def limits_table(summary: dict[str, Any]) -> str:
    """各条件の定義。思考の強さ・思考の上限・生成の上限・問題文は、記録の request と limits から読んだ値。"""

    rows = []
    for condition in summary["conditions"]:
        seen = summary["limits_seen"].get(condition) or []
        efforts = summary["efforts_seen"].get(condition) or []
        budgets = _unique_texts([_tokens_text(entry.get("reasoning_budget_tokens"), "なし") for entry in seen])
        max_tokens = _unique_texts([_tokens_text(entry.get("max_tokens")) for entry in seen])
        languages = _unique_texts([LANG_TEXT.get(entry.get("prompt_lang"), str(entry.get("prompt_lang"))) for entry in seen])
        source = (summary.get("sources") or {}).get(condition)
        name = (f'{esc(cond_label(summary, condition))}'
                + (' <span class="muted">（基準）</span>' if condition == summary["baseline"] else "")
                + f'<br><code>{esc(condition)}</code>'
                + (f'<br><span class="muted">{esc(source.get("note", ""))}</span>' if source else ""))
        rows.append(f'<tr><th class="left">{name}</th>'
                    f'<td class="left">{"<br>".join(esc(text) for text in efforts) or "—"}</td>'
                    f'<td class="left">{"<br>".join(esc(text) for text in budgets) or "—"}</td>'
                    f'<td class="left">{"<br>".join(esc(text) for text in max_tokens) or "—"}</td>'
                    f'<td class="left">{"<br>".join(esc(text) for text in languages) or "—"}</td>'
                    f'<td class="left">{esc(records_text(summary, condition))}</td></tr>')
    return ('<table class="data wide"><thead><tr><th>条件</th><th>思考の強さ</th><th>思考の上限（トークン）</th>'
            '<th>生成の上限（トークン）</th><th>問題文</th><th>記録（C4・C5 の合計。最大 6）</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '<p class="caption">値は記録（&lt;問&gt;-run1.json）の limits と request から読んだ。思考の強さは要求の reasoning_effort で、'
            'high は Strata のテンプレートでは xhigh に当たる（tools/strata/README.md）。思考の上限なしは要求で 0 を送った'
            '（Strata は要求の 0 を予算なしと読み、設定 JSON の予算より優先する）。記録が 1 本も無いモデルは「流していない」。</p>')


# ---- 1 回ごとの点の図（モデルごと。C4・C5 の 2 組を並べる）


def run_marker(run: dict[str, Any], center_x: float, center_y: float) -> str:
    """答えが出た回は Strata の紫の丸、答えなしの回は灰色の×（色だけでなく形でも区別する）。"""

    if run.get("has_answer"):
        return (f'<circle cx="{center_x}" cy="{center_y:.1f}" r="5.5" fill="{COLOR_STRATA}" stroke="var(--surface)" '
                f'stroke-width="1.5"/>')
    return (f'<path d="M{center_x - 5},{center_y - 5:.1f} L{center_x + 5},{center_y + 5:.1f} '
            f'M{center_x + 5},{center_y - 5:.1f} L{center_x - 5},{center_y + 5:.1f}" fill="none" '
            f'stroke="{build_report.COLOR_NA}" stroke-width="2.5" stroke-linecap="round"/>')


def cond_dot_chart(summary: dict[str, Any], model: dict[str, Any]) -> str:
    """1 回ごとの点を印で打ち、平均を横線で示す。問（C4・C5）のグループごとに、条件を横に並べる。基準の枠は薄く塗る。"""

    conditions, items = summary["conditions"], summary["items"]
    slot_width, dot_offsets = 96, (-22, 0, 22)
    group_width = slot_width * len(conditions)
    left, top, plot_height, bottom = 56, 30, 220, 64
    width = left + group_width * len(items) + 10
    height = top + plot_height + bottom

    def y_of(value: float) -> float:
        return top + (1 - value) * plot_height

    title = f"{model['short']}: 1 回ごとの点と平均（問 × 条件）"
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="{esc(title)}">']
    for item_index in range(len(items)):
        shade_x = left + item_index * group_width + conditions.index(summary["baseline"]) * slot_width
        parts.append(f'<rect class="base-shade" x="{shade_x}" y="{top - 6}" width="{slot_width}" height="{plot_height + 6}"/>')
        parts.append(f'<text class="tick" x="{shade_x + slot_width / 2}" y="{top - 12}" text-anchor="middle">基準</text>')
    for value in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line class="grid" x1="{left}" y1="{y_of(value):.1f}" x2="{width - 10}" y2="{y_of(value):.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{y_of(value) + 4:.1f}" text-anchor="end">{value * 100:.0f}%</text>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top - 6}" x2="{left}" y2="{top + plot_height}"/>')
    labels: list[str] = []
    for item_index, item in enumerate(items):
        group_x = left + item_index * group_width
        if item_index:
            parts.append(f'<line class="axis" x1="{group_x}" y1="{top - 6}" x2="{group_x}" y2="{height - bottom + 38}"/>')
        labels.append(f'<text class="group-label" x="{group_x + group_width / 2:.1f}" y="{top + plot_height + 42}" '
                      f'text-anchor="middle">{esc(model["short"])} · {esc(item.upper())}</text>')
        for slot_index, condition in enumerate(conditions):
            center_x = group_x + slot_width * slot_index + slot_width / 2 - 4
            stats = summary["results"][model["key"]][item][condition]
            labels.append(f'<text class="tick" x="{center_x}" y="{top + plot_height + 18}" text-anchor="middle">{esc(condition)}</text>')
            counted = [run for run in stats["runs"] if run["status"] not in ("missing", common.STATUS_SKIPPED)]
            if not counted:
                text = NOT_RUN_TEXT if summary["not_run"][model["key"]][condition] else "記録なし"
                labels.append(f'<text class="muted" x="{center_x}" y="{top + plot_height - 8}" text-anchor="middle">{text}</text>')
                continue
            for run in counted:
                dot_x = center_x + dot_offsets[(run["rep"] - 1) % len(dot_offsets)]
                main, _sub = build_report.cell_texts(run)
                tip = "\n".join([f"{condition} rep{run['rep']}: {main}",
                                 f"{model['short']} / {item.upper()}",
                                 f"終わり方: {END_LABELS[run.get('end', END_ERROR)]}" + ("（打切のあと答えが上限で切れた）" if run.get("truncated") else ""),
                                 f"答え: {'あり' if run.get('has_answer') else 'なし'}　状態: {STATE_TEXT.get(run['status'], run['status'])}",
                                 f"全部合格: {'はい' if run.get('all_passed') else 'いいえ'}"])
                dot_y = y_of(run["score"] or 0.0)
                parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(tip)}"><circle class="hit" cx="{dot_x}" '
                             f'cy="{dot_y:.1f}" r="10"/>{run_marker(run, dot_x, dot_y)}</g>')
            mean_y = y_of(stats["mean"])
            mean_tip = (f"{condition} の平均: {build_report.fmt_pct(stats['mean'])}\n{model['short']} / {item.upper()}\n"
                        f"最小〜最大: {build_report.fmt_pct(stats['min'])}〜{build_report.fmt_pct(stats['max'])}\n"
                        f"答えが出た回: {stats['n_answered']} / {stats['n_records']}")
            parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(mean_tip)}"><line class="mean" '
                         f'x1="{center_x - 28}" y1="{mean_y:.1f}" x2="{center_x + 28}" y2="{mean_y:.1f}"/></g>')
            labels.append(f'<text class="value" x="{center_x + 31}" y="{mean_y + 4:.1f}">{build_report.fmt_pct(stats["mean"])}</text>')
    parts.extend(labels)
    parts.append("</svg>")
    return "".join(parts)


def dot_legend(summary: dict[str, Any]) -> str:
    answered = (f'<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">{run_marker({"has_answer": True}, 9, 9)}</svg>')
    unanswered = (f'<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">{run_marker({"has_answer": False}, 9, 9)}</svg>')
    mean = '<svg width="22" height="18" viewBox="0 0 22 18" aria-hidden="true"><line class="mean" x1="1" y1="9" x2="21" y2="9"/></svg>'
    shade = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><rect width="18" height="14" y="2" fill="#f3f3f1" stroke="#bdbcb6"/></svg>'
    names = "　".join(f"{condition} = {cond_label(summary, condition)}" for condition in summary["conditions"])
    return ('<div class="legend" aria-label="点の図の凡例">'
            f'<span class="legend-item">{answered}紫の丸 = 答えが出た回</span>'
            f'<span class="legend-item">{unanswered}灰色の × = 答えなしの回</span>'
            f'<span class="legend-item">{mean}黒い横線 = 平均（右の数字）</span>'
            f'<span class="legend-item">{shade}薄い灰の枠 = 基準</span></div>'
            f'<p class="caption">横軸の条件名: {esc(names)}</p>')


# ---- 条件ごとの表（モデル × 問）


def fix_score_table(summary: dict[str, Any], model: dict[str, Any]) -> str:
    key = model["key"]
    rows = []
    columns = 3 + len(summary["reps"]) + 6
    for item in summary["items"]:
        for condition in summary["conditions"]:
            stats = summary["results"][key][item][condition]
            head = f'<td>{esc(item.upper())}</td><td class="left">{esc(cond_label(summary, condition))}</td>'
            if summary["not_run"][key][condition]:
                rows.append(f'<tr>{head}<td colspan="{columns - 2}" class="muted">{NOT_RUN_TEXT}</td></tr>')
                continue
            comparison = comparison_of(summary, key, item, condition)
            span = ("—" if stats["min"] is None else
                    f"{build_report.fmt_pct(stats['min'])}〜{build_report.fmt_pct(stats['max'])}")
            chip = '<span class="muted">—</span>' if comparison is None else judge_chip(comparison["label"])
            rows.append(f'<tr>{head}' + "".join(fix_run_cell(run) for run in stats["runs"])
                        + f'<td class="num strong">{build_report.fmt_pct(stats["mean"])}</td><td class="num">{span}</td>'
                          f'<td class="num">{stats["n_all_passed"]} / {stats["n_records"]}</td>'
                          f'<td class="num">{stats["n_answered"]} / {stats["n_records"]}</td>'
                          f'<td class="num">{diff_text(comparison)}</td><td>{chip}</td>'
                          f'<td class="left">{esc(fmt_ends(stats))}</td></tr>')
    headers = "".join(f"<th>{rep} 回目</th>" for rep in summary["reps"])
    return ('<table class="data wide"><thead><tr><th>問</th><th>条件</th>' + headers
            + '<th>平均</th><th>最小〜最大</th><th>全部合格</th><th>答えが出た</th><th>基準との差</th><th>判定</th><th>終わり方</th></tr></thead>'
            + f'<tbody>{"".join(rows)}</tbody></table>')


def fix_section_conclusion(summary: dict[str, Any], findings: dict[str, Any] | None) -> str:
    lines = string_list(findings, "summary")
    summary_block = bullet_list(lines) if lines else unfilled("結論は findings.json の summary（文の配列）に書くと、ここに出る。")
    rows = []
    for model in summary["models"]:
        for condition in summary["conditions"]:
            key = model["key"]
            stats = summary["combined"][key][condition]
            name = esc(cond_label(summary, condition)) + (' <span class="muted">（基準）</span>' if condition == summary["baseline"] else "")
            head = f'<td>{model_label(model)}</td><td class="left">{name}</td>'
            if summary["not_run"][key][condition]:
                rows.append(f'<tr>{head}<td colspan="4" class="muted">{NOT_RUN_TEXT}</td></tr>')
                continue
            comparison = comparison_of(summary, key, COMBINED, condition)
            chip = '<span class="muted">—</span>' if comparison is None else judge_chip(comparison["label"])
            partial = ("" if stats["n_records"] == len(summary["reps"]) * len(summary["items"])
                       else f'<span class="state">記録 {stats["n_records"]} / {len(summary["reps"]) * len(summary["items"])}</span>')
            rows.append(f'<tr>{head}<td class="num strong">{build_report.fmt_pct(stats["mean"])}{partial}</td>'
                        f'<td class="num">{diff_text(comparison)}</td><td>{chip}</td>'
                        f'<td class="num">{stats["n_answered"]} / {stats["n_records"]}</td></tr>')
    total = len(summary["reps"]) * len(summary["items"])
    table = ('<h3>条件 × モデルの平均点と、答えが出た回数</h3>'
             '<table class="data"><thead><tr><th>モデル</th><th>条件</th>'
             f'<th>平均点（C4・C5 の {total} 回）</th><th>基準との差</th><th>判定</th><th>答えが出た回数</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>'
             '<p class="caption">差は平均の差（パーセントポイント。条件 − 基準）。判定は ▲ 上がった・▼ 下がった・＝ 差は判定できない・'
             '？ 比べられない（記号と文字で示す。式は節 7）。答えが出た回数は、本文が空でなく採点できた回（途中で切れた答えも数える）の数 / 記録のある回数。'
             'モデル × 問ごとの数字は節 3。</p>')
    return summary_block + table


def fix_section_settings(summary: dict[str, Any], findings: dict[str, Any] | None, settings: list[dict[str, Any]] | None) -> str:
    rows = settings or (findings or {}).get("settings") or []
    if not rows:
        return unfilled("調べた設定の表は、--settings-table に JSON を渡すか、findings.json の settings 配列"
                        "（item・strata・ollama・verdict の鍵）に書くと、ここに出る。")
    body = "".join(f'<tr><td class="left">{esc(str(row.get("item", "")))}</td><td class="left">{esc(str(row.get("strata", "")))}</td>'
                   f'<td class="left">{esc(str(row.get("ollama", "")))}</td><td class="left">{esc(str(row.get("verdict", "")))}</td></tr>'
                   for row in rows)
    return ('<table class="data"><thead><tr><th>項目</th><th>Strata（評価の送り方）</th><th>Ollama（同じ系統の IQ4_XS）</th><th>判定</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')


def fix_section_evidence(findings: dict[str, Any] | None) -> str:
    evidence = (findings or {}).get("evidence") or []
    if not evidence:
        return unfilled("証拠は findings.json の evidence（文の配列）に書くと、ここに出る。")
    items = []
    for entry in evidence:
        if isinstance(entry, dict):
            source = f'<br><span class="muted">根拠: {esc(str(entry.get("source", "")))}</span>' if entry.get("source") else ""
            items.append(f"<li>{esc(str(entry.get('text', '')))}{source}</li>")
        else:
            items.append(f"<li>{esc(str(entry))}</li>")
    return f'<ul class="notes">{"".join(items)}</ul>'


def fix_section_results(summary: dict[str, Any]) -> str:
    parts = ['<h3>条件の定義</h3>', limits_table(summary), dot_legend(summary)]
    for model in summary["models"]:
        parts.append(f'<h3>{esc(model["short"])}</h3>')
        parts.append(cond_dot_chart(summary, model))
        parts.append(fix_score_table(summary, model))
    parts.append('<p class="caption">図の印は 1 回ごとの点（左から 1・2・3 回目）。印の上にマウスを重ねると回・終わり方・状態が出る。'
                 '表に同じ数字がある。表の各回の小さい文字は終わり方（自己終了・予算打切・答え途中で上限・上限まで答えなし・繰り返し停止・思考中停止）と、'
                 '禁止・文法誤り（0 点の理由）、旧記録（状態を足す前の記録で、本文が空・finish が stop・思考ありのものを思考中停止と同じ扱いにした）、'
                 'やり直し済み（思考中停止を 1 回流し直した。1 回目は &lt;問&gt;-run1.attempt1.json）。エラーの回も 0 点として平均に入れる。'
                 '判定は 3 回の点の最小・最大だけで決める（平均は使わない）。</p>')
    return "".join(parts)


# ---- 終わり方の内訳


def end_pattern_id(color: str, angle: str) -> str:
    return f"ends-{angle}-{color.lstrip('#')}"


def end_fill(name: str) -> str:
    color, angle = END_STYLE[name]
    if color is None:
        return "var(--surface-2)"
    return color if angle is None else f"url(#{end_pattern_id(color, angle)})"


def end_defs() -> str:
    """終わり方の模様（45° と 135° の斜線。同じ色の薄い地に濃い線）。凡例と棒の両方から参照するので、ページの先頭に 1 つだけ置く。"""

    patterns = []
    for color, angle in sorted({style for style in END_STYLE.values() if style[0] and style[1]}):
        light = build_report._mix("#ffffff", color, 0.25)
        patterns.append(f'<pattern id="{end_pattern_id(color, angle)}" width="6" height="6" patternUnits="userSpaceOnUse" '
                        f'patternTransform="rotate({angle})"><rect width="6" height="6" fill="{light}"/>'
                        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{color}" stroke-width="2.5"/></pattern>')
    return ('<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
            + "".join(patterns) + "</defs></svg>")


def end_swatch(name: str) -> str:
    extra = f' stroke="{build_report.COLOR_NA}" stroke-width="1"' if END_STYLE[name][0] is None else ""
    return (f'<svg width="18" height="12" viewBox="0 0 18 12" aria-hidden="true"><rect x="0.5" y="0.5" width="17" height="11" '
            f'rx="2" fill="{end_fill(name)}"{extra}/></svg>')


def ends_present(summary: dict[str, Any]) -> list[str]:
    """記録に出てくる終わり方（凡例に出す）。"""

    return [name for name in END_STATES
            if any(summary["combined"][model["key"]][condition]["ends"].get(name)
                   for model in summary["models"] for condition in summary["conditions"])]


def ends_legend(summary: dict[str, Any]) -> str:
    items = "".join(f'<span class="legend-item">{end_swatch(name)}{esc(END_LABELS[name])}（{esc(name)}）: {esc(END_NOTES[name])}</span>'
                    for name in ends_present(summary))
    return f'<div class="legend" aria-label="終わり方の凡例">{items}</div>'


def ends_chart(summary: dict[str, Any]) -> str:
    """条件 × モデルごとの、終わり方の回数の積み上げ横棒（C4・C5 の合計）。棒の中の数字は幅に収まるときだけ出す。"""

    models, conditions = summary["models"], summary["conditions"]
    total_runs = len(summary["reps"]) * len(summary["items"])
    label_width, plot_width, right = 270, 420, 150
    row_height, bar_height, header_height, group_gap, top, bottom = 28, 18, 22, 10, 6, 34
    unit = plot_width / total_runs
    width = label_width + plot_width + right
    positions: list[tuple[dict[str, Any], str, float]] = []
    headers: list[tuple[dict[str, Any], float]] = []
    y = float(top)
    for model_index, model in enumerate(models):
        if model_index:
            y += group_gap
        headers.append((model, y))
        y += header_height
        for condition in conditions:
            positions.append((model, condition, y))
            y += row_height
    height = int(y + bottom)
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="終わり方の内訳（条件 × モデル）">']
    for tick in range(total_runs + 1):
        x = label_width + tick * unit
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{y + 2:.1f}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{y + 18:.1f}" text-anchor="middle">{tick}</text>')
    parts.append(f'<text class="tick" x="{label_width + plot_width + 8}" y="{y + 18:.1f}">回</text>')
    parts.append(f'<line class="axis" x1="{label_width}" y1="{top}" x2="{label_width}" y2="{y + 2:.1f}"/>')
    for model, header_y in headers:
        parts.append(f'<text class="group-label" x="8" y="{header_y + 15:.1f}">{esc(model["short"])}</text>')
    for model, condition, row_y in positions:
        key = model["key"]
        stats = summary["combined"][key][condition]
        center = row_y + row_height / 2
        top_y = center - bar_height / 2
        parts.append(f'<text class="label" x="{label_width - 10}" y="{center + 4:.1f}" text-anchor="end">{esc(cond_label(summary, condition))}</text>')
        if summary["not_run"][key][condition]:
            parts.append(f'<text class="muted" x="{label_width + 8}" y="{center + 4:.1f}">{NOT_RUN_TEXT}</text>')
            continue
        counts = [(name, stats["ends"].get(name, 0)) for name in END_STATES if stats["ends"].get(name, 0)]
        cursor = float(label_width)
        for index, (name, count) in enumerate(counts):
            segment_width = max(count * unit - 2, 1.5)          # 隣の塗りとの間に 2px の隙間
            tip = (f"{END_LABELS[name]} {count} 回\n{model['short']} / {cond_label(summary, condition)}\n{END_NOTES[name]}"
                   + (f"\nうち答えが上限で途中切れ {stats['n_truncated']} 回" if name == END_BUDGET_CUT and stats["n_truncated"] else ""))
            stroke = f' stroke="{build_report.COLOR_NA}" stroke-width="1"' if END_STYLE[name][0] is None else ""
            if index == len(counts) - 1:
                shape = f'<path d="{build_report._bar_path(cursor, top_y, segment_width, bar_height)}" fill="{end_fill(name)}"{stroke}/>'
            else:
                shape = f'<rect x="{cursor:.1f}" y="{top_y:.1f}" width="{segment_width:.1f}" height="{bar_height}" fill="{end_fill(name)}"{stroke}/>'
            parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(tip)}"><rect class="hit" x="{cursor:.1f}" y="{row_y + 1}" '
                         f'width="{segment_width:.1f}" height="{row_height - 2}"/>{shape}</g>')
            if segment_width >= 22:
                color, angle = END_STYLE[name]
                if color is None or angle is not None:
                    # 模様の上は、白い縁取りの文字（paint-order に頼らず、縁取りと本体の 2 つの text を重ねる）
                    for style in (f'stroke="{SURFACE_COLOR}" stroke-width="3" stroke-linejoin="round" fill="{SURFACE_COLOR}"',
                                  'fill="#0b0b0b"'):
                        parts.append(f'<text class="seg-count" x="{cursor + segment_width / 2:.1f}" y="{center + 4:.1f}" '
                                     f'text-anchor="middle" {style}>{count}</text>')
                else:
                    parts.append(f'<text class="seg-count" x="{cursor + segment_width / 2:.1f}" y="{center + 4:.1f}" '
                                 f'text-anchor="middle" fill="{build_report._ink_on(color)}">{count}</text>')
            cursor += count * unit
        parts.append(f'<text class="value" x="{cursor + 6:.1f}" y="{center + 4:.1f}">答えあり {stats["n_answered"]} / {stats["n_records"]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def fix_ends_table(summary: dict[str, Any]) -> str:
    """終わり方の回数の表（図と同じ数字）と、思考・時間・速さの中央値の表。"""

    count_rows, speed_rows = [], []
    for model in summary["models"]:
        for condition in summary["conditions"]:
            key = model["key"]
            stats = summary["combined"][key][condition]
            head = f'<td>{model_label(model)}</td><td class="left">{esc(cond_label(summary, condition))}</td>'
            if summary["not_run"][key][condition]:
                count_rows.append(f'<tr>{head}<td colspan="{len(END_STATES) + 2}" class="muted">{NOT_RUN_TEXT}</td></tr>')
                speed_rows.append(f'<tr>{head}<td colspan="6" class="muted">{NOT_RUN_TEXT}</td></tr>')
                continue
            count_rows.append(f'<tr>{head}<td class="num">{stats["n_records"]}</td>'
                              + "".join(f'<td class="num">{stats["ends"].get(name, 0)}</td>' for name in END_STATES if name != END_MISSING)
                              + f'<td class="num">{stats["n_truncated"]}</td><td class="num">{stats["n_answered"]}</td></tr>')
            speed_rows.append(f'<tr>{head}<td class="num">{build_report.fmt_int(stats["thinking_tokens_median"])}</td>'
                              f'<td class="num">{build_report.fmt_int(stats["tokens_median"])}</td>'
                              f'<td class="num">{build_report.fmt_time(stats["time_s_median"])}</td>'
                              f'<td class="num">{fmt_number(stats["tok_s_median"], 1)}</td>'
                              f'<td class="num">{stats["n_retried"]}</td>'
                              f'<td class="num">{stats["n_eos"]}（最終 {stats["n_eos_final"]}）</td></tr>')
    state_headers = "".join(f"<th>{esc(END_LABELS[name])}</th>" for name in END_STATES if name != END_MISSING)
    return ('<h3>終わり方の回数（表。図と同じ数字）</h3>'
            '<table class="data wide"><thead><tr><th>モデル</th><th>条件</th><th>記録のある回</th>' + state_headers
            + '<th>うち打切のあと途中切れ</th><th>答えが出た</th></tr></thead>'
            + f'<tbody>{"".join(count_rows)}</tbody></table>'
            '<p class="caption">終わり方は 1 回ごとに 1 つに分類する（規則は節 7）。「予算で打切」のうち、そのあとの答えが生成の上限で切れた回は'
            '「うち打切のあと途中切れ」に数える（終わり方は予算で打切のまま）。</p>'
            '<h3>思考・時間・速さ（中央値）とやり直し</h3>'
            '<table class="data wide"><thead><tr><th>モデル</th><th>条件</th><th>思考（推定）トークン</th><th>出力トークン</th>'
            '<th>1 問の時間</th><th>生成 tok/s</th><th>やり直し（attempt1 のある回）</th><th>思考中停止（1 回目も数える）</th></tr></thead>'
            + f'<tbody>{"".join(speed_rows)}</tbody></table>'
            f'<p class="caption">{esc(build_report.THINKING_EST_NOTE)}1 問の時間は最終の記録の時間（やり直した 1 回目は含まない。エラーと飛ばした問は入れない）。</p>')


def fix_thinking_bars(summary: dict[str, Any]) -> str:
    rows = []
    for model in summary["models"]:
        for position, condition in enumerate(summary["conditions"]):
            key = model["key"]
            not_run = summary["not_run"][key][condition]
            value = None if not_run else summary["combined"][key][condition]["thinking_tokens_median"]
            rows.append({"label": f"{model['short']} · {cond_label(summary, condition)}",
                         "style": 0 if condition == summary["baseline"] else 1, "value": value,
                         "new_group": position == 0, "none_text": NOT_RUN_TEXT if not_run else None,
                         "tip": f"思考（推定）{fmt_number(value, 0, 'トークン')}\n{model['short']}\n{cond_label(summary, condition)}"})
    legend = ('<div class="legend" aria-label="棒の凡例"><span class="legend-item"><span class="swatch swatch-int8"></span>斜線 = 基準</span>'
              f'<span class="legend-item"><span class="swatch swatch-fp16"></span>塗り = 基準と比べる条件</span>'
              f'<span class="legend-item"><span class="swatch" style="background:{COLOR_STRATA}"></span>色は Strata の紫</span></div>')
    return legend + cond_bar_chart(rows, title="思考（推定）トークンの中央値", value_label=lambda value: f"{value:,.0f}",
                                   tick_label=lambda value: f"{value / 1000:g}k", label_width=350)


def fix_section_ends(summary: dict[str, Any]) -> str:
    return ('<h3>終わり方の内訳（条件 × モデル。C4・C5 の合計）</h3>' + ends_legend(summary) + ends_chart(summary)
            + '<p class="caption">棒は 1 回ごとの終わり方を数えた積み上げ。棒の中の数字は回数（幅が足りないときは省く。マウスを重ねると出る）。'
              '右の「答えあり」は答えが出た回数 / 記録のある回数。灰色の 3 種は斜線の向きで区別する（無地 = 上限まで答えなし、'
              '45° = 繰り返しで停止、135° = 思考中停止）。</p>'
            + '<h3>思考（推定）トークンの中央値（条件 × モデル）</h3>' + fix_thinking_bars(summary)
            + fix_ends_table(summary))


# ---- 推奨・所見・注意


def fix_section_recommendations(findings: dict[str, Any] | None) -> str:
    lines = string_list(findings, "recommendations")
    return bullet_list(lines) if lines else unfilled("推奨の設定と申し送りは findings.json の recommendations（文の配列）に書くと、ここに出る。")


def fix_section_findings(findings: dict[str, Any] | None) -> str:
    facts, opinions = string_list(findings, "facts"), string_list(findings, "opinions")
    if not facts and not opinions:
        return unfilled("所見は findings.json の facts と opinions（文の配列）に書くと、ここに出る。")
    return ('<h3>事実</h3>' + (bullet_list(facts) if facts else unfilled("")) +
            '<h3>意見（解釈）</h3>' + (bullet_list(opinions) if opinions else unfilled("")))


def fix_server_tables(summary: dict[str, Any]) -> str:
    """条件 × モデルの起動の記録と、モデルの unit の journal の行数。"""

    start_rows = []
    for model in summary["models"]:
        for condition in summary["conditions"]:
            server = summary["servers"][model["key"]].get(condition)
            head = f'<tr><td>{model_label(model)}</td><td class="left">{esc(condition)}</td>'
            if server is None:
                if summary["not_run"][model["key"]][condition]:
                    reason = NOT_RUN_TEXT
                elif condition in (summary.get("sources") or {}):
                    reason = "起動の記録なし（既存の記録の写しで、この調査では起動していない）"
                else:
                    reason = "起動の記録なし"
                start_rows.append(f'{head}<td colspan="8" class="muted">{reason}</td></tr>')
                continue
            peak = server.get("memory_peak_bytes")
            start_rows.append(
                f'{head}<td>{esc(str(server.get("status")))}</td>'
                f'<td class="num">{fmt_number(server.get("start_s"), 0, "秒")}</td>'
                f'<td class="num">{fmt_number(server.get("slots_filled"), 0)} / {fmt_number(server.get("slots_total"), 0)}</td>'
                f'<td class="num">{fmt_number(server.get("cache_hit_pct"), 1, "%")}</td>'
                f'<td class="num">{fmt_number(server.get("vram_used_mib"), 0, "MiB")}</td>'
                f'<td class="num">{fmt_number(peak / 1024 ** 3 if peak is not None else None, 2, "GiB")}</td>'
                f'<td class="num">{esc(", ".join(f"rep{rep}" for rep in server.get("reps") or []) or "—")}</td>'
                f'<td>{esc(str(server.get("engine_kv") or "—"))}</td></tr>')
    journal_rows = []
    for model in summary["models"]:
        data = (summary.get("journal_counts") or {}).get(model["key"])
        if not data:
            journal_rows.append(f'<tr><td>{model_label(model)}</td><td colspan="5" class="muted">journal の記録なし</td></tr>')
            continue
        scopes = [("起動から停止まで", (data.get("total") or {}).get("counts"))]
        scopes += [(f"条件 {arm}", (entry or {}).get("counts")) for arm, entry in (data.get("arms") or {}).items()]
        for scope, counts in scopes:
            if not counts:
                journal_rows.append(f'<tr><td>{model_label(model)}</td><td class="left">{esc(scope)}</td><td colspan="4" class="muted">記録なし</td></tr>')
                continue
            journal_rows.append(
                f'<tr><td>{model_label(model)}</td><td class="left">{esc(scope)}</td>'
                f'<td class="num">{counts.get("repeated_reasoning", 0)}</td><td class="num">{counts.get("thinking_budget_reached", 0)}</td>'
                f'<td class="num">{counts.get("max_tokens_reached", 0)}</td><td class="num">{counts.get("lines", 0):,}</td></tr>')
    return ('<h3>サーバーの起動の記録</h3>'
            '<table class="data wide"><thead><tr><th>モデル</th><th>条件</th><th>結果</th><th>起動</th><th>エキスパートの枠</th>'
            '<th>キャッシュ命中率</th><th>VRAM</th><th>RAM（memory.peak）</th><th>この起動で流した回</th><th>起動行の --kv</th></tr></thead>'
            f'<tbody>{"".join(start_rows)}</tbody></table>'
            '<p class="caption">1 回の起動で複数の条件を続けて流したので、枠は同じ値、RAM の memory.peak は起動からの最大値（条件ごとには分けていない）。'
            '命中率はその条件を流した間のエンジンのログの行から、VRAM は条件を流し終えた直後の値。</p>'
            '<h3>journal の行数（モデルの unit）</h3>'
            '<table class="data wide"><thead><tr><th>モデル</th><th>範囲</th><th>ループの回復（repeated reasoning detected）</th>'
            '<th>思考の予算に届いた（thinking budget reached）</th><th>生成の上限に届いた（the reply reached max tokens）</th>'
            '<th>journal の全行数</th></tr></thead>'
            f'<tbody>{"".join(journal_rows)}</tbody></table>'
            '<p class="caption">journalctl --user -u &lt;unit&gt; の出力で、文を含む行を数えた。上限なしの条件で「思考の予算に届いた」が 0 なら、'
            '予算は効いていない。ループの回復は Strata の既定（有効）のまま使った。</p>')


def fix_section_notes(summary: dict[str, Any], findings: dict[str, Any] | None) -> str:
    record_counts = sorted({stats["n_records"] for per_model in summary["results"].values()
                            for per_item in per_model.values() for stats in per_item.values()} - {0})
    count_text = (str(record_counts[0]) if len(record_counts) == 1 else f"{record_counts[0]}〜{record_counts[-1]}") if record_counts else "—"
    max_tokens = sorted({entry["max_tokens"] for seen in summary["limits_seen"].values() for entry in seen
                         if isinstance(entry.get("max_tokens"), int)})
    max_tokens_text = " と ".join(f"{value:,}" for value in max_tokens) or "—"
    baseline = summary["baseline"]
    notes = string_list(findings, "caveats")
    notes += [
        f"試行は各条件・各問 {count_text} 回だけで少ない。サンプリングありで、同じ条件でも回によって点が大きく変わりうる。"
        "最小〜最大の幅が重なる差は「差は判定できない」とし、差があるとは言わない。",
        f"生成の上限が条件で違う（{max_tokens_text}）。条件どうしの点の差には、思考の強さ・思考の上限の差だけでなく、生成の上限の差も混ざる。",
        "Ollama のモデルは同じ問題を生成の上限 32,768・思考の上限なしで測っている（AI モデル評価）。Strata の生成の上限が 65,536 の条件とは"
        "上限が違うので、直接は比べられない。",
        "隠しテストは C4 と C5 の 2 問だけ。ほかの問（C1〜C3・C6）や追加の試験では確かめていない。",
        "「答えが出た」は、本文が空でなく採点できた回。生成の上限で途中で切れた答えも数える（採点は切れた本文のコードで行う）。"
        "思考トークンは推定（出力トークン × 思考の文字数 ÷ (思考 + 本文の文字数)）。",
    ]
    if baseline in (summary.get("sources") or {}):
        notes.append(f"基準「{cond_label(summary, baseline)}」の記録は、この調査のために流したものではなく別の日のもの"
                     "（rep1 は 2026-10-08、rep2・rep3 は 2026-10-09 の KV の比べの int8）。ほかの条件の記録とは機体の状態"
                     "（温度・空きメモリ・起動のたびのエキスパートの枠）が違うかもしれない。")
    for key, reason in (summary.get("excluded") or {}).items():
        target = targets_module.get(key)
        notes.append(f"外したモデル: {SHORT_NAMES.get(key, target.label)}（{key}）— {reason}。集計・表・図・足りない記録の一覧に入れていない"
                     "（記録のファイルは残してある）。")
    not_run = [f"{model['short']} × {cond_label(summary, condition)}" for model in summary["models"]
               for condition in summary["conditions"] if summary["not_run"][model["key"]][condition]]
    if not_run:
        notes.append("流していない組（記録が 1 本も無い。足りない記録には数えない）: " + "、".join(not_run) + "。")
    data_paths = [
        ("記録", f"{summary['root']}/<条件>/rep<1〜3>/local/<slug>/coding/<c4|c5>-run1.json（やり直した問の 1 回目は -run1.attempt1.json）"),
        ("起動の記録", f"{summary['root']}/<条件>/server-<slug>.json（journal-*.txt は起動の失敗時）"),
        ("journal の行数", f"{summary['root']}/journal-counts-<slug>.json"),
        ("外したモデル", f"{summary['root']}/excluded.json"),
        ("基準の写し元", f"{summary['root']}/{baseline}/source.json"),
        ("集計", f"{summary['root']}/summary.json"),
        ("実行の記録", f"{summary['root']}/DONE と tools/model-eval/work/run_fix_compare-{summary['date']}.log"),
        ("問題と隠しテスト", "tools/model-eval/suites/coding/c4・c5（英語版は prompt.en.md、対応表は TRANSLATION_NOTES.md）"),
    ]
    path_rows = "".join(f"<tr><th>{esc(name)}</th><td><code>{esc(path)}</code></td></tr>" for name, path in data_paths)
    formula = "".join(f"<li>{esc(line)}</li>" for line in FIX_FORMULA)
    end_rules = [
        "思考の途中で停止トークン（status が eos_in_thinking。古い記録の finish が stop・本文が空・思考ありも同じ）→ eos_in_thinking",
        "status が length で、completion_tokens が記録の生成の上限（limits.max_tokens。無い古い記録は 32,768）未満 → repeat_stop",
        "status が length で、上限以上・本文なし → no_answer_at_limit",
        "status が length で、上限以上・本文あり → answer_truncated。ただし思考に Strata の打ち切り文があれば budget_cut（途中切れの印つき）",
        "status が ok → 思考に Strata の打ち切り文があれば budget_cut、なければ self_finished",
        "それ以外（error・timeout・stall、本文が空の異常な ok）→ error。記録が無い・飛ばした → missing",
    ]
    end_rule_html = "".join(f"<li>{esc(line)}</li>" for line in end_rules)
    problems = [str(line) for line in summary.get("warnings") or []] + [str(line) for line in summary.get("missing") or []]
    problem_html = "".join(f"<li>{esc(line)}</li>" for line in problems)
    return (bullet_list(notes)
            + f'<h3>点の判定の規則</h3><ul class="notes formulas">{formula}</ul>'
            + '<p class="caption">条件ごと・モデル × 問ごとに、基準の 3 回と比べる。最小と最大だけを比べる（平均は使わない）。差は平均の差（条件 − 基準）。</p>'
            + f'<h3>終わり方の分類の規則</h3><ul class="notes formulas">{end_rule_html}</ul>'
            + f'<h3>生データの場所</h3><table class="data kv"><tbody>{path_rows}</tbody></table>'
            + (f'<h3>足りない記録・条件の食い違い</h3><ul class="notes">{problem_html}</ul>' if problems else "")
            + f'<details><summary>起動の記録と journal の行数</summary>{fix_server_tables(summary)}</details>')


def build_fix_html(summary: dict[str, Any], findings: dict[str, Any] | None = None,
                   settings: list[dict[str, Any]] | None = None) -> str:
    sections = [
        ("s0", "0. 結論", fix_section_conclusion(summary, findings)),
        ("s1", "1. 調べた設定", fix_section_settings(summary, findings, settings)),
        ("s2", "2. 証拠", fix_section_evidence(findings)),
        ("s3", "3. 条件ごとの結果", fix_section_results(summary)),
        ("s4", "4. 終わり方の内訳", fix_section_ends(summary)),
        ("s5", "5. 推奨の設定と申し送り", fix_section_recommendations(findings)),
        ("s6", "6. 所見", fix_section_findings(findings)),
        ("s7", "7. 注意と生データ", fix_section_notes(summary, findings)),
    ]
    toc = "".join(f'<li><a href="#{anchor}">{esc(title)}</a></li>' for anchor, title, _body in sections)
    body = "".join(f'<section id="{anchor}"><h2>{esc(title)}</h2>{content}</section>' for anchor, title, content in sections)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Strata のコーディング性能の調査 {esc(summary["date"])}</title>'
        f'<style>{build_report.STYLE}{FIX_STYLE}</style></head>'
        f'<body class="viz-root">{HATCH_DEFS}{end_defs()}<main>'
        '<h1>Strata のコーディング性能の調査（思考の強さ・思考の上限・問題文の言語・C4・C5）</h1>'
        f'<p class="sub">計測 {esc(summary["date"])}・集計 {esc(summary["generated_at"])}・'
        'tools/model-eval/cond_compare.py が記録から生成（手で書き換えない）。基準 = '
        f'{esc(cond_label(summary, summary["baseline"]))}、ほかの条件を全部基準と比べる</p>'
        f'<nav aria-label="目次"><ol>{toc}</ol></nav>{body}</main>'
        f'<div id="tip" role="tooltip" hidden></div><script>{build_report.SCRIPT}</script></body></html>\n'
    )


# ------------------------------------------------------------------------------------------------ コマンド


def cmd_report(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    findings_path = Path(args.findings) if args.findings else root / "findings.json"
    findings = common.read_json(findings_path) if findings_path.exists() else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.kind == KIND_KV:
        summary = common.read_json(Path(args.summary)) if args.summary else build_summary(root)
        out.write_text(build_kv_html(summary, findings), encoding="utf-8")
    else:
        conditions, labels = parse_conditions(args.conditions, args.labels)
        summary = common.read_json(Path(args.summary)) if args.summary else build_fix_summary(root, conditions, labels)
        settings = common.read_json(Path(args.settings_table)) if args.settings_table else None
        out.write_text(build_fix_html(summary, findings, settings), encoding="utf-8")
    print(f"{out} を書いた（{out.stat().st_size:,} バイト）")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    print(count_pending(Path(args.root).resolve(), args.cond, args.rep, args.slug, retry_errors=args.retry_errors))
    return 0


def cmd_copy_int8_rep1(args: argparse.Namespace) -> int:
    actions = copy_int8_rep1(Path(args.root).resolve(), Path(args.source_dir).resolve(), args.slug, dry_run=args.dry_run)
    for action in actions:
        print(("[dry-run] " if args.dry_run else "") + action)
    return 0


def cmd_copy_baseline(args: argparse.Namespace) -> int:
    actions = copy_baseline(Path(args.root).resolve(), args.arm, Path(args.rep1_source).resolve(),
                            Path(args.reps_source).resolve(), args.slug, dry_run=args.dry_run)
    for action in actions:
        print(("[dry-run] " if args.dry_run else "") + action)
    return 0


def main(argv: list[str] | None = None, *, default_kind: str = KIND_FIX) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_kind(sub_parser: argparse.ArgumentParser) -> None:
        sub_parser.add_argument("--kind", choices=[KIND_FIX, KIND_KV], default=default_kind,
                                help=f"fix = コーディング性能の調査（条件は任意）、kv = KV の型の比べ（int8 と fp16）。既定 {default_kind}")
        sub_parser.add_argument("--conditions", default=None,
                                help="fix の条件の名前（カンマ区切り。先頭が基準で、ほかを全部基準と比べる。"
                                     "既定 budget24k-ja,nobudget-ja,nobudget-en,low-ja,low-65k-ja）")
        sub_parser.add_argument("--labels", default=None,
                                help="--conditions と同じ数の表示名（カンマ区切り。数字に挟まれた「,」は割らない）。無ければ既定の表示名か条件名")

    def add_root(sub_parser: argparse.ArgumentParser) -> None:
        sub_parser.add_argument("--root", default=str(KV_ROOT if default_kind == KIND_KV else FIX_ROOT),
                                help=f"既定 results/{KV_TAG if default_kind == KIND_KV else FIX_TAG}")

    summarize_parser = sub.add_parser("summarize", help="<root>/summary.json を書く")
    add_root(summarize_parser)
    add_kind(summarize_parser)
    summarize_parser.add_argument("--out", default=None, help="既定 <root>/summary.json")
    summarize_parser.set_defaults(func=cmd_summarize)

    report = sub.add_parser("report", help="1 ファイルの HTML を作る")
    add_root(report)
    add_kind(report)
    report.add_argument("--summary", default=None, help="既定は記録から集め直す（summary.json は読まない）")
    report.add_argument("--findings", default=None, help="既定 <root>/findings.json（無ければ空欄）")
    report.add_argument("--settings-table", default=None,
                        help="節 1 の表の JSON（項目・Strata・Ollama・判定 を item・strata・ollama・verdict の鍵で並べた配列）。無ければ findings.json の settings")
    report.add_argument("--out", default=str(KV_OUT if default_kind == KIND_KV else FIX_OUT))
    report.set_defaults(func=cmd_report)

    server = sub.add_parser("server-info", help="条件ごとの起動の記録 <root>/<条件>/server-<slug>.json を書く")
    add_root(server)
    server.add_argument("--cond", "--kv", dest="cond", required=True, help="条件の名前（fix の腕、KV の比べでは int8 / fp16）")
    server.add_argument("--target", required=True, help="targets.py の key")
    server.add_argument("--unit", required=True, help="systemd user unit（cgroup の memory.peak を読む）")
    server.add_argument("--slug", default=None, help="既定は target の slug")
    server.add_argument("--engine-log", required=True)
    server.add_argument("--after-line", type=int, default=0, help="起動の前に数えたログの行数")
    server.add_argument("--hits-after-line", type=int, default=0,
                        help="命中率の行を、ログの先頭から数えてこの行数より後ろのものだけにする（1 回の起動で複数の条件を流すとき）")
    server.add_argument("--start-s", type=float, default=None)
    server.add_argument("--status", required=True, choices=SERVER_STATUSES)
    server.add_argument("--reps", default="", help="この条件で流した回（例 \"2 3\"）")
    server.add_argument("--vram-before", type=int, default=None, help="起動の前の VRAM 使用（MiB）")
    server.set_defaults(func=cmd_server_info)

    journal = sub.add_parser("journal-counts", help="モデルの unit の journal の行数を <root>/journal-counts-<slug>.json に書く")
    add_root(journal)
    journal.add_argument("--slug", required=True)
    journal.add_argument("--unit", required=True)
    journal.add_argument("--since", required=True, help="journalctl --since に渡す時刻（例 \"2026-10-09 15:00:00\"）")
    journal.add_argument("--until", default=None)
    journal.add_argument("--arm", default=None, help="条件の名前。付けると条件ごとの欄に、無ければ起動からの全部の欄に書く")
    journal.add_argument("--journal-file", default=None, help="journalctl の代わりに読むファイル（試験用）")
    journal.set_defaults(func=cmd_journal_counts)

    check = sub.add_parser("check-kv", help="engine の最後の起動行の --kv を確かめる（0 一致・1 不一致）")
    check.add_argument("--log", required=True)
    check.add_argument("--after-line", type=int, default=0)
    check.add_argument("--kv", required=True, choices=KV_TYPES)
    check.set_defaults(func=cmd_check_kv)

    pending = sub.add_parser("pending", help="まだ流していない問（C4・C5）の数")
    add_root(pending)
    pending.add_argument("--cond", "--kv", dest="cond", required=True, help="条件の名前")
    pending.add_argument("--rep", required=True, type=int)
    pending.add_argument("--slug", required=True)
    pending.add_argument("--retry-errors", action="store_true")
    pending.set_defaults(func=cmd_pending)

    copy = sub.add_parser("copy-int8-rep1", help="既存の int8 の記録を rep1 に写し、source.json を書く（KV の比べ）")
    add_root(copy)
    copy.add_argument("--source-dir", default=str(SOURCE_DIR))
    copy.add_argument("--slug", action="append", required=True)
    copy.add_argument("--dry-run", action="store_true")
    copy.set_defaults(func=cmd_copy_int8_rep1)

    baseline = sub.add_parser("copy-baseline", help="基準（思考の上限 24,576）の既存の記録を <条件>/rep1〜3 に写し、source.json を書く（fix）")
    add_root(baseline)
    baseline.add_argument("--arm", default=COND_BASELINE, help=f"写し先の条件の名前（既定 {COND_BASELINE}）")
    baseline.add_argument("--rep1-source", default=str(BASELINE_REP1_SOURCE), help="rep1 の写し元（既定 results/2026-10-08）")
    baseline.add_argument("--reps-source", default=str(BASELINE_REPS_SOURCE),
                          help="rep2・rep3 の写し元（<dir>/rep<N>/local/…。既定 results/2026-10-09-kv/int8）")
    baseline.add_argument("--slug", action="append", required=True)
    baseline.add_argument("--dry-run", action="store_true")
    baseline.set_defaults(func=cmd_copy_baseline)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
