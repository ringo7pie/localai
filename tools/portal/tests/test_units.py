"""portal.py の単体テスト。ネットワーク・GPU・systemd には触れない。

実行コマンド（システムに pytest は入っていないので uv の一時環境で走らせる）:
    uvx --with pytest pytest tools/portal/tests/test_units.py -q
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import sys
import threading
import unittest.mock
from pathlib import Path

import pytest

PORTAL_DIR = Path(__file__).resolve().parent.parent
PORTAL_PY = PORTAL_DIR / "portal.py"
INDEX_HTML = PORTAL_DIR / "index.html"


def _load_portal_module():
    """portal.py をパッケージ化せずにモジュールとして読み込む。"""
    module_spec = importlib.util.spec_from_file_location("portal", PORTAL_PY)
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec.loader is not None
    module_spec.loader.exec_module(module)
    return module


portal = _load_portal_module()


# ---------------------------------------------------------------------------
# parse_nvidia_smi
# ---------------------------------------------------------------------------

def test_parse_nvidia_smi_normal_output():
    result = portal.parse_nvidia_smi("4, 24576")
    assert result == {"used_mib": 4, "total_mib": 24576}


def test_parse_nvidia_smi_trailing_newline():
    result = portal.parse_nvidia_smi("4, 24576\n")
    assert result == {"used_mib": 4, "total_mib": 24576}


def test_parse_nvidia_smi_broken_input_returns_none_without_raising():
    assert portal.parse_nvidia_smi("") is None
    assert portal.parse_nvidia_smi("これは壊れた出力です") is None
    assert portal.parse_nvidia_smi("4") is None
    assert portal.parse_nvidia_smi("abc, def") is None


# ---------------------------------------------------------------------------
# parse_ollama_ps
# ---------------------------------------------------------------------------

def test_parse_ollama_ps_with_model():
    payload = {"models": [{"name": "qwen3.8:27b", "size_vram": 23279276032}]}
    result = portal.parse_ollama_ps(payload)
    assert len(result) == 1
    assert result[0]["name"] == "qwen3.8:27b"
    # 23279276032 バイト ≈ 22201 MiB
    assert result[0]["size_vram_mib"] == 22201


def test_parse_ollama_ps_empty():
    assert portal.parse_ollama_ps({"models": []}) == []


def test_parse_ollama_ps_broken_input_does_not_raise():
    assert portal.parse_ollama_ps({}) == []
    assert portal.parse_ollama_ps({"models": [{"name": "x"}]})[0]["size_vram_mib"] == 0
    assert portal.parse_ollama_ps({"models": ["文字列だけ"]}) == []


# ---------------------------------------------------------------------------
# port_is_open
# ---------------------------------------------------------------------------

def test_port_is_open_true_for_listening_socket():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(1)
    bound_port = server_socket.getsockname()[1]
    try:
        assert portal.port_is_open(bound_port) is True
    finally:
        server_socket.close()


def test_port_is_open_false_for_closed_port():
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe_socket.bind(("127.0.0.1", 0))
    closed_port = probe_socket.getsockname()[1]
    probe_socket.close()
    assert portal.port_is_open(closed_port) is False


# ---------------------------------------------------------------------------
# unit_state
# ---------------------------------------------------------------------------

def test_unit_state_running_when_port_open():
    assert portal.unit_state("active", "loaded", True) == "running"
    # ポートが開いていれば ActiveState が何であっても running（届いた実測を優先する）
    assert portal.unit_state("inactive", "loaded", True) == "running"


def test_unit_state_starting_when_active_but_port_closed():
    assert portal.unit_state("active", "loaded", False) == "starting"
    assert portal.unit_state("activating", "loaded", False) == "starting"


def test_unit_state_stopped_when_inactive_and_port_closed():
    assert portal.unit_state("inactive", "loaded", False) == "stopped"
    assert portal.unit_state("failed", "loaded", False) == "stopped"


def test_unit_state_not_installed_when_not_loaded():
    assert portal.unit_state("unknown", "not-found", False) == "not_installed"
    # ロードされていないなら、ポートがたまたま開いていても not_installed を優先する
    assert portal.unit_state("unknown", "not-found", True) == "not_installed"


# ---------------------------------------------------------------------------
# is_controllable
# ---------------------------------------------------------------------------

def test_is_controllable_true_when_unit_present_and_installed():
    assert portal.is_controllable({"unit": "hunyuan3d", "state": "stopped"}) is True
    assert portal.is_controllable({"unit": "hunyuan3d", "state": "running"}) is True


def test_is_controllable_false_when_unit_is_none():
    assert portal.is_controllable({"unit": None, "state": "not_installed"}) is False


def test_is_controllable_false_when_not_installed():
    assert portal.is_controllable({"unit": "hunyuan3d", "state": "not_installed"}) is False


# ---------------------------------------------------------------------------
# parse_service_action_path
# ---------------------------------------------------------------------------

def test_parse_service_action_path_valid():
    assert portal.parse_service_action_path("/api/service/hunyuan3d/start") == ("hunyuan3d", "start")
    assert portal.parse_service_action_path("/api/service/open-webui/stop") == ("open-webui", "stop")


def test_parse_service_action_path_invalid_shapes_return_none():
    assert portal.parse_service_action_path("/api/service/hunyuan3d") is None
    assert portal.parse_service_action_path("/api/service/hunyuan3d/start/extra") is None
    assert portal.parse_service_action_path("/api/service//start") is None
    assert portal.parse_service_action_path("/api/status") is None


# ---------------------------------------------------------------------------
# read_unit_state（subprocess を monkeypatch。実際の systemctl は呼ばない）
# ---------------------------------------------------------------------------

def test_read_unit_state_parses_key_value_lines(monkeypatch):
    class FakeCompletedProcess:
        returncode = 0
        # 実機で確認済み: systemd は --property の指定順に関係なく LoadState を先に出す。
        # 行の位置ではなくキー名で拾うことを確認するため、わざと ActiveState を先に置く。
        stdout = "ActiveState=active\nLoadState=loaded\n"
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        assert args[:4] == ["systemctl", "--user", "show", "hunyuan3d"]
        assert "--property=ActiveState" in args
        assert "--property=LoadState" in args
        assert "--value" not in args
        return FakeCompletedProcess()

    monkeypatch.setattr(portal.subprocess, "run", fake_run)
    assert portal.read_unit_state("hunyuan3d") == ("active", "loaded")


def test_read_unit_state_is_order_independent():
    # systemd の実際の出力順（LoadState が先）を模した入力でも正しく拾えること。
    # ここは fake_run を使わず、パース自体を確かめたいので read_unit_state の代わりに
    # 同じキー名照合ロジックを通す形で、実際の systemctl 出力に近い例を subprocess 経由で確認する。
    class FakeCompletedProcess:
        returncode = 0
        stdout = "LoadState=loaded\nActiveState=inactive\n"
        stderr = ""

    with unittest.mock.patch.object(portal.subprocess, "run", return_value=FakeCompletedProcess()):
        assert portal.read_unit_state("open-webui") == ("inactive", "loaded")


def test_read_unit_state_returns_unknown_on_missing_systemctl(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("systemctl が見つかりません")

    monkeypatch.setattr(portal.subprocess, "run", fake_run)
    assert portal.read_unit_state("hunyuan3d") == ("unknown", "not-found")


def test_read_unit_state_returns_unknown_on_nonzero_returncode(monkeypatch):
    class FakeCompletedProcess:
        returncode = 1
        stdout = ""
        stderr = "no such unit"

    monkeypatch.setattr(portal.subprocess, "run", lambda *args, **kwargs: FakeCompletedProcess())
    assert portal.read_unit_state("hunyuan3d") == ("unknown", "not-found")


# ---------------------------------------------------------------------------
# build_service_status / build_status
# ---------------------------------------------------------------------------

def test_build_service_status_includes_state_and_controllable():
    entry = portal.build_service_status(
        {"key": "hunyuan3d", "name": "Hunyuan3D", "port": 7860, "unit": "hunyuan3d"},
        port_open=False,
        active_state="active",
        load_state="loaded",
    )
    assert entry == {
        "key": "hunyuan3d",
        "name": "Hunyuan3D",
        "port": 7860,
        "up": False,
        "state": "starting",
        "controllable": True,
    }


def test_build_service_status_not_installed_is_not_controllable():
    entry = portal.build_service_status(
        {"key": "comfyui", "name": "ComfyUI", "port": 8188, "unit": None},
        port_open=False,
        active_state="unknown",
        load_state="not-found",
    )
    assert entry["state"] == "not_installed"
    assert entry["controllable"] is False


def test_build_status_shape_all_available():
    services = [
        {"key": "open-webui", "name": "Open WebUI", "port": 8081, "up": True, "state": "running", "controllable": True},
        {"key": "hunyuan3d", "name": "Hunyuan3D", "port": 7860, "up": False, "state": "stopped", "controllable": True},
        {"key": "comfyui", "name": "ComfyUI", "port": 8188, "up": False, "state": "not_installed", "controllable": False},
    ]
    status = portal.build_status(
        {"used_mib": 4, "total_mib": 24576},
        [{"name": "qwen3.8:27b", "size_vram_mib": 22201}],
        services,
    )
    assert status == {
        "gpu": {"used_mib": 4, "total_mib": 24576, "available": True},
        "ollama": {"reachable": True, "models": [{"name": "qwen3.8:27b", "size_vram_mib": 22201}]},
        "services": services,
    }


def test_build_status_shape_when_gpu_and_ollama_unreachable():
    status = portal.build_status(None, None, [])
    assert status["gpu"] == {"used_mib": None, "total_mib": None, "available": False}
    assert status["ollama"] == {"reachable": False, "models": []}
    assert status["services"] == []


# ---------------------------------------------------------------------------
# GET /api/status（http.server をエフェメラルポートで立てて叩く。外部へは出ない）
# ---------------------------------------------------------------------------

@pytest.fixture()
def running_server(monkeypatch):
    monkeypatch.setattr(portal, "read_nvidia_smi", lambda: {"used_mib": 4, "total_mib": 24576})
    monkeypatch.setattr(
        portal,
        "read_ollama_ps",
        lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}],
    )
    monkeypatch.setattr(portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: port == 8081)
    # systemd には実際には触れない。既定では「入っていて動いている」ことにしておく
    # （個々のテストで必要なら上書きする）。
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("active", "loaded"))

    server = portal.ThreadingHTTPServer(("127.0.0.1", 0), portal.PortalRequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_get_api_status_returns_200_and_json(running_server):
    host, port = running_server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()

    assert response.status == 200
    assert response.getheader("Content-Type", "").startswith("application/json")

    payload = json.loads(body)
    assert payload["gpu"] == {"used_mib": 4, "total_mib": 24576, "available": True}
    assert payload["ollama"]["reachable"] is True
    service_by_key = {service["key"]: service for service in payload["services"]}
    assert service_by_key["open-webui"]["up"] is True
    assert service_by_key["hunyuan3d"]["up"] is False
    assert service_by_key["comfyui"]["up"] is False
    # state と controllable が各サービスに入っている
    assert service_by_key["open-webui"]["state"] == "running"
    assert service_by_key["open-webui"]["controllable"] is True
    assert service_by_key["hunyuan3d"]["state"] == "starting"
    assert service_by_key["hunyuan3d"]["controllable"] is True
    assert service_by_key["comfyui"]["state"] == "not_installed"
    assert service_by_key["comfyui"]["controllable"] is False


def test_get_root_returns_index_html(running_server):
    host, port = running_server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()

    assert response.status == 200
    assert response.getheader("Content-Type", "").startswith("text/html")
    assert b"<html" in body.lower()


# ---------------------------------------------------------------------------
# POST /api/service/<key>/<action>（systemctl は monkeypatch。実際には呼ばない）
# ---------------------------------------------------------------------------

def _request(server, method, path, headers=None):
    """テスト用の HTTP 呼び出し。

    POST（起動・停止）は既定で X-Portal-Request ヘッダを付ける。入口ページの JavaScript が
    付けるのと同じもので、他サイトからのクロスオリジン POST を防ぐために必須になっている。
    ヘッダ無しの挙動を試したいときは headers={} を渡す。
    """
    if headers is None:
        headers = {"X-Portal-Request": "1"} if method == "POST" else {}
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    return response, body


def test_post_start_calls_systemctl_with_our_unit_name(running_server, monkeypatch):
    captured_calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured_calls.append({"args": args, "timeout": timeout})
        return FakeCompletedProcess()

    # is_controllable の判定に使う現在状態は「停止中」にしておく（start できる状態）。
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("inactive", "loaded"))
    monkeypatch.setattr(portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: False)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/service/hunyuan3d/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True

    # 実際に systemctl を呼んだのは control_unit（start 本体）だけ。
    # こちらが持っているユニット名（"hunyuan3d"）で呼ばれていて、利用者からの入力はどこにも渡らない。
    start_calls = [call for call in captured_calls if call["args"][2] == "start"]
    assert len(start_calls) == 1
    assert start_calls[0]["args"] == ["systemctl", "--user", "start", "hunyuan3d"]
    assert start_calls[0]["timeout"] == portal.SYSTEMCTL_START_TIMEOUT_SEC


def test_post_unknown_key_returns_404(running_server):
    response, body = _request(running_server, "POST", "/api/service/nosuch/start")
    assert response.status == 404
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_invalid_action_returns_400(running_server):
    response, body = _request(running_server, "POST", "/api/service/hunyuan3d/restart")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_get_service_action_path_returns_405(running_server):
    response, body = _request(running_server, "GET", "/api/service/hunyuan3d/start")
    assert response.status == 405
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_comfyui_start_returns_409_not_installed(running_server):
    response, body = _request(running_server, "POST", "/api/service/comfyui/start")
    assert response.status == 409
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_portal_itself_returns_404():
    # portal は SERVICES に入っていない。自分自身を止められないことの確認。
    assert "portal" not in portal.SERVICES_BY_KEY


def test_post_portal_key_via_http_returns_404(running_server):
    response, body = _request(running_server, "POST", "/api/service/portal/start")
    assert response.status == 404
    payload = json.loads(body)
    assert payload["ok"] is False


# ---------------------------------------------------------------------------
# index.html の中身の確認
# ---------------------------------------------------------------------------

def test_index_html_builds_links_from_location_hostname():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert "location.hostname" in html_text


def test_index_html_has_no_hardcoded_server_ip():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert "<server-ip>" not in html_text


def test_index_html_references_service_action_endpoint():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert "/api/service/" in html_text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_post_without_required_header_is_rejected(running_server, monkeypatch):
    """入口ページ以外からのクロスオリジン POST を防ぐため、専用ヘッダが無ければ操作しない。"""
    called = []
    monkeypatch.setattr(
        portal, "control_unit", lambda *args, **kwargs: called.append(args) or None
    )
    response, body = _request(
        running_server, "POST", "/api/service/hunyuan3d/start", headers={}
    )
    assert response.status == 403
    payload = json.loads(body)
    assert payload["ok"] is False
    assert "X-Portal-Request" in payload["message"]
    assert called == [], "ヘッダが無いのに systemctl が呼ばれてはいけない"


def test_post_with_wrong_header_value_is_rejected(running_server, monkeypatch):
    """ヘッダ名だけ合っていて値が違う場合も拒否する。"""
    called = []
    monkeypatch.setattr(
        portal, "control_unit", lambda *args, **kwargs: called.append(args) or None
    )
    response, _ = _request(
        running_server,
        "POST",
        "/api/service/hunyuan3d/start",
        headers={"X-Portal-Request": "nope"},
    )
    assert response.status == 403
    assert called == []


def test_index_html_sends_required_header() -> None:
    """画面側の fetch が必須ヘッダを付けていること（付け忘れるとボタンが全部 403 になる）。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "X-Portal-Request" in html
