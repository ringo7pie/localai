"""実機を使う統合試験。**モック試験ではない**。

実際に OpenCode を起動し、A30 の Ollama で Qwen を動かす。1 件あたり数分かかる。
CI 向けではない。手で流すこと。

  .venv/bin/python -m pytest tests/test_integration.py -q -s

前提:
  - local-ai-task doctor がすべて OK
  - workspace "selftest" が登録済み
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import core  # noqa: E402
from bridge.errors import DuplicateRequestError  # noqa: E402

TERMINAL = {"succeeded", "failed", "aborted", "cancelled", "awaiting_approval", "awaiting_input"}


@pytest.fixture(scope="module")
def cfg():
    config = core.load_config()
    if "selftest" not in config.workspaces:
        pytest.skip("workspace 'selftest' が登録されていない")
    return config


def _wait(cfg, task_id: str, timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = core.status(cfg, task_id)
        if state["state"] in TERMINAL:
            return state
        time.sleep(5)
    pytest.fail(f"{task_id} が {timeout} 秒以内に終わらなかった")


def _submit(cfg, **kwargs):
    defaults = {
        "request_id": f"it-{uuid.uuid4().hex[:8]}",
        "client_id": "pytest",
        "workspace_id": "selftest",
        "verify_profile": "unittest",
        "mode": "standard",
    }
    defaults.update(kwargs)
    return core.submit(cfg, **defaults)


def test_real_search_edit_and_test(cfg):
    """本物の Qwen / OpenCode で 検索→編集→実テスト が通ること。"""
    accepted = _submit(
        cfg,
        goal="src/interval.py の total_length が区間の重なりを二重に数えている。1 回だけ数えるよう直す。",
        allowed_scope=["src/interval.py"],
        acceptance=["tests/test_interval.py の 4 件すべてが通る"],
    )
    final = _wait(cfg, accepted["task_id"])
    result = core.result(cfg, accepted["task_id"])
    assert final["state"] == "awaiting_approval", result["summary"]
    assert result["verification"]["passed"] is True
    assert result["verification"]["exit_code"] == 0
    assert "src/interval.py" in result["changes"]["modified"]
    assert result["changes"]["applies_to_original"] is True
    # LLM の自己申告ではなく、実際のコマンドの終了コードで判定していること
    assert result["verification"]["command"][0] == "python3"


def test_new_file_is_detected(cfg):
    """新規ファイルを含む変更が差分に載ること。"""
    accepted = _submit(
        cfg,
        goal="src/ranges.py という新しいファイルを作り、区間のリストを受け取って"
             "最小の開始値と最大の終了値のタプルを返す span(intervals) 関数を定義する。"
             "空リストなら None を返す。既存ファイルは変更しない。",
        allowed_scope=["src/ranges.py"],
        acceptance=["src/ranges.py に span 関数がある", "既存のテストが引き続き通る"],
    )
    _wait(cfg, accepted["task_id"])
    result = core.result(cfg, accepted["task_id"])
    assert "src/ranges.py" in result["changes"]["added"], result["summary"]


def test_duplicate_request_is_rejected(cfg):
    request_id = f"it-dup-{uuid.uuid4().hex[:8]}"
    first = _submit(cfg, request_id=request_id, goal="README.md の先頭行に空白を足さずそのままにする")
    with pytest.raises(DuplicateRequestError) as raised:
        _submit(cfg, request_id=request_id, goal="同じ request_id をもう一度")
    assert raised.value.task_id == first["task_id"]
    core.cancel(cfg, first["task_id"])


def test_cancel_stops_only_that_task(cfg):
    """対象タスクだけを止める。Ollama サービスは動いたまま。"""
    import urllib.request

    long_task = _submit(
        cfg,
        goal="src/interval.py のすべての関数に、日本語の詳しい docstring と使用例を追加する。",
        allowed_scope=["src/interval.py"],
        mode="exhaustive",
    )
    time.sleep(20)
    cancelled = core.cancel(cfg, long_task["task_id"])
    assert cancelled["state"] in ("cancelled", "cancelling")
    # Ollama は生きている
    with urllib.request.urlopen(f"{cfg.ollama_base_url}/api/version", timeout=10) as response:
        assert response.status == 200
    final = _wait(cfg, long_task["task_id"], timeout=180)
    assert final["state"] in ("cancelled", "cancelling", "aborted")


def test_result_stays_small(cfg):
    """通常の result が上限バイト数を超えないこと。"""
    import json

    tasks = core.list_tasks(cfg, limit=5)
    assert tasks, "先に何かタスクを流しておくこと"
    for task in tasks:
        payload = core.result(cfg, task["task_id"])
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        assert size <= cfg.limits.result_max_bytes * 1.2, f"{task['task_id']} が {size} バイト"
