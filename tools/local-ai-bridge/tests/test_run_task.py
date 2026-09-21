"""core.run_task の単体試験。モデルも実時間も使わない。

実行: .venv/bin/python -m pytest tests/test_run_task.py -q

委譲の中身（OpenCode / Ollama）は呼ばない。submit だけは本物を使い
（worktree を作るだけ）、実行管理プロセスの起動と完了待ち・結果の組み立て・
再検証は差し替える。確かめるのは run_task の判定・適用・戻しの筋道だけ。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

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


def _install(monkeypatch, cfg, outcome_builder, *, wait_payload=None):
    """_spawn_runner / wait_for_task / result を差し替える。"""
    monkeypatch.setattr(core, "_spawn_runner", lambda *a, **k: None)

    def fake_wait(_cfg, task_id, max_wait_sec=None, include_diff=True):
        if wait_payload is not None:
            return dict(wait_payload, task_id=task_id)
        _finish_task(_cfg, task_id)
        return {"task_id": task_id, "state": "awaiting_approval"}

    monkeypatch.setattr(core, "wait_for_task", fake_wait)
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


def _run(cfg, **overrides):
    kwargs = dict(
        request_id="req-1",
        client_id="c1",
        workspace_id="demo",
        goal="src/app.py の VALUE を 2 にする",
    )
    kwargs.update(overrides)
    return core.run_task(cfg, **kwargs)


# --- (1) 6 フラグ -----------------------------------------------------
def _break_state(outcome):
    outcome["state"] = "failed"


def _break_verification(outcome):
    outcome["verification"] = None


def _break_scope(outcome):
    outcome["changes"]["out_of_scope"] = ["docs/other.md"]


def _break_integrity(outcome):
    outcome["test_integrity"]["suspicious"] = True


def _break_secrets(outcome):
    outcome["changes"]["blocked_secret_paths"] = [".env"]


def _break_applies(outcome):
    outcome["changes"]["applies_to_original"] = False


@pytest.mark.parametrize(
    ("reason", "breaker"),
    [
        ('state == "awaiting_approval"', _break_state),
        ("verification.passed is True", _break_verification),
        ("changes.out_of_scope == []", _break_scope),
        ("test_integrity.suspicious is False", _break_integrity),
        ("changes.blocked_secret_paths == []", _break_secrets),
        ("changes.applies_to_original is True", _break_applies),
    ],
)
def test_each_flag_blocks_apply(tmp_path, monkeypatch, reason, breaker):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)

    def builder(task_id):
        outcome = _good_outcome(task_id)
        breaker(outcome)
        return outcome

    _install(monkeypatch, cfg, builder)
    _fake_verify(monkeypatch, 0)

    report = _run(cfg)
    assert report["applied"] is False
    assert report["judged_ok"] is False
    assert report["reasons"] == [reason]
    # 元の作業ツリーは触っていない
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert report["apply_hint"] is not None


# --- (2) 全部真＋再検証合格 -------------------------------------------
def test_applies_and_marks_succeeded(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    _install(monkeypatch, cfg, _good_outcome)
    _fake_verify(monkeypatch, 0)

    report = _run(cfg)
    assert report["judged_ok"] is True
    assert report["applied"] is True
    assert report["reasons"] == []
    assert report["state"] == "succeeded"
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == NEW_CONTENT
    assert report["changed_files"]["modified"] == ["src/app.py"]
    assert report["verify"]["exit_code"] == 0
    assert report["verify"]["passed"] is True
    assert report["local_usage"] == {"model_calls": 3, "tool_calls": 7}
    assert "apply_hint" not in report

    ledger = Ledger(cfg.ledger_path)
    task = ledger.get(report["task_id"])
    assert task["state"] == "succeeded"
    kinds = [event["kind"] for event in ledger.events(report["task_id"])]
    assert "applied_by_run" in kinds


# --- (3) 全部真＋再検証不合格 -----------------------------------------
def test_reverts_when_reverify_fails(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    _install(monkeypatch, cfg, _good_outcome)
    _fake_verify(monkeypatch, 1)

    report = _run(cfg)
    assert report["applied"] is False
    assert report["judged_ok"] is False
    assert any("再検証が不合格" in reason for reason in report["reasons"])
    # 作業ツリーは元に戻っている
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert worktree.dirty_entries(repo) == []

    ledger = Ledger(cfg.ledger_path)
    kinds = [event["kind"] for event in ledger.events(report["task_id"])]
    assert "apply_reverted" in kinds
    # 成功にはしない
    assert ledger.get(report["task_id"])["state"] == "awaiting_approval"


# --- (4) 時間切れ -----------------------------------------------------
def test_timed_out_returns_task_id_and_hint(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    _install(
        monkeypatch,
        cfg,
        _good_outcome,
        wait_payload={"state": "running", "timed_out": True, "hint": "get_task_status で続きを見る"},
    )
    _fake_verify(monkeypatch, 0)

    report = _run(cfg)
    assert report["timed_out"] is True
    assert report["judged_ok"] is False
    assert report["applied"] is False
    assert report["task_id"].startswith("task_")
    assert "wait" in report["hint"]
    assert report["task_id"] in report["hint"]
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


# --- (5) apply=False --------------------------------------------------
def test_no_apply_judges_only(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    _install(monkeypatch, cfg, _good_outcome)

    def forbidden_verify(**_kwargs):
        raise AssertionError("apply=False のときは再検証しない")

    monkeypatch.setattr(verify, "run_profile", forbidden_verify)

    report = _run(cfg, apply=False)
    assert report["judged_ok"] is True
    assert report["applied"] is False
    assert report["reasons"] == []
    assert report["state"] == "awaiting_approval"
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert report["apply_hint"] is not None


# --- 検証プロファイル未登録 -------------------------------------------
def test_applies_but_waits_for_human_without_profile(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    cfg = _config(tmp_path, repo)
    workspace = config_module.Workspace(
        workspace_id="demo", path=repo.resolve(), default_verify=None, verify_profiles={}
    )
    object.__setattr__(cfg, "workspaces", {"demo": workspace})
    _install(monkeypatch, cfg, _good_outcome)

    report = _run(cfg)
    assert report["applied"] is True
    assert report["judged_ok"] is False
    assert report["reasons"] == ["検証プロファイル未登録のため再検証していない"]
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == NEW_CONTENT
