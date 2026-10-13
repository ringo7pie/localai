"""web_tools.py の試験。

ネットワークにも Ollama にも触れない。urllib.request と ddgs は必ず monkeypatch する。
"""

from __future__ import annotations

import socket
import urllib.error

import pytest

from qwen_worker import web_tools

# 公開 IP のリテラル。urlparse().hostname が IP そのものだと socket.getaddrinfo は
# 名前解決をせずローカルで即答するため、DNS 越しにネットワークへ出ない。
_PUBLIC_IP_URL = "http://93.184.216.34/page"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://192.168.1.10:8081",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "ftp://example.com",
    ],
)
def test_validate_url_rejects_internal_and_disallowed(url: str) -> None:
    assert web_tools.validate_url(url) is not None


def test_validate_url_allows_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    assert web_tools.validate_url(_PUBLIC_IP_URL.replace("http", "https")) is None


def test_validate_url_rejects_hostname_resolving_to_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    """外部ドメインの見た目でも、解決先が内部 IP なら拒否する（DNS リバインディング対策）。"""

    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "internal.example.test"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(web_tools.socket, "getaddrinfo", fake_getaddrinfo)
    reason = web_tools.validate_url("https://internal.example.test/")
    assert reason is not None


def test_validate_url_allows_hostname_resolving_to_public(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "example.test"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(web_tools.socket, "getaddrinfo", fake_getaddrinfo)
    assert web_tools.validate_url("https://example.test/") is None


@pytest.mark.parametrize(
    ("ip_text", "blocked"),
    [
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("172.16.0.1", True),
        ("192.168.1.1", True),
        ("169.254.169.254", True),
        ("::1", True),
        ("224.0.0.1", True),  # マルチキャスト
        ("0.0.0.0", True),  # 未指定
        ("not-an-ip", True),  # 解析不能は安全側で拒否
        ("93.184.216.34", False),
        ("8.8.8.8", False),
    ],
)
def test_is_blocked_address(ip_text: str, blocked: bool) -> None:
    assert web_tools.is_blocked_address(ip_text) is blocked


class _FakeHeaders:
    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._headers.get(key, default)


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self._body = body
        self.headers = _FakeHeaders({"Content-Type": content_type})
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size >= len(self._body):
            chunk, self._body = self._body, b""
            return chunk
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk

    def close(self) -> None:
        self.closed = True


def test_fetch_url_rejects_redirect_to_internal_address(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_open_request(opener, request):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            request.full_url, 302, "Found", {"Location": "http://127.0.0.1:11434/internal"}, None
        )

    monkeypatch.setattr(web_tools, "_open_request", fake_open_request)
    result = web_tools.fetch_url(_PUBLIC_IP_URL)
    assert "error" in result
    # 内部アドレスは検査で弾かれ、そこへは実際に開きに行かない。
    assert calls["count"] == 1


def test_fetch_url_truncates_and_marks_it(monkeypatch: pytest.MonkeyPatch) -> None:
    long_body = ("あ" * 100).encode("utf-8")
    monkeypatch.setattr(
        web_tools, "_open_request", lambda opener, request: _FakeResponse(long_body, "text/plain; charset=utf-8")
    )
    result = web_tools.fetch_url(_PUBLIC_IP_URL, max_chars=10)
    assert result["truncated"] is True
    assert "text" in result
    assert "切り詰め" in result["text"]
    assert len(result["text"]) < len(long_body.decode("utf-8"))


def test_fetch_url_success_without_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "本文です".encode("utf-8")
    monkeypatch.setattr(
        web_tools, "_open_request", lambda opener, request: _FakeResponse(body, "text/plain; charset=utf-8")
    )
    result = web_tools.fetch_url(_PUBLIC_IP_URL, max_chars=1000)
    assert result["truncated"] is False
    assert result["text"] == "本文です"


def test_web_search_returns_error_on_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(query, max_results):
        raise RuntimeError("レート制限に達しました")

    monkeypatch.setattr(web_tools, "_run_ddgs_search", fake_search)
    result = web_tools.web_search("何か調べたいこと")
    assert "error" in result
    assert "results" not in result


def test_web_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(query, max_results):
        assert query == "qwen worker"
        return [
            {"title": "見出し1", "href": "https://example.test/1", "body": "抜粋1"},
            {"title": "見出し2", "href": "https://example.test/2", "body": "抜粋2"},
        ]

    monkeypatch.setattr(web_tools, "_run_ddgs_search", fake_search)
    result = web_tools.web_search("qwen worker", max_results=2)
    assert "results" in result
    assert len(result["results"]) == 2
    assert result["results"][0] == {
        "title": "見出し1",
        "url": "https://example.test/1",
        "snippet": "抜粋1",
    }


def test_html_to_text_drops_script_and_style_content() -> None:
    html = (
        "<html><head><style>body{color:red}</style>"
        "<script>alert('should-not-appear')</script></head>"
        "<body><p>見える本文</p></body></html>"
    ).encode("utf-8")
    text = web_tools._html_to_text(html, "text/html; charset=utf-8")
    assert "alert" not in text
    assert "should-not-appear" not in text
    assert "color:red" not in text
    assert "見える本文" in text
