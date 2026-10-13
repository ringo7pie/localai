"""各ツールの setup-server.sh の一般化（雛形の書き出し・URL のホスト・portal のポート・Hunyuan3D の使用許諾）の試験。

setup-server.sh は本物では走らせない（数十 GB のダウンロードとビルド、systemctl --user の操作が起きる）。
一時ディレクトリに偽のリポジトリ（scripts/lib/ と対象ツールの setup-server.sh・雛形だけ）を作り、
HOME もその中に向け、uv・git・systemctl・ss・curl・hostname は PATH の先頭に置いた偽物に差し替えて流す。
走らせ方: uvx --with pytest pytest scripts/tests -q
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_TOOLS = ("comfyui", "hunyuan3d", "pixal3d", "portal", "qwen-worker", "strata")
FAKE_HOST_ADDRESS = "192.168.50.7"

# 作者の機体の IP。ソース中に直書きしない（公開前の置換で壊れないよう、部品から組み立てる）。
MAINTAINER_SERVER_IP = ".".join(("192", "168", "8", "103"))


def setup_script(tool: str) -> Path:
    return REPO_ROOT / "tools" / tool / "setup-server.sh"


# --------------------------------------------------------------------------
# 全ツール共通（中身の検査と、副作用の無い呼び出しだけ）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tool", SETUP_TOOLS)
def test_setup_script_passes_bash_syntax_check(tool: str) -> None:
    result = subprocess.run(["bash", "-n", str(setup_script(tool))], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tool", SETUP_TOOLS)
def test_setup_script_help_exits_zero(tool: str, tmp_path: Path) -> None:
    # --help は何も作らずに終わる（Hunyuan3D も使用許諾の同意なしで出せる）
    env = {key: value for key, value in os.environ.items() if key != "HY3D_ACCEPT_LICENSE"}
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        ["bash", str(setup_script(tool)), "--help"], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "使い方" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tool", SETUP_TOOLS)
def test_setup_script_has_no_machine_specific_values(tool: str) -> None:
    text = setup_script(tool).read_text(encoding="utf-8")
    for fixed in (MAINTAINER_SERVER_IP, "%h/Proj/localai", "/home/mt", "mt ユーザー"):
        assert fixed not in text, fixed


@pytest.mark.parametrize("tool", SETUP_TOOLS)
def test_setup_script_renders_templates_instead_of_copying(tool: str) -> None:
    # 雛形（*.example）を cp -p でそのまま写さず、render_unit_file で @REPO_ROOT@ を置き換えて置く
    lines = setup_script(tool).read_text(encoding="utf-8").splitlines()
    assert not [line for line in lines if "cp -p" in line and "EXAMPLE" in line.upper()]
    assert any("scripts/lib/render-unit.sh" in line and line.startswith("source ") for line in lines)
    assert any("render_unit_file " in line for line in lines)


@pytest.mark.parametrize("tool", ("comfyui", "hunyuan3d", "pixal3d", "portal", "strata"))
def test_setup_script_builds_urls_from_detected_host(tool: str) -> None:
    text = setup_script(tool).read_text(encoding="utf-8")
    assert 'source "' in text and "scripts/lib/server-host.sh" in text
    assert 'SERVER_HOST="$(detect_server_host)"' in text
    assert "http://$SERVER_HOST:" in text


# --------------------------------------------------------------------------
# 偽のリポジトリと偽のコマンド
# --------------------------------------------------------------------------

STUB_SCRIPTS = {
    # 呼ばれた引数を STUB_LOG に残すだけ。is-active / is-enabled は FAKE_PORTAL_ACTIVE=1 のときだけ真。
    "systemctl": """#!/bin/bash
printf 'systemctl %s\\n' "$*" >> "$STUB_LOG"
for arg in "$@"
do
  case "$arg" in
    is-active|is-enabled)
      [ "${FAKE_PORTAL_ACTIVE:-0}" = 1 ] && exit 0
      exit 3
      ;;
  esac
done
exit 0
""",
    # 最後の引数（"sport = :8080"）のポートが FAKE_SS_PORTS にあれば、別ユーザーでない待受として 1 行返す。
    "ss": """#!/bin/bash
printf 'ss %s\\n' "$*" >> "$STUB_LOG"
last_arg="${!#}"
target_port="${last_arg##*:}"
for busy_port in ${FAKE_SS_PORTS:-}
do
  if [ "$busy_port" = "$target_port" ]; then
    printf 'LISTEN 0 4096 0.0.0.0:%s 0.0.0.0:* users:(("open-webui",pid=4242,fd=7))\\n' "$target_port"
  fi
done
exit 0
""",
    "curl": """#!/bin/bash
printf 'curl %s\\n' "$*" >> "$STUB_LOG"
printf '{"services": []}'
""",
    "hostname": f"""#!/bin/bash
