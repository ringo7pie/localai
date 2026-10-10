"""OllamaChatClient の試験。

Ollama にも GPU にも触れない。urllib.request.urlopen を monkeypatch してネットワークを遮断する。
"""

from __future__ import annotations

import json
from typing import Any

from qwen_worker import ollama_client
from qwen_worker.ollama_client import OllamaChatClient


class _FakeResponse:
    """urlopen の with 文で使うダミー応答。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def _client() -> OllamaChatClient:
    return OllamaChatClient("http://127.0.0.1:11434", "qwen3.8:27b", 60)


def test_chat_without_response_format_omits_format_key(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", fake_urlopen)
    _client().chat([{"role": "user", "content": "hi"}], think=False, options={})

    assert "format" not in captured["body"]


def test_chat_with_response_format_sets_format_key(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"message": {"content": "{}"}})

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", fake_urlopen)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    _client().chat(
        [{"role": "user", "content": "hi"}], think=False, options={}, response_format=schema
    )

    assert captured["body"]["format"] == schema


def test_list_models_parses_tags_response(monkeypatch) -> None:
    def fake_urlopen(url, timeout=None):
        assert url.endswith("/api/tags")
        return _FakeResponse({"models": [{"name": "qwen3.8:27b", "size": 123}]})

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", fake_urlopen)
    models = _client().list_models()

    assert models == [{"name": "qwen3.8:27b", "size": 123}]


def test_list_models_returns_none_on_failure(monkeypatch) -> None:
    def fake_urlopen(url, timeout=None):
        raise OSError("接続失敗")

    monkeypatch.setattr(ollama_client.urllib.request, "urlopen", fake_urlopen)

    assert _client().list_models() is None
