"""ToolRunner 経由のウェブツール配線の試験。

web_search / fetch_url そのものの網羅的な試験は test_web_tools.py にある。
ここでは仕様の出し分け・回数上限・エラーの伝播だけを見る。ネットワークにも
Ollama にも触れない（worker_tools 側の web_search / fetch_url を monkeypatch する）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qwen_worker import worker_tools
from qwen_worker.sandbox import build_sandbox
from qwen_worker.worker_tools import ToolRunner, implement_tool_specs, read_only_tool_specs


def _spec_names(specs: list[dict]) -> set[str]:
    return {spec["function"]["name"] for spec in specs}


def test_read_only_tool_specs_include_web_tools_by_default() -> None:
    assert {"web_search", "fetch_url"} <= _spec_names(read_only_tool_specs())


def test_read_only_tool_specs_exclude_web_tools_when_disabled() -> None:
    names = _spec_names(read_only_tool_specs(web_enabled=False))
    assert "web_search" not in names
    assert "fetch_url" not in names


def test_implement_tool_specs_include_web_tools_by_default() -> None:
    assert {"web_search", "fetch_url"} <= _spec_names(implement_tool_specs())


def test_implement_tool_specs_exclude_web_tools_when_disabled() -> None:
    names = _spec_names(implement_tool_specs(web_enabled=False))
    assert "web_search" not in names
    assert "fetch_url" not in names


@pytest.fixture
def sandbox(tmp_path: Path):
    (tmp_path / "src").mkdir()
    return build_sandbox(tmp_path, ["src"], ["src"], ())


def test_tool_runner_hides_web_tools_when_disabled(sandbox) -> None:
    runner = ToolRunner(sandbox, 20000, allow_write=False, web_enabled=False)
    assert "web_search" not in runner.available_names
    assert "fetch_url" not in runner.available_names
    outcome = runner.run("web_search", {"query": "x"})
    assert outcome.is_error


def test_tool_runner_web_search_dispatches_and_formats(monkeypatch, sandbox) -> None:
    monkeypatch.setattr(
        worker_tools,
        "web_search",
        lambda query, max_results: {
            "results": [{"title": "見出し", "url": "https://example.test", "snippet": "抜粋"}]
        },
    )
    runner = ToolRunner(sandbox, 20000, allow_write=False, web_enabled=True)
    outcome = runner.run("web_search", {"query": "何か"})
    assert not outcome.is_error
    assert "https://example.test" in outcome.text


def test_tool_runner_web_search_propagates_error(monkeypatch, sandbox) -> None:
    monkeypatch.setattr(worker_tools, "web_search", lambda query, max_results: {"error": "検索失敗"})
    runner = ToolRunner(sandbox, 20000, allow_write=False, web_enabled=True)
    outcome = runner.run("web_search", {"query": "x"})
    assert outcome.is_error
    assert "検索失敗" in outcome.text


def test_tool_runner_web_search_hits_limit(monkeypatch, sandbox) -> None:
    monkeypatch.setattr(worker_tools, "web_search", lambda query, max_results: {"results": []})
    runner = ToolRunner(sandbox, 20000, allow_write=False, web_enabled=True, max_web_searches=1)
    first = runner.run("web_search", {"query": "1回目"})
    assert not first.is_error
    second = runner.run("web_search", {"query": "2回目"})
    assert not second.is_error
    assert "上限" in second.text
    assert runner.web_search_count == 1


def test_tool_runner_fetch_url_hits_limit(monkeypatch, sandbox) -> None:
    monkeypatch.setattr(
        worker_tools, "fetch_url", lambda url, max_chars: {"text": "本文", "truncated": False}
    )
    runner = ToolRunner(sandbox, 20000, allow_write=False, web_enabled=True, max_web_fetches=1)
    first = runner.run("fetch_url", {"url": "https://example.test/1"})
    assert not first.is_error
    second = runner.run("fetch_url", {"url": "https://example.test/2"})
    assert "上限" in second.text
    assert runner.web_fetch_count == 1
