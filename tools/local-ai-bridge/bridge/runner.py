"""タスクの実行管理プロセス。

`python -m bridge.runner <task_id>` で動く。CLI / MCP の接続が切れても
ここが動き続ける。受付（core.submit）と実行（ここ）を分けているのは、
長い仕事を 1 回の MCP 応答へ閉じ込めないため。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import config as config_module
from . import opencode, procs, verify, worktree
from .ledger import Ledger
from .locking import SlotBusy, job_slot
from .prompts import counterexample_review, implement, plan_options, repair, review

STAGE_AGENTS = {
    # OpenCode の組み込みエージェント。build は編集可、plan は読み取り中心。
    "plan": "plan",
    "implement": "build",
    "review": "plan",
    "counterexample": "plan",
    "repair": "build",
}


_FAILURE_LINE = re.compile(r"^(?:FAIL|ERROR|FAILED|not ok)[: ]\s*(.+)$", re.MULTILINE)


def _failing_names(result) -> set[str]:
    """検証ログから落ちた項目の名前を拾う。拾えない形式なら空集合を返す。

    形式が分からないときに 0 件と断定しない。呼び出し側は
    「空集合 かつ 終了コード非 0」を「詳細不明の失敗」として扱う。
    """
    if result is None or result.passed:
        return set()
    try:
        text = Path(result.log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names = {match.strip() for match in _FAILURE_LINE.findall(text)}
    return {name for name in names if name and not name.startswith("(")}


def classify_outcome(
    verify_passed: bool,
    new_failures,
    unfixed,
    baseline_failures,
    changes_empty: bool,
    no_verify: bool,
    baseline_failed: bool | None = None,
) -> tuple[str, str]:
    """検証結果から (state, headline) を決める純関数。副作用なし。

    引数:
      verify_passed     検証が合格したか（未実施なら False）
      new_failures      このタスクで新しく落ちた項目
      unfixed           基準コミットでも落ちていて、今も落ちている項目
      baseline_failures 基準コミットの時点で落ちていた項目
      changes_empty     差分が空か
      no_verify         検証が未実施か
      baseline_failed   基準の検証が不合格だったか（省略時は baseline_failures の有無）

    実測で見つかった欠陥への対応: 基準で 3 件落ちていて変更後も同じ 3 件が落ちている
    （＝1 つも直っていない）状態を、以前は「基準時点で既に同じ失敗」として
    awaiting_approval にし「実装は完了」と書いていた。これは failed に分類する。
    """
    new_failures = set(new_failures or ())
    unfixed = set(unfixed or ())
    baseline_failures = set(baseline_failures or ())
    if baseline_failed is None:
        baseline_failed = bool(baseline_failures)

    if changes_empty:
        return "failed", "変更が生成されなかった"
    if no_verify:
        return "awaiting_approval", "実装は完了。自動検証は未登録のため未実施"
    if verify_passed:
        return "awaiting_approval", "実装と検証が完了。差分の適用には承認が必要"
    if not new_failures and baseline_failed:
        if baseline_failures and unfixed == baseline_failures:
            # 基準で落ちていたものが 1 つも直っていない。何も直っていないのだから
            # 「実装は完了」とは書けない。
            return "failed", "基準コミットで落ちていた検証が直っていない"
        if unfixed and unfixed < baseline_failures:
            return (
                "awaiting_approval",
                f"一部の検証は直ったが {len(unfixed)} 件が未修正",
            )
        # 失敗項目の名前が拾えなかった場合を含む。従来どおり人の判断へ回す。
        return (
            "awaiting_approval",
            "実装は完了。検証は不合格だが、基準コミットの時点で既に同じ失敗があった",
        )
    return "failed", "検証が不合格のまま上限に達した"


def _out_of_scope(changed: list[str], allowed_scope: list[str]) -> list[str]:
    """変更可能範囲として渡されたパターンから外れたファイルを返す。

    allowed_scope が空なら「範囲指定なし」とみなして何も報告しない。
    パターンは fnmatch。ディレクトリ名だけを書いた場合はその配下すべてを許す。
    これは強制ではなく検出。編集自体は OpenCode 側の permission が担う。
    """
    if not allowed_scope:
        return []
    violations = []
    for path_text in changed:
        allowed = False
        for pattern in allowed_scope:
            pattern = pattern.strip().rstrip("/")
            if not pattern:
                continue
            if (
                fnmatch.fnmatch(path_text, pattern)
                or fnmatch.fnmatch(path_text, f"{pattern}/**")
                or path_text == pattern
                or path_text.startswith(pattern + "/")
            ):
                allowed = True
                break
        if not allowed:
            violations.append(path_text)
    return violations


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class Runner:
    def __init__(self, task_id: str, cfg: config_module.Config) -> None:
        self.task_id = task_id
        self.config = cfg
        self.ledger = Ledger(cfg.ledger_path)
        self.task_dir = cfg.tasks_dir / task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.profile = opencode.Profile(cfg.opencode_profile_dir, cfg.opencode_config_source)
        self.stage_records: list[dict[str, Any]] = []
        self.open_questions: list[str] = []
        self.baseline_failures: set[str] = set()
        self.child: subprocess.Popen | None = None
        self.budget_overrides: dict[str, Any] = {}

    # --- 補助 ----------------------------------------------------------
    def log(self, kind: str, detail: Any = None) -> None:
        self.ledger.add_event(self.task_id, kind, detail)

    def _register_child(self, process: subprocess.Popen | None) -> None:
        """動いている OpenCode の PID を覚え、ファイルにも残す。

        runner が SIGTERM で落とされたときに子を確実に止めるためと、
        runner ごと消えた場合に cancel 側が後始末できるようにするため。
        """
        self.child = process
        pid_file = self.task_dir / "child.pid"
        if process is None:
            pid_file.unlink(missing_ok=True)
        else:
            pid_file.write_text(str(process.pid), encoding="utf-8")

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            self.log("signal", {"signal": signum})
            child = self.child
            if child is not None and child.poll() is None:
                procs.terminate_tree(child.pid, grace_seconds=5.0)
            self.ledger.update(
                self.task_id,
                state="cancelled",
                ended_at=time.time(),
                summary="停止要求（シグナル）により中断した。途中成果は作業ツリーとログに残してある。",
            )
            (self.task_dir / "child.pid").unlink(missing_ok=True)
            # 途中成果の索引も残す。ここを飛ばすと result が読めなくなる。
            try:
                self._write_result_file()
            except Exception:  # noqa: BLE001 — 後始末で失敗しても停止は続ける
                self.log("result_file_write_failed")
            raise SystemExit(143)

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def cancelled(self) -> bool:
        task = self.ledger.get(self.task_id)
        return bool(task and task.get("cancel_requested_at"))

    def budget(self, seconds_left: int) -> opencode.Budget:
        """1 段階分の上限。依頼ごとの上書きを設定の既定より優先する。

        max_seconds に 60 秒の下限を置いているのは、残り時間が 0 以下でも
        段階の途中で即死させないため。タスク全体の期限は _run_pipeline の
        deadline が別に見ている。
        """
        limits = self.config.limits
        overrides = getattr(self, "budget_overrides", {})
        return opencode.Budget(
            max_seconds=max(30, seconds_left),
            max_model_calls=int(overrides.get("max_model_calls", limits.max_model_calls)),
            max_tool_calls=int(overrides.get("max_tool_calls", limits.max_tool_calls)),
            max_output_tokens=int(
                overrides.get("max_output_tokens_total", limits.max_output_tokens_total)
            ),
            stall_seconds=limits.opencode_stall_seconds,
        )

    def run_stage(
        self,
        stage: str,
        prompt: str,
        work_dir: Path,
        deadline: float,
        reuse_session: bool,
    ) -> opencode.RunOutcome:
        """1 段階を実行する。独立したタスクの間で会話履歴を使い回さない。

        reuse_session=True の段階（修正）は、実装と同じセッションを続ける。
        レビューは必ず別セッションで行う（reuse_session=False）。
        """
        self.ledger.update(self.task_id, stage=stage)
        self.log("stage_start", {"stage": stage})
        session_id = self.ledger.session_for_role(self.task_id, "implement") if reuse_session else None
        outcome = opencode.run(
            binary=self.config.opencode_binary,
            profile=self.profile,
            cwd=work_dir,
            prompt=prompt,
            model=f"ollama/{self.config.model}",
            agent=STAGE_AGENTS.get(stage),
            budget=self.budget(int(deadline - time.time())),
            events_path=self.task_dir / f"events-{stage}-{len(self.stage_records)}.jsonl",
            stderr_path=self.task_dir / f"stderr-{stage}-{len(self.stage_records)}.log",
            session_id=session_id,
            should_cancel=self.cancelled,
            on_child_start=self._register_child,
        )
        self._register_child(None)
        role = "implement" if stage in ("implement", "repair") else stage
        if outcome.session_id:
            self.ledger.add_session(self.task_id, role, outcome.session_id)
        record = {"stage": stage, **outcome.as_dict()}
        self.stage_records.append(record)
        self.log("stage_end", record)
        if outcome.truncated_generation:
            self.open_questions.append(
                f"{stage} の生成が途中で打ち切られた（finish_reason={outcome.finish_reasons}）。"
            )
        for message in outcome.errors:
            self.open_questions.append(f"{stage}: {message}")
        return outcome

    def verify_now(
        self, work_dir: Path, base_commit: str, profile_name: str | None, label: str = "変更後"
    ) -> tuple[verify.VerifyResult | None, str]:
        workspace = self.config.workspace(self.ledger.get(self.task_id)["workspace_id"])
        profile = workspace.profile(profile_name)
        if profile is None:
            return None, "検証プロファイルが登録されていないため、自動検証は実行していない。"
        changes = worktree.collect_changes(work_dir, base_commit)
        seq = len(self.ledger.verifications(self.task_id)) + 1
        result = verify.run_profile(
            profile=profile,
            cwd=work_dir,
            log_path=self.task_dir / f"verify-{seq}.log",
            tree_hash=changes.tree_hash,
            timeout_sec=min(profile.timeout_sec, self.config.limits.verify_timeout_sec),
        )
        self.ledger.add_verification(
            self.task_id,
            {
                "profile": result.profile,
                "command": result.command,
                "cwd": result.cwd,
                "exit_code": result.exit_code,
                "started_at": result.started_at,
                "ended_at": result.ended_at,
                "log_path": result.log_path,
                "tree_hash": result.tree_hash,
            },
        )
        self.log("verify", result.as_dict())
        status = "合格" if result.passed else ("タイムアウト" if result.timed_out else "不合格")
        summary = (
            f"[{label}] {status}: `{' '.join(result.command)}` 終了コード={result.exit_code} "
            f"({round(result.ended_at - result.started_at, 1)}秒)\n"
            f"ログ末尾:\n{result.tail[-1500:]}"
        )
        return result, summary

    # --- 本体 ----------------------------------------------------------
    def execute(self) -> None:
        task = self.ledger.get(self.task_id)
        if task is None:
            raise SystemExit(f"task {self.task_id} が台帳にありません。")
        limits = self.config.limits
        queued_at = float(task["created_at"])

        try:
            with job_slot(self.config.job_lock_dir, limits.max_concurrent_jobs, limits.queue_wait_seconds):
                wait_sec = time.time() - queued_at
                claimed = self.ledger.compare_and_set_state(
                    self.task_id,
                    "queued",
                    "running",
                    started_at=time.time(),
                    queue_wait_sec=wait_sec,
                    runner_pid=os.getpid(),
                    runner_host=procs.hostname(),
                    runner_boot_id=procs.identity(),
                )
                if not claimed:
                    current = self.ledger.get(self.task_id)
                    self.log("duplicate_run_blocked", {"state": current["state"] if current else None})
                    return
                self.log("queue_wait", {"seconds": round(wait_sec, 2)})
                self._run_pipeline(task)
        except SlotBusy as exc:
            self.ledger.update(
                self.task_id,
                state="aborted",
                ended_at=time.time(),
                summary=f"ジョブ枠の待ちが上限に達したため受け付けを取り消した: {exc}",
            )
            self.log("aborted", {"reason": "queue_wait_exceeded"})
        except Exception as exc:  # noqa: BLE001 — 失敗も必ず台帳へ残す
            self.ledger.update(
                self.task_id,
                state="failed",
                ended_at=time.time(),
                summary=f"実行中に例外が発生した: {type(exc).__name__}: {exc}",
            )
            self.log("exception", {"type": type(exc).__name__, "message": str(exc)})
            raise

    def _run_pipeline(self, task) -> None:
        cfg = self.config
        limits = cfg.limits
        # 依頼ごとの予算は受付時に台帳へ入れてある。設定の既定より優先する。
        # （ここを読まないと --max-seconds が効かない。実測で効いていなかった。）
        self.budget_overrides = _load_json(task["budget_json"], {}) or {}
        max_job_seconds = int(self.budget_overrides.get("max_job_seconds", limits.max_job_seconds))
        deadline = time.time() + max_job_seconds
        workspace = cfg.workspace(task["workspace_id"])
        goal = task["goal"]
        allowed_scope = _load_json(task["scope_json"], [])
        forbidden = _load_json(task["forbidden_json"], [])
        acceptance = _load_json(task["acceptance_json"], [])
        mode = task["mode"]
        verify_profile_name = task["verify_profile"]
        work_dir = Path(task["worktree_path"])
        base_commit = task["base_commit"]
        verify_profile = workspace.profile(verify_profile_name)
        verify_command = list(verify_profile.command) if verify_profile else None

        max_repairs = int(
            self.budget_overrides.get("max_repair_rounds", limits.repair_rounds.get(mode, 1))
        )
        attempt = 0

        # 基準コミットの時点でテストが通るかを先に測る。
        # これをしないと、元から落ちていたテストをこのタスクの失敗として扱ってしまう
        # （実測で誤判定した）。基準が落ちていれば、それは「既存の失敗」として報告する。
        baseline_result, baseline_summary = self.verify_now(
            work_dir, base_commit, verify_profile_name, label="基準コミット"
        )
        self.baseline_failures = _failing_names(baseline_result)
        if baseline_result is not None and not baseline_result.passed:
            self.open_questions.append(
                "基準コミットの時点で検証が不合格だった"
                f"（終了コード {baseline_result.exit_code}、失敗 {sorted(self.baseline_failures) or '詳細不明'}）。"
                "このタスクが原因ではない失敗を含む。"
            )

        # 1. exhaustive のときだけ、先に方針を 2 案まで比較する（編集しない）。
        plan_note = ""
        if mode == "exhaustive":
            outcome = self.run_stage(
                "plan",
                plan_options(goal=goal, allowed_scope=allowed_scope, acceptance=acceptance),
                work_dir,
                deadline,
                reuse_session=False,
            )
            plan_note = f"## 先に比較した方針\n{outcome.final_text[:2000]}\n\n上の推奨案 1 つだけを実装すること。"
            if self._should_stop(outcome, deadline):
                return

        # 2. 実装。
        outcome = self.run_stage(
            "implement",
            implement(
                goal=goal,
                allowed_scope=allowed_scope,
                forbidden=forbidden,
                acceptance=acceptance,
                verify_command=verify_command,
                extra_note=plan_note,
            ),
            work_dir,
            deadline,
            reuse_session=False,
        )
        if self._should_stop(outcome, deadline):
            return

        # 3. 検証 → レビュー → 修正 を上限まで回す。
        verify_result, verify_summary = self.verify_now(work_dir, base_commit, verify_profile_name)
        findings = ""
        while True:
            changes = worktree.collect_changes(
                work_dir, base_commit, self.task_dir / "changes.diff"
            )
            self.ledger.mark_verifications_stale(self.task_id, changes.tree_hash)
            verify_failures = _failing_names(verify_result)
            new_failures = verify_failures - self.baseline_failures
            unfixed = verify_failures & self.baseline_failures
            # 基準の時点で落ちていたものは、このタスクの責任ではない。
            # 新しく壊れたものがあるときだけ修正へ回す。ただし、基準で落ちていたものが
            # 1 つも直っていない段階（＝何も直せていない）も修正ラウンドへ回す。
            nothing_fixed = bool(self.baseline_failures) and unfixed == self.baseline_failures
            need_repair = verify_result is not None and not verify_result.passed and (
                bool(new_failures)
                or baseline_result is None
                or baseline_result.passed
                or nothing_fixed
            )

            if mode in ("deep", "exhaustive") and not need_repair:
                stage = "counterexample" if mode == "exhaustive" else "review"
                builder = (
                    counterexample_review(goal=goal, acceptance=acceptance, diff_text=changes.diff_text[:24000])
                    if stage == "counterexample"
                    else review(
                        goal=goal,
                        acceptance=acceptance,
                        diff_text=changes.diff_text[:24000],
                        verify_summary=verify_summary,
                        focus="合格条件を満たしているか、境界条件、既存の振る舞いを壊していないか",
                    )
                )
                review_outcome = self.run_stage(stage, builder, work_dir, deadline, reuse_session=False)
                findings = review_outcome.final_text
                lowered = findings.lower()
                need_repair = ("要修正" in findings) or ("反例:" in findings and "なし" not in findings[:200])
                if "判定: ok" in lowered or "判定: OK" in findings:
                    need_repair = False

            if not need_repair or attempt >= max_repairs or time.time() > deadline:
                break
            attempt += 1
            self.ledger.update(self.task_id, attempt_count=attempt)
            outcome = self.run_stage(
                "repair",
                repair(
                    goal=goal,
                    acceptance=acceptance,
                    findings=findings or "（レビュー指摘なし。検証が不合格）",
                    verify_summary=verify_summary,
                ),
                work_dir,
                deadline,
                reuse_session=True,
            )
            if self._should_stop(outcome, deadline):
                return
            # 変更が入ったので前の検証結果は失効。必ず取り直す。
            verify_result, verify_summary = self.verify_now(work_dir, base_commit, verify_profile_name)

        self._finish(
            task, work_dir, base_commit, verify_result, verify_summary, findings, attempt,
            baseline_result=baseline_result, baseline_summary=baseline_summary,
        )

    def _should_stop(self, outcome: opencode.RunOutcome, deadline: float) -> bool:
        if outcome.stop_reason == "cancelled" or self.cancelled():
            self.ledger.update(
                self.task_id,
                state="cancelled",
                ended_at=time.time(),
                summary="停止要求により中断した。途中成果は作業ツリーとログに残してある。",
            )
            self._write_result_file()
            return True
        if outcome.stop_reason in ("budget", "stall"):
            self.ledger.update(
                self.task_id,
                state="aborted",
                ended_at=time.time(),
                summary="予算または無応答の上限に達したため停止した。途中成果は保存してある。",
                open_questions_json=json.dumps(self.open_questions, ensure_ascii=False),
            )
            self._write_result_file()
            return True
        if time.time() > deadline:
            self.ledger.update(
                self.task_id,
                state="aborted",
                ended_at=time.time(),
                summary="タスク全体の制限時間に達したため停止した。途中成果は保存してある。",
                open_questions_json=json.dumps(self.open_questions, ensure_ascii=False),
            )
            self._write_result_file()
            return True
        return False

    def _finish(
        self,
        task,
        work_dir: Path,
        base_commit: str,
        verify_result,
        verify_summary: str,
        findings: str,
        attempt: int,
        baseline_result=None,
        baseline_summary: str = "",
    ) -> None:
        changes = worktree.collect_changes(work_dir, base_commit, self.task_dir / "changes.diff")
        integrity = verify.check_test_integrity(work_dir, base_commit)
        workspace = self.config.workspace(task["workspace_id"])
        applies, apply_error = (False, "差分なし")
        if changes.diff_path:
            applies, apply_error = worktree.verify_applies(workspace.path, Path(changes.diff_path))

        if integrity.suspicious:
            self.open_questions.append(
                "既存テストが削除／短縮されている: "
                + ", ".join(integrity.deleted + integrity.shrunk)
            )
        touched = changes.added + changes.modified + changes.deleted + changes.renamed
        violations = _out_of_scope(touched, _load_json(task["scope_json"], []))
        if violations:
            self.open_questions.append(
                "変更可能範囲の外を書き換えている: " + ", ".join(violations)
                + "（適用前に人が確認すること）"
            )
        if changes.blocked_secret_paths:
            self.open_questions.append(
                "秘密情報とみなしたパスの変更を差分から除外した: "
                + ", ".join(changes.blocked_secret_paths)
            )
        if not applies and changes.diff_path:
            self.open_questions.append(f"差分が元のリポジトリへそのまま当たらない: {apply_error}")

        verified_ok = verify_result is not None and verify_result.passed
        no_verify = verify_result is None
        baseline_failures = getattr(self, "baseline_failures", set())
        verify_failures = _failing_names(verify_result)
        new_failures = verify_failures - baseline_failures
        unfixed = verify_failures & baseline_failures
        baseline_failed = baseline_result is not None and not baseline_result.passed
        state, headline = classify_outcome(
            verified_ok,
            new_failures,
            unfixed,
            baseline_failures,
            changes.is_empty,
            no_verify,
            baseline_failed=baseline_failed,
        )
        if new_failures:
            self.open_questions.append(
                "このタスクで新しく落ちた検証: " + ", ".join(sorted(new_failures))
            )
        if unfixed and not verified_ok and not no_verify and not changes.is_empty:
            self.open_questions.append(
                "基準コミットでも落ちていて、今も直っていない検証: " + ", ".join(sorted(unfixed))
            )

        summary = self._compose_summary(headline, changes, verify_result, attempt, findings)
        usage = {
            "local_inference": {
                "model_calls": sum(record["model_calls"] for record in self.stage_records),
                "tool_calls": sum(record["tool_calls"] for record in self.stage_records),
                "output_tokens": sum(record["tokens"]["output"] for record in self.stage_records),
                "input_tokens": sum(record["tokens"]["input"] for record in self.stage_records),
                "cache_read_tokens": sum(record["tokens"]["cache_read"] for record in self.stage_records),
            },
            # クラウド側の実トークン数はこのプロセスからは取得できない。推定で埋めない。
            "cloud_tokens": None,
            "cloud_tokens_note": "クラウド側の消費は Claude Code のセッション記録から bench/measure_cloud_tokens.py で測る。この値には入れない。",
            "returned_bytes": None,  # core.result() が確定させる
        }
        self.ledger.update(
            self.task_id,
            state=state,
            stage="done",
            ended_at=time.time(),
            diff_path=changes.diff_path,
            new_files_json=json.dumps(changes.added, ensure_ascii=False),
            attempt_count=attempt,
            open_questions_json=json.dumps(self.open_questions, ensure_ascii=False),
            summary=summary,
            usage_json=json.dumps(usage, ensure_ascii=False),
            effective_json=json.dumps(
                {
                    "ollama_base_url": self.config.ollama_base_url,
                    "model": self.config.model,
                    "opencode_binary": str(self.config.opencode_binary),
                    "opencode_profile": str(self.config.opencode_profile_dir),
                    "mode": task["mode"],
                },
                ensure_ascii=False,
            ),
        )
        self._write_result_file(
            extra={
                "changes": {
                    "summary": changes.summary_line(),
                    "added": changes.added,
                    "modified": changes.modified,
                    "deleted": changes.deleted,
                    "renamed": changes.renamed,
                    "binary": changes.binary,
                    "blocked_secret_paths": changes.blocked_secret_paths,
                    "ignored_build_artifacts": changes.ignored_build_artifacts,
                    "diff_path": changes.diff_path,
                    "diff_line_count": len(changes.diff_text.splitlines()),
                    "applies_to_original": applies,
                    "out_of_scope": violations,
                },
                "verification": verify_result.as_dict() if verify_result else None,
                "baseline_verification": baseline_result.as_dict() if baseline_result else None,
                "unfixed_baseline_failures": sorted(unfixed),
                "new_failures": sorted(new_failures),
                "verify_summary": verify_summary,
                "baseline_summary": baseline_summary,
                "test_integrity": integrity.as_dict(),
                "review_findings": findings[:4000],
            }
        )
        self.log("finished", {"state": state})

    def _compose_summary(self, headline, changes, verify_result, attempt, findings) -> str:
        lines = [headline + "。", f"変更: {changes.summary_line()}。"]
        if verify_result is not None:
            status = "合格" if verify_result.passed else "不合格"
            lines.append(f"検証: {status}（終了コード {verify_result.exit_code}）。")
        else:
            lines.append("検証: 未実施（プロファイル未登録）。")
        if attempt:
            lines.append(f"修正回数: {attempt}。")
        if self.open_questions:
            lines.append("未解決: " + " / ".join(self.open_questions[:4]))
        text = " ".join(lines)
        limit = self.config.limits.result_summary_max_chars
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _write_result_file(self, extra: dict[str, Any] | None = None) -> None:
        task = self.ledger.get(self.task_id)
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "state": task["state"] if task else "unknown",
            "summary": task["summary"] if task else None,
            "stages": self.stage_records,
            "open_questions": self.open_questions,
            "sessions": self.ledger.sessions(self.task_id),
            "verifications": self.ledger.verifications(self.task_id),
        }
        if extra:
            payload.update(extra)
        (self.task_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m bridge.runner <task_id>", file=sys.stderr)
        return 2
    cfg = config_module.load()
    runner = Runner(argv[1], cfg)
    runner.install_signal_handlers()
    runner.execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
