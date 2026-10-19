"""localai（ルートの導入用 CLI）と scripts/build-site.sh の試験。

実機の GPU・systemd・Ollama・入口ページには触れない。subprocess で呼び、PATH を作り直して
nvidia-smi や git が無い機体、systemctl や ss が偽物の機体を再現する。入口ページと Ollama は
127.0.0.1 の使い捨ての HTTP サーバーで代用する（LOCALAI_PORTAL_URL / LOCALAI_OLLAMA_URL）。
試験の中で localai の start / stop を呼んでも、実機のサービスには届かない。

実行: uvx --with pytest pytest scripts/tests/test_localai.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCALAI_SCRIPT = REPO_ROOT / "localai"
BUILD_SITE_SCRIPT = REPO_ROOT / "scripts" / "build-site.sh"
BASH = shutil.which("bash") or "/usr/bin/bash"

# localai が使うふつうの外部コマンド。偽の PATH へは実物への symlink で置く。
# nvidia-smi・git・uv・systemctl・ss・df・ollama は含めない（試験ごとに偽物を置くか、置かない）。
BASE_COMMANDS = [
    "bash", "readlink", "dirname", "grep", "head", "tail", "cut", "tr", "awk", "sed",
    "uname", "timeout", "cat", "sort", "wc", "find", "ls", "mkdir", "cp", "rm", "env",
]

SYSTEMCTL_STUB = textwrap.dedent(
    """\
    #!/bin/sh
    # 試験用の systemctl。呼び出しを calls.log に残す。unit の状態は $FAKE_SYSTEMD_DIR/<unit> の
    # 1 行（"<LoadState> <ActiveState>"）から返す。ファイルが無い unit は not-found。
    printf '%s\\n' "$*" >> "$FAKE_SYSTEMD_DIR/calls.log"
    if [ "$1" = "--user" ]; then shift; fi
    case "$1" in
      show-environment)
        if [ -f "$FAKE_SYSTEMD_DIR/no-user-bus" ]; then exit 1; fi
        echo "HOME=/fake"
        exit 0
        ;;
      show)
        unit="$2"
        if [ -f "$FAKE_SYSTEMD_DIR/$unit" ]; then
          read -r load active < "$FAKE_SYSTEMD_DIR/$unit"
        else
          load="not-found"
          active="inactive"
        fi
        echo "LoadState=$load"
        echo "ActiveState=$active"
        exit 0
        ;;
      is-active)
        unit="$2"
        active="inactive"
        if [ -f "$FAKE_SYSTEMD_DIR/$unit" ]; then
          read -r load active < "$FAKE_SYSTEMD_DIR/$unit"
        fi
        echo "$active"
        [ "$active" = "active" ]
        exit $?
        ;;
      *)
        exit 0
        ;;
    esac
    """
)

SS_STUB = textwrap.dedent(
    """\
    #!/bin/sh
    # 試験用の ss。$FAKE_LISTEN_FILE の各行 "<ポート> <プロセス名>" にあるポートだけが待受中。
    for last_arg in "$@"; do :; done
    port="${last_arg##*:}"
    case "$*" in *-ltnp*) with_users=1 ;; *) with_users=0 ;; esac
    if [ -f "$FAKE_LISTEN_FILE" ]; then
      while read -r listen_port listen_name; do
        if [ "$listen_port" = "$port" ]; then
          if [ "$with_users" = 1 ]; then
            echo "LISTEN 0 4096 0.0.0.0:$port 0.0.0.0:* users:((\\"$listen_name\\",pid=123,fd=3))"
          else
            echo "LISTEN 0 4096 0.0.0.0:$port 0.0.0.0:*"
          fi
        fi
      done < "$FAKE_LISTEN_FILE"
    fi
    exit 0
    """
)

DF_STUB = textwrap.dedent(
    """\
    #!/bin/sh
    # 試験用の df。空きは $FAKE_DF_AVAIL_KIB（既定 500 GiB）。
    echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
    echo "/dev/fake 999999999 1000000 ${FAKE_DF_AVAIL_KIB:-524288000} 1% /fake"
    """
)

NVIDIA_SMI_STUB = textwrap.dedent(
    """\
    #!/bin/sh
    # 試験用の nvidia-smi。$FAKE_NVIDIA_SMI_OUTPUT（既定は A30）をそのまま返す。
    echo "${FAKE_NVIDIA_SMI_OUTPUT:-NVIDIA A30, 24576, 595.91.07}"
    """
)


# ---------------------------------------------------------------- 偽の機体


def _free_port() -> int:
    """いま誰も待受していないポートを 1 つ返す（接続拒否を再現するための閉じたポート）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class FakeMachine:
    """PATH・HOME・各種の差し替え先を tmp_path の中に作る。localai をその機体で走らせる。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin_dir = root / "bin"
        self.home_dir = root / "home"
        self.systemd_dir = root / "systemd"
        self.logs_dir = root / "logs"
        self.listen_file = root / "listen.txt"
        for directory in (self.bin_dir, self.home_dir, self.systemd_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)

        for name in BASE_COMMANDS:
            real_path = shutil.which(name)
            if real_path:
                (self.bin_dir / name).symlink_to(real_path)
        # python3 は、試験を走らせている環境の仮想環境ではなく、あればシステムのものを使う。
        python3_path = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else shutil.which("python3")
        if python3_path:
            (self.bin_dir / "python3").symlink_to(python3_path)
        curl_path = shutil.which("curl")
        if curl_path:
            (self.bin_dir / "curl").symlink_to(curl_path)

        self.add_stub("git", '#!/bin/sh\necho "git version 9.9.9"\n')
        self.add_stub("uv", '#!/bin/sh\necho "uv 9.9.9"\n')
        self.add_stub("nvidia-smi", NVIDIA_SMI_STUB)
        self.add_stub("systemctl", SYSTEMCTL_STUB)
        self.add_stub("ss", SS_STUB)
        self.add_stub("df", DF_STUB)

        self.os_release = root / "os-release"
        self.os_release.write_text(
            'PRETTY_NAME="Ubuntu 24.04.5 LTS"\nID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8"
        )
        self.meminfo = root / "meminfo"
        self.set_ram_gib(64)
        self.cuda_root = root / "cuda"
        for version in ("13.2", "12.6"):
            _write_executable(self.cuda_root / f"cuda-{version}" / "bin" / "nvcc", "#!/bin/sh\n")

        # 入口ページと Ollama は、既定では閉じたポートを指す（応答しない機体）。
        self.portal_url = f"http://127.0.0.1:{_free_port()}"
        self.ollama_url = f"http://127.0.0.1:{_free_port()}"
        self.extra_env: dict[str, str] = {}
        self.script = LOCALAI_SCRIPT

    # ---- 機体の組み立て

    def add_stub(self, name: str, text: str) -> None:
        _write_executable(self.bin_dir / name, text)

    def remove(self, name: str) -> None:
        path = self.bin_dir / name
        if path.exists() or path.is_symlink():
            path.unlink()

    def set_ram_gib(self, gib: float) -> None:
        self.meminfo.write_text(f"MemTotal:       {int(gib * 1024 * 1024)} kB\n", encoding="utf-8")

    def set_unit(self, unit: str, load_state: str = "loaded", active_state: str = "inactive") -> None:
        (self.systemd_dir / unit).write_text(f"{load_state} {active_state}\n", encoding="utf-8")

    def set_listening(self, port: int, process_name: str) -> None:
        with self.listen_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{port} {process_name}\n")

    def systemctl_calls(self) -> list[str]:
        log_path = self.systemd_dir / "calls.log"
        if not log_path.exists():
            return []
        return log_path.read_text(encoding="utf-8").splitlines()

    # ---- 実行

    def env(self) -> dict[str, str]:
        environment = {
            "PATH": str(self.bin_dir),
            "HOME": str(self.home_dir),
            "LANG": "C.UTF-8",
            "NO_COLOR": "1",
            "LOCALAI_OS_RELEASE": str(self.os_release),
            "LOCALAI_MEMINFO": str(self.meminfo),
            "LOCALAI_CUDA_ROOT": str(self.cuda_root),
            "LOCALAI_PORTAL_URL": self.portal_url,
            "LOCALAI_OLLAMA_URL": self.ollama_url,
            "FAKE_SYSTEMD_DIR": str(self.systemd_dir),
            "FAKE_LISTEN_FILE": str(self.listen_file),
            "FAKE_LOG_DIR": str(self.logs_dir),
        }
        environment.update(self.extra_env)
        return environment

    def run(self, *arguments: str, script: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(script or self.script), *arguments],
            env=self.env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            cwd=self.root,
            check=False,
        )


@pytest.fixture()
def machine(tmp_path: Path) -> FakeMachine:
    return FakeMachine(tmp_path)


def make_fake_repo(machine: FakeMachine, files: list[str]) -> Path:
    """localai を複製した小さなリポジトリを作る（スクリプトの位置からリポジトリの場所を決める確認も兼ねる）。

    files は作る空ファイル（"tools/portal/setup-server.sh" など）。末尾が "/" ならディレクトリ。
    """
    repo = machine.root / "repo"
    repo.mkdir()
    copied = repo / "localai"
    shutil.copy2(LOCALAI_SCRIPT, copied)
    copied.chmod(0o755)
    for name in files:
        target = repo / name
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
    machine.script = copied
    return repo


# ---------------------------------------------------------------- 使い捨ての HTTP サーバー


class JsonServer:
    """127.0.0.1 の空きポートで、固定の JSON を返す。受けた要求を requests に残す。

    routes は {(メソッド, パス): (ステータス, 応答の dict)} か、要求を受けて (ステータス, dict) を返す関数。
    """

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        self.routes = routes
        self.requests: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                record = {"method": self.command, "path": self.path, "headers": dict(self.headers)}
                owner.requests.append(record)
                route = owner.routes.get((self.command, self.path))
                if callable(route):
                    status, body = route(record)
                elif route is not None:
                    status, body = route
                else:
                    status, body = 404, {"ok": False, "message": "no route"}
                payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _handle
            do_POST = _handle

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "JsonServer":
        self.thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def portal_status_body() -> dict[str, object]:
    services = [
        ("open-webui", 8081),
        ("strata", 8082),
        ("strata-coder", 8083),
        ("strata-official", 8084),
        ("strata-official-iq3s", 8085),
        ("strata-swift", 8086),
        ("hunyuan3d", 7860),
        ("pixal3d", 7861),
        ("comfyui", 8188),
    ]
    return {
        "gpu": {"used_mib": 16, "total_mib": 24576, "available": True},
        "ollama": {"reachable": True, "models": []},
        "services": [
            {"key": key, "name": key, "port": port, "up": False, "state": "stopped", "controllable": True}
            for key, port in services
        ],
    }


def portal_routes(overrides: dict[tuple[str, str], object] | None = None) -> dict[tuple[str, str], object]:
    """入口ページの応答。X-Portal-Request ヘッダが無い POST は 403（本物と同じ）。"""

    def service_action(key: str, action: str) -> Callable[[dict[str, object]], tuple[int, dict[str, object]]]:
        def respond(record: dict[str, object]) -> tuple[int, dict[str, object]]:
            headers = {name.lower(): value for name, value in dict(record["headers"]).items()}  # type: ignore[arg-type]
            if headers.get("x-portal-request") != "1":
                return 403, {"ok": False, "message": "X-Portal-Request ヘッダが要ります"}
            label = "起動" if action == "start" else "停止"
            return 200, {"ok": True, "message": f"{key} の{label}を要求しました。", "state": "starting"}

        return respond

    routes: dict[tuple[str, str], object] = {("GET", "/api/status"): (200, portal_status_body())}
    for key in ("open-webui", "strata", "strata-coder", "strata-official", "strata-official-iq3s", "strata-swift",
                "hunyuan3d", "pixal3d", "comfyui"):
        for action in ("start", "stop"):
            routes[("POST", f"/api/service/{key}/{action}")] = service_action(key, action)
    routes.update(overrides or {})
    return routes


# ---------------------------------------------------------------- 引数の処理


def test_help_exits_zero_and_lists_subcommands(machine: FakeMachine) -> None:
    for flag in ("-h", "--help"):
        result = machine.run(flag)
        assert result.returncode == 0, result.stderr
        for word in ("doctor", "install", "start", "stop", "restart", "status", "test"):
            assert word in result.stdout


def test_no_arguments_prints_usage(machine: FakeMachine) -> None:
    result = machine.run()
    assert result.returncode == 0
    assert "使い方: localai" in result.stdout


def test_unknown_subcommand_exits_2(machine: FakeMachine) -> None:
    result = machine.run("frobnicate")
    assert result.returncode == 2
    assert "frobnicate" in result.stderr


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_control_requires_service_name(machine: FakeMachine, action: str) -> None:
    result = machine.run(action)
    assert result.returncode == 2
    assert "サービス名" in result.stderr


@pytest.mark.parametrize("arguments", [("start", "nope"), ("stop", "nope"), ("status", "nope")])
def test_unknown_service_exits_2(machine: FakeMachine, arguments: tuple[str, ...]) -> None:
    result = machine.run(*arguments)
    assert result.returncode == 2
    assert "nope" in result.stderr


@pytest.mark.parametrize("arguments", [("test", "--bogus"), ("test", "--only"), ("test", "--only", "nope")])
def test_test_bad_arguments_exit_2(machine: FakeMachine, arguments: tuple[str, ...]) -> None:
    result = machine.run(*arguments)
    assert result.returncode == 2


# ---------------------------------------------------------------- install


def test_install_without_name_lists_tools_and_minimal_path(machine: FakeMachine) -> None:
    result = machine.run("install")
    assert result.returncode == 0
    for name in ("portal", "strata", "pixal3d", "comfyui", "hunyuan3d", "qwen-worker", "ollama"):
        assert name in result.stdout
    assert "最小の導入経路" in result.stdout


def test_install_unknown_name_exits_2(machine: FakeMachine) -> None:
    result = machine.run("install", "nope")
    assert result.returncode == 2


def test_install_ollama_only_prints_the_official_steps(machine: FakeMachine) -> None:
    # curl と sh が呼ばれたら記録する。表示だけで、何も実行しないこと。
    marker = machine.logs_dir / "called.log"
    for name in ("curl", "sh", "ollama", "sudo"):
        machine.remove(name)
        machine.add_stub(name, f'#!/bin/sh\necho "{name} $*" >> "{marker}"\n')
    result = machine.run("install", "ollama")
    assert result.returncode == 0
    assert "https://ollama.com/download" in result.stdout
    assert "ollama pull qwen3.8:27b" in result.stdout
    assert not marker.exists()


def test_install_passes_arguments_to_setup_script(machine: FakeMachine) -> None:
    repo = make_fake_repo(machine, [])
    setup_script = repo / "tools" / "strata" / "setup-server.sh"
    _write_executable(setup_script, '#!/usr/bin/env bash\necho "setup-called: $*"\nexit 7\n')
    result = machine.run("install", "strata", "--model", "coder", "--skip-models")
    assert result.returncode == 7  # setup-server.sh の終了コードをそのまま返す
    assert "setup-called: --model coder --skip-models" in result.stdout


def test_install_reports_missing_setup_script(machine: FakeMachine) -> None:
    make_fake_repo(machine, [])
    result = machine.run("install", "pixal3d")
    assert result.returncode == 1
    assert "setup-server.sh" in result.stderr


def test_repo_root_is_resolved_from_a_symlink(machine: FakeMachine) -> None:
    repo = make_fake_repo(machine, [])
    _write_executable(repo / "tools" / "portal" / "setup-server.sh", '#!/usr/bin/env bash\necho "root-ok"\n')
    link_dir = machine.root / "elsewhere"
    link_dir.mkdir()
    (link_dir / "localai").symlink_to(repo / "localai")
    result = machine.run("install", "portal", script=link_dir / "localai")
    assert result.returncode == 0
    assert "root-ok" in result.stdout


# ---------------------------------------------------------------- doctor


def doctor(machine: FakeMachine) -> subprocess.CompletedProcess[str]:
    return machine.run("doctor")


def test_doctor_a30_machine_has_no_ng(machine: FakeMachine) -> None:
    result = doctor(machine)
    assert result.returncode == 0, result.stdout
    assert "[ OK ] GPU 0: NVIDIA A30" in result.stdout
    assert "[ OK ] NVIDIA ドライバ: 595.91.07" in result.stdout
    assert "[ OK ] CUDA 13.2" in result.stdout
    assert "[ OK ] CUDA 12.6" in result.stdout
    assert "NG 0" in result.stdout


def test_doctor_without_nvidia_smi_warns_and_exits_zero(machine: FakeMachine) -> None:
    machine.remove("nvidia-smi")
    result = doctor(machine)
    assert result.returncode == 0, result.stdout
    assert "[WARN] GPU: nvidia-smi が無い" in result.stdout
    assert "portal・評価レポートの閲覧・試験" in result.stdout


def test_doctor_small_gpu_warns(machine: FakeMachine) -> None:
    machine.extra_env["FAKE_NVIDIA_SMI_OUTPUT"] = "NVIDIA T4, 15360, 595.91.07"
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] GPU 0" in result.stdout
    assert "24 GiB 未満" in result.stdout
    assert "A30 24GB 前提" in result.stdout


def test_doctor_24gb_card_that_reports_24564_mib_is_ok(machine: FakeMachine) -> None:
    machine.extra_env["FAKE_NVIDIA_SMI_OUTPUT"] = "NVIDIA GeForce RTX 4090, 24564, 595.91.07"
    result = doctor(machine)
    assert "[ OK ] GPU 0: NVIDIA GeForce RTX 4090" in result.stdout


def test_doctor_old_driver_warns(machine: FakeMachine) -> None:
    machine.extra_env["FAKE_NVIDIA_SMI_OUTPUT"] = "NVIDIA A30, 24576, 550.54.15"
    result = doctor(machine)
    assert "[WARN] NVIDIA ドライバ: 550.54.15" in result.stdout


def test_doctor_missing_cuda_warns_per_version(machine: FakeMachine) -> None:
    shutil.rmtree(machine.cuda_root / "cuda-13.2")
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] CUDA 13.2" in result.stdout
    assert "[ OK ] CUDA 12.6" in result.stdout


def test_doctor_ram_thresholds(machine: FakeMachine) -> None:
    machine.set_ram_gib(16)
    assert "[WARN] RAM: 16.0 GiB（32 GiB 未満）" in doctor(machine).stdout
    machine.set_ram_gib(48)
    output = doctor(machine).stdout
    assert "[ OK ] RAM: 48.0 GiB" in output
    assert "64 GiB 推奨" in output
    machine.set_ram_gib(62.5)
    assert "[ OK ] RAM: 62.5 GiB\n" in doctor(machine).stdout


def test_doctor_low_disk_warns(machine: FakeMachine) -> None:
    machine.extra_env["FAKE_DF_AVAIL_KIB"] = str(50 * 1024 * 1024)
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] ディスク（ホーム）: 空き 50 GiB" in result.stdout


def test_doctor_non_ubuntu_warns(machine: FakeMachine) -> None:
    machine.os_release.write_text('PRETTY_NAME="Debian GNU/Linux 12"\nID=debian\nVERSION_ID="12"\n', encoding="utf-8")
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] OS: Debian GNU/Linux 12" in result.stdout


@pytest.mark.parametrize("missing", ["git", "uv"])
def test_doctor_exits_1_when_a_required_tool_is_missing(machine: FakeMachine, missing: str) -> None:
    machine.remove(missing)
    result = doctor(machine)
    assert result.returncode == 1
    assert f"[ NG ] {missing}" in result.stdout


def test_doctor_exits_1_when_python3_is_missing(machine: FakeMachine) -> None:
    machine.remove("python3")
    result = doctor(machine)
    assert result.returncode == 1
    assert "[ NG ] python3" in result.stdout


def test_doctor_old_python3_warns(machine: FakeMachine) -> None:
    machine.remove("python3")
    machine.add_stub("python3", '#!/bin/sh\necho "3.10.12"\n')
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] python3: 3.10.12（3.12 未満）" in result.stdout


def test_doctor_systemd_user_unavailable_warns(machine: FakeMachine) -> None:
    (machine.systemd_dir / "no-user-bus").write_text("", encoding="utf-8")
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] systemctl --user" in result.stdout


def test_doctor_reports_missing_ollama_and_unreachable_api(machine: FakeMachine) -> None:
    result = doctor(machine)
    assert "[WARN] ollama: 無い" in result.stdout
    assert "./localai install ollama" in result.stdout
    assert "[WARN] Ollama API" in result.stdout


def test_doctor_checks_the_ollama_model(machine: FakeMachine) -> None:
    tags_with_model = {"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b"}]}
    with JsonServer({("GET", "/api/tags"): (200, tags_with_model)}) as server:
        machine.ollama_url = server.url
        output = doctor(machine).stdout
    assert "[ OK ] Ollama API" in output
    assert "[ OK ] Ollama のモデル: qwen3.8:27b がある" in output

    with JsonServer({("GET", "/api/tags"): (200, {"models": [{"name": "gemma4:e4b"}]})}) as server:
        machine.ollama_url = server.url
        output = doctor(machine).stdout
    assert "[WARN] Ollama のモデル: qwen3.8:27b が無い" in output
    assert "ollama pull qwen3.8:27b" in output


def test_doctor_port_used_by_another_process_warns(machine: FakeMachine) -> None:
    machine.set_listening(8082, "someserver")
    result = doctor(machine)
    assert result.returncode == 0
    assert "[WARN] ポート 8082: 使用中（使用者: someserver。strata 用のポート）" in result.stdout
    assert "[ OK ] ポート 8083: 空き" in result.stdout


def test_doctor_port_used_by_its_own_unit_is_ok(machine: FakeMachine) -> None:
    machine.set_listening(8080, "python3")
    machine.set_unit("portal", "loaded", "active")
    result = doctor(machine)
    assert "[ OK ] ポート 8080: portal が使用中" in result.stdout


# ---------------------------------------------------------------- test


# 全部の試験が見つかる小さなリポジトリ（中身は空。uvx は偽物に差し替える）。
ALL_TEST_PATHS = [
    "scripts/tests/",
    "tools/portal/tests/test_units.py",
    "tools/gpu-watch-gui/tests/test_units.py",
    "tools/pixal3d/tests/test_units.py",
    "tools/hunyuan3d/tests/test_units.py",
    "tools/comfyui/tests/test_units.py",
    "tools/strata/tests/",
    "tools/qwen-worker/tests/",
    "tools/local-ai-bridge/tests/",
    "tools/model-eval/tests/",
]


def add_fake_uvx(machine: FakeMachine, exit_code: int = 0, summary: str = "5 passed in 0.01s") -> Path:
    """呼び出しの引数を 1 行ずつ log に残し、summary を出して exit_code で終わる uvx。"""
    log_path = machine.logs_dir / "uvx.log"
    machine.add_stub(
        "uvx",
        f'#!/bin/sh\necho "$*" >> "{log_path}"\necho "{summary}"\nexit {exit_code}\n',
    )
    return log_path


def uvx_calls(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []
    return log_path.read_text(encoding="utf-8").splitlines()


def test_test_list_names_every_test_without_running_anything(machine: FakeMachine) -> None:
    result = machine.run("test", "--list")
    assert result.returncode == 0
    for name in (
        "localai", "portal", "gpu-watch-gui", "pixal3d", "hunyuan3d", "comfyui", "strata",
        "qwen-worker", "local-ai-bridge", "model-eval", "hunyuan3d-real", "local-ai-bridge-real",
    ):
        assert name in result.stdout


def test_test_only_runs_just_the_selected_test(machine: FakeMachine) -> None:
    make_fake_repo(machine, ALL_TEST_PATHS)
    log_path = add_fake_uvx(machine)
    result = machine.run("test", "--only", "strata")
    assert result.returncode == 0, result.stdout
    assert "[ OK ] strata: 5 passed in 0.01s" in result.stdout
    assert "portal" not in result.stdout
    calls = uvx_calls(log_path)
    assert len(calls) == 1
    assert "tools/strata/tests" in calls[0]


def test_test_only_accepts_commas_and_repeats(machine: FakeMachine) -> None:
    make_fake_repo(machine, ALL_TEST_PATHS)
    log_path = add_fake_uvx(machine)
    result = machine.run("test", "--only", "strata,pixal3d", "--only", "portal")
    assert result.returncode == 0, result.stdout
    assert len(uvx_calls(log_path)) == 3
    for name in ("strata", "pixal3d", "portal"):
        assert f"[ OK ] {name}:" in result.stdout


def test_test_failure_exits_1_and_shows_the_output(machine: FakeMachine) -> None:
    make_fake_repo(machine, ALL_TEST_PATHS)
    add_fake_uvx(machine, exit_code=1, summary="2 failed, 3 passed in 0.10s")
    result = machine.run("test", "--only", "pixal3d")
    assert result.returncode == 1
    assert "[FAIL] pixal3d" in result.stdout
    assert "2 failed, 3 passed" in result.stdout
    assert "FAIL 1" in result.stdout


def test_test_real_machine_tests_are_always_skipped(machine: FakeMachine) -> None:
    # uvx が無くても、SKIP だけの指定なら走らせるものが無いので成功する。
    result = machine.run("test", "--only", "hunyuan3d-real", "--only", "local-ai-bridge-real")
    assert result.returncode == 0, result.stdout
    assert "[SKIP] hunyuan3d-real" in result.stdout
    assert "[SKIP] local-ai-bridge-real" in result.stdout
    assert "GPU" in result.stdout


def test_test_without_uvx_fails_instead_of_skipping_everything(machine: FakeMachine) -> None:
    make_fake_repo(machine, ALL_TEST_PATHS)
    result = machine.run("test", "--only", "strata")
    assert result.returncode == 1
    assert "uvx" in result.stderr


def test_test_skips_when_the_tests_are_not_in_this_clone(machine: FakeMachine) -> None:
    make_fake_repo(machine, ["tools/portal/tests/test_units.py"])
    log_path = add_fake_uvx(machine)
    result = machine.run("test", "--only", "strata,portal")
    assert result.returncode == 0, result.stdout
    assert "[SKIP] strata" in result.stdout
    assert "[ OK ] portal" in result.stdout
    assert len(uvx_calls(log_path)) == 1


def test_test_default_runs_every_listed_test_and_skips_the_real_ones(machine: FakeMachine) -> None:
    make_fake_repo(machine, ALL_TEST_PATHS)
    log_path = add_fake_uvx(machine)
    result = machine.run("test")
    assert result.returncode == 0, result.stdout
    assert "OK 10 / FAIL 0 / SKIP 2" in result.stdout
    # comfyui は 2 回（ワークフロー検査とメッシュ計測）走るので、uvx の呼び出しは 11 回。
    calls = uvx_calls(log_path)
    assert len(calls) == 11
    assert sum("numpy" in call for call in calls) == 1
    # 依存を持つツールは、venv が無ければ lock を渡す。
    assert any("--with-requirements tools/qwen-worker/requirements.lock.txt" in call for call in calls)
    assert any("--with-requirements tools/local-ai-bridge/requirements.lock.txt" in call for call in calls)
    assert any("--ignore=tools/local-ai-bridge/tests/test_integration.py" in call for call in calls)


# ---------------------------------------------------------------- start / stop / restart / status（入口ページ経由）


def test_start_goes_through_the_portal_api_with_the_required_header(machine: FakeMachine) -> None:
    with JsonServer(portal_routes()) as server:
        machine.portal_url = server.url
        result = machine.run("start", "strata")
    assert result.returncode == 0, result.stderr
    assert "strata の起動を要求しました。" in result.stdout
    posts = [request for request in server.requests if request["method"] == "POST"]
    assert [request["path"] for request in posts] == ["/api/service/strata/start"]
    header_names = {name.lower() for name in dict(posts[0]["headers"])}  # type: ignore[arg-type]
    assert "x-portal-request" in header_names
    # 入口ページに任せるので、systemctl は呼ばない。
    assert machine.systemctl_calls() == []


def test_start_shows_what_the_portal_stopped_and_unloaded(machine: FakeMachine) -> None:
    body = {
        "ok": True,
        "message": "Pixal3D を停止してから起動しました。",
        "state": "starting",
        "stopped": ["pixal3d"],
        "unloaded_models": ["qwen3.8:27b"],
    }
    with JsonServer(portal_routes({("POST", "/api/service/strata/start"): (200, body)})) as server:
        machine.portal_url = server.url
        result = machine.run("start", "strata")
    assert result.returncode == 0
    assert "先に停止したサービス: pixal3d" in result.stdout
    assert "降ろした Ollama のモデル: qwen3.8:27b" in result.stdout


def test_start_of_a_service_that_is_not_installed_points_to_install(machine: FakeMachine) -> None:
    body = {"ok": False, "message": "未導入です。操作できません。", "state": "not_installed"}
    with JsonServer(portal_routes({("POST", "/api/service/pixal3d/start"): (409, body)})) as server:
        machine.portal_url = server.url
        result = machine.run("start", "pixal3d")
    assert result.returncode == 1
    assert "未導入" in result.stdout
    assert "./localai install pixal3d" in result.stdout


def test_failed_action_reported_by_the_portal_exits_1(machine: FakeMachine) -> None:
    body = {"ok": False, "message": "Pixal3D の停止に失敗したため、起動を中止しました。", "state": "stopped"}
    with JsonServer(portal_routes({("POST", "/api/service/strata/start"): (200, body)})) as server:
        machine.portal_url = server.url
        result = machine.run("start", "strata")
    assert result.returncode == 1
    assert "起動を中止しました" in result.stdout


def test_stop_goes_through_the_portal_api(machine: FakeMachine) -> None:
    with JsonServer(portal_routes()) as server:
        machine.portal_url = server.url
        result = machine.run("stop", "comfyui")
    assert result.returncode == 0
    assert [r["path"] for r in server.requests if r["method"] == "POST"] == ["/api/service/comfyui/stop"]


def test_restart_stops_then_starts_through_the_portal(machine: FakeMachine) -> None:
    with JsonServer(portal_routes()) as server:
        machine.portal_url = server.url
        result = machine.run("restart", "hunyuan3d")
    assert result.returncode == 0
    posts = [r["path"] for r in server.requests if r["method"] == "POST"]
    assert posts == ["/api/service/hunyuan3d/stop", "/api/service/hunyuan3d/start"]


def test_portal_itself_is_controlled_with_systemctl_even_when_the_portal_is_up(machine: FakeMachine) -> None:
    machine.set_unit("portal", "loaded", "inactive")
    with JsonServer(portal_routes()) as server:
        machine.portal_url = server.url
        result = machine.run("restart", "portal")
    assert result.returncode == 0, result.stderr
    assert [r for r in server.requests if r["method"] == "POST"] == []
    assert any("restart" in call and "portal" in call for call in machine.systemctl_calls())


def test_status_through_the_portal_lists_every_service(machine: FakeMachine) -> None:
    with JsonServer(portal_routes()) as server:
        machine.portal_url = server.url
        result = machine.run("status")
    assert result.returncode == 0
    assert "GPU: VRAM 16 / 24576 MiB" in result.stdout
    assert "strata: 停止中（:8082）" in result.stdout
    assert "comfyui: 停止中（:8188）" in result.stdout
    # 入口ページ経由なら systemctl は要らない。
    assert machine.systemctl_calls() == []


def test_status_of_one_service_through_the_portal(machine: FakeMachine) -> None:
    with JsonServer(portal_routes()) as server:
        machine.portal_url = server.url
        result = machine.run("status", "pixal3d")
    assert result.returncode == 0
    assert result.stdout.strip() == "pixal3d: 停止中（:7861）"


# ---------------------------------------------------------------- start / stop / status（入口ページが応答しない）


def test_start_without_portal_uses_systemctl_and_warns_for_gpu_services(machine: FakeMachine) -> None:
    machine.set_unit("strata", "loaded", "inactive")
    machine.set_unit("pixal3d", "loaded", "active")
    result = machine.run("start", "strata")
    assert result.returncode == 0, result.stderr
    assert "--user start --no-block strata" in machine.systemctl_calls()
    assert "ほかの GPU サービスを自分で止めて" in result.stderr
    assert "pixal3d" in result.stderr  # いま動いている GPU サービスを挙げる
    assert "ollama stop" in result.stderr


def test_start_without_portal_does_not_warn_for_a_non_gpu_service(machine: FakeMachine) -> None:
    machine.set_unit("open-webui", "loaded", "inactive")
    result = machine.run("start", "open-webui")
    assert result.returncode == 0
    assert "GPU" not in result.stderr
    assert "--user start --no-block open-webui" in machine.systemctl_calls()


def test_start_without_portal_reports_a_missing_unit(machine: FakeMachine) -> None:
    result = machine.run("start", "pixal3d")
    assert result.returncode == 1
    assert "未導入。./localai install pixal3d" in result.stderr
    assert not any("start" in call for call in machine.systemctl_calls())


def test_start_strata_variants_point_to_the_right_install_command(machine: FakeMachine) -> None:
    coder = machine.run("start", "strata-coder")
    assert "./localai install strata --model coder" in coder.stderr
    official = machine.run("start", "strata-official")
    assert "./localai install strata --model official" in official.stderr
    official_iq3s = machine.run("start", "strata-official-iq3s")
    assert "./localai install strata --model official-iq3s" in official_iq3s.stderr
    swift = machine.run("start", "strata-swift")
    assert "./localai install strata --model swift" in swift.stderr


def test_stop_without_portal_uses_systemctl(machine: FakeMachine) -> None:
    machine.set_unit("comfyui", "loaded", "active")
    result = machine.run("stop", "comfyui")
    assert result.returncode == 0
    assert "--user stop comfyui" in machine.systemctl_calls()


def test_control_without_systemd_user_exits_1(machine: FakeMachine) -> None:
    (machine.systemd_dir / "no-user-bus").write_text("", encoding="utf-8")
    result = machine.run("start", "strata")
    assert result.returncode == 1
    assert "systemctl --user が使えません" in result.stderr


def test_status_without_portal_reads_systemd(machine: FakeMachine) -> None:
    machine.set_unit("strata", "loaded", "inactive")
    machine.set_unit("comfyui", "loaded", "active")
    machine.set_listening(8188, "python3")
    result = machine.run("status")
    assert result.returncode == 0
    assert "strata: 停止中（:8082）" in result.stdout
    assert "comfyui: 稼働中（:8188）" in result.stdout
    assert "pixal3d: 未導入（:7861）" in result.stdout


# ---------------------------------------------------------------- scripts/build-site.sh


@pytest.fixture()
def site_repo(tmp_path: Path) -> Path:
    """build-site.sh を複製した、サイトの元になるファイルを持つ小さなリポジトリ。"""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts" / "build-site.sh"
    shutil.copy2(BUILD_SITE_SCRIPT, script)
    script.chmod(0o755)
    (repo / "docs" / "site").mkdir(parents=True)
    (repo / "docs" / "site" / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    (repo / "docs" / "site" / "guide.html").write_text("guide", encoding="utf-8")
    (repo / "docs" / "images").mkdir()
    (repo / "docs" / "images" / "chart.png").write_bytes(b"png")
    (repo / "Documents" / "nested").mkdir(parents=True)
    (repo / "Documents" / "評価レポート.html").write_text("<title>評価</title>", encoding="utf-8")
    (repo / "Documents" / "memo.md").write_text("memo", encoding="utf-8")
    (repo / "Documents" / "nested" / "inner.html").write_text("inner", encoding="utf-8")
    return repo


def run_build_site(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(repo / "scripts" / "build-site.sh"), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_build_site_assembles_the_pages_layout(site_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_build_site(site_repo, str(output))
    assert result.returncode == 0, result.stderr
    assert (output / "index.html").read_text(encoding="utf-8") == "<h1>site</h1>"
    assert (output / "guide.html").is_file()
    assert (output / "reports" / "評価レポート.html").is_file()
    assert (output / "images" / "chart.png").is_file()
    assert (output / ".nojekyll").is_file()
    # Documents 直下の *.html だけを載せる。Markdown と入れ子は載せない。
    assert not (output / "reports" / "memo.md").exists()
    assert not (output / "reports" / "nested").exists()
    assert not (output / "reports" / "inner.html").exists()


def test_build_site_skips_missing_directories_and_lists_the_reports(site_repo: Path, tmp_path: Path) -> None:
    shutil.rmtree(site_repo / "docs")
    output = tmp_path / "out"
    result = run_build_site(site_repo, str(output))
    assert result.returncode == 0, result.stderr
    assert "docs/site/ が無いので飛ばします" in result.stdout
    assert not (output / "images").exists()
    index_html = (output / "index.html").read_text(encoding="utf-8")
    assert "reports/" in index_html
    assert "評価" in index_html  # <title> から取ったリンクの文字
    assert (output / ".nojekyll").is_file()


def test_build_site_refuses_a_non_empty_output(site_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    result = run_build_site(site_repo, str(output))
    assert result.returncode == 2
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_build_site_refuses_to_write_into_a_source_directory(site_repo: Path) -> None:
    target = site_repo / "docs" / "site" / "out"
    result = run_build_site(site_repo, str(target))
    assert result.returncode == 2
    assert not target.exists()


def test_build_site_requires_exactly_one_argument(site_repo: Path) -> None:
    assert run_build_site(site_repo).returncode == 2
    assert run_build_site(site_repo, "a", "b").returncode == 2
    assert run_build_site(site_repo, "--help").returncode == 0
