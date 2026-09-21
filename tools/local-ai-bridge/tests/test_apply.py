"""core.apply_task（local-ai-task apply の実体）の単体試験。モデルも実時間も使わない。

実行: .venv/bin/python -m pytest tests/test_apply.py -q

tests/test_run_task.py と同じやり方（tmp_path にダミーの git リポジトリ・
task ディレクトリ・result.json・changes.diff を作り、config を組む）に合わせる。
委譲の中身（OpenCode / Ollama）は呼ばない。submit だけは本物を使い
（worktree を作るだけ）、result() と再検証（verify.run_profile）は差し替える。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import config as config_module  # noqa: E402
from bridge import core, verify, worktree  # noqa: E402
from bridge.ledger import Ledger  # noqa: E402

GIT = config_module.git_binary()


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    subprocess.run([GIT, "init", "-q", str(repo)], check=True)
    subprocess.run([GIT, "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [GIT, "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    return repo


def _config(tmp_path: Path, repo: Path) -> config_module.Config:
    profile = config_module.VerifyProfile(
        name="unit", command=("/bin/true",), timeout_sec=30, description="試験用"
    )
    workspace = config_module.Workspace(
        workspace_id="demo",
        path=repo.resolve(),
        default_verify="unit",
        verify_profiles={"unit": profile},
    )
    cfg = config_module.Config(
        config_path=tmp_path / "bridge.toml",
        ollama_base_url="http://127.0.0.1:11434",
        model="m",
        opencode_binary=Path(sys.executable),
        opencode_profile_dir=tmp_path / "prof",
        opencode_config_source=tmp_path / "src.json",
        state_root=tmp_path / "state",
        limits=config_module.Limits(),
        workspaces={"demo": workspace},
    )
    cfg.ensure_dirs()
    return cfg


NEW_CONTENT = "VALUE = 2\n"


def _submit_task(cfg: config_module.Config, monkeypatch) -> str:
    """runner を起動せず、受付だけ本物の submit で行う（worktree を作るため）。"""
    monkeypatch.setattr(core, "_spawn_runner", lambda *a, **k: None)
    accepted = core.submit(
        cfg,
        request_id="req-apply-1",
        client_id="c1",
        workspace_id="demo",
        goal="src/app.py の VALUE を 2 にする",
    )
    return accepted["task_id"]


def _finish_task(cfg: config_module.Config, task_id: str) -> None:
    """runner がやることのうち、差分の作成と台帳の更新だけを代わりに行う。"""
    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(task_id)
    work_dir = Path(task["worktree_path"])
    (work_dir / "src" / "app.py").write_text(NEW_CONTENT, encoding="utf-8")
    changes = worktree.collect_changes(
        work_dir, task["base_commit"], cfg.tasks_dir / task_id / "changes.diff"
    )
    assert changes.diff_path is not None
    ledger.update(
        task_id,
        state="awaiting_approval",
        stage="done",
        diff_path=changes.diff_path,
        ended_at=time.time(),
        summary="実装と検証が完了。差分の適用には承認が必要。",
    )


def _good_outcome(task_id: str) -> dict:
    """result() が返す形のうち、判定に使う項目を埋めたもの。"""
    return {
        "task_id": task_id,
        "state": "awaiting_approval",
        "summary": "実装と検証が完了。差分の適用には承認が必要。",
        "changes": {
            "added": [],
            "modified": ["src/app.py"],
            "deleted": [],
            "renamed": [],
            "blocked_secret_paths": [],
            "out_of_scope": [],
            "applies_to_original": True,
        },
        "verification": {
            "profile": "unit",
            "command": ["/bin/true"],
            "exit_code": 0,
            "passed": True,
            "stale": False,
            "log_path": "/tmp/verify-1.log",
            "tree_hash": None,
        },
        "test_integrity": {"suspicious": False},
        "open_questions": [],
        "usage": {"local_inference": {"model_calls": 3, "tool_calls": 7}},
        "apply_hint": "確認してから当てる: git apply --check ...",
    }


def _patch_result(monkeypatch, outcome_builder) -> None:
    monkeypatch.setattr(
        core, "result", lambda _cfg, task_id, include_diff=False: outcome_builder(task_id)
    )


def _fake_verify(monkeypatch, exit_code: int):
    def fake_run_profile(*, profile, cwd, log_path, tree_hash, timeout_sec=None):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"exit={exit_code}\n", encoding="utf-8")
        now = time.time()
        return verify.VerifyResult(
            profile=profile.name,
            command=list(profile.command),
            cwd=str(cwd),
            exit_code=exit_code,
            started_at=now,
            ended_at=now,
            log_path=str(log_path),
            tree_hash=tree_hash,
        )

    monkeypatch.setattr(verify, "run_profile", fake_run_profile)


# --- (a) 6 フラグ合格 → 適用 -------------------------------------------
def test_apply_task_applies_when_all_flags_pass(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    task_id = _submit_task(cfg, monkeypatch)
    _finish_task(cfg, task_id)
    _patch_result(monkeypatch, _good_outcome)
    _fake_verify(monkeypatch, 0)

    report = core.apply_task(cfg, task_id)
    assert report["task_id"] == task_id
    assert report["workspace_id"] == "demo"
    assert report["applied"] is True
    assert report["reasons"] == []
    assert report["verification"]["passed"] is True
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == NEW_CONTENT

    ledger = Ledger(cfg.ledger_path)
    assert ledger.get(task_id)["state"] == "succeeded"
    kinds = [event["kind"] for event in ledger.events(task_id)]
    assert "applied_by_run" in kinds


# --- (b) verification.passed=false → 適用しない -----------------------
def test_apply_task_blocks_when_verification_failed(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    task_id = _submit_task(cfg, monkeypatch)
    _finish_task(cfg, task_id)

    def bad_outcome(tid):
        outcome = _good_outcome(tid)
        outcome["verification"]["passed"] = False
        return outcome

    _patch_result(monkeypatch, bad_outcome)

    def forbidden_verify(**_kwargs):
        raise AssertionError("6 フラグ不合格のときは再検証もしない")

    monkeypatch.setattr(verify, "run_profile", forbidden_verify)

    report = core.apply_task(cfg, task_id)
    assert report["applied"] is False
    assert report["reasons"] == ["verification.passed is True"]
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    ledger = Ledger(cfg.ledger_path)
    assert ledger.get(task_id)["state"] == "awaiting_approval"


# --- (c) 再検証コマンドが失敗 → git apply -R で戻す --------------------
def test_apply_task_reverts_when_reverify_fails(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    task_id = _submit_task(cfg, monkeypatch)
    _finish_task(cfg, task_id)
    _patch_result(monkeypatch, _good_outcome)
    _fake_verify(monkeypatch, 1)

    report = core.apply_task(cfg, task_id)
    assert report["applied"] is False
    assert any("再検証が不合格" in reason for reason in report["reasons"])
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert worktree.dirty_entries(repo) == []

    ledger = Ledger(cfg.ledger_path)
    assert ledger.get(task_id)["state"] == "awaiting_approval"
    kinds = [event["kind"] for event in ledger.events(task_id)]
    assert "apply_reverted" in kinds


# --- (d) 2 回目の apply は already_applied ------------------------------
def test_apply_task_second_call_is_already_applied(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    task_id = _submit_task(cfg, monkeypatch)
    _finish_task(cfg, task_id)
    _patch_result(monkeypatch, _good_outcome)

    def forbidden_verify(**_kwargs):
        raise AssertionError("verify=False のときは再検証しない")

    monkeypatch.setattr(verify, "run_profile", forbidden_verify)

    first = core.apply_task(cfg, task_id, verify=False)
    assert first["applied"] is True
    assert first["reasons"] == []
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == NEW_CONTENT

    second = core.apply_task(cfg, task_id, verify=False)
    assert second["applied"] is False
    assert second["reasons"] == ["already_applied"]
    # 2 回目は当たらないので内容は変わらない
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == NEW_CONTENT

    ledger = Ledger(cfg.ledger_path)
    # 再検証していないので台帳の状態は変わらない
    assert ledger.get(task_id)["state"] == "awaiting_approval"


# --- task_id が台帳に無い ------------------------------------------------
def test_apply_task_unknown_task_id_raises(tmp_path):
    from bridge.errors import NotFoundError

    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    try:
        core.apply_task(cfg, "task_does_not_exist")
        raise AssertionError("NotFoundError が飛ぶはず")
    except NotFoundError:
        pass
