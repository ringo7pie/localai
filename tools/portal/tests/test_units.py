"""portal.py の単体テスト。ネットワーク・GPU・systemd には触れない。

実行コマンド（システムに pytest は入っていないので uv の一時環境で走らせる）:
    uvx --with pytest pytest tools/portal/tests/test_units.py -q
"""
from __future__ import annotations

import http.client
import http.server
import importlib.util
import json
import re
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
        "options": {},
        "memory": None,
    }


def test_build_control_command_start_does_not_block_but_stop_does():
    # Strata のユニットは API の応答まで systemctl start が戻らない（最大 15 分）ので、start は待たない。
    assert portal.build_control_command("strata", "start") == ["systemctl", "--user", "start", "--no-block", "strata"]
    assert portal.build_control_command("strata", "stop") == ["systemctl", "--user", "stop", "strata"]
    # コード向けの Strata（strata-coder）も同じ。
    assert portal.build_control_command("strata-coder", "start") == [
        "systemctl", "--user", "start", "--no-block", "strata-coder"
    ]
    assert portal.build_control_command("strata-coder", "stop") == ["systemctl", "--user", "stop", "strata-coder"]
    # 公式量子化版の Strata（strata-official）も同じ。
    assert portal.build_control_command("strata-official", "start") == [
        "systemctl", "--user", "start", "--no-block", "strata-official"
    ]
    assert portal.build_control_command("strata-official", "stop") == [
        "systemctl", "--user", "stop", "strata-official"
    ]


def test_build_memory_entry_uses_service_default_or_common_default():
    values = {"high_gib": 10.0, "max_gib": 12.0, "current_gib": 1.0}
    common = portal.build_memory_entry({"key": "x"}, values)
    assert common["default_high_gib"] == portal.MEMORY_DEFAULT_HIGH_GIB
    assert common["default_max_gib"] == portal.MEMORY_DEFAULT_MAX_GIB
    custom = portal.build_memory_entry({"key": "y", "memory_default": {"high_gib": 54, "max_gib": 58}}, values)
    assert (custom["default_high_gib"], custom["default_max_gib"]) == (54, 58)
    # 元の辞書は書き換えない。unit を持たないサービス（memory が None）は None のまま。
    assert "default_high_gib" not in values
    assert portal.build_memory_entry({"key": "z"}, None) is None
    # 既定値は許容上限（RAM 総量 - 4 GiB、この機体で 58 GiB）を超えない。
    bounds = portal.memory_bounds(62.5)
    for service in portal.SERVICES:
        memory_default = service.get("memory_default")
        if memory_default:
            assert memory_default["high_gib"] <= memory_default["max_gib"] <= bounds["allowed_max_gib"]


def test_build_service_status_not_installed_is_not_controllable():
    # ComfyUI のユニットがまだ作られていない（systemd が not-found を返す）間は未導入扱い。
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["comfyui"],
        port_open=False,
        active_state="unknown",
        load_state="not-found",
    )
    assert entry["state"] == "not_installed"
    assert entry["controllable"] is False


def test_build_service_status_comfyui_with_unit_is_controllable():
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["comfyui"],
        port_open=False,
        active_state="inactive",
        load_state="loaded",
    )
    assert entry["state"] == "stopped"
    assert entry["controllable"] is True


def test_build_status_shape_all_available():
    services = [
        {"key": "open-webui", "name": "Open WebUI", "port": 8081, "up": True, "state": "running", "controllable": True},
        {"key": "hunyuan3d", "name": "Hunyuan3D", "port": 7860, "up": False, "state": "stopped", "controllable": True},
        {"key": "comfyui", "name": "ComfyUI", "port": 8188, "up": False, "state": "stopped", "controllable": True},
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
        "ram": {
            "total_gib": None,
            "allowed_max_gib": None,
            "recommended_max_gib": None,
            "min_gib": portal.MEMORY_MIN_GIB,
            "default_high_gib": portal.MEMORY_DEFAULT_HIGH_GIB,
            "default_max_gib": portal.MEMORY_DEFAULT_MAX_GIB,
            "available": False,
        },
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

    # 実際の Ollama へモデルを降ろす要求は送らない（Strata の起動を試すテストが、手元の Qwen を
    # 降ろしてしまわないように）。呼ばれたモデル名は server.unload_calls に残る。
    unload_calls: list[str] = []
    monkeypatch.setattr(
        portal,
        "request_ollama_unload",
        lambda model_name, timeout=portal.OLLAMA_UNLOAD_TIMEOUT_SEC: unload_calls.append(model_name) or True,
    )

    server = portal.ThreadingHTTPServer(("127.0.0.1", 0), portal.PortalRequestHandler)
    server.unload_calls = unload_calls
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
    # ComfyUI もユニットを持つので、他のサービスと同じ判定になる（ユニット active・ポート閉 = 起動中）。
    assert service_by_key["comfyui"]["state"] == "starting"
    assert service_by_key["comfyui"]["controllable"] is True
    # Strata も同じ（ユニット active・ポート 8082 閉 = 起動中）。
    assert service_by_key["strata"]["port"] == 8082
    assert service_by_key["strata"]["up"] is False
    assert service_by_key["strata"]["state"] == "starting"
    assert service_by_key["strata"]["controllable"] is True


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
    assert start_calls[0]["args"] == ["systemctl", "--user", "start", "--no-block", "hunyuan3d"]
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


def test_post_comfyui_start_returns_409_when_unit_not_installed(running_server, monkeypatch):
    # ComfyUI のユニットがまだ無い間（systemd が not-found）は、未導入として操作を断る。
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("unknown", "not-found"))
    called = []
    monkeypatch.setattr(
        portal, "control_unit", lambda *args, **kwargs: called.append(args) or None
    )
    response, body = _request(running_server, "POST", "/api/service/comfyui/start")
    assert response.status == 409
    payload = json.loads(body)
    assert payload["ok"] is False
    assert called == [], "未導入のユニットに systemctl を呼んではいけない"


def test_post_comfyui_start_calls_systemctl_with_comfyui_unit(running_server, monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        calls.append(list(args))
        return FakeCompletedProcess()

    # 全サービスが停止中（ComfyUI を start できる状態。他に止めるものも無い）。
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("inactive", "loaded"))
    monkeypatch.setattr(portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: False)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/service/comfyui/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert "stopped" not in payload
    assert ["systemctl", "--user", "start", "--no-block", "comfyui"] in calls
    assert [call for call in calls if call[2] == "stop"] == []


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


# ---------------------------------------------------------------------------
# マウスオーバー説明（TOOLTIPS）・専門用語ダイアログ（GLOSSARY）
# ---------------------------------------------------------------------------

def _extract_js_object_block(html_text: str, const_name: str) -> str:
    """`const <const_name> = { ... };` の中身（波括弧の対応を数えて）を切り出す。"""
    marker = f"const {const_name} = {{"
    start = html_text.index(marker)
    brace_start = html_text.index("{", start)
    depth = 0
    for index in range(brace_start, len(html_text)):
        character = html_text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return html_text[brace_start:index + 1]
    raise AssertionError(f"{const_name} の閉じ括弧が見つかりません")


def _html_text() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_index_html_defines_tooltips_and_glossary():
    html_text = _html_text()
    assert "const TOOLTIPS = {" in html_text
    assert "const GLOSSARY = {" in html_text


def test_all_data_term_attributes_exist_in_glossary():
    html_text = _html_text()
    glossary_block = _extract_js_object_block(html_text, "GLOSSARY")
    glossary_keys = set(re.findall(r'"([^"]+)":\s*\n?\s*"', glossary_block))
    assert len(glossary_keys) >= 17, "用語集は依頼の最低限（17 項目程度）を満たすこと"

    data_terms = set(re.findall(r'data-term="([^"]+)"', html_text))
    # index.html 内のコメント文にある説明用の "..." は実際のキーではないため除く。
    data_terms.discard("...")
    assert data_terms, "data-term を使った要素が 1 つも見つからない"
    missing = data_terms - glossary_keys
    assert not missing, f"GLOSSARY に無い data-term がある: {missing}"

    # buildTermSpan("...") で動的に付ける data-term も同様にチェックする。
    build_term_calls = set(re.findall(r'buildTermSpan\("([^"]+)"\)', html_text))
    missing_dynamic = build_term_calls - glossary_keys
    assert not missing_dynamic, f"GLOSSARY に無い buildTermSpan の用語がある: {missing_dynamic}"


def test_all_tooltips_references_are_defined():
    html_text = _html_text()
    tooltips_block = _extract_js_object_block(html_text, "TOOLTIPS")
    tooltip_keys = set(re.findall(r'(\w+):\s*\n?\s*"', tooltips_block))
    assert len(tooltip_keys) >= 10, "TOOLTIPS はボタン・入力・スイッチ・バッジ・GPU 帯を広くカバーすること"

    dot_refs = set(re.findall(r'TOOLTIPS\.(\w+)', html_text))
    bracket_refs = set(re.findall(r'TOOLTIPS\["([^"]+)"\]', html_text))
    # STATE_BADGE の tooltipKey は文字列で TOOLTIPS[badgeMeta.tooltipKey] のように間接参照されるため、
    # 定義側の文字列リテラルも対象に含めて確認する。
    indirect_refs = set(re.findall(r'tooltipKey:\s*"([^"]+)"', html_text))

    used_keys = dot_refs | bracket_refs | indirect_refs
    assert used_keys, "TOOLTIPS を参照している箇所が見つからない"
    missing = used_keys - tooltip_keys
    assert not missing, f"TOOLTIPS に定義が無いキーが参照されている: {missing}"


def test_term_dialog_body_uses_textcontent_not_innerhtml():
    html_text = _html_text()
    assert "termDialogBody.textContent" in html_text
    assert "termDialogBody.innerHTML" not in html_text


def test_index_html_has_term_dialog_element():
    html_text = _html_text()
    assert '<dialog id="term-dialog">' in html_text
    assert 'id="term-dialog-title"' in html_text
    assert 'id="term-dialog-body"' in html_text


def test_index_html_term_click_uses_event_delegation_on_document():
    # カードは 5 秒ごとに作り直されるため、個々の要素ではなく document に委譲すること。
    html_text = _html_text()
    assert 'document.addEventListener("click"' in html_text


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


# ---------------------------------------------------------------------------
# parse_option_path
# ---------------------------------------------------------------------------

def test_parse_option_path_valid():
    assert portal.parse_option_path("/api/option/hunyuan3d/low-vram/on") == (
        "hunyuan3d",
        "low-vram",
        "on",
    )
    assert portal.parse_option_path("/api/option/pixal3d/low-vram/off") == (
        "pixal3d",
        "low-vram",
        "off",
    )


