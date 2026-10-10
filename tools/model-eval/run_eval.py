#!/usr/bin/env python3
"""ローカルの 7 モデルにコーディング 6 問と追加 3 試験（各 3 問）を解かせて採点し、Claude の答えも同じ採点器にかける。

  run_eval.py run --target gemma4:e4b --suite all                 # 1 モデルを全問（途中からの再開に対応）
  run_eval.py run --target gemma4:e4b --suite coding --limit 1 --results-dir work/smoke
  run_eval.py run --target strata-official:IQ3_XXS --suite extra --retry-errors
  run_eval.py run --target strata-official:IQ3_XXS --suite coding --items c4,c5 --reasoning-budget 0 --max-tokens 65536 \\
      --prompt-lang en --results-dir work/fix                     # 思考の上限なし・生成 65,536・英語の問題文
  run_eval.py grade-claude                                        # results/<日付>/claude/ の答えを採点して書き戻す
  run_eval.py regrade --target gemma4:e4b                         # ローカルの記録を（問い合わせずに）採点し直す
  run_eval.py unload --target gemma4:e4b                          # Ollama のモデルを VRAM から降ろす（keep_alive:0）
  run_eval.py pending --target strata-official:IQ3_XXS            # 流す必要のある問の数（run_local.sh が使う）
  run_eval.py show-prompt --suite coding --item c1 [--for-claude] # 送る問題文の全文を出す
  run_eval.py list                                                # 対象と問の一覧

記録は 1 要求につき 1 つの JSON（results/<日付>/local/<slug>/<suite>/<問>-run1.json）。既にある問は飛ばす
（status が error のものは --retry-errors、skipped_time_budget のものは --retry-skipped で流し直す。--redo は全部）。
1 つのモデルの累計時間（ロードを除く壁時計）が 100 分を超えたら、残りの問を skipped_time_budget として記録する。
思考の途中で停止トークンが出て本文が空だった要求（status が eos_in_thinking）は、--retry-eos（既定）なら 1 回だけ同じ要求を流し直す。
1 回目の記録は <問>-run1.attempt1.json に残し、2 回目を <問>-run1.json に書く（attempts と first_attempt_status を付ける）。
標準ライブラリのみ。/usr/bin/python3 で動く。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import targets as targets_module  # noqa: E402
from evallib import clients, common, sandbox  # noqa: E402
from suites.extra import grade_extra  # noqa: E402

# Ollama のモデルを読み込む要求の時間上限（IQ4_XS は 97 GB をディスクから読む）
PRELOAD_TIMEOUT_S = 30 * 60
# 実行中にモデルを VRAM に留めておく時間（最後は unload で降ろす）
DEFAULT_KEEP_ALIVE = "15m"
NO_ANSWER_STATUSES = {common.STATUS_TIMEOUT, common.STATUS_STALL, common.STATUS_ERROR, common.STATUS_SKIPPED,
                      common.STATUS_EOS_IN_THINKING}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ------------------------------------------------------------------------------------------------ 採点


def grade_answer(suite: str, item: str, content: str, status: str, work_dir: Path) -> dict[str, Any]:
    """1 問の答えを採点する。答えなし・上限で空・時間切れ・stall・エラーは 0 点（reason に理由）。"""

    if status in NO_ANSWER_STATUSES:
        return {"kind": suite, "score": 0.0, "all_passed": False, "no_answer": True, "reason": status}
    if not (content or "").strip():
        reason = "length（上限に達して本文が無い）" if status == common.STATUS_LENGTH else "本文が無い"
        return {"kind": suite, "score": 0.0, "all_passed": False, "no_answer": True, "reason": reason}
    if suite == "coding":
        return sandbox.grade_coding(content, common.item_dir(suite, item), work_dir)
    if suite == "extra":
        return grade_extra.grade_extra(content, common.item_dir(suite, item))
    raise ValueError(f"採点器が無い試験: {suite}")


# ------------------------------------------------------------------------------------------------ 要求の組み立て


# Strata に送る思考の強さ（reasoning_effort）。high はテンプレートの xhigh の文、low は low の文、medium は文なし。
# Ollama には送らない（think:true の既定で、qwen3.8 の renderer が xhigh の文を入れる）
REASONING_EFFORTS = ("low", "medium", "high")
DEFAULT_REASONING_EFFORT = "high"


def effective_limits(suite: str, max_tokens: int | None = None, reasoning_budget: int | None = None) -> dict[str, Any]:
    """試験ごとの既定の上限（common.SUITE_LIMITS）を、引数で上書きしたもの。None は既定のまま。

    reasoning_budget は 0 のとき「上限なし」（Strata は要求の 0 を予算なしと読む）。
    """

    limits = dict(common.SUITE_LIMITS[suite])
    if max_tokens is not None:
        limits["max_tokens"] = max_tokens
    if reasoning_budget is not None:
        limits["reasoning_budget_tokens"] = reasoning_budget
    return limits


def sent_limits(target: targets_module.Target, limits: dict[str, Any]) -> dict[str, Any]:
    """記録の limits に書く、実際に送った上限。思考の予算は Strata の要求にだけ付くので、Ollama は None。"""

    return {"max_tokens": limits["max_tokens"],
            "reasoning_budget_tokens": limits["reasoning_budget_tokens"] if target.backend == "strata" else None,
            "request_timeout_s": limits["request_timeout_s"]}


def build_payload(target: targets_module.Target, suite: str, prompt: str, keep_alive: str, *,
                  max_tokens: int | None = None, reasoning_budget: int | None = None,
                  reasoning_effort: str = DEFAULT_REASONING_EFFORT) -> dict[str, Any]:
    limits = effective_limits(suite, max_tokens, reasoning_budget)
    messages = [{"role": "user", "content": prompt}]
    if target.backend == "ollama":
        # サンプリングと num_ctx は送らない（各 Modelfile とサーバーの既定で動かす）
        return {"model": target.model, "messages": messages, "stream": True, "think": True,
                "options": {"num_predict": limits["max_tokens"]}, "keep_alive": keep_alive}
    if target.backend == "strata":
        # reasoning_budget_tokens が 0 のときも鍵を 0 で送る（Strata は要求の 0 を「予算なし」と読み、設定 JSON の予算より優先する）
        return {"model": target.model, "messages": messages, "stream": True, "max_tokens": limits["max_tokens"],
                "reasoning_effort": reasoning_effort, "reasoning_budget_tokens": limits["reasoning_budget_tokens"],
                **targets_module.STRATA_SAMPLING}
    raise ValueError(f"{target.key} はローカルのモデルではない")


def send(target: targets_module.Target, payload: dict[str, Any], suite: str) -> dict[str, Any]:
    deadline = common.SUITE_LIMITS[suite]["request_timeout_s"]
    if target.backend == "ollama":
        return clients.chat_ollama(target.base_url, payload, stall_s=common.STALL_TIMEOUT_S, deadline_s=deadline)
    return clients.chat_strata(target.base_url, payload, stall_s=common.STALL_TIMEOUT_S, deadline_s=deadline)


# ------------------------------------------------------------------------------------------------ サーバーの確認


def gpu_snapshot() -> dict[str, Any] | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout.strip().splitlines()[0]
        used, total, utilization = (int(part.strip()) for part in output.split(","))
        return {"memory_used_mib": used, "memory_total_mib": total, "utilization_pct": utilization}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def ollama_ps(target: targets_module.Target) -> dict[str, Any] | None:
    try:
        models = clients.get_json(target.base_url + "/api/ps").get("models") or []
    except (OSError, ValueError):
        return None
    for entry in models:
        if entry.get("name") == target.model or entry.get("model") == target.model:
            size, size_vram = entry.get("size") or 0, entry.get("size_vram") or 0
            return {"name": entry.get("name"), "size": size, "size_vram": size_vram,
                    "gpu_ratio": round(size_vram / size, 3) if size else None,
                    "context_length": entry.get("context_length"), "expires_at": entry.get("expires_at")}
    return None


def preflight(target: targets_module.Target, keep_alive: str, preload: bool) -> dict[str, Any]:
    """サーバーとモデルがあるかを確かめ、Ollama ならモデルを先に読み込む（ロード時間を問の時間から外すため）。"""

    info: dict[str, Any] = {"checked_at": common.now_iso(), "gpu_before": gpu_snapshot()}
    if target.backend == "ollama":
        tags = clients.get_json(target.base_url + "/api/tags")
        names = {model.get("name") for model in tags.get("models") or []}
        if target.model not in names:
            raise SystemExit(f"Ollama に {target.model} がありません。先に ollama pull {target.model}")
        try:
            info["ollama_version"] = clients.get_json(target.base_url + "/api/version").get("version")
        except (OSError, ValueError):
            info["ollama_version"] = None
        if preload:
            log(f"{target.model} を読み込みます（keep_alive {keep_alive}）")
            started = time.monotonic()
            response = clients.post_json(target.base_url + "/api/generate",
                                         {"model": target.model, "keep_alive": keep_alive}, PRELOAD_TIMEOUT_S)
            info["preload_s"] = round(time.monotonic() - started, 2)
            load_ns = response.get("load_duration")
            info["preload_load_duration_s"] = round(load_ns / 1e9, 2) if isinstance(load_ns, int) else None
            info["ollama_ps"] = ollama_ps(target)
            log(f"読み込み {info['preload_s']} 秒、配置 {info['ollama_ps']}")
    elif target.backend == "strata":
        models = clients.get_json(target.base_url + "/models")
        ids = [model.get("id") for model in models.get("data") or []]
        info["strata_models"] = ids
        if target.model not in ids:
            raise SystemExit(f"{target.base_url} のモデルは {ids}。{target.model} ではありません"
                             f"（systemctl --user start {target.unit} で起動しているか）")
    info["gpu_after_preload"] = gpu_snapshot()
    return info


def append_meta(results_dir: Path, target: targets_module.Target, session: dict[str, Any]) -> None:
    path = results_dir / "local" / target.slug / "meta.json"
    meta = common.read_json(path) if path.exists() else {"target": target.key, "slug": target.slug, "sessions": []}
    meta["sessions"].append(session)
    common.write_json(path, meta)


# ------------------------------------------------------------------------------------------------ run


def used_seconds(results_dir: Path, target: targets_module.Target) -> float:
    total = 0.0
    for _path, record in common.iter_local_records(results_dir, target.slug):
        if record.get("status") == common.STATUS_SKIPPED:
            continue
        total += float(record.get("wall_excl_load_s") or record.get("wall_s") or 0.0)
    # やり直した問の 1 回目の分も足す（<問>-run1.attempt1.json）
    for _path, record in common.iter_attempt_records(results_dir, target.slug):
        total += float(record.get("wall_excl_load_s") or record.get("wall_s") or 0.0)
    return total


def selected_items(suite_arg: str, items_arg: str | None, limit: int | None) -> list[tuple[str, str]]:
    suites = ("coding", "extra") if suite_arg == "all" else (suite_arg,)
    pairs = [(suite, item) for suite in suites for item in common.SUITE_ITEMS[suite]]
    if items_arg:
        wanted = {item.strip() for item in items_arg.split(",") if item.strip()}
        unknown = wanted - {item for _suite, item in pairs}
        if unknown:
            raise SystemExit(f"知らない問: {', '.join(sorted(unknown))}")
        pairs = [pair for pair in pairs if pair[1] in wanted]
    return pairs[:limit] if limit else pairs


def should_run(path: Path, args: argparse.Namespace) -> bool:
    if args.redo or not path.exists():
        return True
    status = common.read_json(path).get("status")
    if status == common.STATUS_ERROR and args.retry_errors:
        return True
    if status == common.STATUS_SKIPPED and args.retry_skipped:
        return True
    return status not in common.FINAL_STATUSES and status != common.STATUS_ERROR


def base_record(target: targets_module.Target, suite: str, item: str, prompt: str, *, lang: str = "ja",
                limits: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {"schema": 1, "target": target.key, "label": target.label, "family": target.family,
              "backend": target.backend, "model": target.model, "slug": target.slug, "suite": suite, "item": item,
              "run": 1, "prompt": prompt, "prompt_chars": len(prompt), "prompt_lang": lang}
    if limits is not None:
        record["limits"] = sent_limits(target, limits)
    return record


def run_attempt(target: targets_module.Target, suite: str, item: str, prompt: str, payload: dict[str, Any],
                work_dir: Path, *, lang: str, limits: dict[str, Any]) -> dict[str, Any]:
    """1 要求を送って、採点まで済ませた記録を返す（書き出しは呼び出し側）。"""

    record = base_record(target, suite, item, prompt, lang=lang, limits=limits)
    record["request"] = {key: value for key, value in payload.items() if key != "messages"}
    record["started_at"] = common.now_iso()
    result = send(target, payload, suite)
    record["finished_at"] = common.now_iso()
    record.update(result)
    record["has_answer"] = bool((record.get("content") or "").strip())
    load = record.get("load_s") or 0.0
    record["wall_excl_load_s"] = round(record["wall_s"] - load, 3) if record.get("wall_s") is not None else None
    record["grade"] = grade_answer(suite, item, record.get("content") or "", record["status"], work_dir)
    return record


def log_record(suite: str, item: str, record: dict[str, Any]) -> None:
    log(f"{suite}/{item}: {record['status']} 点 {record['grade'].get('score')} "
        f"出力 {record.get('completion_tokens')} トークン（思考 約 {record.get('thinking_tokens_est')}）"
        f" {record.get('wall_excl_load_s')} 秒 {record.get('server_decode_tok_s')} tok/s"
        + (f" エラー: {record.get('error')}" if record.get("error") else ""))


def cmd_run(args: argparse.Namespace) -> int:
    target = targets_module.get(args.target)
    if target.backend == "claude":
        raise SystemExit("Claude はメインが Agent ツールで流す。ここでは grade-claude を使う")
    for name in ("max_tokens", "reasoning_budget"):
        value = getattr(args, name)
        if value is not None and value < 0:
            raise SystemExit(f"--{name.replace('_', '-')} は 0 以上")
    results_dir = Path(args.results_dir).resolve() if args.results_dir else common.results_dir_for(args.date)
    budget_s = args.time_budget_min * 60
    pairs = selected_items(args.suite, args.items, args.limit)
    todo = [(suite, item) for suite, item in pairs
            if should_run(common.local_record_path(results_dir, target.slug, suite, item), args)]
    lang = args.prompt_lang
    log(f"{target.label}: {len(pairs)} 問のうち {len(todo)} 問を流す（結果 {results_dir}）")
    if args.dry_run:
        # 上書きした上限と問題文の言語を確かめられるように、記録済みで飛ばす問も含めて表示する
        for suite, item in pairs:
            limits = sent_limits(target, effective_limits(suite, args.max_tokens, args.reasoning_budget))
            prompt_chars = len(common.build_prompt(suite, item, lang))
            state = "流す" if (suite, item) in todo else "記録済みで飛ばす"
            print(f"  {suite}/{item}: {state}。問題文 {lang} {prompt_chars:,} 文字、上限 {json.dumps(limits, ensure_ascii=False)}"
                  f"、思考の強さ {args.reasoning_effort if target.backend == 'strata' else '（Ollama は既定）'}"
                  f"、思考中の停止トークンのやり直し {'あり' if args.retry_eos else 'なし'}")
        return 0
    if not todo:
        return 0

    session = {"started_at": common.now_iso(), "argv": sys.argv[1:], "items": [f"{s}/{i}" for s, i in todo],
               "prompt_lang": lang, "retry_eos": args.retry_eos}
    session.update(preflight(target, args.keep_alive, preload=not args.no_preload))
    append_meta(results_dir, target, session)

    errors = 0
    for suite, item in todo:
        path = common.local_record_path(results_dir, target.slug, suite, item)
        prompt = common.build_prompt(suite, item, lang)
        limits = effective_limits(suite, args.max_tokens, args.reasoning_budget)
        spent = used_seconds(results_dir, target)
        if spent >= budget_s:
            record = base_record(target, suite, item, prompt, lang=lang, limits=limits)
            record.update({"started_at": common.now_iso(), "status": common.STATUS_SKIPPED,
                           "error": f"累計 {spent / 60:.1f} 分が上限 {args.time_budget_min} 分を超えた",
                           "content": "", "thinking": "", "has_answer": False, "wall_s": None,
                           "wall_excl_load_s": None})
            record["grade"] = grade_answer(suite, item, "", common.STATUS_SKIPPED, Path())
            common.write_json(path, record)
            log(f"{suite}/{item}: skipped_time_budget（累計 {spent / 60:.1f} 分）")
            continue
        payload = build_payload(target, suite, prompt, args.keep_alive,
                                max_tokens=args.max_tokens, reasoning_budget=args.reasoning_budget,
                                reasoning_effort=args.reasoning_effort)
        work_dir = common.WORK_DIR / results_dir.name / target.slug / item
        log(f"{suite}/{item}: 送信（累計 {spent / 60:.1f} 分）")
        record = run_attempt(target, suite, item, prompt, payload, work_dir, lang=lang, limits=limits)
        record["attempts"] = 1
        log_record(suite, item, record)
        if record["status"] == common.STATUS_EOS_IN_THINKING and args.retry_eos:
            # 1 回目の記録を残してから、同じ要求を 1 回だけ流し直す（2 回目も eos なら、そのまま 0 点で記録する）
            first_status = record["status"]
            common.write_json(common.attempt_record_path(path, 1), record)
            log(f"{suite}/{item}: 思考中に停止トークン。1 回やり直す（1 回目の記録は {common.attempt_record_path(path, 1).name}）")
            record = run_attempt(target, suite, item, prompt, payload, work_dir, lang=lang, limits=limits)
            record["attempts"] = 2
            record["first_attempt_status"] = first_status
            log_record(suite, item, record)
        common.write_json(path, record)
        if record["status"] == common.STATUS_ERROR:
            errors += 1
    return 1 if errors else 0


# ------------------------------------------------------------------------------------------------ 採点し直し


CLAUDE_REQUIRED = ("model", "suite", "item", "run", "content", "wall_s", "tool_uses")
MATH3D_KEYS = ("q1", "q2", "q3", "q4")


def cmd_grade_claude(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir).resolve() if args.results_dir else common.results_dir_for(args.date)
    problems = 0
    graded = 0
    for path, record in common.iter_claude_records(results_dir):
        relative = path.relative_to(results_dir)
        missing = [key for key in CLAUDE_REQUIRED if key not in record]
        if missing:
            print(f"形式の不足 {relative}: {', '.join(missing)}")
            problems += 1
            continue
        if args.model and record["model"] != args.model:
            continue
        expected_name = f"{record['item']}-run{record['run']}.json"
        if path.name != expected_name or path.parent.name != record["suite"] or path.parent.parent.name != record["model"]:
            print(f"置き場所と中身が合わない {relative}（中身: {record['model']}/{record['suite']}/{expected_name}）")
            problems += 1
        if record.get("tool_uses"):
            print(f"ツールを使った回（無効。やり直す）: {relative} tool_uses={record['tool_uses']}")
            problems += 1
        suite = record["suite"]
        if suite == "math3d":
            grade = record.get("grade")
            if not isinstance(grade, dict) or any(key not in grade for key in MATH3D_KEYS):
                print(f"3D の採点が未記入: {relative}（grade に q1〜q4 を true / false / null で書く）")
                problems += 1
            continue
        if suite not in common.SUITE_ITEMS or record["item"] not in common.SUITE_ITEMS[suite]:
            print(f"知らない試験・問: {relative}")
            problems += 1
            continue
        status = common.STATUS_OK if (record.get("content") or "").strip() else "no_content"
        work_dir = common.WORK_DIR / results_dir.name / f"claude-{record['model']}" / f"{record['item']}-run{record['run']}"
        record["grade"] = grade_answer(suite, record["item"], record.get("content") or "", status, work_dir)
        record["graded_by"] = "run_eval.py grade-claude"
        record["graded_at"] = common.now_iso()
        common.write_json(path, record)
        graded += 1
        print(f"{relative}: 点 {record['grade'].get('score')}"
              + (f"（{record['grade'].get('reason')}）" if record["grade"].get("reason") else ""))
    print(f"採点 {graded} 件、要確認 {problems} 件")
    return 1 if problems else 0


def cmd_regrade(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir).resolve() if args.results_dir else common.results_dir_for(args.date)
    chosen = [targets_module.get(args.target)] if args.target else list(targets_module.LOCAL_TARGETS)
    for target in chosen:
        for path, record in common.iter_local_records(results_dir, target.slug):
            work_dir = common.WORK_DIR / results_dir.name / target.slug / record["item"]
            record["grade"] = grade_answer(record["suite"], record["item"], record.get("content") or "",
                                           record.get("status") or common.STATUS_ERROR, work_dir)
            common.write_json(path, record)
            print(f"{target.slug}/{record['suite']}/{record['item']}: 点 {record['grade'].get('score')}")
    return 0


# ------------------------------------------------------------------------------------------------ その他


def cmd_unload(args: argparse.Namespace) -> int:
    target = targets_module.get(args.target)
    if target.backend != "ollama":
        raise SystemExit("unload は Ollama のモデルだけ（Strata は systemctl --user stop）")
    if ollama_ps(target) is None:
        # 載っていないモデルに keep_alive:0 を送ると、読み込んでから降ろすことになる（IQ4_XS は 97 GB）。送らない
        log(f"{target.model} は載っていない。GPU {gpu_snapshot()}")
        return 0
    try:
        clients.post_json(target.base_url + "/api/generate", {"model": target.model, "keep_alive": 0}, 120)
    except (urllib.error.URLError, OSError) as exc:
        print(f"降ろす要求に失敗: {exc}", file=sys.stderr)
        return 1
    for _ in range(60):
        if ollama_ps(target) is None:
            log(f"{target.model} を降ろした。GPU {gpu_snapshot()}")
            return 0
        time.sleep(1)
    print(f"{target.model} が 60 秒たっても /api/ps に残っている", file=sys.stderr)
    return 1


def cmd_pending(args: argparse.Namespace) -> int:
    """流す必要のある問の数だけを出す（run_local.sh が Strata を起動するかどうかを決めるのに使う）。"""

    target = targets_module.get(args.target)
    results_dir = Path(args.results_dir).resolve() if args.results_dir else common.results_dir_for(args.date)
    pairs = selected_items(args.suite, None, None)
    print(sum(1 for suite, item in pairs
              if should_run(common.local_record_path(results_dir, target.slug, suite, item), args)))
    return 0


def cmd_show_prompt(args: argparse.Namespace) -> int:
    text = common.build_prompt(args.suite, args.item, args.prompt_lang)
    if args.for_claude:
        text = f"{text}\n\n{common.CLAUDE_SUFFIX}"
    sys.stdout.write(text + "\n")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    for target in targets_module.TARGETS:
        print(f"{target.key:32} {target.family:7} {target.slug:28} {target.base_url}")
    for suite, items in common.SUITE_ITEMS.items():
        limits = common.SUITE_LIMITS[suite]
        print(f"{suite}: {', '.join(items)}（max_tokens {limits['max_tokens']}、Strata の思考予算 "
              f"{limits['reasoning_budget_tokens']}、1 要求 {limits['request_timeout_s'] // 60} 分）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_results(sub_parser: argparse.ArgumentParser) -> None:
        sub_parser.add_argument("--results-dir", default=None,
                                help="結果の置き場（既定 results/<--date>）。スモークは work/ の下を指す")
        sub_parser.add_argument("--date", default=common.DEFAULT_DATE, help=f"既定 {common.DEFAULT_DATE}")

    run = sub.add_parser("run", help="ローカルの 1 モデルに問題を解かせて採点する")
    run.add_argument("--target", required=True, help="targets.py の key（例 gemma4:e4b）か slug")
    run.add_argument("--suite", choices=["coding", "extra", "all"], default="all")
    run.add_argument("--items", default=None, help="カンマ区切りで問を絞る（例 c1,c3）")
    run.add_argument("--limit", type=int, default=None, help="先頭から N 問だけ")
    add_results(run)
    run.add_argument("--retry-errors", action="store_true", help="status が error の問を流し直す")
    run.add_argument("--retry-skipped", action="store_true", help="skipped_time_budget の問を流し直す")
    run.add_argument("--redo", action="store_true", help="記録があっても全部流し直す")
    run.add_argument("--time-budget-min", type=float, default=common.MODEL_TIME_BUDGET_S / 60,
                     help="1 モデルの累計時間の上限（分、既定 100）")
    run.add_argument("--keep-alive", default=DEFAULT_KEEP_ALIVE, help="Ollama の keep_alive（既定 15m）")
    run.add_argument("--no-preload", action="store_true", help="Ollama のモデルを先に読み込まない")
    run.add_argument("--dry-run", action="store_true",
                     help="流す問と、上書き後の上限・問題文の言語を表示するだけ（サーバーにつながない）")
    run.add_argument("--max-tokens", type=int, default=None,
                     help="生成の上限（Ollama の num_predict = Strata の max_tokens）。既定は試験ごとの値（coding 32,768）")
    run.add_argument("--reasoning-budget", type=int, default=None,
                     help="Strata の思考の予算（reasoning_budget_tokens）。0 は上限なし。Ollama には関係ない。"
                          "既定は試験ごとの値（coding 24,576）")
    run.add_argument("--prompt-lang", choices=common.PROMPT_LANGS, default=common.DEFAULT_PROMPT_LANG,
                     help="問題文の言語（既定 ja）。en は coding の PREAMBLE.en.md と prompt.en.md")
    run.add_argument("--reasoning-effort", choices=REASONING_EFFORTS, default=DEFAULT_REASONING_EFFORT,
                     help="Strata に送る思考の強さ（既定 high = テンプレートの xhigh）。Ollama には関係ない")
    run.add_argument("--retry-eos", action=argparse.BooleanOptionalAction, default=True,
                     help="思考中に停止トークンが出て本文が空だった要求を 1 回だけ流し直す（既定 あり。--no-retry-eos でなし）")
    run.set_defaults(func=cmd_run)

    grade_claude = sub.add_parser("grade-claude", help="results/<日付>/claude/ のコーディングと追加の答えを採点して書き戻す")
    add_results(grade_claude)
    grade_claude.add_argument("--model", choices=["sonnet", "opus"], default=None)
    grade_claude.set_defaults(func=cmd_grade_claude)

    regrade = sub.add_parser("regrade", help="ローカルの記録を（問い合わせずに）採点し直す")
    add_results(regrade)
    regrade.add_argument("--target", default=None)
    regrade.set_defaults(func=cmd_regrade)

    pending = sub.add_parser("pending", help="流す必要のある問の数を出す（run と同じ再開の規則）")
    pending.add_argument("--target", required=True)
    pending.add_argument("--suite", choices=["coding", "extra", "all"], default="all")
    add_results(pending)
    pending.add_argument("--retry-errors", action="store_true")
    pending.add_argument("--retry-skipped", action="store_true")
    pending.add_argument("--redo", action="store_true")
    pending.set_defaults(func=cmd_pending)

    unload = sub.add_parser("unload", help="Ollama のモデルを降ろす（keep_alive:0）")
    unload.add_argument("--target", required=True)
    unload.set_defaults(func=cmd_unload)

    show = sub.add_parser("show-prompt", help="送る問題文の全文を出す")
    show.add_argument("--suite", choices=["coding", "extra"], required=True)
    show.add_argument("--item", required=True)
    show.add_argument("--for-claude", action="store_true", help=f"最後に「{common.CLAUDE_SUFFIX}」を足す")
    show.add_argument("--prompt-lang", choices=common.PROMPT_LANGS, default=common.DEFAULT_PROMPT_LANG,
                      help="問題文の言語（既定 ja）")
    show.set_defaults(func=cmd_show_prompt)

    listing = sub.add_parser("list", help="対象と問の一覧")
    listing.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
