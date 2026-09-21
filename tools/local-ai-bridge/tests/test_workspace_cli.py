"""`local-ai-task workspace add/list/which/remove` の単体試験。

モデルは呼ばない。config.load() で読み込んだ Config に対して bridge.core の
workspace_* 関数を直に呼ぶ（実行系のワーカーは介さない）。

実行: .venv/bin/python -m pytest tests/test_workspace_cli.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import cli, config as config_module, core  # noqa: E402
from bridge.errors import BridgeError, NotFoundError  # noqa: E402

GIT = config_module.git_binary()


def _make_git_repo(path: Path) -> Path:
    """path を Git リポジトリにして、空コミットを 1 つ作る。"""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(path)], check=True)
    subprocess.run(
        [
            GIT, "-C", str(path),
            "-c", "user.email=t@example.com", "-c", "user.name=t",
            "commit", "-q", "--allow-empty", "-m", "init",
        ],
        check=True,
    )
    return path


def _write_config(
    tmp_path: Path,
    *,
    allowed_roots: list[str] | None,
    workspaces_toml: str = "",
) -> Path:
    config_file = tmp_path / "bridge.toml"
    registration_block = ""
    if allowed_roots is not None:
        roots = ", ".join(f'"{root}"' for root in allowed_roots)
        registration_block = f"[registration]\nallowed_roots = [{roots}]\n"
    config_file.write_text(
        f"""