def test_parse_option_path_invalid_shapes_return_none():
    assert portal.parse_option_path("/api/option/hunyuan3d/low-vram") is None
    assert portal.parse_option_path("/api/option/hunyuan3d/low-vram/on/extra") is None
    assert portal.parse_option_path("/api/option//low-vram/on") is None
    assert portal.parse_option_path("/api/option/hunyuan3d//on") is None
    assert portal.parse_option_path("/api/status") is None
    assert portal.parse_option_path("") is None


# ---------------------------------------------------------------------------
# parse_env_file
# ---------------------------------------------------------------------------

def test_parse_env_file_reads_key_value_lines():
    text = "FOO=1\nBAR=baz\n"
    assert portal.parse_env_file(text) == {"FOO": "1", "BAR": "baz"}


def test_parse_env_file_ignores_comments_and_blank_lines():
    text = "# コメント\n\nFOO=1\n   \n# 別のコメント\nBAR=2\n"
    assert portal.parse_env_file(text) == {"FOO": "1", "BAR": "2"}


def test_parse_env_file_empty_text_returns_empty_dict():
    assert portal.parse_env_file("") == {}


# ---------------------------------------------------------------------------
# render_env_file
# ---------------------------------------------------------------------------

def test_render_env_file_replaces_existing_value_and_keeps_comments():
    text = "# 見出しコメント\nHY3D_LOW_VRAM=1\n# 末尾のコメント\n"
    rendered = portal.render_env_file(text, "HY3D_LOW_VRAM", "0")
    assert "HY3D_LOW_VRAM=0" in rendered
    assert "HY3D_LOW_VRAM=1" not in rendered
    assert "# 見出しコメント" in rendered
    assert "# 末尾のコメント" in rendered


def test_render_env_file_appends_when_variable_missing():
    text = "# 既存の設定\nOTHER=1\n"
    rendered = portal.render_env_file(text, "HY3D_LOW_VRAM", "1")
    assert "OTHER=1" in rendered
    assert "HY3D_LOW_VRAM=1" in rendered
    # 既存の行を壊さず、末尾に足されていること
    assert rendered.index("OTHER=1") < rendered.index("HY3D_LOW_VRAM=1")


def test_render_env_file_builds_new_content_when_empty():
    rendered = portal.render_env_file("", "HY3D_LOW_VRAM", "1")
    assert "HY3D_LOW_VRAM=1" in rendered
    assert rendered.strip().startswith("#")


# ---------------------------------------------------------------------------
# services_to_stop_before_start
# ---------------------------------------------------------------------------

def test_services_to_stop_before_start_returns_running_conflict():
    states = {"hunyuan3d": "running", "pixal3d": "stopped"}
    assert portal.services_to_stop_before_start("pixal3d", states) == ["hunyuan3d"]


def test_services_to_stop_before_start_returns_starting_conflict():
    states = {"hunyuan3d": "starting", "pixal3d": "stopped"}
    assert portal.services_to_stop_before_start("pixal3d", states) == ["hunyuan3d"]


def test_services_to_stop_before_start_empty_when_conflict_stopped():
    states = {"hunyuan3d": "stopped", "pixal3d": "stopped"}
    assert portal.services_to_stop_before_start("pixal3d", states) == []


def test_services_to_stop_before_start_excludes_self():
    # 自分自身が running であっても、返り値には自分の key を含めない。
    states = {"hunyuan3d": "running", "pixal3d": "running"}
    assert portal.services_to_stop_before_start("pixal3d", states) == ["hunyuan3d"]


def test_services_to_stop_before_start_empty_for_non_exclusive_key():
    states = {"hunyuan3d": "running", "pixal3d": "running", "comfyui": "running"}
    assert portal.services_to_stop_before_start("open-webui", states) == []


def test_services_to_stop_before_start_comfyui_stops_running_pixal3d():
    states = {"hunyuan3d": "stopped", "pixal3d": "running", "comfyui": "stopped"}
    assert portal.services_to_stop_before_start("comfyui", states) == ["pixal3d"]


def test_services_to_stop_before_start_comfyui_stops_starting_hunyuan3d():
    states = {"hunyuan3d": "starting", "pixal3d": "stopped", "comfyui": "stopped"}
    assert portal.services_to_stop_before_start("comfyui", states) == ["hunyuan3d"]


def test_services_to_stop_before_start_pixal3d_stops_running_comfyui():
    states = {"hunyuan3d": "stopped", "pixal3d": "stopped", "comfyui": "running"}
    assert portal.services_to_stop_before_start("pixal3d", states) == ["comfyui"]


def test_services_to_stop_before_start_hunyuan3d_stops_both_others():
    states = {"hunyuan3d": "stopped", "pixal3d": "running", "comfyui": "running"}
    assert portal.services_to_stop_before_start("hunyuan3d", states) == ["pixal3d", "comfyui"]


def test_services_to_stop_before_start_ignores_stopped_and_not_installed_in_three_way_group():
    states = {"hunyuan3d": "stopped", "pixal3d": "not_installed", "comfyui": "stopped"}
    assert portal.services_to_stop_before_start("comfyui", states) == []


def test_comfyui_is_in_gpu_exclusive_group_with_unit_and_no_options():
    assert portal.GPU_EXCLUSIVE_KEYS == (
        "hunyuan3d", "pixal3d", "comfyui", "strata", "strata-coder", "strata-official"
    )
    comfyui_service = portal.SERVICES_BY_KEY["comfyui"]
    assert comfyui_service["unit"] == "comfyui"
    assert comfyui_service["port"] == 8188
    # 低 VRAM のスイッチは持たない
    assert portal.find_service_option(comfyui_service, "low_vram") is None


# ---------------------------------------------------------------------------
# build_service_status の options
# ---------------------------------------------------------------------------

def test_build_service_status_includes_options_when_given():
    service = {
        "key": "hunyuan3d",
        "name": "Hunyuan3D",
        "port": 7860,
        "unit": "hunyuan3d",
        "options": {"low_vram": {"env_file": "~/x", "var": "HY3D_LOW_VRAM", "default": True}},
    }
    entry = portal.build_service_status(
        service,
        port_open=True,
        active_state="active",
        load_state="loaded",
        option_values={"low_vram": True},
    )
    assert entry["options"] == {"low_vram": True}


def test_build_service_status_options_defaults_to_empty_dict():
    entry = portal.build_service_status(
        {"key": "open-webui", "name": "Open WebUI", "port": 8081, "unit": "open-webui"},
        port_open=True,
        active_state="active",
        load_state="loaded",
    )
    assert entry["options"] == {}


# ---------------------------------------------------------------------------
# POST /api/option/<key>/<option>/<value>（systemctl・ファイル I/O は monkeypatch）
# ---------------------------------------------------------------------------

def test_post_option_without_header_returns_403(running_server):
    response, body = _request(
        running_server, "POST", "/api/option/hunyuan3d/low-vram/on", headers={}
    )
    assert response.status == 403
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_option_unknown_key_returns_404(running_server):
    response, body = _request(running_server, "POST", "/api/option/nosuch/low-vram/on")
    assert response.status == 404
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_option_unknown_option_name_returns_400(running_server):
    response, body = _request(running_server, "POST", "/api/option/hunyuan3d/foo/on")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_option_invalid_value_returns_400(running_server):
    response, body = _request(running_server, "POST", "/api/option/hunyuan3d/low-vram/maybe")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_option_unsupported_service_returns_400(running_server):
    # Open WebUI には低 VRAM モードの設定が無い。
    response, body = _request(running_server, "POST", "/api/option/open-webui/low-vram/on")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_option_running_service_returns_409(running_server, monkeypatch):
    # hunyuan3d のポート（7860）が開いているとみなし、running にする。
    monkeypatch.setattr(
        portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: port == 7860
    )
    response, body = _request(running_server, "POST", "/api/option/hunyuan3d/low-vram/on")
    assert response.status == 409
    payload = json.loads(body)
    assert payload["ok"] is False
    assert "停止" in payload["message"]


def test_get_option_path_returns_405(running_server):
    response, body = _request(running_server, "GET", "/api/option/hunyuan3d/low-vram/on")
    assert response.status == 405
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_option_success_writes_value_and_does_not_touch_real_file(running_server, monkeypatch):
    # ポートを閉じ・非アクティブにして「停止中」にする（変更が許される状態）。
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("inactive", "loaded"))
    monkeypatch.setattr(portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: False)
    written = []
    monkeypatch.setattr(
        portal,
        "write_option_value",
        lambda option_config, enabled: written.append((option_config["var"], enabled)),
    )
    response, body = _request(running_server, "POST", "/api/option/hunyuan3d/low-vram/off")
    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["value"] is False
    assert written == [("HY3D_LOW_VRAM", False)]


# ---------------------------------------------------------------------------
# POST /api/service/<key>/start の GPU 排他（Hunyuan3D ⇔ Pixal3D）
# ---------------------------------------------------------------------------

def test_post_pixal3d_start_stops_hunyuan3d_first(running_server, monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        calls.append(list(args))
        return FakeCompletedProcess()

    def fake_read_unit_state(unit):
        # hunyuan3d は稼働中、pixal3d は停止中（start できる状態）にする。
        if unit == "hunyuan3d":
            return ("active", "loaded")
        return ("inactive", "loaded")

    def fake_port_is_open(port, host="127.0.0.1", timeout=0.3):
        return port == 7860  # hunyuan3d のポートだけ開いている

    monkeypatch.setattr(portal, "read_unit_state", fake_read_unit_state)
    monkeypatch.setattr(portal, "port_is_open", fake_port_is_open)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/service/pixal3d/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["hunyuan3d"]

    stop_call_index = next(
        index for index, call in enumerate(calls) if call == ["systemctl", "--user", "stop", "hunyuan3d"]
    )
    start_call_index = next(
        index for index, call in enumerate(calls) if call == ["systemctl", "--user", "start", "--no-block", "pixal3d"]
    )
    assert stop_call_index < start_call_index


def _fake_states_for_exclusive_test(monkeypatch, running_unit_to_port):
    """`running_unit_to_port`（{ユニット名: ポート}）のユニットだけを稼働中（active・ポート開）にする。

    それ以外のユニットは loaded・inactive・ポート閉（start できる停止中）。
    systemctl の呼び出しは記録して返す。
    """
    calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        calls.append(list(args))
        return FakeCompletedProcess()

    def fake_read_unit_state(unit):
        if unit in running_unit_to_port:
            return ("active", "loaded")
        return ("inactive", "loaded")

    def fake_port_is_open(port, host="127.0.0.1", timeout=0.3):
        return port in running_unit_to_port.values()

    monkeypatch.setattr(portal, "read_unit_state", fake_read_unit_state)
    monkeypatch.setattr(portal, "port_is_open", fake_port_is_open)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)
    return calls