printf '%s\\n' '{FAKE_HOST_ADDRESS} 172.17.0.1'
""",
    # uv venv のときだけ、偽の python を venv に置く。ほか（pip install）は何もしない。
    "uv": """#!/bin/bash
printf 'uv %s\\n' "$*" >> "$STUB_LOG"
if [ "$1" = "venv" ]; then
  venv_dir="${!#}"
  mkdir -p "$venv_dir/bin"
  cp "$FAKE_PYTHON" "$venv_dir/bin/python"
fi
exit 0
""",
    "git": """#!/bin/bash
printf 'git %s\\n' "$*" >> "$STUB_LOG"
if [ "$1" = "init" ]; then
  mkdir -p "$2/.git"
fi
exit 0
""",
}

# venv の python の偽物。sysconfig の INCLUDEPY を聞かれたら Python.h のある場所を返し、import は全部成功させる。
FAKE_PYTHON = """#!/bin/bash
printf 'python %s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  *INCLUDEPY*) printf '%s\\n' "$FAKE_INCLUDE_DIR" ;;
esac
exit 0
"""


@dataclass
class Sandbox:
    repo: Path
    home: Path
    env: dict[str, str]
    log: Path

    @property
    def unit_dir(self) -> Path:
        return self.home / ".config" / "systemd" / "user"

    def run(self, tool: str, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", str(self.repo / "tools" / tool / "setup-server.sh"), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.home,
            timeout=120,
            check=False,
        )

    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def make_sandbox(tmp_path: Path):
    def factory(tool: str) -> Sandbox:
        repo = tmp_path / "repo"
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        if not (repo / "scripts" / "lib").exists():
            shutil.copytree(REPO_ROOT / "scripts" / "lib", repo / "scripts" / "lib")
        tool_dir = repo / "tools" / tool
        (tool_dir / "systemd").mkdir(parents=True, exist_ok=True)
        shutil.copy2(setup_script(tool), tool_dir / "setup-server.sh")
        for template in (REPO_ROOT / "tools" / tool / "systemd").glob("*.example"):
            shutil.copy2(template, tool_dir / "systemd" / template.name)

        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir(exist_ok=True)
        for name, text in STUB_SCRIPTS.items():
            write_executable(fake_bin / name, text)
        write_executable(tmp_path / "fake-python", FAKE_PYTHON)
        include_dir = tmp_path / "include"
        include_dir.mkdir(exist_ok=True)
        (include_dir / "Python.h").write_text("", encoding="utf-8")

        log = tmp_path / "calls.log"
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("HY3D_ACCEPT_LICENSE", "LOCALAI_SERVER_HOST", "FAKE_SS_PORTS", "FAKE_PORTAL_ACTIVE")
        }
        env.update(
            {
                "HOME": str(home),
                # 偽物を先に見つけさせる。本物の uv（~/.local/bin）は HOME を変えたので見えない
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "STUB_LOG": str(log),
                "FAKE_PYTHON": str(tmp_path / "fake-python"),
                "FAKE_INCLUDE_DIR": str(include_dir),
            }
        )
        return Sandbox(repo=repo, home=home, env=env, log=log)

    return factory


@pytest.fixture
def listening_port() -> Iterator[int]:
    """127.0.0.1 で待ち受けるだけのソケット。入口ページが立ち上がった後の点検（/dev/tcp への接続）に使う。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(16)
        yield server.getsockname()[1]


# --------------------------------------------------------------------------
# portal
# --------------------------------------------------------------------------


def write_open_webui_unit(sandbox: Sandbox, port: int) -> Path:
    sandbox.unit_dir.mkdir(parents=True, exist_ok=True)
    unit = sandbox.unit_dir / "open-webui.service"
    unit.write_text(
        f"[Service]\nExecStart=/usr/bin/open-webui serve --host 0.0.0.0 --port {port}\n", encoding="utf-8"
    )
    return unit


def test_portal_default_installs_on_given_port_without_touching_open_webui(make_sandbox, listening_port: int) -> None:
    sandbox = make_sandbox("portal")
    webui_unit = write_open_webui_unit(sandbox, 8080)
    webui_before = webui_unit.read_text(encoding="utf-8")

    result = sandbox.run("portal", "--port", str(listening_port))

    assert result.returncode == 0, result.stdout + result.stderr
    portal_unit = sandbox.unit_dir / "portal.service"
    exec_lines = [line for line in portal_unit.read_text(encoding="utf-8").splitlines() if line.startswith("ExecStart=")]
    assert exec_lines == [
        f"ExecStart=/usr/bin/python3 {sandbox.repo.resolve()}/tools/portal/portal.py --host 0.0.0.0 --port {listening_port}"
    ]
    # 既定では Open WebUI を移さない（ユニットも .bak も触らない、再起動もしない）
    assert webui_unit.read_text(encoding="utf-8") == webui_before
    assert not (sandbox.unit_dir / "open-webui.service.bak").exists()
    calls = sandbox.calls()
    assert "systemctl --user enable --now portal" in calls
    assert not [call for call in calls if "open-webui" in call and call.startswith("systemctl")]
    assert f"http://{FAKE_HOST_ADDRESS}:{listening_port}" in result.stdout
    assert MAINTAINER_SERVER_IP not in result.stdout