[ollama]
model = "m"
[opencode]
binary = "{sys.executable}"
[state]
root = "{tmp_path / 'state'}"
{registration_block}
{workspaces_toml}
""",
        encoding="utf-8",
    )
    return config_file


# --- 許可ルート・Git 判定 ----------------------------------------------
def test_workspace_add_rejects_outside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside" / "repo"
    _make_git_repo(outside)
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)

    with pytest.raises(BridgeError, match="許可ルート外"):
        core.workspace_add(cfg, path=str(outside))


def test_workspace_add_rejects_when_no_allowed_roots(tmp_path):
    repo = _make_git_repo(tmp_path / "repo")
    config_file = _write_config(tmp_path, allowed_roots=None)
    cfg = config_module.load(config_file)

    with pytest.raises(BridgeError, match="allowed_roots"):
        core.workspace_add(cfg, path=str(repo))


def test_workspace_add_rejects_non_git_dir(tmp_path):
    allowed = tmp_path / "allowed"
    plain_dir = allowed / "not-a-repo"
    plain_dir.mkdir(parents=True)
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)

    with pytest.raises(BridgeError, match="Git リポジトリ"):
        core.workspace_add(cfg, path=str(plain_dir))


def test_workspace_add_rejects_symlink_escaping_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside_repo = _make_git_repo(tmp_path / "outside" / "repo")
    link = allowed / "escape-link"
    link.symlink_to(outside_repo, target_is_directory=True)
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)

    # symlink 越しに allowed の内側を指しているように見えるが、
    # resolve() で実体パス（allowed の外）になるので拒否されるはず。
    with pytest.raises(BridgeError, match="許可ルート外"):
        core.workspace_add(cfg, path=str(link))


# --- 追記・再パース ------------------------------------------------------
def test_workspace_add_appends_without_touching_existing_content(tmp_path):
    allowed = tmp_path / "allowed"
    repo = _make_git_repo(allowed / "myrepo")
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    original_text = config_file.read_text(encoding="utf-8")
    cfg = config_module.load(config_file)

    result = core.workspace_add(
        cfg,
        path=str(repo),
        workspace_id="myrepo",
        verify_profiles={"pytest": ["python3", "-m", "pytest", "-q"]},
        default_verify="pytest",
    )

    assert result["workspace_id"] == "myrepo"
    assert result["backup_path"] is not None
    assert Path(result["backup_path"]).read_text(encoding="utf-8") == original_text

    new_text = config_file.read_text(encoding="utf-8")
    assert new_text.startswith(original_text)
    assert new_text != original_text

    reloaded = config_module.load(config_file)
    assert "myrepo" in reloaded.workspaces
    ws = reloaded.workspaces["myrepo"]
    assert ws.path == repo.resolve()
    assert ws.default_verify == "pytest"
    assert ws.verify_profiles["pytest"].command == ("python3", "-m", "pytest", "-q")


def test_workspace_add_duplicate_id_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    repo_a = _make_git_repo(allowed / "repo-a")
    repo_b = _make_git_repo(allowed / "repo-b")
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)
    core.workspace_add(cfg, path=str(repo_a), workspace_id="dup")

    cfg2 = config_module.load(config_file)
    with pytest.raises(BridgeError, match="既に登録"):
        core.workspace_add(cfg2, path=str(repo_b), workspace_id="dup")


def test_workspace_add_duplicate_path_different_id_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    repo = _make_git_repo(allowed / "myrepo")
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)
    core.workspace_add(cfg, path=str(repo), workspace_id="first")

    cfg2 = config_module.load(config_file)
    with pytest.raises(BridgeError, match="既に workspace"):
        core.workspace_add(cfg2, path=str(repo), workspace_id="second")


def test_workspace_add_dry_run_does_not_modify_file(tmp_path):
    allowed = tmp_path / "allowed"
    repo = _make_git_repo(allowed / "myrepo")
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    original_text = config_file.read_text(encoding="utf-8")
    cfg = config_module.load(config_file)

    result = core.workspace_add(cfg, path=str(repo), dry_run=True)

    assert result["dry_run"] is True
    assert result["backup_path"] is None
    assert config_file.read_text(encoding="utf-8") == original_text
    # 未指定なら resolved.name から id を作る
    assert result["workspace_id"] == "myrepo"


# --- which -------------------------------------------------------------
def test_workspace_which_matches_subpath_and_deepest(tmp_path):
    allowed = tmp_path / "allowed"
    outer_repo = _make_git_repo(allowed / "outer")
    inner_dir = outer_repo / "sub" / "inner"
    inner_dir.mkdir(parents=True)
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)
    core.workspace_add(cfg, path=str(outer_repo), workspace_id="outer")
    cfg = config_module.load(config_file)

    assert core.workspace_which(cfg, str(outer_repo)) == "outer"
    assert core.workspace_which(cfg, str(inner_dir)) == "outer"
    assert core.workspace_which(cfg, str(tmp_path)) is None


# --- remove --------------------------------------------------------------
def test_workspace_remove_deletes_only_its_block(tmp_path):
    allowed = tmp_path / "allowed"
    repo_a = _make_git_repo(allowed / "a")
    repo_b = _make_git_repo(allowed / "b")
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)
    core.workspace_add(
        cfg,
        path=str(repo_a),
        workspace_id="a",
        verify_profiles={"t1": ["python3", "-m", "pytest"]},
        default_verify="t1",
    )
    cfg = config_module.load(config_file)
    core.workspace_add(
        cfg,
        path=str(repo_b),
        workspace_id="b",
        verify_profiles={"t2": ["python3", "-m", "pytest"]},
        default_verify="t2",
    )
    cfg = config_module.load(config_file)
    assert set(cfg.workspaces) >= {"a", "b"}

    result = core.workspace_remove(cfg, "a")
    assert result["workspace_id"] == "a"

    reloaded = config_module.load(config_file)
    assert "a" not in reloaded.workspaces
    assert "b" in reloaded.workspaces
    assert reloaded.workspaces["b"].verify_profiles["t2"].command == (
        "python3", "-m", "pytest",
    )


def test_workspace_remove_unknown_id_raises(tmp_path):
    allowed = tmp_path / "allowed"
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)

    with pytest.raises(NotFoundError):
        core.workspace_remove(cfg, "does-not-exist")


# --- list ----------------------------------------------------------------
def test_workspace_list_reports_registered_workspaces(tmp_path):
    allowed = tmp_path / "allowed"
    repo = _make_git_repo(allowed / "myrepo")
    config_file = _write_config(tmp_path, allowed_roots=[str(allowed)])
    cfg = config_module.load(config_file)
    core.workspace_add(
        cfg,
        path=str(repo),
        workspace_id="myrepo",
        verify_profiles={"pytest": ["python3", "-m", "pytest", "-q"]},
        default_verify="pytest",
    )
    cfg = config_module.load(config_file)

    listed = core.workspace_list(cfg)
    entry = next(item for item in listed if item["workspace_id"] == "myrepo")
    assert entry["default_verify"] == "pytest"
    assert entry["verify_profiles"] == ["pytest"]


# --- cli._build_verify_profiles（shlex 分割） -----------------------------
def test_build_verify_profiles_splits_shell_string():
    profiles = cli._build_verify_profiles(["pytest"], ["python3 -m pytest -q"])
    assert profiles == {"pytest": ["python3", "-m", "pytest", "-q"]}


def test_build_verify_profiles_rejects_count_mismatch():
    with pytest.raises(BridgeError, match="同じ回数"):
        cli._build_verify_profiles(["a", "b"], ["echo hi"])


def test_build_verify_profiles_rejects_empty_cmd():
    with pytest.raises(BridgeError, match="空です"):
        cli._build_verify_profiles(["a"], ["   "])


def test_build_verify_profiles_rejects_duplicate_name():
    with pytest.raises(BridgeError, match="重複"):
        cli._build_verify_profiles(["a", "a"], ["echo hi", "echo bye"])