def test_post_comfyui_start_stops_pixal3d_first(running_server, monkeypatch):
    calls = _fake_states_for_exclusive_test(monkeypatch, {"pixal3d": 7861})

    response, body = _request(running_server, "POST", "/api/service/comfyui/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["pixal3d"]
    assert "Pixal3D" in payload["message"]

    stop_call_index = calls.index(["systemctl", "--user", "stop", "pixal3d"])
    start_call_index = calls.index(["systemctl", "--user", "start", "--no-block", "comfyui"])
    assert stop_call_index < start_call_index


def test_post_pixal3d_start_stops_comfyui_first(running_server, monkeypatch):
    calls = _fake_states_for_exclusive_test(monkeypatch, {"comfyui": 8188})

    response, body = _request(running_server, "POST", "/api/service/pixal3d/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["comfyui"]

    stop_call_index = calls.index(["systemctl", "--user", "stop", "comfyui"])
    start_call_index = calls.index(["systemctl", "--user", "start", "--no-block", "pixal3d"])
    assert stop_call_index < start_call_index


def test_post_hunyuan3d_start_stops_comfyui_first(running_server, monkeypatch):
    calls = _fake_states_for_exclusive_test(monkeypatch, {"comfyui": 8188})

    response, body = _request(running_server, "POST", "/api/service/hunyuan3d/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["stopped"] == ["comfyui"]
    assert ["systemctl", "--user", "stop", "comfyui"] in calls


def test_post_comfyui_start_does_not_stop_open_webui(running_server, monkeypatch):
    # Open WebUI は GPU の排他グループに入っていないので、動いていても止めない。
    calls = _fake_states_for_exclusive_test(monkeypatch, {"open-webui": 8081})

    response, body = _request(running_server, "POST", "/api/service/comfyui/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert "stopped" not in payload
    assert [call for call in calls if call[2] == "stop"] == []


def test_post_comfyui_start_aborts_when_stopping_pixal3d_fails(running_server, monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(list(args))
        if args[2] == "stop":
            return type("FakeCompletedProcess", (), {"returncode": 1, "stdout": "", "stderr": "失敗"})()
        return type("FakeCompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def fake_read_unit_state(unit):
        if unit == "pixal3d":
            return ("active", "loaded")
        return ("inactive", "loaded")

    monkeypatch.setattr(portal, "read_unit_state", fake_read_unit_state)
    monkeypatch.setattr(
        portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: port == 7861
    )
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/service/comfyui/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is False
    assert [call for call in calls if call[2] == "start"] == []


# ---------------------------------------------------------------------------
# parse_meminfo_total_gib
# ---------------------------------------------------------------------------

def test_parse_meminfo_total_gib_normal_output():
    text = "MemTotal:       65504276 kB\nMemFree:         1234 kB\n"
    result = portal.parse_meminfo_total_gib(text)
    assert result is not None
    assert abs(result - 62.47) < 0.01


def test_parse_meminfo_total_gib_broken_input_returns_none():
    assert portal.parse_meminfo_total_gib("") is None
    assert portal.parse_meminfo_total_gib("これは壊れた出力です") is None
    assert portal.parse_meminfo_total_gib("MemTotal:\n") is None
    assert portal.parse_meminfo_total_gib("MemTotal: abc kB\n") is None


# ---------------------------------------------------------------------------
# memory_bounds
# ---------------------------------------------------------------------------

def test_memory_bounds_matches_real_machine():
    bounds = portal.memory_bounds(62.47)
    assert bounds["total_gib"] == 62.47
    assert bounds["allowed_max_gib"] == 58
    assert bounds["recommended_max_gib"] == 48
    assert bounds["min_gib"] == portal.MEMORY_MIN_GIB


# ---------------------------------------------------------------------------
# validate_memory_limits
# ---------------------------------------------------------------------------

def test_validate_memory_limits_ok_for_default_values():
    bounds = portal.memory_bounds(62.47)
    assert portal.validate_memory_limits(44, 48, bounds) is None


def test_validate_memory_limits_rejects_high_greater_than_max():
    bounds = portal.memory_bounds(62.47)
    reason = portal.validate_memory_limits(50, 48, bounds)
    assert reason is not None
    assert "MemoryMax" in reason or "MemoryHigh" in reason


def test_validate_memory_limits_rejects_below_min():
    bounds = portal.memory_bounds(62.47)
    reason = portal.validate_memory_limits(1, 48, bounds)
    assert reason is not None
    assert "MemoryHigh" in reason


def test_validate_memory_limits_rejects_above_allowed_max():
    bounds = portal.memory_bounds(62.47)
    reason = portal.validate_memory_limits(44, 100, bounds)
    assert reason is not None
    assert "MemoryMax" in reason


def test_validate_memory_limits_rejects_non_integer():
    bounds = portal.memory_bounds(62.47)
    reason = portal.validate_memory_limits(44.5, 48, bounds)
    assert reason is not None
    assert "整数" in reason


# ---------------------------------------------------------------------------
# memory_warning
# ---------------------------------------------------------------------------

def test_memory_warning_none_when_within_recommendation():
    bounds = portal.memory_bounds(62.47)
    assert portal.memory_warning(48, bounds) is None


def test_memory_warning_present_when_above_recommendation():
    bounds = portal.memory_bounds(62.47)
    warning = portal.memory_warning(56, bounds)
    assert warning is not None
    assert "48" in warning


# ---------------------------------------------------------------------------
# parse_memory_properties
# ---------------------------------------------------------------------------

def test_parse_memory_properties_parses_byte_counts():
    stdout = (
        f"MemoryHigh={44 * portal.GIB_BYTES}\n"
        f"MemoryMax={48 * portal.GIB_BYTES}\n"
        f"MemoryCurrent={10 * portal.GIB_BYTES}\n"
    )
    result = portal.parse_memory_properties(stdout)
    assert result["high_gib"] == 44.0
    assert result["max_gib"] == 48.0
    assert result["current_gib"] == 10.0


def test_parse_memory_properties_treats_infinity_and_not_set_as_none():
    stdout = "MemoryHigh=infinity\nMemoryMax=infinity\nMemoryCurrent=[not set]\n"
    result = portal.parse_memory_properties(stdout)
    assert result == {"high_gib": None, "max_gib": None, "current_gib": None}


def test_parse_memory_properties_is_order_independent():
    stdout = (
        f"MemoryCurrent={5 * portal.GIB_BYTES}\n"
        f"MemoryMax={48 * portal.GIB_BYTES}\n"
        f"MemoryHigh={44 * portal.GIB_BYTES}\n"
    )
    result = portal.parse_memory_properties(stdout)
    assert result["high_gib"] == 44.0
    assert result["max_gib"] == 48.0
    assert result["current_gib"] == 5.0


# ---------------------------------------------------------------------------
# build_set_property_commands
# ---------------------------------------------------------------------------

def test_build_set_property_commands_builds_persistent_and_runtime():
    commands = portal.build_set_property_commands("pixal3d", 44, 48)
    assert len(commands) == 2
    persistent_command, runtime_command = commands
    assert "--runtime" not in persistent_command
    assert "--runtime" in runtime_command
    for command in (persistent_command, runtime_command):
        assert "MemoryHigh=44G" in command
        assert "MemoryMax=48G" in command
        assert "pixal3d" in command


# ---------------------------------------------------------------------------
# parse_memory_path
# ---------------------------------------------------------------------------

def test_parse_memory_path_valid():
    assert portal.parse_memory_path("/api/memory/pixal3d/44/48") == ("pixal3d", "44", "48")


def test_parse_memory_path_invalid_shapes_return_none():
    assert portal.parse_memory_path("/api/memory/pixal3d/44") is None
    assert portal.parse_memory_path("/api/memory/pixal3d/44/48/extra") is None
    assert portal.parse_memory_path("/api/memory//44/48") is None
    assert portal.parse_memory_path("/api/status") is None


# ---------------------------------------------------------------------------
# POST /api/memory/<key>/<high>/<max>（systemctl は monkeypatch。実際には呼ばない）
# ---------------------------------------------------------------------------

def test_post_memory_calls_subprocess_twice_with_expected_args(running_server, monkeypatch):
    captured_calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured_calls.append(list(args))
        return FakeCompletedProcess()

    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/memory/pixal3d/44/48")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True

    set_property_calls = [call for call in captured_calls if "set-property" in call]
    assert len(set_property_calls) == 2
    persistent_call, runtime_call = set_property_calls
    assert "--runtime" not in persistent_call
    assert "--runtime" in runtime_call
    for call in (persistent_call, runtime_call):
        assert "MemoryHigh=44G" in call
        assert "MemoryMax=48G" in call
        assert "pixal3d" in call


def test_post_memory_without_header_returns_403(running_server, monkeypatch):
    called = []
    monkeypatch.setattr(
        portal, "set_unit_memory_limits", lambda *args, **kwargs: called.append(args) or []
    )
    response, body = _request(running_server, "POST", "/api/memory/pixal3d/44/48", headers={})
    assert response.status == 403
    payload = json.loads(body)
    assert payload["ok"] is False
    assert called == []


def test_get_memory_path_returns_405(running_server):
    response, body = _request(running_server, "GET", "/api/memory/pixal3d/44/48")
    assert response.status == 405
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_memory_unknown_key_returns_404(running_server):
    response, body = _request(running_server, "POST", "/api/memory/nosuch/44/48")
    assert response.status == 404
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_memory_comfyui_sets_limits_on_comfyui_unit(running_server, monkeypatch):
    # ComfyUI も unit を持つので、他のサービスと同じようにメモリ上限を設定できる。
    captured_calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured_calls.append(list(args))
        return FakeCompletedProcess()

    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/memory/comfyui/44/48")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    set_property_calls = [call for call in captured_calls if "set-property" in call]
    assert len(set_property_calls) == 2
    for call in set_property_calls:
        assert "comfyui" in call
        assert "MemoryHigh=44G" in call
        assert "MemoryMax=48G" in call


def test_post_memory_not_installed_unit_returns_409(running_server, monkeypatch):
    # ComfyUI のユニットがまだ無い間は、set-property を呼ばずに断る。
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("unknown", "not-found"))
    called = []
    monkeypatch.setattr(
        portal, "set_unit_memory_limits", lambda *args, **kwargs: called.append(args) or []
    )
    response, body = _request(running_server, "POST", "/api/memory/comfyui/44/48")
    assert response.status == 409
    payload = json.loads(body)
    assert payload["ok"] is False
    assert "未導入" in payload["message"]
    assert called == []


def test_index_html_hides_memory_panel_for_not_installed():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert 'service.state === "not_installed"' in html_text


def test_post_memory_portal_itself_returns_404(running_server):
    # portal は SERVICES に無いため 404（自分自身のメモリ上限は操作できない）。
    response, body = _request(running_server, "POST", "/api/memory/portal/44/48")
    assert response.status == 404
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_memory_non_integer_returns_400(running_server):
    response, body = _request(running_server, "POST", "/api/memory/pixal3d/abc/48")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_memory_high_greater_than_max_returns_400(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    response, body = _request(running_server, "POST", "/api/memory/pixal3d/50/48")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_memory_above_allowed_max_returns_400(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    response, body = _request(running_server, "POST", "/api/memory/pixal3d/44/100")
    assert response.status == 400
    payload = json.loads(body)
    assert payload["ok"] is False


def test_post_memory_success_returns_warning_and_memory(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(portal.subprocess, "run", lambda *args, **kwargs: FakeCompletedProcess())
    monkeypatch.setattr(
        portal,
        "read_memory_properties",
        lambda unit: {"high_gib": 56.0, "max_gib": 56.0, "current_gib": 10.0},
    )

    response, body = _request(running_server, "POST", "/api/memory/pixal3d/56/56")
    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["warning"] is not None
    assert payload["memory"] == {"high_gib": 56.0, "max_gib": 56.0, "current_gib": 10.0}


def test_post_memory_failure_reports_ok_false_not_500(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)

    class FakeFailedProcess:
        returncode = 1
        stdout = ""
        stderr = "権限がありません"

    monkeypatch.setattr(portal.subprocess, "run", lambda *args, **kwargs: FakeFailedProcess())

    response, body = _request(running_server, "POST", "/api/memory/pixal3d/44/48")
    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is False
    assert "権限がありません" in payload["message"]


# ---------------------------------------------------------------------------
# GET /api/status に ram / memory が入ること
# ---------------------------------------------------------------------------

def test_get_api_status_includes_ram_and_service_memory(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    monkeypatch.setattr(
        portal,
        "read_memory_properties",
        lambda unit: {"high_gib": 44.0, "max_gib": 48.0, "current_gib": 12.0},
    )

    host, port = running_server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()

    payload = json.loads(body)
    assert payload["ram"]["available"] is True
    assert payload["ram"]["allowed_max_gib"] == 58
    assert payload["ram"]["recommended_max_gib"] == 48
    assert payload["ram"]["default_high_gib"] == portal.MEMORY_DEFAULT_HIGH_GIB
    assert payload["ram"]["default_max_gib"] == portal.MEMORY_DEFAULT_MAX_GIB

    service_by_key = {service["key"]: service for service in payload["services"]}
    assert service_by_key["hunyuan3d"]["memory"] == {
        "high_gib": 44.0,
        "max_gib": 48.0,
        "current_gib": 12.0,
        "default_high_gib": portal.MEMORY_DEFAULT_HIGH_GIB,
        "default_max_gib": portal.MEMORY_DEFAULT_MAX_GIB,
    }
    assert service_by_key["comfyui"]["memory"] == {
        "high_gib": 44.0,
        "max_gib": 48.0,
        "current_gib": 12.0,
        "default_high_gib": portal.MEMORY_DEFAULT_HIGH_GIB,
        "default_max_gib": portal.MEMORY_DEFAULT_MAX_GIB,
    }
    # Strata は RAM を約 50 GiB 以上使うので、共通の既定値（44 / 48）より大きい既定値を持つ。
    assert service_by_key["strata"]["memory"]["default_high_gib"] == 50
    assert service_by_key["strata"]["memory"]["default_max_gib"] == 54
    # Strata Flash-Next Coder は RAM を約 36 GiB 使う（実測）。既定値は 36 / 40。
    assert service_by_key["strata-coder"]["memory"]["default_high_gib"] == 36
    assert service_by_key["strata-coder"]["memory"]["default_max_gib"] == 40
    # Strata 公式版は汎用の Strata と同じ値（50 / 54）。2026-10-07 の実測（memory.peak 50.00 GiB）で、この値のままでよいと確かめた。
    assert service_by_key["strata-official"]["memory"]["default_high_gib"] == 50
    assert service_by_key["strata-official"]["memory"]["default_max_gib"] == 54


def test_index_html_calls_memory_endpoint():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert "/api/memory/" in html_text


def test_index_html_gpu_exclusive_keys_match_portal_py():
    # 確認ダイアログの対象（画面側）と、実際に止める対象（サーバー側）がずれないこと。
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    match = re.search(r"const GPU_EXCLUSIVE_KEYS = \[([^\]]*)\];", html_text)
    assert match is not None
    html_keys = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    assert html_keys == portal.GPU_EXCLUSIVE_KEYS


def test_index_html_comfyui_card_describes_installed_service():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    comfyui_block = html_text[html_text.index('"comfyui": {'):]
    comfyui_block = comfyui_block[:comfyui_block.index("}")]
    assert "まだ導入されていません" not in comfyui_block
    assert "stoppedReason" in comfyui_block
    assert "startingReason" in comfyui_block


def test_post_start_does_not_start_when_conflicting_stop_fails(running_server, monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(list(args))
        if args[2] == "stop":
            return type("FakeCompletedProcess", (), {"returncode": 1, "stdout": "", "stderr": "失敗"})()
        return type("FakeCompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def fake_read_unit_state(unit):
        if unit == "hunyuan3d":
            return ("active", "loaded")
        return ("inactive", "loaded")

    def fake_port_is_open(port, host="127.0.0.1", timeout=0.3):
        return port == 7860

    monkeypatch.setattr(portal, "read_unit_state", fake_read_unit_state)
    monkeypatch.setattr(portal, "port_is_open", fake_port_is_open)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/service/pixal3d/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is False
    # start は一度も呼ばれていないこと（両方立ち上がって RAM が枯れるのを防ぐため）。
    start_calls = [call for call in calls if call[2] == "start"]
    assert start_calls == []

def test_validate_memory_limits_names_the_offending_value() -> None:
    """どの値が大きすぎる / 小さすぎるのかと、いまの値・直し先が文面に入ること。

    「MemoryHigh は MemoryMax 以下にしてください」のような数値の無い文だけだと、
    利用者がどちらをいくつに直せばよいか分からないため。
    """
    bounds = portal.memory_bounds(62.47)

    too_small = portal.validate_memory_limits(2, 48, bounds)
    assert "MemoryHigh" in too_small and "小さすぎ" in too_small
    assert "2 GiB" in too_small and "4 GiB" in too_small

    high_over_max = portal.validate_memory_limits(52, 48, bounds)
    assert "大きすぎ" in high_over_max
    assert "52 GiB" in high_over_max and "48 GiB" in high_over_max

    max_over_allowed = portal.validate_memory_limits(44, 60, bounds)
    assert "MemoryMax" in max_over_allowed and "大きすぎ" in max_over_allowed
    assert "60 GiB" in max_over_allowed and "58 GiB" in max_over_allowed

    not_integer = portal.validate_memory_limits("abc", 48, bounds)
    assert "整数" in not_integer and "abc" in not_integer

    assert portal.validate_memory_limits(44, 48, bounds) is None


# ---------------------------------------------------------------------------
# Strata（ポート 8082。GPU 排他グループの 4 つ目。起動前に Ollama のモデルを降ろす）
# ---------------------------------------------------------------------------

def test_strata_service_definition_and_order():
    strata_service = portal.SERVICES_BY_KEY["strata"]
    assert strata_service["name"] == "Strata（Qwen3.8 Flash Next）"
    assert strata_service["port"] == 8082
    assert strata_service["unit"] == "strata"
    # 低 VRAM のスイッチは持たない
    assert portal.find_service_option(strata_service, "low_vram") is None
    # チャット系なので Open WebUI の次に並べる（画面のカードの並びはこの順）。
    service_keys = [service["key"] for service in portal.SERVICES]
    assert service_keys.index("strata") == service_keys.index("open-webui") + 1


def test_build_service_status_strata_not_installed():
    # strata のユニットがまだ作られていない間は「未導入」。ボタンも出さない。
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata"],
        port_open=False,
        active_state="unknown",
        load_state="not-found",
    )
    assert entry["state"] == "not_installed"
    assert entry["controllable"] is False
    assert entry["port"] == 8082


def test_build_service_status_strata_stopped():
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata"],
        port_open=False,
        active_state="inactive",
        load_state="loaded",
    )
    assert entry["state"] == "stopped"
    assert entry["controllable"] is True


def test_build_service_status_strata_running():
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata"],
        port_open=True,
        active_state="active",
        load_state="loaded",
    )
    assert entry["state"] == "running"
    assert entry["up"] is True


def test_services_to_stop_before_start_strata_stops_all_running_others():
    states = {"hunyuan3d": "running", "pixal3d": "starting", "comfyui": "running", "strata": "stopped"}
    assert portal.services_to_stop_before_start("strata", states) == ["hunyuan3d", "pixal3d", "comfyui"]


def test_services_to_stop_before_start_others_stop_running_strata():
    states = {"hunyuan3d": "stopped", "pixal3d": "stopped", "comfyui": "stopped", "strata": "running"}
    for key in ("hunyuan3d", "pixal3d", "comfyui"):
        assert portal.services_to_stop_before_start(key, states) == ["strata"]


def test_services_to_stop_before_start_exclusive_group_is_symmetric():
    # 排他グループ（6 つ）のどれを起動しても、自分以外のうち動いているものだけが対象になる。
    for key in portal.GPU_EXCLUSIVE_KEYS:
        states = {other_key: "running" for other_key in portal.GPU_EXCLUSIVE_KEYS}
        expected = [other_key for other_key in portal.GPU_EXCLUSIVE_KEYS if other_key != key]
        assert portal.services_to_stop_before_start(key, states) == expected


def test_services_to_stop_before_start_ignores_not_installed_strata():
    states = {"hunyuan3d": "stopped", "pixal3d": "stopped", "comfyui": "stopped", "strata": "not_installed"}
    assert portal.services_to_stop_before_start("comfyui", states) == []


# --- Ollama のモデルを降ろす純粋関数 -------------------------------------------

def test_ollama_models_to_unload_returns_names_in_order_without_duplicates():
    models = [
        {"name": "qwen3.8:27b", "size_vram_mib": 22201},
        {"name": "gemma4:e4b", "size_vram_mib": 9000},
        {"name": "qwen3.8:27b", "size_vram_mib": 1},
    ]
    assert portal.ollama_models_to_unload(models) == ["qwen3.8:27b", "gemma4:e4b"]


def test_ollama_models_to_unload_empty_for_none_and_empty_list():
    assert portal.ollama_models_to_unload(None) == []
    assert portal.ollama_models_to_unload([]) == []


def test_ollama_models_to_unload_skips_unnamed_entries():
    # parse_ollama_ps は名前の無い項目を "?" にする。それを降ろす要求の model に使ってはいけない。
    models = [{"name": "?", "size_vram_mib": 0}, {"name": "", "size_vram_mib": 0}, {"size_vram_mib": 0}, "壊れた項目"]
    assert portal.ollama_models_to_unload(models) == []


def test_build_ollama_unload_body_has_model_and_keep_alive_zero_only():
    body = json.loads(portal.build_ollama_unload_body("qwen3.8:27b"))
    # prompt を付けない（付けると生成が始まる）。keep_alive は文字列ではなく数値の 0。
    assert body == {"model": "qwen3.8:27b", "keep_alive": 0}
    assert body["keep_alive"] == 0 and not isinstance(body["keep_alive"], str)


def test_describe_ollama_unload_nothing_to_say_when_nothing_loaded():
    assert portal.describe_ollama_unload({"unloaded": [], "failed": [], "checked": True}) == ""


def test_describe_ollama_unload_lists_unloaded_models():
    message = portal.describe_ollama_unload(
        {"unloaded": ["qwen3.8:27b", "gemma4:e4b"], "failed": [], "checked": True}
    )
    assert "qwen3.8:27b" in message and "gemma4:e4b" in message
    assert "降ろしました" in message
    assert "注意" not in message


def test_describe_ollama_unload_warns_about_failed_models():
    message = portal.describe_ollama_unload({"unloaded": [], "failed": ["qwen3.8:27b"], "checked": True})
    assert message.startswith("注意")
    assert "qwen3.8:27b" in message and "降ろせませんでした" in message


def test_describe_ollama_unload_warns_when_ollama_unreachable():
    message = portal.describe_ollama_unload({"unloaded": [], "failed": [], "checked": False})
    assert message.startswith("注意")
    assert "接続できず" in message


def test_describe_ollama_unload_reports_both_unloaded_and_failed():
    message = portal.describe_ollama_unload({"unloaded": ["a"], "failed": ["b"], "checked": True})
    assert "（a）を VRAM から降ろしました" in message
    assert "注意" in message and "（b）を降ろせませんでした" in message


def test_unload_ollama_models_unloads_every_loaded_model(monkeypatch):
    monkeypatch.setattr(
        portal,
        "read_ollama_ps",
        lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 1}, {"name": "gemma4:e4b", "size_vram_mib": 1}],
    )
    requested = []
    monkeypatch.setattr(
        portal,
        "request_ollama_unload",
        lambda model_name, timeout=1.0: requested.append(model_name) or True,
    )
    result = portal.unload_ollama_models()
    assert requested == ["qwen3.8:27b", "gemma4:e4b"]
    assert result == {"unloaded": ["qwen3.8:27b", "gemma4:e4b"], "failed": [], "checked": True}


def test_unload_ollama_models_separates_failed_from_unloaded(monkeypatch):
    monkeypatch.setattr(
        portal,
        "read_ollama_ps",
        lambda: [{"name": "a", "size_vram_mib": 1}, {"name": "b", "size_vram_mib": 1}],
    )
    monkeypatch.setattr(portal, "request_ollama_unload", lambda model_name, timeout=1.0: model_name == "a")
    result = portal.unload_ollama_models()
    assert result == {"unloaded": ["a"], "failed": ["b"], "checked": True}


def test_unload_ollama_models_reports_unchecked_when_ps_unreachable(monkeypatch):
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: None)
    called = []
    monkeypatch.setattr(
        portal, "request_ollama_unload", lambda model_name, timeout=1.0: called.append(model_name) or True
    )
    result = portal.unload_ollama_models()
    assert result == {"unloaded": [], "failed": [], "checked": False}
    assert called == []


# --- request_ollama_unload（手元の偽 Ollama に対する実際の HTTP。外には出ない） ---------

@pytest.fixture()
def fake_ollama(monkeypatch):
    """POST /api/generate を受けて内容を記録する偽の Ollama を、エフェメラルポートで立てる。"""
    received: list[dict] = []

    class FakeOllamaHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received.append(
                {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "body": json.loads(self.rfile.read(length)),
                }
            )
            response_body = json.dumps({"done": True, "done_reason": "unload"}).encode("utf-8")
            self.send_response(self.server.response_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format_string, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    server.response_status = 200
    server.received = received
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    monkeypatch.setattr(portal, "OLLAMA_GENERATE_URL", f"http://{host}:{port}/api/generate")
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_request_ollama_unload_posts_model_and_keep_alive_zero(fake_ollama):
    assert portal.request_ollama_unload("qwen3.8:27b", timeout=5) is True
    assert fake_ollama.received == [
        {
            "path": "/api/generate",
            "content_type": "application/json",
            "body": {"model": "qwen3.8:27b", "keep_alive": 0},
        }
    ]


def test_request_ollama_unload_returns_false_on_http_error(fake_ollama):
    fake_ollama.response_status = 500
    assert portal.request_ollama_unload("qwen3.8:27b", timeout=5) is False


def test_request_ollama_unload_returns_false_when_ollama_unreachable(monkeypatch):
    # 待受の無いポートへ向ける（接続拒否）。例外ではなく False を返す。
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(portal, "OLLAMA_GENERATE_URL", f"http://127.0.0.1:{closed_port}/api/generate")
    assert portal.request_ollama_unload("qwen3.8:27b", timeout=2) is False


# --- POST /api/service/strata/start（起動の応答に unloaded_models が入る） -------------

def _record_start_events(monkeypatch, running_unit_to_port):
    """systemctl の呼び出しと Ollama を降ろす要求を、1 つの時系列リストへ記録する。

    要素は ["systemctl", "--user", "stop", "pixal3d"] のような systemctl の引数、または
    ["unload", "<モデル名>"]。`running_unit_to_port` の使い方は _fake_states_for_exclusive_test と同じ。
    """
    events = _fake_states_for_exclusive_test(monkeypatch, running_unit_to_port)
    monkeypatch.setattr(
        portal,
        "request_ollama_unload",
        lambda model_name, timeout=1.0: events.append(["unload", model_name]) or True,
    )
    return events


def test_post_strata_start_unloads_ollama_models_and_reports_them(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(
        portal,
        "read_ollama_ps",
        lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}, {"name": "gemma4:e4b", "size_vram_mib": 1}],
    )

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["unloaded_models"] == ["qwen3.8:27b", "gemma4:e4b"]
    assert "qwen3.8:27b" in payload["message"] and "降ろしました" in payload["message"]
    assert "注意" not in payload["message"]
    assert "stopped" not in payload
    # 降ろしてから起動する（起動のあとに降ろしても、VRAM を取り合ってしまうため）。
    start_index = events.index(["systemctl", "--user", "start", "--no-block", "strata"])
    assert events.index(["unload", "qwen3.8:27b"]) < start_index
    assert events.index(["unload", "gemma4:e4b"]) < start_index


def test_post_strata_start_stops_other_services_before_unloading_ollama(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"comfyui": 8188})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 1}])

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["comfyui"]
    assert payload["unloaded_models"] == ["qwen3.8:27b"]
    stop_index = events.index(["systemctl", "--user", "stop", "comfyui"])
    unload_index = events.index(["unload", "qwen3.8:27b"])
    start_index = events.index(["systemctl", "--user", "start", "--no-block", "strata"])
    assert stop_index < unload_index < start_index


def test_post_strata_start_with_nothing_loaded_returns_empty_unloaded_models(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [])

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["unloaded_models"] == []
    assert [event for event in events if event[0] == "unload"] == []
    assert "注意" not in payload["message"]


def test_post_strata_start_continues_with_warning_when_unload_fails(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 1}])
    monkeypatch.setattr(portal, "request_ollama_unload", lambda model_name, timeout=1.0: False)

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    assert response.status == 200
    payload = json.loads(body)
    # 降ろせなくても起動は続ける。注意を message に書く。
    assert payload["ok"] is True
    assert payload["unloaded_models"] == []
    assert "注意" in payload["message"] and "qwen3.8:27b" in payload["message"]
    assert ["systemctl", "--user", "start", "--no-block", "strata"] in events


