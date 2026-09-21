"""連携層の単体試験。モデルを呼ばない（モック試験。実機試験とは別）。

実行: .venv/bin/python -m pytest tests/test_units.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import config as config_module  # noqa: E402
from bridge import core, locking, opencode, procs, verify, worktree  # noqa: E402
from bridge.errors import BridgeError, ConfigError, DirtyWorkspaceError, NotFoundError  # noqa: E402
from bridge.ledger import Ledger  # noqa: E402

GIT = config_module.git_binary()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / ".env").write_text("TOKEN=dummy\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", str(repo)], check=True)
    subprocess.run([GIT, "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [GIT, "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    return repo


# --- 秘密パターン ----------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "app/.env",
        "deep/nested/.env.production",
        "keys/server.pem",
        "a/b/id_ed25519",
        "home/.ssh/config",
        "conf/credentials.json",
        "x/my_secret_values.txt",
    ],
)
def test_secret_paths_are_detected(path):
    assert worktree.is_secret_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "tests/test_app.py", "README.md", "src/keyboard.py", "docs/environment.md"],
)
def test_normal_paths_are_not_secret(path):
    # 「末尾セグメントをファイル名に当てる」方式だと src/ まで秘密扱いになる。
    # そうなっていないことを確かめる回帰試験。
    assert worktree.is_secret_path(path) is False


# --- 設定 ------------------------------------------------------------
def test_config_rejects_shell_string_command(tmp_path):
    repo = _make_repo(tmp_path)
    config_file = tmp_path / "bridge.toml"
    config_file.write_text(
        f"""
[ollama]
model = "qwen3.8:27b"
[opencode]
binary = "{sys.executable}"
[state]
root = "{tmp_path / 'state'}"
[workspace.demo]
path = "{repo}"
[workspace.demo.verify.bad]
command = "python3 -m pytest"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="配列"):
        config_module.load(config_file)


