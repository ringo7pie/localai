"""server.py のモデル選択（_resolve_model / _cached_models）の試験。

Ollama にも GPU にも触れない。OllamaChatClient.list_models 相当のフェイクだけを使う。
_model_cache はモジュールレベルのグローバルなので、各試験の前に空へ戻す。
"""

from __future__ import annotations

from typing import Any

import pytest

from qwen_worker import server


class _FakeClient:
    """OllamaChatClient.list_models だけを真似るフェイク。"""

    def __init__(self, models: list[dict[str, Any]] | None) -> None:
        self._models = models
        self.calls = 0

    def list_models(self, timeout: float = 5.0) -> list[dict[str, Any]] | None:
        self.calls += 1
        return self._models


@pytest.fixture(autouse=True)
def _reset_model_cache() -> None:
    server._model_cache["models"] = None
    server._model_cache["fetched_at"] = 0.0
    yield
    server._model_cache["models"] = None
    server._model_cache["fetched_at"] = 0.0


def test_resolve_model_none_uses_config_default_without_fetching() -> None:
    client = _FakeClient([{"name": "qwen3.8:27b"}])

    resolved, models, error = server._resolve_model(client, None, "qwen3.8:27b")

    assert resolved == "qwen3.8:27b"
    assert error is None
    # model 未指定なら一覧を取りに行く必要がない。
    assert client.calls == 0


def test_resolve_model_known_name_is_passed_through() -> None:
    client = _FakeClient([{"name": "qwen3.8:27b"}, {"name": "gemma4:e4b"}])

    resolved, models, error = server._resolve_model(client, "gemma4:e4b", "qwen3.8:27b")

    assert resolved == "gemma4:e4b"
    assert error is None
    assert models is not None


def test_resolve_model_unknown_name_blocks_with_available_list() -> None:
    client = _FakeClient([{"name": "qwen3.8:27b"}, {"name": "gemma4:e4b"}])

    resolved, models, error = server._resolve_model(client, "no-such-model", "qwen3.8:27b")

    assert resolved is None
    assert error is not None
    assert "gemma4:e4b" in error
    assert "qwen3.8:27b" in error


def test_resolve_model_tags_unavailable_passes_through_with_warning() -> None:
    # /api/tags が取れないとき、一覧を確認できないことを理由には止めない。
    # 親が明示的に選んだモデルの実行そのものは通す（後段の /api/chat が
    # 実在しなければそのとき失敗する）。
    client = _FakeClient(None)

    resolved, models, error = server._resolve_model(client, "gemma4:e4b", "qwen3.8:27b")

    assert resolved == "gemma4:e4b"
    assert error is None
    assert models is None


def test_cached_models_uses_cache_within_ttl() -> None:
    client = _FakeClient([{"name": "a"}])

    first = server._cached_models(client)
    second = server._cached_models(client)

    assert first == second == [{"name": "a"}]
    assert client.calls == 1


def test_cached_models_refetches_when_source_returns_none() -> None:
    client = _FakeClient(None)

    first = server._cached_models(client)
    second = server._cached_models(client)

    assert first is None
    assert second is None
    # 取得できなかった結果はキャッシュせず、毎回取りに行く。
    assert client.calls == 2