def test_post_strata_start_continues_with_warning_when_ollama_unreachable(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: None)

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["unloaded_models"] == []
    assert "注意" in payload["message"] and "接続できず" in payload["message"]
    assert ["systemctl", "--user", "start", "--no-block", "strata"] in events


def test_post_strata_start_does_not_unload_when_not_installed(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("unknown", "not-found"))
    monkeypatch.setattr(portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: False)
    started = []
    monkeypatch.setattr(portal, "control_unit", lambda *args, **kwargs: started.append(args) or None)

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    assert response.status == 409
    assert json.loads(body)["ok"] is False
    assert started == []
    assert running_server.unload_calls == [], "起動できないのに Ollama のモデルを降ろしてはいけない"


def test_post_strata_start_does_not_unload_when_already_running(running_server, monkeypatch):
    # すでに動いている Strata への start は何も起こさない。Qwen を巻き込んで降ろさない。
    events = _record_start_events(monkeypatch, {"strata": 8082})

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert "unloaded_models" not in payload
    assert [event for event in events if event[0] == "unload"] == []


def test_post_strata_start_does_not_unload_when_stopping_other_service_fails(running_server, monkeypatch):
    events = []

    def fake_run(args, capture_output, text, timeout):
        events.append(list(args))
        if args[2] == "stop":
            return type("FakeCompletedProcess", (), {"returncode": 1, "stdout": "", "stderr": "失敗"})()
        return type("FakeCompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        portal, "read_unit_state", lambda unit: ("active", "loaded") if unit == "comfyui" else ("inactive", "loaded")
    )
    monkeypatch.setattr(portal, "port_is_open", lambda port, host="127.0.0.1", timeout=0.3: port == 8188)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert payload["ok"] is False
    assert [event for event in events if event[2] == "start"] == []
    assert running_server.unload_calls == [], "起動を中止したときは Ollama のモデルを降ろさない"


