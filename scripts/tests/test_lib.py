"""scripts/lib/ の共通ヘルパー（render-unit.sh・server-host.sh）の単体試験。

bash を subprocess で呼び、ヘルパーを source して関数を試す。ネットワーク・GPU・systemd には触れない。
走らせ方: uvx --with pytest pytest scripts/tests -q
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "scripts" / "lib"
RENDER_UNIT = LIB_DIR / "render-unit.sh"
SERVER_HOST = LIB_DIR / "server-host.sh"


def run_bash(script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """`set -euo pipefail` の bash で script を走らせる。$1 以降に args が入る。"""
    return subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + script, "test-lib", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def make_fake_repo(parent: Path, name: str) -> Path:
    """parent/name に scripts/lib/ だけを持つ偽のリポジトリを作り、その根を返す。"""
    repo_dir = parent / name
    (repo_dir / "scripts" / "lib").mkdir(parents=True)
    for helper in (RENDER_UNIT, SERVER_HOST):
        shutil.copy2(helper, repo_dir / "scripts" / "lib" / helper.name)
    return repo_dir


# --------------------------------------------------------------------------
# render-unit.sh
# --------------------------------------------------------------------------


def test_helpers_pass_bash_syntax_check() -> None:
    for helper in (RENDER_UNIT, SERVER_HOST):
        result = subprocess.run(["bash", "-n", str(helper)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_repo_root_is_resolved_from_helper_location() -> None:
    result = run_bash('source "$1"; printf %s "$LOCALAI_REPO_ROOT"', str(RENDER_UNIT))
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(REPO_ROOT)


def test_repo_root_follows_symlinked_directory(tmp_path: Path) -> None:
    # symlink 経由で source しても、ユニットには実体のパスが入る（pwd -P）
    real_repo = make_fake_repo(tmp_path, "real-repo")
    link_repo = tmp_path / "link-repo"
    link_repo.symlink_to(real_repo, target_is_directory=True)
    result = run_bash(
        'source "$1/scripts/lib/render-unit.sh"; printf %s "$LOCALAI_REPO_ROOT"', str(link_repo)
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(real_repo.resolve())


@pytest.mark.parametrize("repo_name", ["plain", "a|b", "a&b", "a\\b", "a|b&c\\d", "x\\1&y"])
def test_render_unit_file_replaces_placeholder_literally(tmp_path: Path, repo_name: str) -> None:
    # sed の区切り（|）・一致部分（&）・エスケープ（\）として解釈されず、文字どおりに入ること
    repo_dir = make_fake_repo(tmp_path, repo_name)
    template = tmp_path / "unit.service.example"
    template.write_text(
        "[Service]\n"
        "WorkingDirectory=@REPO_ROOT@/tools/x\n"
        "ExecStart=@REPO_ROOT@/tools/x/run serve --root @REPO_ROOT@\n"
        "EnvironmentFile=-%h/.config/x/x.env\n"
        "# 印の無い行と & \\ | はそのまま\n",
        encoding="utf-8",
    )
    output = tmp_path / "unit.service"
    result = run_bash(
        'source "$1/scripts/lib/render-unit.sh"; render_unit_file "$2" "$3"',
        str(repo_dir),
        str(template),
        str(output),
    )
    assert result.returncode == 0, result.stderr
    root = str(repo_dir.resolve())
    assert output.read_text(encoding="utf-8") == (
        "[Service]\n"
        f"WorkingDirectory={root}/tools/x\n"
        f"ExecStart={root}/tools/x/run serve --root {root}\n"
        "EnvironmentFile=-%h/.config/x/x.env\n"
        "# 印の無い行と & \\ | はそのまま\n"
    )


def test_render_unit_file_warns_when_path_has_systemd_special_characters(tmp_path: Path) -> None:
    repo_dir = make_fake_repo(tmp_path, "with space")
    template = tmp_path / "unit.service.example"
    template.write_text("ExecStart=@REPO_ROOT@/run\n", encoding="utf-8")
    output = tmp_path / "unit.service"
    result = run_bash(
        'source "$1/scripts/lib/render-unit.sh"; render_unit_file "$2" "$3"',
        str(repo_dir),
        str(template),
        str(output),
    )
    assert result.returncode == 0, result.stderr
    assert "警告" in result.stderr
    assert output.read_text(encoding="utf-8") == f"ExecStart={repo_dir.resolve()}/run\n"


def test_render_unit_file_does_not_warn_for_plain_path(tmp_path: Path) -> None:
    repo_dir = make_fake_repo(tmp_path, "plain")
    template = tmp_path / "unit.service.example"
    template.write_text("ExecStart=@REPO_ROOT@/run\n", encoding="utf-8")
    result = run_bash(
        'source "$1/scripts/lib/render-unit.sh"; render_unit_file "$2" "$3"',
        str(repo_dir),
        str(template),
        str(tmp_path / "unit.service"),
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize("mode", [0o644, 0o600, 0o755, 0o640])
def test_render_unit_file_keeps_template_mode(tmp_path: Path, mode: int) -> None:
    template = tmp_path / "unit.service.example"
    template.write_text("ExecStart=@REPO_ROOT@/run\n", encoding="utf-8")
    template.chmod(mode)
    output = tmp_path / "unit.service"
    result = run_bash('source "$1"; render_unit_file "$2" "$3"', str(RENDER_UNIT), str(template), str(output))
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(output.stat().st_mode) == mode
    # 一時ファイル（出力先.XXXXXX）を残さない
    assert sorted(path.name for path in tmp_path.iterdir()) == ["unit.service", "unit.service.example"]


def test_render_unit_file_without_placeholder_copies_as_is(tmp_path: Path) -> None:
    # qwen-worker の設定のように、印の無い雛形はそのまま写る（cp -p の代わりに使える）
    text = 'allowed_roots = [\n  "~/Proj",\n]\n# 100% \\ & |\n'
    template = tmp_path / "config.toml.example"
    template.write_text(text, encoding="utf-8")
    output = tmp_path / "config.toml"
    result = run_bash('source "$1"; render_unit_file "$2" "$3"', str(RENDER_UNIT), str(template), str(output))
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == text


def test_render_unit_file_missing_template_fails_without_output(tmp_path: Path) -> None:
    output = tmp_path / "unit.service"
    result = run_bash(
        'source "$1"; render_unit_file "$2" "$3"', str(RENDER_UNIT), str(tmp_path / "missing.example"), str(output)
    )
    assert result.returncode == 1
    assert "雛形が見つかりません" in result.stderr
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_render_unit_file_rejects_wrong_argument_count(tmp_path: Path) -> None:
    result = run_bash('source "$1"; render_unit_file "$2"', str(RENDER_UNIT), str(tmp_path / "only-one"))
    assert result.returncode == 2
    assert "使い方" in result.stderr


def test_render_unit_text_writes_to_stdout(tmp_path: Path) -> None:
    template = tmp_path / "unit.service.example"
    template.write_text("A=@REPO_ROOT@@REPO_ROOT@\nB=@REPO_ROOT\n", encoding="utf-8")
    result = run_bash('source "$1"; render_unit_text "$2"', str(RENDER_UNIT), str(template))
    assert result.returncode == 0, result.stderr
    # 連続した印もそれぞれ置き換え、閉じていない印（@REPO_ROOT）は触らない
    assert result.stdout == f"A={REPO_ROOT}{REPO_ROOT}\nB=@REPO_ROOT\n"


def unit_templates() -> list[Path]:
    return sorted((REPO_ROOT / "tools").glob("*/systemd/*.service.example"))


def test_unit_templates_exist() -> None:
    names = {path.name for path in unit_templates()}
    assert {
        "comfyui.service.example",
        "hunyuan3d.service.example",
        "pixal3d.service.example",
        "portal.service.example",
        "strata.service.example",
        "strata-coder.service.example",
        "strata-official.service.example",
    } <= names


@pytest.mark.parametrize("template", unit_templates(), ids=lambda path: path.name)
def test_unit_templates_use_placeholder_not_fixed_home_path(template: Path) -> None:
    text = template.read_text(encoding="utf-8")
    assert "@REPO_ROOT@" in text
    assert "%h/Proj" not in text
    assert "/home/" not in text


@pytest.mark.parametrize("template", unit_templates(), ids=lambda path: path.name)
def test_rendered_unit_points_to_existing_files_in_this_repo(template: Path) -> None:
    # 置き換えたユニットのリポジトリ内のパス（WorkingDirectory・ExecStart の実行ファイルなど）が実在すること
    result = run_bash('source "$1"; render_unit_text "$2"', str(RENDER_UNIT), str(template))
    assert result.returncode == 0, result.stderr
    assert "@REPO_ROOT@" not in result.stdout
    repo_paths = [
        token
        for line in result.stdout.splitlines()
        if not line.startswith("#") and "=" in line
        for token in line.split("=", 1)[1].split()
        if token.startswith(str(REPO_ROOT) + "/")
    ]
    assert repo_paths, "リポジトリ内のパスが 1 つも無い"
    for repo_path in repo_paths:
        assert Path(repo_path).exists(), repo_path


# --------------------------------------------------------------------------
# server-host.sh
# --------------------------------------------------------------------------


def fake_hostname_env(tmp_path: Path, addresses: str | None) -> dict[str, str]:
    """hostname -I が addresses を返す偽の hostname を PATH の先頭に置いた環境。None なら hostname 自体を置かない。"""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    if addresses is not None:
        hostname_stub = fake_bin / "hostname"
        hostname_stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{addresses}'\n", encoding="utf-8")
        hostname_stub.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key != "LOCALAI_SERVER_HOST"}
    # hostname を置かないときに本物を拾わないよう、PATH は偽の bin だけにする（ヘルパーは bash の組み込みだけで動く）
    env["PATH"] = str(fake_bin) if addresses is None else f"{fake_bin}:/usr/bin:/bin"
    return env


def detect_host(env: dict[str, str]) -> str:
    result = subprocess.run(
        ["/bin/bash", "-c", 'set -euo pipefail; source "$1"; detect_server_host', "test-lib", str(SERVER_HOST)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_detect_server_host_prefers_environment_variable(tmp_path: Path) -> None:
    env = fake_hostname_env(tmp_path, "192.168.1.5")
    env["LOCALAI_SERVER_HOST"] = "a30.example.lan"
    assert detect_host(env) == "a30.example.lan\n"


@pytest.mark.parametrize(
    ("addresses", "expected"),
    [
        ("192.168.1.10 172.17.0.1 172.18.0.1 ", "192.168.1.10"),
        # 最初の私的 IPv4 を採る（並び順のまま。Docker のブリッジが先なら LOCALAI_SERVER_HOST で指定する）
        ("172.17.0.1 192.168.1.5", "172.17.0.1"),
        ("fe80::1 2001:db8::1 8.8.8.8 10.1.2.3", "10.1.2.3"),
        ("203.0.113.7 172.31.255.254", "172.31.255.254"),
        ("203.0.113.7 172.32.0.1 192.169.0.1", "localhost"),
        ("", "localhost"),
    ],
)
def test_detect_server_host_uses_first_private_ipv4(tmp_path: Path, addresses: str, expected: str) -> None:
    assert detect_host(fake_hostname_env(tmp_path, addresses)) == expected + "\n"


def test_detect_server_host_without_hostname_command(tmp_path: Path) -> None:
    assert detect_host(fake_hostname_env(tmp_path, None)) == "localhost\n"


def test_detect_server_host_ignores_empty_environment_variable(tmp_path: Path) -> None:
    env = fake_hostname_env(tmp_path, "10.0.0.8")
    env["LOCALAI_SERVER_HOST"] = ""
    assert detect_host(env) == "10.0.0.8\n"


@pytest.mark.parametrize(
    ("address", "is_private"),
    [
        ("10.0.0.1", True),
        ("10.255.255.255", True),
        ("172.15.255.255", False),
        ("172.16.0.0", True),
        ("172.31.0.1", True),
        ("172.32.0.1", False),
        ("192.168.0.1", True),
        ("192.167.0.1", False),
        ("192.169.0.1", False),
        ("127.0.0.1", False),
        ("8.8.8.8", False),
        ("256.168.0.1", False),
        ("192.168.0.256", False),
        ("010.0.0.1", True),
        ("1.2.3", False),
        ("1.2.3.4.5", False),
        ("fe80::1", False),
        ("", False),
        ("192.168.0.1x", False),
    ],
)
def test_is_private_ipv4_address(address: str, is_private: bool) -> None:
    result = run_bash('source "$1"; is_private_ipv4_address "$2"', str(SERVER_HOST), address)
    assert result.returncode == (0 if is_private else 1), (address, result.stderr)