def test_portal_stops_when_port_is_used_by_another_process(make_sandbox) -> None:
    sandbox = make_sandbox("portal")
    write_open_webui_unit(sandbox, 8080)

    result = sandbox.run("portal", extra_env={"FAKE_SS_PORTS": "8080"})

    assert result.returncode == 1
    assert "ポート 8080 は他のプロセスが使っています" in result.stderr
    # 使っているものを表示し、別ポートと Open WebUI を移す道を示す
    assert '"open-webui",pid=4242' in result.stderr
    assert "--port N" in result.stderr
    assert "--move-open-webui" in result.stderr
    assert not (sandbox.unit_dir / "portal.service").exists()
    assert not [call for call in sandbox.calls() if call.startswith("systemctl --user enable")]


def test_portal_keeps_existing_unit_and_uses_its_port(make_sandbox, listening_port: int) -> None:
    # 既に置いてあるユニットは上書きしない。点検はそのユニットのポートで行う
    sandbox = make_sandbox("portal")
    sandbox.unit_dir.mkdir(parents=True)
    portal_unit = sandbox.unit_dir / "portal.service"
    existing = f"[Service]\nExecStart=/usr/bin/python3 /opt/portal.py --host 0.0.0.0 --port {listening_port}\n"
    portal_unit.write_text(existing, encoding="utf-8")

    result = sandbox.run("portal")

    assert result.returncode == 0, result.stdout + result.stderr
    assert portal_unit.read_text(encoding="utf-8") == existing
    assert f"既存の portal.service はポート {listening_port} です" in result.stderr
    assert f"http://{FAKE_HOST_ADDRESS}:{listening_port}" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--port", "abc"),
        ("--port", "0"),
        ("--port", "65536"),
        ("--port", "80 80"),
        ("--port",),
        ("--revert", "--port", "9000"),
        ("--move-open-webui", "--port", "8081"),
        ("--unknown",),
    ],
)
def test_portal_rejects_bad_arguments(make_sandbox, args: tuple[str, ...]) -> None:
    sandbox = make_sandbox("portal")
    result = sandbox.run("portal", *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert sandbox.calls() == []
    assert not sandbox.unit_dir.exists()


def test_portal_revert_without_flag_leaves_open_webui(make_sandbox) -> None:
    sandbox = make_sandbox("portal")
    webui_unit = write_open_webui_unit(sandbox, 8081)
    backup = sandbox.unit_dir / "open-webui.service.bak"
    backup.write_text("[Service]\nExecStart=/usr/bin/open-webui serve --port 8080\n", encoding="utf-8")
    webui_before = webui_unit.read_text(encoding="utf-8")

    result = sandbox.run("portal", "--revert")

    assert result.returncode == 0, result.stdout + result.stderr
    assert webui_unit.read_text(encoding="utf-8") == webui_before
    assert "--revert --move-open-webui" in result.stdout
    assert not [call for call in sandbox.calls() if "open-webui" in call]


def test_portal_unit_example_port_is_replaceable() -> None:
    # setup-server.sh は ExecStart の --port の値を置き換える。雛形にその形があること
    text = (REPO_ROOT / "tools" / "portal" / "systemd" / "portal.service.example").read_text(encoding="utf-8")
    exec_lines = [line for line in text.splitlines() if line.startswith("ExecStart=")]
    assert exec_lines == ["ExecStart=/usr/bin/python3 @REPO_ROOT@/tools/portal/portal.py --host 0.0.0.0 --port 8080"]


def test_portal_py_accepts_port_argument() -> None:
    text = (REPO_ROOT / "tools" / "portal" / "portal.py").read_text(encoding="utf-8")
    assert 'add_argument("--port"' in text


# --------------------------------------------------------------------------
# hunyuan3d
# --------------------------------------------------------------------------

LICENSE_URL = (
    "https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/f8db63096c8282cb27354314d896feba5ba6ff8a/LICENSE"
)


def make_hunyuan3d_sandbox(make_sandbox) -> Sandbox:
    sandbox = make_sandbox("hunyuan3d")
    # 重みの取得と点検は run-hunyuan3d が行う。偽物にして呼ばれた引数だけ残す
    write_executable(
        sandbox.repo / "tools" / "hunyuan3d" / "run-hunyuan3d",
        "#!/bin/bash\nprintf 'run-hunyuan3d %s\\n' \"$*\" >> \"$STUB_LOG\"\nexit 0\n",
    )
    return sandbox


@pytest.mark.parametrize("env_value", [None, "", "0", "yes", "true"])
def test_hunyuan3d_stops_before_anything_without_license_acceptance(make_sandbox, env_value: str | None) -> None:
    sandbox = make_hunyuan3d_sandbox(make_sandbox)
    extra_env = {} if env_value is None else {"HY3D_ACCEPT_LICENSE": env_value}

    result = sandbox.run("hunyuan3d", extra_env=extra_env)

    assert result.returncode == 2
    # 要約の 4 点と原文の URL を表示する
    for phrase in ("欧州連合（EU）・英国（UK）・韓国", "100 万人", "Notice", "他の AI モデルを改善してはいけません"):
        assert phrase in result.stdout, phrase
    assert LICENSE_URL in result.stdout
    assert "vendor/Hunyuan3D-2/LICENSE" in result.stdout
    assert "--accept-tencent-license" in result.stderr
    # uv・git・run-hunyuan3d のどれも呼ばず、何も作らない
    assert sandbox.calls() == []
    tool_dir = sandbox.repo / "tools" / "hunyuan3d"
    assert not (tool_dir / ".venv").exists()
    assert not (tool_dir / "vendor").exists()
    assert not sandbox.unit_dir.exists()


@pytest.mark.parametrize(
    ("args", "extra_env"),
    [
        (("--accept-tencent-license",), {}),
        ((), {"HY3D_ACCEPT_LICENSE": "1"}),
    ],
)
def test_hunyuan3d_runs_through_with_acceptance_and_skips_missing_patches(
    make_sandbox, args: tuple[str, ...], extra_env: dict[str, str]
) -> None:
    sandbox = make_hunyuan3d_sandbox(make_sandbox)

    result = sandbox.run("hunyuan3d", *args, extra_env=extra_env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "使用許諾: 同意を確認しました" in result.stdout
    # 公開版には patches/ が無い。当て物の工程を飛ばしたことを 1 行で知らせる
    skip_lines = [line for line in result.stdout.splitlines() if line.startswith("パッチ:")]
    assert len(skip_lines) == 1
    assert "公開版にはパッチを含めない" in skip_lines[0]
    assert "UI の説明・設定の保存・失敗パラメータの表示は使えない" in skip_lines[0]
    assert not [call for call in sandbox.calls() if call.startswith("git ") and "checkout -- ." in call]
    # ユニットはこの偽のリポジトリの絶対パスを指す
    unit_text = (sandbox.unit_dir / "hunyuan3d.service").read_text(encoding="utf-8")
    repo_root = sandbox.repo.resolve()
    assert f"WorkingDirectory={repo_root}/tools/hunyuan3d" in unit_text.splitlines()
    assert f"ExecStart={repo_root}/tools/hunyuan3d/run-hunyuan3d serve" in unit_text.splitlines()
    assert "@REPO_ROOT@" not in unit_text
    assert f"http://{FAKE_HOST_ADDRESS}:7860" in result.stdout
    calls = sandbox.calls()
    assert "run-hunyuan3d fetch-models" in calls
    assert "run-hunyuan3d doctor" in calls


def test_hunyuan3d_does_not_overwrite_existing_unit(make_sandbox) -> None:
    sandbox = make_hunyuan3d_sandbox(make_sandbox)
    sandbox.unit_dir.mkdir(parents=True)
    unit = sandbox.unit_dir / "hunyuan3d.service"
    unit.write_text("# 手で直したユニット\n", encoding="utf-8")

    result = sandbox.run("hunyuan3d", "--accept-tencent-license", "--skip-models", "--no-autostart")

    assert result.returncode == 0, result.stdout + result.stderr
    assert unit.read_text(encoding="utf-8") == "# 手で直したユニット\n"
    assert "systemd ユニット: 既にあります" in result.stdout


def test_hunyuan3d_applies_patches_when_present(make_sandbox) -> None:
    # 手元に patches/ があるときは、従来どおり固定コミットへ戻してから当てる
    sandbox = make_hunyuan3d_sandbox(make_sandbox)
    patch_dir = sandbox.repo / "tools" / "hunyuan3d" / "patches"
    patch_dir.mkdir()
    (patch_dir / "0001-example.patch").write_text("", encoding="utf-8")

    result = sandbox.run("hunyuan3d", "--accept-tencent-license", "--skip-models", "--no-autostart")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "パッチ 0001-example.patch: 当てました" in result.stdout
    assert not [line for line in result.stdout.splitlines() if line.startswith("パッチ:")]
    calls = sandbox.calls()
    assert any(call.endswith("checkout -- .") for call in calls)
    assert any("apply" in call and call.endswith("0001-example.patch") for call in calls)