def test_post_strata_stop_does_not_unload_ollama(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata": 8082})

    response, body = _request(running_server, "POST", "/api/service/strata/stop")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert "unloaded_models" not in payload
    assert [event for event in events if event[0] == "unload"] == []


def test_post_other_exclusive_services_do_not_unload_ollama(running_server, monkeypatch):
    # 対象は Strata の 3 つ（汎用版・Coder 版・公式版）だけ。ComfyUI などの起動では、これまでどおり Ollama に触らない。
    assert portal.OLLAMA_UNLOAD_BEFORE_START_KEYS == ("strata", "strata-coder", "strata-official")
    events = _record_start_events(monkeypatch, {})
    for key in ("comfyui", "hunyuan3d", "pixal3d", "open-webui"):
        response, body = _request(running_server, "POST", f"/api/service/{key}/start")
        assert response.status == 200
        assert "unloaded_models" not in json.loads(body)
    assert [event for event in events if event[0] == "unload"] == []


def test_post_hunyuan3d_start_stops_running_strata_first(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata": 8082})

    response, body = _request(running_server, "POST", "/api/service/hunyuan3d/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["strata"]
    assert events.index(["systemctl", "--user", "stop", "strata"]) < events.index(
        ["systemctl", "--user", "start", "--no-block", "hunyuan3d"]
    )


# --- メモリ上限（ユニットがあれば他のサービスと同じ仕組みで対象になる） -----------------

def test_post_memory_strata_sets_limits_on_strata_unit(running_server, monkeypatch):
    captured_calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured_calls.append(list(args))
        return FakeCompletedProcess()

    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/memory/strata/52/56")

    assert response.status == 200
    assert json.loads(body)["ok"] is True
    set_property_calls = [call for call in captured_calls if "set-property" in call]
    assert len(set_property_calls) == 2
    for call in set_property_calls:
        assert "strata" in call
        assert "MemoryHigh=52G" in call
        assert "MemoryMax=56G" in call


def test_post_memory_strata_not_installed_returns_409(running_server, monkeypatch):
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("unknown", "not-found"))
    called = []
    monkeypatch.setattr(
        portal, "set_unit_memory_limits", lambda *args, **kwargs: called.append(args) or []
    )
    response, body = _request(running_server, "POST", "/api/memory/strata/52/56")
    assert response.status == 409
    assert "未導入" in json.loads(body)["message"]
    assert called == []


def test_get_api_status_strata_not_installed_has_no_controls(running_server, monkeypatch):
    # ユニットが無い間は未導入と出し、操作もメモリ上限も対象外（画面は state でボタン・欄を出さない）。
    monkeypatch.setattr(
        portal, "read_unit_state", lambda unit: ("unknown", "not-found") if unit == "strata" else ("active", "loaded")
    )
    _, body = _request(running_server, "GET", "/api/status")
    service_by_key = {service["key"]: service for service in json.loads(body)["services"]}
    assert service_by_key["strata"]["state"] == "not_installed"
    assert service_by_key["strata"]["controllable"] is False
    assert service_by_key["open-webui"]["state"] == "running"


# --- index.html の Strata ---------------------------------------------------

def _strata_meta_block(service_key: str = "strata") -> str:
    html_text = _html_text()
    block = html_text[html_text.index(f'"{service_key}": {{'):]
    # 入れ子の波括弧があっても切れるよう、_extract_js_object_block と同じ要領で閉じ括弧を数える。
    depth = 0
    for index, character in enumerate(block):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return block[:index + 1]
    raise AssertionError(f"SERVICE_META.{service_key} の閉じ括弧が見つかりません")


def test_index_html_strata_card_has_required_texts():
    strata_block = _strata_meta_block()
    for field in ("description:", "stoppedReason:", "startingReason:", "note:"):
        assert field in strata_block, f"SERVICE_META.strata に {field} が無い"
    # 起動に数分かかること・83GB のモデルを読むこと。
    assert "数分" in strata_block and "83GB" in strata_block
    # note: チャットの入口・Ollama のモデルが降ろされること・他サービスと同時に使えないこと。
    assert "Open WebUI（8081）" in strata_block
    assert "Ollama のモデルは、Strata の起動時に降ろされます" in strata_block
    assert "ComfyUI" in strata_block and "同時に使えません" in strata_block


def test_index_html_strata_card_points_to_open_webui_for_chat():
    # 稼働中の 2 つ目のリンクは Open WebUI へ。key が SERVICES に実在すること。
    # リンクの定義は 2 つの Strata カードで共有する STRATA_OPEN_LINKS にある（Strata の画面リンクの節を参照）。
    assert "alsoOpen: STRATA_OPEN_LINKS.alsoOpen" in _strata_meta_block()
    links_block = _extract_js_object_block(_html_text(), "STRATA_OPEN_LINKS")
    match = re.search(r'alsoOpen:\s*\{\s*key:\s*"([^"]+)"', links_block)
    assert match is not None
    assert match.group(1) in portal.SERVICES_BY_KEY
    assert match.group(1) == "open-webui"


def test_index_html_glossary_has_strata_and_abliterated():
    glossary_block = _extract_js_object_block(_html_text(), "GLOSSARY")
    glossary_keys = set(re.findall(r'"([^"]+)":\s*\n?\s*"', glossary_block))
    assert "Strata" in glossary_keys
    assert "abliterated" in glossary_keys
    # 説明に「拒否を取り除いた改変版」という意味を書く。
    assert "拒否を取り除いた改変版" in glossary_block


def test_index_html_ollama_unload_keys_match_portal_py():
    # 確認ダイアログに出す「降ろされるモデル」の対象（画面側）と、実際に降ろす対象（サーバー側）がずれないこと。
    match = re.search(r"const OLLAMA_UNLOAD_BEFORE_START_KEYS = \[([^\]]*)\];", _html_text())
    assert match is not None
    html_keys = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    assert html_keys == portal.OLLAMA_UNLOAD_BEFORE_START_KEYS


def test_index_html_gpu_exclusive_keys_include_strata_in_both():
    assert "strata" in portal.GPU_EXCLUSIVE_KEYS
    match = re.search(r"const GPU_EXCLUSIVE_KEYS = \[([^\]]*)\];", _html_text())
    assert match is not None and '"strata"' in match.group(1)
    # コード向けの版（strata-coder）も、サーバー側・画面側の両方に入っていること。
    assert "strata-coder" in portal.GPU_EXCLUSIVE_KEYS
    assert '"strata-coder"' in match.group(1)
    # 公式量子化版（strata-official）も同じ。
    assert "strata-official" in portal.GPU_EXCLUSIVE_KEYS
    assert '"strata-official"' in match.group(1)


def test_index_html_service_meta_keys_cover_every_service():
    # SERVICES に足したのに SERVICE_META を書き忘れると、カードの説明が空になる。
    meta_block = _extract_js_object_block(_html_text(), "SERVICE_META")
    for key in portal.SERVICES_BY_KEY:
        assert f'"{key}": {{' in meta_block, f"SERVICE_META に {key} が無い"


# ---------------------------------------------------------------------------
# Strata Flash-Next Coder（ポート 8083。コード向けの 2 つ目の Strata。GPU 排他グループの 5 つ目）
# ---------------------------------------------------------------------------

def test_strata_coder_service_definition_and_order():
    coder_service = portal.SERVICES_BY_KEY["strata-coder"]
    assert coder_service["name"] == "Strata Flash-Next Coder"
    assert coder_service["port"] == 8083
    assert coder_service["unit"] == "strata-coder"
    # 低 VRAM のスイッチは持たない
    assert portal.find_service_option(coder_service, "low_vram") is None
    # 汎用の Strata の次に並べる（画面のカードの並びはこの順）。
    service_keys = [service["key"] for service in portal.SERVICES]
    assert service_keys.index("strata-coder") == service_keys.index("strata") + 1
    # ポートと unit は他のサービスと重ならない（portal 自身の 8080 も含む）。
    ports = [service["port"] for service in portal.SERVICES]
    assert len(ports) == len(set(ports)) and 8080 not in ports
    units = [service["unit"] for service in portal.SERVICES]
    assert len(units) == len(set(units))


def test_strata_coder_memory_default_is_measured_and_within_allowed_max():
    # 36 / 40 GiB は実測の値（cgroup の memory.peak 36.00 GiB）。汎用の Strata（50 / 54）より小さく、共通の既定値（44 / 48）以下。
    entry = portal.build_memory_entry(
        portal.SERVICES_BY_KEY["strata-coder"], {"high_gib": 10.0, "max_gib": 12.0, "current_gib": 1.0}
    )
    assert (entry["default_high_gib"], entry["default_max_gib"]) == (36, 40)
    # 既定値は許容上限（RAM 総量 - 4 GiB）以下で、画面の検証（validate_memory_limits）も通る。
    bounds = portal.memory_bounds(62.5)
    assert entry["default_max_gib"] <= bounds["allowed_max_gib"]
    assert portal.validate_memory_limits(entry["default_high_gib"], entry["default_max_gib"], bounds) is None


def test_build_service_status_strata_coder_not_installed():
    # strata-coder のユニットがまだ作られていない間は「未導入」。ボタンも出さない。
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata-coder"],
        port_open=False,
        active_state="unknown",
        load_state="not-found",
    )
    assert entry["state"] == "not_installed"
    assert entry["controllable"] is False
    assert entry["port"] == 8083


def test_build_service_status_strata_coder_stopped():
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata-coder"],
        port_open=False,
        active_state="inactive",
        load_state="loaded",
    )
    assert entry["state"] == "stopped"
    assert entry["controllable"] is True