def test_config_rejects_zero_limits(tmp_path):
    repo = _make_repo(tmp_path)
    config_file = tmp_path / "bridge.toml"
    config_file.write_text(
        f"""
[ollama]
model = "m"
[opencode]
binary = "{sys.executable}"
[state]
root = "{tmp_path / 'state'}"
[limits]
max_job_seconds = 0
[workspace.demo]
path = "{repo}"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="1 以上"):
        config_module.load(config_file)


def test_unknown_workspace_and_profile(tmp_path):
    repo = _make_repo(tmp_path)
    config_file = tmp_path / "bridge.toml"
    config_file.write_text(
        f"""
[ollama]
model = "m"
[opencode]
binary = "{sys.executable}"
[state]
root = "{tmp_path / 'state'}"
[workspace.demo]
path = "{repo}"
[workspace.demo.verify.ok]
command = ["true"]
""",
        encoding="utf-8",
    )
    cfg = config_module.load(config_file)
    with pytest.raises(NotFoundError):
        cfg.workspace("missing")
    with pytest.raises(NotFoundError):
        cfg.workspace("demo").profile("missing")


# --- worktree --------------------------------------------------------
def test_dirty_workspace_waits_by_default(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(DirtyWorkspaceError):
        worktree.prepare(repo=repo, worktree=tmp_path / "wt", base_commit=None, on_dirty="wait")
    # 元のツリーは触られていない
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert len(worktree.dirty_entries(repo)) == 1


def test_include_uncommitted_copies_new_files_but_skips_secrets(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "brand_new.py").write_text("NEW = True\n", encoding="utf-8")
    (repo / "extra.env").write_text("SECRET=zzz\n", encoding="utf-8")
    prepared = worktree.prepare(
        repo=repo, worktree=tmp_path / "wt", base_commit=None, on_dirty="include_uncommitted"
    )
    assert (prepared.worktree / "src" / "brand_new.py").is_file()
    assert (prepared.worktree / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert not (prepared.worktree / "extra.env").exists()
    assert "extra.env" in prepared.skipped_secrets


def test_collect_changes_detects_add_modify_delete(tmp_path):
    repo = _make_repo(tmp_path)
    prepared = worktree.prepare(repo=repo, worktree=tmp_path / "wt", base_commit=None)
    work = prepared.worktree
    (work / "src" / "app.py").write_text("VALUE = 99\n", encoding="utf-8")
    (work / "src" / "added.py").write_text("X = 1\n", encoding="utf-8")
    (work / "tests" / "test_app.py").unlink()
    diff_path = tmp_path / "changes.diff"
    changes = worktree.collect_changes(work, prepared.base_commit, diff_path)
    assert changes.modified == ["src/app.py"]
    assert changes.added == ["src/added.py"]
    assert changes.deleted == ["tests/test_app.py"]
    assert changes.tree_hash
    ok, error = worktree.verify_applies(repo, diff_path)
    assert ok, error


def test_secret_changes_are_excluded_from_diff(tmp_path):
    repo = _make_repo(tmp_path)
    prepared = worktree.prepare(repo=repo, worktree=tmp_path / "wt", base_commit=None)
    (prepared.worktree / ".env").write_text("TOKEN=leaked-value-xyz\n", encoding="utf-8")
    changes = worktree.collect_changes(prepared.worktree, prepared.base_commit, tmp_path / "d.diff")
    assert ".env" in changes.blocked_secret_paths
    assert "leaked-value-xyz" not in changes.diff_text


def test_base_commit_must_exist(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(BridgeError):
        worktree.prepare(repo=repo, worktree=tmp_path / "wt", base_commit="0" * 40)


# --- テストの削除・緩和の検出 ----------------------------------------
def test_detects_deleted_and_shrunk_tests(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "tests" / "test_big.py").write_text("\n".join(f"# line {i}" for i in range(20)), encoding="utf-8")
    subprocess.run([GIT, "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [GIT, "-C", str(repo), "-c", "user.email=t@e.com", "-c", "user.name=t", "commit", "-qm", "more"],
        check=True,
    )
    prepared = worktree.prepare(repo=repo, worktree=tmp_path / "wt", base_commit=None)
    (prepared.worktree / "tests" / "test_app.py").unlink()
    (prepared.worktree / "tests" / "test_big.py").write_text("# line 0\n", encoding="utf-8")
    worktree.collect_changes(prepared.worktree, prepared.base_commit)
    integrity = verify.check_test_integrity(prepared.worktree, prepared.base_commit)
    assert "tests/test_app.py" in integrity.deleted
    assert "tests/test_big.py" in integrity.shrunk
    assert integrity.suspicious


# --- 入れ子リポジトリの誤検出防止 --------------------------------------
def test_prepare_uses_nested_repo_head_not_outer_repo(tmp_path):
    # 外側リポジトリの中に、独自の .git を持つ別リポジトリを作る
    # （local-ai-bridge の fixtures / ab-benchmark のような入れ子配置を再現）。
    outer = _make_repo(tmp_path)
    nested = outer / "vendor" / "nested"
    nested.mkdir(parents=True)
    (nested / "inner.py").write_text("INNER = 1\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", str(nested)], check=True)
    subprocess.run([GIT, "-C", str(nested), "add", "-A"], check=True)
    subprocess.run(
        [GIT, "-C", str(nested), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-qm", "nested init"],
        check=True,
    )
    nested_head = _git(nested, "rev-parse", "HEAD").strip()
    outer_head = _git(outer, "rev-parse", "HEAD").strip()
    assert nested_head != outer_head

    prepared = worktree.prepare(repo=nested, worktree=tmp_path / "wt-nested", base_commit=None)
    # 入れ子側の HEAD が基準コミットになっていること（外側の HEAD ではないこと）。
    assert prepared.base_commit == nested_head
    assert (prepared.worktree / "inner.py").is_file()


def test_prepare_rejects_non_toplevel_subdirectory(tmp_path):
    # 外側リポジトリの中の、ただのサブディレクトリ（git 管理下だがトップレベルではない）を
    # 渡すと、git -C が外側リポジトリを掴んでしまう前に弾かれること。
    outer = _make_repo(tmp_path)
    with pytest.raises(BridgeError):
        worktree.prepare(repo=outer / "src", worktree=tmp_path / "wt-src", base_commit=None)


# --- 検証の実行 ------------------------------------------------------
def test_verify_records_exit_code_and_log(tmp_path):
    profile = config_module.VerifyProfile(
        name="fail", command=(sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"),
        timeout_sec=30,
    )
    result = verify.run_profile(
        profile=profile, cwd=tmp_path, log_path=tmp_path / "v.log", tree_hash="abc"
    )
    assert result.exit_code == 3
    assert result.passed is False
    assert "boom" in Path(result.log_path).read_text(encoding="utf-8")


def test_verify_timeout_is_not_success(tmp_path):
    profile = config_module.VerifyProfile(
        name="slow", command=(sys.executable, "-c", "import time; time.sleep(30)"), timeout_sec=2
    )
    result = verify.run_profile(
        profile=profile, cwd=tmp_path, log_path=tmp_path / "v.log", tree_hash=None
    )
    assert result.timed_out is True
    assert result.passed is False


# --- 台帳 ------------------------------------------------------------
def _insert(ledger: Ledger, task_id: str, request_id: str, client_id: str = "c1") -> None:
    ledger.insert_task(
        {
            "task_id": task_id, "request_id": request_id, "client_id": client_id,
            "workspace_id": "w", "workspace_path": "/tmp", "goal": "g",
            "scope_json": "[]", "forbidden_json": "[]", "acceptance_json": "[]",
            "mode": "deep", "budget_json": "{}", "state": "queued",
            "created_at": time.time(),
        }
    )


def test_ledger_rejects_duplicate_request_id(tmp_path):
    ledger = Ledger(tmp_path / "l.db")
    _insert(ledger, "t1", "req-1")
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        _insert(ledger, "t2", "req-1")


def test_ledger_separates_clients(tmp_path):
    ledger = Ledger(tmp_path / "l.db")
    _insert(ledger, "t1", "req-1", client_id="claude")
    _insert(ledger, "t2", "req-1", client_id="codex")
    assert ledger.find_by_request("claude", "req-1")["task_id"] == "t1"
    assert ledger.find_by_request("codex", "req-1")["task_id"] == "t2"


def test_compare_and_set_prevents_double_run(tmp_path):
    ledger = Ledger(tmp_path / "l.db")
    _insert(ledger, "t1", "req-1")
    assert ledger.compare_and_set_state("t1", "queued", "running") is True
    assert ledger.compare_and_set_state("t1", "queued", "running") is False


def test_verifications_become_stale_when_tree_changes(tmp_path):
    ledger = Ledger(tmp_path / "l.db")
    _insert(ledger, "t1", "req-1")
    ledger.add_verification(
        "t1",
        {"profile": "p", "command": ["true"], "cwd": "/tmp", "exit_code": 0,
         "started_at": 1.0, "ended_at": 2.0, "log_path": "/tmp/x.log", "tree_hash": "AAA"},
    )
    assert ledger.verifications("t1")[0]["stale"] is False
    ledger.mark_verifications_stale("t1", "BBB")
    assert ledger.verifications("t1")[0]["stale"] is True


# --- 排他 ------------------------------------------------------------
def test_job_slot_blocks_second_holder(tmp_path):
    with locking.job_slot(tmp_path, slots=1, wait_seconds=1):
        with pytest.raises(locking.SlotBusy):
            with locking.job_slot(tmp_path, slots=1, wait_seconds=1):
                pass


def test_job_slot_allows_configured_count(tmp_path):
    with locking.job_slot(tmp_path, slots=2, wait_seconds=1) as first:
        with locking.job_slot(tmp_path, slots=2, wait_seconds=1) as second:
            assert first != second


# --- プロセス識別 ----------------------------------------------------
def test_identity_detects_dead_process():
    assert procs.alive(procs.identity()) is True
    assert procs.alive("badformat") is False
    assert procs.alive(f"{procs.boot_id()}:999999:12345") is False


# --- 環境の隔離 ------------------------------------------------------
def test_child_env_drops_cloud_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-pass")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-pass")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-pass")
    profile = opencode.Profile(tmp_path / "prof", tmp_path / "src.json")
    env = profile.child_env()
    assert not any(key.startswith(("ANTHROPIC_", "OPENAI_", "AWS_")) for key in env)
    assert env["XDG_CONFIG_HOME"].startswith(str(tmp_path))


def test_profile_backs_up_before_overwrite(tmp_path):
    source = tmp_path / "src.json"
    source.write_text('{"a":1}', encoding="utf-8")
    profile = opencode.Profile(tmp_path / "prof", source)
    profile.ensure()
    source.write_text('{"a":2}', encoding="utf-8")
    profile.ensure()
    backups = list(profile.config_file.parent.glob("opencode.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"a":1}'
    assert profile.config_file.read_text(encoding="utf-8") == '{"a":2}'


def test_profile_ensure_is_idempotent(tmp_path):
    source = tmp_path / "src.json"
    source.write_text('{"a":1}', encoding="utf-8")
    profile = opencode.Profile(tmp_path / "prof", source)
    profile.ensure()
    second = profile.ensure()
    assert "設定は最新（変更なし）" in second["actions"]
    assert not list(profile.config_file.parent.glob("opencode.json.*.bak"))


# --- 予算 ------------------------------------------------------------
def test_budget_breaches():
    budget = opencode.Budget(
        max_seconds=100, max_model_calls=2, max_tool_calls=3, max_output_tokens=50, stall_seconds=10
    )
    outcome = opencode.RunOutcome(started_at=1000.0)
    assert budget.breach(outcome, 1001.0, 1001.0) is None
    outcome.model_calls = 3
    assert "モデル呼出回数" in budget.breach(outcome, 1001.0, 1001.0)
    outcome.model_calls = 1
    outcome.tokens_output = 51
    assert "生成トークン" in budget.breach(outcome, 1001.0, 1001.0)
    outcome.tokens_output = 0
    assert "イベントが無い" in budget.breach(outcome, 1050.0, 1000.0)
    assert "総実行時間" in budget.breach(outcome, 1200.0, 1200.0)


def test_truncated_generation_is_not_success():
    outcome = opencode.RunOutcome(finish_reasons=["length"])
    assert outcome.truncated_generation is True
    assert opencode.RunOutcome(finish_reasons=["stop"]).truncated_generation is False


# --- イベント解釈 ----------------------------------------------------
def test_absorb_counts_events_and_errors():
    outcome = opencode.RunOutcome(started_at=0.0)
    lines = [
        {"type": "step_start", "sessionID": "ses_1", "part": {}},
        {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed"}}},
        {"type": "tool_use", "part": {"tool": "edit", "state": {"status": "error", "error": "denied"}}},
        {"type": "text", "part": {"text": "できました"}},
        {"type": "step_finish", "part": {"reason": "stop",
                                          "tokens": {"input": 10, "output": 5, "reasoning": 1,
                                                     "cache": {"read": 7}}}},
    ]
    for line in lines:
        opencode._absorb(outcome, json.dumps(line))
    assert outcome.session_id == "ses_1"
    assert outcome.model_calls == 1
    assert outcome.tool_calls == 2
    assert outcome.tool_names == ["read", "edit"]
    assert outcome.tokens_output == 5
    assert outcome.cache_read == 7
    assert outcome.final_text == "できました"
    assert any("denied" in message for message in outcome.errors)


def test_absorb_survives_broken_json():
    outcome = opencode.RunOutcome()
    opencode._absorb(outcome, "これは JSON ではない")
    assert outcome.errors  # 黙って落とさない


# --- 成果物の取り出し範囲 --------------------------------------------
def test_get_artifact_rejects_paths(tmp_path):
    cfg = _minimal_config(tmp_path)
    ledger = Ledger(cfg.ledger_path)
    _insert(ledger, "t1", "req-1")
    (cfg.tasks_dir / "t1").mkdir(parents=True)
    (cfg.tasks_dir / "t1" / "changes.diff").write_text("line1\nline2\nline3\n", encoding="utf-8")
    got = core.get_artifact(cfg, "t1", "diff", start_line=2, line_count=1)
    assert got["text"] == "line2"
    for bad in ("../../../etc/passwd", "/etc/passwd", ".ssh/id_rsa", "runner.log"):
        with pytest.raises(BridgeError):
            core.get_artifact(cfg, "t1", bad)


def _minimal_config(tmp_path) -> config_module.Config:
    return config_module.Config(
        config_path=tmp_path / "bridge.toml",
        ollama_base_url="http://127.0.0.1:11434",
        model="m",
        opencode_binary=Path(sys.executable),
        opencode_profile_dir=tmp_path / "prof",
        opencode_config_source=tmp_path / "src.json",
        state_root=tmp_path / "state",
        limits=config_module.Limits(),
        workspaces={},
    )


def test_submit_rejects_bad_identifiers(tmp_path):
    cfg = _minimal_config(tmp_path)
    cfg.ensure_dirs()
    for bad in ("", "has space", "../escape", "x" * 200):
        with pytest.raises(BridgeError):
            core.submit(cfg, request_id=bad, client_id="c", workspace_id="w", goal="g")
    with pytest.raises(BridgeError):
        core.submit(cfg, request_id="ok", client_id="c", workspace_id="w", goal="g", mode="turbo")


# --- 変更可能範囲の逸脱検出 ------------------------------------------
def test_out_of_scope_detection():
    from bridge.runner import _out_of_scope

    assert _out_of_scope(["src/a.py"], []) == []  # 範囲指定なしなら報告しない
    assert _out_of_scope(["README.md"], ["README.md"]) == []
    assert _out_of_scope(["src/interval.py"], ["README.md"]) == ["src/interval.py"]
    assert _out_of_scope(["src/deep/x.py"], ["src"]) == []
    assert _out_of_scope(["src/deep/x.py"], ["src/*.py"]) == []  # fnmatch の * は / を越える
    assert _out_of_scope(["tests/t.py", "docs/d.md"], ["tests"]) == ["docs/d.md"]


def test_failing_names_extracts_unittest_failures(tmp_path):
    from bridge.runner import _failing_names

    log = tmp_path / "v.log"
    log.write_text(
        "FAIL: test_alpha (pkg.TestX.test_alpha)\n"
        "ERROR: test_beta (pkg.TestX.test_beta)\n"
        "Ran 3 tests\nFAILED (failures=1, errors=1)\n",
        encoding="utf-8",
    )
    result = verify.VerifyResult(
        profile="p", command=["x"], cwd=".", exit_code=1, started_at=0.0, ended_at=1.0,
        log_path=str(log), tree_hash=None,
    )
    names = _failing_names(result)
    assert "test_alpha (pkg.TestX.test_alpha)" in names
    assert "test_beta (pkg.TestX.test_beta)" in names
    # 合格したものからは何も拾わない
    passed = verify.VerifyResult(
        profile="p", command=["x"], cwd=".", exit_code=0, started_at=0.0, ended_at=1.0,
        log_path=str(log), tree_hash=None,
    )
    assert _failing_names(passed) == set()
