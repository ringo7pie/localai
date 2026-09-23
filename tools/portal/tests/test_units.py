"""portal.py の単体テスト。ネットワーク・GPU・systemd には触れない。

実行コマンド（システムに pytest は入っていないので uv の一時環境で走らせる）:
    uvx --with pytest pytest tools/portal/tests/test_units.py -q
"""
from __future__ import annotations

import http.client
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
    states = {"hunyuan3d": "running", "pixal3d": "running"}
    assert portal.services_to_stop_before_start("open-webui", states) == []


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
        index for index, call in enumerate(calls) if call == ["systemctl", "--user", "start", "pixal3d"]
    )
    assert stop_call_index < start_call_index


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


def test_post_memory_comfyui_returns_404(running_server):
    # ComfyUI は unit を持たないため対象外。
    response, body = _request(running_server, "POST", "/api/memory/comfyui/44/48")
    assert response.status == 404
    payload = json.loads(body)
    assert payload["ok"] is False


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
    }
    assert service_by_key["comfyui"]["memory"] is None


def test_index_html_calls_memory_endpoint():
    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert "/api/memory/" in html_text


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