def test_build_service_status_strata_coder_running():
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata-coder"],
        port_open=True,
        active_state="active",
        load_state="loaded",
    )
    assert entry["state"] == "running"
    assert entry["up"] is True


def test_build_service_status_strata_coder_starting():
    # ユニット active・ポート閉 = 起動中（モデルの読み込みに数分かかる間）。
    entry = portal.build_service_status(
        portal.SERVICES_BY_KEY["strata-coder"],
        port_open=False,
        active_state="active",
        load_state="loaded",
    )
    assert entry["state"] == "starting"
    assert entry["controllable"] is True


def test_services_to_stop_before_start_six_services_are_mutually_exclusive():
    # 6 つ（hunyuan3d・pixal3d・comfyui・strata・strata-coder・strata-official）のうち同時に動くのは 1 つだけ。
    exclusive_keys = ("hunyuan3d", "pixal3d", "comfyui", "strata", "strata-coder", "strata-official")
    assert set(portal.GPU_EXCLUSIVE_KEYS) == set(exclusive_keys)
    for running_key in exclusive_keys:
        states = {key: ("running" if key == running_key else "stopped") for key in exclusive_keys}
        for start_key in exclusive_keys:
            expected = [] if start_key == running_key else [running_key]
            assert portal.services_to_stop_before_start(start_key, states) == expected


def test_services_to_stop_before_start_strata_coder_stops_all_running_others():
    states = {
        "hunyuan3d": "running",
        "pixal3d": "starting",
        "comfyui": "running",
        "strata": "running",
        "strata-coder": "stopped",
        "strata-official": "running",
    }
    assert portal.services_to_stop_before_start("strata-coder", states) == [
        "hunyuan3d", "pixal3d", "comfyui", "strata", "strata-official"
    ]


def test_services_to_stop_before_start_strata_variants_stop_each_other():
    # 汎用の Strata・Coder 版・公式版は、どれも同時に動かせない（RAM・VRAM が足りない）。
    states = {"strata": "running", "strata-coder": "stopped", "strata-official": "stopped"}
    assert portal.services_to_stop_before_start("strata-coder", states) == ["strata"]
    states = {"strata": "stopped", "strata-coder": "starting", "strata-official": "stopped"}
    assert portal.services_to_stop_before_start("strata", states) == ["strata-coder"]
    states = {"strata": "running", "strata-coder": "running", "strata-official": "stopped"}
    assert portal.services_to_stop_before_start("strata-official", states) == ["strata", "strata-coder"]


def test_services_to_stop_before_start_ignores_not_installed_strata_coder():
    states = {"strata": "stopped", "strata-coder": "not_installed"}
    assert portal.services_to_stop_before_start("strata", states) == []
    assert portal.services_to_stop_before_start("comfyui", states) == []


def test_ollama_unload_targets_are_all_strata():
    # 起動前に Ollama のモデルを降ろす対象は Strata の 3 つ（汎用版・Coder 版・公式版）だけ。
    assert set(portal.OLLAMA_UNLOAD_BEFORE_START_KEYS) == {"strata", "strata-coder", "strata-official"}
    for key in portal.OLLAMA_UNLOAD_BEFORE_START_KEYS:
        assert key in portal.GPU_EXCLUSIVE_KEYS


# --- POST /api/service/strata-coder/... ------------------------------------------

def test_post_strata_coder_start_unloads_ollama_models_and_reports_them(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(
        portal,
        "read_ollama_ps",
        lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}],
    )

    response, body = _request(running_server, "POST", "/api/service/strata-coder/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["unloaded_models"] == ["qwen3.8:27b"]
    assert "stopped" not in payload
    # 降ろしてから、--no-block で起動する。
    start_index = events.index(["systemctl", "--user", "start", "--no-block", "strata-coder"])
    assert events.index(["unload", "qwen3.8:27b"]) < start_index


def test_post_strata_coder_start_stops_running_general_strata_first(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata": 8082})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [])

    response, body = _request(running_server, "POST", "/api/service/strata-coder/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["strata"]
    assert payload["unloaded_models"] == []
    assert events.index(["systemctl", "--user", "stop", "strata"]) < events.index(
        ["systemctl", "--user", "start", "--no-block", "strata-coder"]
    )


def test_post_strata_start_stops_running_strata_coder_first(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata-coder": 8083})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [])

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["strata-coder"]
    assert events.index(["systemctl", "--user", "stop", "strata-coder"]) < events.index(
        ["systemctl", "--user", "start", "--no-block", "strata"]
    )


def test_post_hunyuan3d_start_stops_running_strata_coder_first(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata-coder": 8083})

    response, body = _request(running_server, "POST", "/api/service/hunyuan3d/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["strata-coder"]
    assert events.index(["systemctl", "--user", "stop", "strata-coder"]) < events.index(
        ["systemctl", "--user", "start", "--no-block", "hunyuan3d"]
    )


def test_post_strata_coder_start_does_not_unload_when_already_running(running_server, monkeypatch):
    # すでに動いている Coder 版への start は何も起こさない。Qwen を巻き込んで降ろさない。
    events = _record_start_events(monkeypatch, {"strata-coder": 8083})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}])

    response, body = _request(running_server, "POST", "/api/service/strata-coder/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert "unloaded_models" not in payload
    assert [event for event in events if event[0] == "unload"] == []


def test_post_strata_coder_start_not_installed_returns_409_without_unloading(running_server, monkeypatch):
    # ユニットが無い間は未導入。Ollama のモデルも降ろさない。
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("unknown", "not-found"))
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}])

    response, body = _request(running_server, "POST", "/api/service/strata-coder/start")

    assert response.status == 409
    assert "未導入" in json.loads(body)["message"]
    assert [event for event in events if event[0] == "unload"] == []
    assert not any(event[:3] == ["systemctl", "--user", "start"] for event in events)


def test_post_strata_coder_stop_does_not_unload_ollama(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata-coder": 8083})

    response, body = _request(running_server, "POST", "/api/service/strata-coder/stop")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert "unloaded_models" not in payload
    assert ["systemctl", "--user", "stop", "strata-coder"] in events
    assert [event for event in events if event[0] == "unload"] == []


def test_post_memory_strata_coder_sets_limits_on_strata_coder_unit(running_server, monkeypatch):
    captured_calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured_calls.append(list(args))
        return FakeCompletedProcess()

    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/memory/strata-coder/36/40")

    assert response.status == 200
    assert json.loads(body)["ok"] is True
    set_property_calls = [call for call in captured_calls if "set-property" in call]
    assert len(set_property_calls) == 2
    for call in set_property_calls:
        assert "strata-coder" in call
        assert "MemoryHigh=36G" in call
        assert "MemoryMax=40G" in call


def test_get_api_status_strata_coder_not_installed_has_no_controls(running_server, monkeypatch):
    # ユニットが無い間は未導入と出し、操作もメモリ上限も対象外。他のサービスには影響しない。
    monkeypatch.setattr(
        portal,
        "read_unit_state",
        lambda unit: ("unknown", "not-found") if unit == "strata-coder" else ("active", "loaded"),
    )
    _, body = _request(running_server, "GET", "/api/status")
    service_by_key = {service["key"]: service for service in json.loads(body)["services"]}
    assert service_by_key["strata-coder"]["state"] == "not_installed"
    assert service_by_key["strata-coder"]["controllable"] is False
    assert service_by_key["strata-coder"]["port"] == 8083
    assert service_by_key["strata"]["state"] != "not_installed"


# --- index.html の Strata Flash-Next Coder ---------------------------------------

def test_index_html_strata_coder_card_has_required_texts():
    coder_block = _strata_meta_block("strata-coder")
    for field in ("description:", "stoppedReason:", "startingReason:", "note:"):
        assert field in coder_block, f"SERVICE_META.strata-coder に {field} が無い"
    # 説明: 半分に削ったコード向けのモデル。作者の数字は「作者の報告」と明記する。
    assert "512 エキスパート" in coder_block and "半分" in coder_block and "コード向け" in coder_block
    assert "SWE-bench Verified 75.6" in coder_block and "作者の報告" in coder_block
    # 起動に数分かかること。
    assert "数分" in coder_block
    # note: チャットの入口・Ollama のモデルが降ろされること・汎用の Strata などと同時に使えないこと・
    # 日本語が弱いこと・画像入力が未対応であること。
    assert "Open WebUI（8081）" in coder_block
    assert "Ollama のモデルは" in coder_block and "降ろされます" in coder_block
    assert "汎用の Strata" in coder_block and "ComfyUI" in coder_block and "同時に使えません" in coder_block
    assert "日本語は実用になりません" in coder_block
    assert "画像入力は未対応" in coder_block


def test_index_html_all_strata_cards_share_open_links():
    # 「Strata の画面」リンクは、カードのポート（service.port）で開く共通の定義を 3 つのカードで使う。
    # 汎用版（8082）だけに固定せず、Coder 版（8083）・公式版（8084）も同じ書き方で動くこと。
    html_text = _html_text()
    links_block = _extract_js_object_block(html_text, "STRATA_OPEN_LINKS")
    assert "8082" not in links_block and "8083" not in links_block and "8084" not in links_block
    for service_key in ("strata", "strata-coder", "strata-official"):
        service_block = _strata_meta_block(service_key)
        assert "openLabel: STRATA_OPEN_LINKS.openLabel" in service_block
        assert "openTooltip: STRATA_OPEN_LINKS.openTooltip" in service_block
        assert "alsoOpen: STRATA_OPEN_LINKS.alsoOpen" in service_block
    # リンク先のポートは SERVICES 由来（サービスごとの service.port）。
    assert "buildOpenLink(service.port, meta.openLabel" in html_text


def test_index_html_glossary_has_strata_coder_and_mentions_both_strata():
    html_text = _html_text()
    glossary_block = _extract_js_object_block(html_text, "GLOSSARY")
    glossary_keys = set(re.findall(r'"([^"]+)":\s*\n?\s*"', glossary_block))
    # カードの名前（括弧が無いので名前全体）が用語になるので、用語集に同じ名前が要る。
    assert portal.SERVICES_BY_KEY["strata-coder"]["name"] in glossary_keys
    assert "Strata" in glossary_keys
    # ポートの説明に 8083 が入っている。
    port_start = glossary_block.index('"ポート":')
    assert "8083" in glossary_block[port_start:port_start + 600]
    # 排他の説明は 6 つを挙げる。
    exclusive_start = glossary_block.index('"GPU の排他":')
    exclusive_text = glossary_block[exclusive_start:exclusive_start + 600]
    assert "Strata Flash-Next Coder" in exclusive_text and "Strata 公式版" in exclusive_text and "6 つ" in exclusive_text


def test_index_html_qwen_warning_mentions_all_strata():
    # Ollama にモデルが載っているときの警告文。Strata は 3 つとも起動時に自動で降ろす。
    assert "Strata（汎用版・Coder 版・公式版）は起動時に自動で降ろします" in _html_text()


def test_index_html_other_gpu_cards_mention_strata_variants_in_exclusive_notes():
    # Pixal3D・ComfyUI のカードの「同時に使えない」説明に、Coder 版・公式版も含まれる。
    for service_key in ("pixal3d", "comfyui"):
        block = _strata_meta_block(service_key)
        assert "Strata（Coder 版・公式版を含む）" in block, (
            f"SERVICE_META.{service_key} の排他の説明に Coder 版・公式版が無い"
        )


# ---------------------------------------------------------------------------
# Strata 公式版（ポート 8084。3 つ目の Strata。Qwen3.8-Flash-Next の公式量子化 IQ3_XXS。GPU 排他グループの 6 つ目）
# ---------------------------------------------------------------------------

def test_strata_official_service_definition_and_order():
    official_service = portal.SERVICES_BY_KEY["strata-official"]
    assert official_service["name"] == "Strata 公式版（IQ3_XXS）"
    assert official_service["port"] == 8084
    assert official_service["unit"] == "strata-official"
    # 低 VRAM のスイッチは持たない
    assert portal.find_service_option(official_service, "low_vram") is None
    # 汎用の Strata・Coder 版の次に並べる（画面のカードの並びはこの順）。
    service_keys = [service["key"] for service in portal.SERVICES]
    assert service_keys.index("strata-official") == service_keys.index("strata-coder") + 1
    # サービスは 7 つ（open-webui・strata 3 つ・hunyuan3d・pixal3d・comfyui）。
    assert len(service_keys) == 7
    # ポートと unit は他のサービスと重ならない（portal 自身の 8080 も含む）。
    ports = [service["port"] for service in portal.SERVICES]
    assert len(ports) == len(set(ports)) and 8080 not in ports
    units = [service["unit"] for service in portal.SERVICES]
    assert len(units) == len(set(units))


def test_strata_official_memory_default_is_measured_and_equal_to_general_strata():
    # 50 / 54 GiB は汎用の Strata と同じ値。2026-10-07 の実測（cgroup の memory.peak 50.00 GiB = MemoryHigh）で確かめた。
    entry = portal.build_memory_entry(
        portal.SERVICES_BY_KEY["strata-official"], {"high_gib": 10.0, "max_gib": 12.0, "current_gib": 1.0}
    )
    assert (entry["default_high_gib"], entry["default_max_gib"]) == (50, 54)
    assert portal.SERVICES_BY_KEY["strata-official"]["memory_default"] == portal.SERVICES_BY_KEY["strata"]["memory_default"]
    # 既定値は許容上限（RAM 総量 - 4 GiB）以下で、画面の検証（validate_memory_limits）も通る。
    bounds = portal.memory_bounds(62.5)
    assert entry["default_max_gib"] <= bounds["allowed_max_gib"]
    assert portal.validate_memory_limits(entry["default_high_gib"], entry["default_max_gib"], bounds) is None


def test_build_service_status_strata_official_states():
    service = portal.SERVICES_BY_KEY["strata-official"]
    # ユニットがまだ作られていない間は「未導入」。ボタンも出さない。
    entry = portal.build_service_status(service, port_open=False, active_state="unknown", load_state="not-found")
    assert (entry["state"], entry["controllable"], entry["port"]) == ("not_installed", False, 8084)
    entry = portal.build_service_status(service, port_open=False, active_state="inactive", load_state="loaded")
    assert (entry["state"], entry["controllable"]) == ("stopped", True)
    # ユニット active・ポート閉 = 起動中（モデルの読み込みに数分かかる間）。
    entry = portal.build_service_status(service, port_open=False, active_state="active", load_state="loaded")
    assert (entry["state"], entry["controllable"]) == ("starting", True)
    entry = portal.build_service_status(service, port_open=True, active_state="active", load_state="loaded")
    assert (entry["state"], entry["up"]) == ("running", True)


def test_services_to_stop_before_start_strata_official_stops_all_running_others():
    states = {
        "hunyuan3d": "running",
        "pixal3d": "starting",
        "comfyui": "running",
        "strata": "running",
        "strata-coder": "running",
        "strata-official": "stopped",
    }
    assert portal.services_to_stop_before_start("strata-official", states) == [
        "hunyuan3d", "pixal3d", "comfyui", "strata", "strata-coder"
    ]


def test_services_to_stop_before_start_ignores_not_installed_strata_official():
    states = {"strata": "stopped", "strata-coder": "stopped", "strata-official": "not_installed"}
    assert portal.services_to_stop_before_start("strata", states) == []
    assert portal.services_to_stop_before_start("comfyui", states) == []


# --- POST /api/service/strata-official/... ---------------------------------------

def test_post_strata_official_start_unloads_ollama_models_and_reports_them(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(
        portal,
        "read_ollama_ps",
        lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}],
    )

    response, body = _request(running_server, "POST", "/api/service/strata-official/start")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["unloaded_models"] == ["qwen3.8:27b"]
    assert "stopped" not in payload
    # 降ろしてから、--no-block で起動する。
    start_index = events.index(["systemctl", "--user", "start", "--no-block", "strata-official"])
    assert events.index(["unload", "qwen3.8:27b"]) < start_index


def test_post_strata_official_start_stops_running_general_and_coder_strata_first(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata": 8082, "strata-coder": 8083})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [])

    response, body = _request(running_server, "POST", "/api/service/strata-official/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["strata", "strata-coder"]
    start_index = events.index(["systemctl", "--user", "start", "--no-block", "strata-official"])
    assert events.index(["systemctl", "--user", "stop", "strata"]) < start_index
    assert events.index(["systemctl", "--user", "stop", "strata-coder"]) < start_index


def test_post_strata_start_stops_running_strata_official_first(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata-official": 8084})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [])

    response, body = _request(running_server, "POST", "/api/service/strata/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["stopped"] == ["strata-official"]
    assert events.index(["systemctl", "--user", "stop", "strata-official"]) < events.index(
        ["systemctl", "--user", "start", "--no-block", "strata"]
    )


def test_post_strata_official_start_does_not_unload_when_already_running(running_server, monkeypatch):
    # すでに動いている公式版への start は何も起こさない。Qwen を巻き込んで降ろさない。
    events = _record_start_events(monkeypatch, {"strata-official": 8084})
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}])

    response, body = _request(running_server, "POST", "/api/service/strata-official/start")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert "unloaded_models" not in payload
    assert [event for event in events if event[0] == "unload"] == []


def test_post_strata_official_start_not_installed_returns_409_without_unloading(running_server, monkeypatch):
    # ユニットが無い間は未導入。Ollama のモデルも降ろさない。
    events = _record_start_events(monkeypatch, {})
    monkeypatch.setattr(portal, "read_unit_state", lambda unit: ("unknown", "not-found"))
    monkeypatch.setattr(portal, "read_ollama_ps", lambda: [{"name": "qwen3.8:27b", "size_vram_mib": 22201}])

    response, body = _request(running_server, "POST", "/api/service/strata-official/start")

    assert response.status == 409
    assert "未導入" in json.loads(body)["message"]
    assert [event for event in events if event[0] == "unload"] == []
    assert not any(event[:3] == ["systemctl", "--user", "start"] for event in events)


def test_post_strata_official_stop_does_not_unload_ollama(running_server, monkeypatch):
    events = _record_start_events(monkeypatch, {"strata-official": 8084})

    response, body = _request(running_server, "POST", "/api/service/strata-official/stop")

    payload = json.loads(body)
    assert payload["ok"] is True
    assert "unloaded_models" not in payload
    assert ["systemctl", "--user", "stop", "strata-official"] in events
    assert [event for event in events if event[0] == "unload"] == []


def test_post_memory_strata_official_sets_limits_on_strata_official_unit(running_server, monkeypatch):
    captured_calls = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout):
        captured_calls.append(list(args))
        return FakeCompletedProcess()

    monkeypatch.setattr(portal, "read_meminfo_total_gib", lambda: 62.47)
    monkeypatch.setattr(portal.subprocess, "run", fake_run)

    response, body = _request(running_server, "POST", "/api/memory/strata-official/50/54")

    assert response.status == 200
    assert json.loads(body)["ok"] is True
    set_property_calls = [call for call in captured_calls if "set-property" in call]
    assert len(set_property_calls) == 2
    for call in set_property_calls:
        assert "strata-official" in call
        assert "MemoryHigh=50G" in call
        assert "MemoryMax=54G" in call


def test_get_api_status_strata_official_not_installed_has_no_controls(running_server, monkeypatch):
    # ユニットが無い間は未導入と出し、操作もメモリ上限も対象外。他のサービスには影響しない。
    monkeypatch.setattr(
        portal,
        "read_unit_state",
        lambda unit: ("unknown", "not-found") if unit == "strata-official" else ("active", "loaded"),
    )
    _, body = _request(running_server, "GET", "/api/status")
    payload = json.loads(body)
    service_by_key = {service["key"]: service for service in payload["services"]}
    assert len(payload["services"]) == 7
    assert service_by_key["strata-official"]["state"] == "not_installed"
    assert service_by_key["strata-official"]["controllable"] is False
    assert service_by_key["strata-official"]["port"] == 8084
    assert service_by_key["strata"]["state"] != "not_installed"
    assert service_by_key["strata-coder"]["state"] != "not_installed"


# --- index.html の Strata 公式版 ---------------------------------------------------

def test_index_html_strata_official_card_has_required_texts():
    official_block = _strata_meta_block("strata-official")
    for field in ("description:", "stoppedReason:", "startingReason:", "note:"):
        assert field in official_block, f"SERVICE_META.strata-official に {field} が無い"
    # 説明: 公式の量子化（ISTA-DASLab の GSQ-RCO・IQ3_XXS）・512 エキスパートのまま・abliterated ではない・汎用版と比べる用。
    assert "ISTA-DASLab" in official_block and "GSQ-RCO" in official_block and "IQ3_XXS" in official_block
    assert "512 エキスパート" in official_block and "abliterated ではない" in official_block
    assert "汎用版" in official_block and "比べる" in official_block
    # 起動に数分かかること。
    assert "数分" in official_block
    # note: チャットの入口・API のモデル名・Ollama のモデルが降ろされること・他と同時に使えないこと・RAM と VRAM が実測の値で書かれていること。
    assert "Open WebUI（8081）" in official_block and "strata-official:IQ3_XXS" in official_block
    assert "Ollama のモデルは" in official_block and "降ろされます" in official_block
    assert "汎用の Strata" in official_block and "ComfyUI" in official_block and "同時に使えません" in official_block
    # 実測の値（RAM 約 50GiB・VRAM 23,899 MiB・実測の日付）が入っていて、「未計測」「見込み」は残っていない。
    assert "約 50GiB" in official_block and "23,899 MiB" in official_block and "2026-10-07 の実測" in official_block
    assert "未計測" not in official_block and "見込み" not in official_block
    # 用途の説明に、数学など長く考える問題は公式版のほうが答えに届きやすいという実測が入っている。
    assert "長く考える問題は公式版のほうが答えに届きやすい" in official_block


def test_index_html_glossary_has_strata_official_and_port_8084():
    glossary_block = _extract_js_object_block(_html_text(), "GLOSSARY")
    glossary_keys = set(re.findall(r'"([^"]+)":\s*\n?\s*"', glossary_block))
    # カードの名前は括弧の前（「Strata 公式版」）が用語になるので、用語集に同じ語が要る。
    assert portal.SERVICES_BY_KEY["strata-official"]["name"].split("（")[0] in glossary_keys
    # ポートの説明に 8084 が入っている。
    port_start = glossary_block.index('"ポート":')
    assert "8084" in glossary_block[port_start:port_start + 600]
    # 用語集の公式版と RAM の説明は実測の値で書かれていて、「未計測」「見込み」は残っていない。
    official_start = glossary_block.index('"Strata 公式版":')
    assert "約 50 GiB" in glossary_block[official_start:official_start + 800]
    assert "23,899 MiB" in glossary_block[official_start:official_start + 800]
    assert "未計測" not in glossary_block and "見込み" not in glossary_block

