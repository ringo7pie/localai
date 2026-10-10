"""Ollama（/api/chat、NDJSON のストリーム）と Strata（/v1/chat/completions、SSE）を同じ形の結果に揃えて叩く。

作りの手本:
- Ollama: tools/qwen-worker/qwen_worker/ollama_client.py の chat()（こちらは stream にして ttft と stall を測る）
- Strata: tools/strata/scripts/bench_api.py の stream_chat()（SSE の読み取り）

打ち切り:
- stall: 何も届かないまま stall_s 秒たったら（ソケットの読み取りの timeout）。Strata は prefill 中も
  コメント行（": ping"）を送るので、読み込み中は stall にならない。
- timeout: 要求の開始から deadline_s 秒を過ぎたら、次の行が届いた時点で接続を切る。
接続を切ると、Ollama も Strata も生成を止める。

終わり方 status: ok / length（上限）/ eos_in_thinking（finish が stop で本文が空・思考あり）/ timeout / stall / error。

思考のトークン数はどちらの API も直接は出さない（Strata の SSE の usage には reasoning_tokens が無い。
vendor/Strata/serve/server.py の openai_chunks）。そこで「出力トークン × 思考の文字数 ÷ (思考 + 本文の文字数)」で
推定し、thinking_tokens_source に推定であることを書く。
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

THINKING_ESTIMATE_NOTE = "estimate: 出力トークン × 思考の文字数 ÷ (思考 + 本文の文字数)"


def estimate_thinking_tokens(completion_tokens: int | None, thinking_chars: int, content_chars: int) -> int | None:
    if completion_tokens is None:
        return None
    if thinking_chars == 0:
        return 0
    total = thinking_chars + content_chars
    return round(completion_tokens * thinking_chars / total) if total else None


def _empty_result() -> dict[str, Any]:
    return {
        "content": "", "thinking": "", "finish": None, "status": None, "error": None,
        "prompt_tokens": None, "completion_tokens": None, "ttft_s": None, "t_first_content_s": None,
        "wall_s": None, "load_s": None, "server_decode_tok_s": None, "server_prefill_tok_s": None,
        "server_timings": None,
    }


def _finalize(result: dict[str, Any], started: float, first_any: float | None, first_content: float | None,
              last_delta: float | None, ended: float, content: list[str], thinking: list[str]) -> dict[str, Any]:
    result["content"] = "".join(content)
    result["thinking"] = "".join(thinking)
    result["wall_s"] = round(ended - started, 3)
    result["ttft_s"] = round(first_any - started, 3) if first_any is not None else None
    result["t_first_content_s"] = round(first_content - started, 3) if first_content is not None else None
    completion = result.get("completion_tokens")
    # 壁時計での生成速度（最初の差分から最後の差分まで）。サーバーの値の検算用
    if completion and first_any is not None and last_delta is not None and last_delta > first_any and completion > 1:
        result["wall_decode_tok_s"] = round((completion - 1) / (last_delta - first_any), 2)
    else:
        result["wall_decode_tok_s"] = None
    result["thinking_chars"] = len(result["thinking"])
    result["content_chars"] = len(result["content"])
    result["thinking_tokens_est"] = estimate_thinking_tokens(completion, result["thinking_chars"],
                                                             result["content_chars"])
    result["thinking_tokens_source"] = THINKING_ESTIMATE_NOTE
    if result["status"] is None:
        if result["finish"] == "length":
            result["status"] = "length"
        elif result["finish"] == "stop" and not result["content"].strip() and result["thinking"].strip():
            # 思考の途中で停止トークンが出て、本文が空のまま終わった（Ollama も Strata も同じ扱い。error ではない）
            result["status"] = "eos_in_thinking"
        else:
            result["status"] = "ok"
    return result


def _open(url: str, payload: dict[str, Any], headers: dict[str, str], stall_s: float):
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
    return urllib.request.urlopen(request, timeout=stall_s)


def _stream(url: str, payload: dict[str, Any], headers: dict[str, str], *, stall_s: float, deadline_s: float,
            handle_line: Callable[[str, dict[str, Any], dict[str, Any]], bool],
            clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """1 行ずつ handle_line(line, result, state) に渡す共通の読み取り。handle_line が True を返したら終わる。"""

    result = _empty_result()
    state: dict[str, Any] = {"content": [], "thinking": [], "first_any": None, "first_content": None,
                             "last_delta": None, "clock": clock, "chunks": 0}
    started = clock()
    state["started"] = started
    try:
        with _open(url, payload, headers, stall_s) as response:
            for raw in response:
                if clock() - started > deadline_s:
                    result["status"] = "timeout"
                    result["error"] = f"要求の時間上限 {deadline_s:.0f} 秒を超えた"
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if handle_line(line, result, state):
                    break
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        result["status"] = "error"
        result["error"] = f"HTTP {exc.code}: {detail}"
    except (socket.timeout, TimeoutError):
        result["status"] = "stall"
        result["error"] = f"{stall_s:.0f} 秒のあいだ何も届かなかった"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            result["status"] = "stall"
            result["error"] = f"{stall_s:.0f} 秒のあいだ応答が無かった（接続時）"
        else:
            result["status"] = "error"
            result["error"] = f"接続に失敗: {exc.reason}"
    except (ConnectionError, OSError) as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    except ValueError as exc:  # 行が JSON として読めない（サーバーの異常）
        result["status"] = "error"
        result["error"] = f"応答の行を読めない: {exc}"[:800]
    # 文字の入った差分の数（ほぼ 1 トークンに 1 つ）。時間切れ・stall でサーバーの数が無いときの目安
    result["delta_chunks"] = state["chunks"]
    return _finalize(result, started, state["first_any"], state["first_content"], state["last_delta"], clock(),
                     state["content"], state["thinking"])


def _note_delta(state: dict[str, Any], *, is_content: bool) -> None:
    now = state["clock"]()
    state["chunks"] += 1
    if state["first_any"] is None:
        state["first_any"] = now
    if is_content and state["first_content"] is None:
        state["first_content"] = now
    state["last_delta"] = now


def chat_ollama(base_url: str, payload: dict[str, Any], *, stall_s: float, deadline_s: float,
                clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Ollama の /api/chat を stream で呼ぶ。payload には stream:true を入れておく。"""

    def handle(line: str, result: dict[str, Any], state: dict[str, Any]) -> bool:
        chunk = json.loads(line)
        if chunk.get("error"):
            result["status"] = "error"
            result["error"] = str(chunk["error"])[:800]
            return True
        message = chunk.get("message") or {}
        thinking_part = message.get("thinking") or ""
        content_part = message.get("content") or ""
        if thinking_part:
            state["thinking"].append(thinking_part)
            _note_delta(state, is_content=False)
        if content_part:
            state["content"].append(content_part)
            _note_delta(state, is_content=True)
        if chunk.get("done"):
            result["finish"] = chunk.get("done_reason")
            result["prompt_tokens"] = chunk.get("prompt_eval_count")
            result["completion_tokens"] = chunk.get("eval_count")
            load_ns = chunk.get("load_duration")
            result["load_s"] = round(load_ns / 1e9, 3) if isinstance(load_ns, int) else None
            eval_ns, eval_count = chunk.get("eval_duration"), chunk.get("eval_count")
            if isinstance(eval_ns, int) and eval_ns > 0 and isinstance(eval_count, int):
                result["server_decode_tok_s"] = round(eval_count / (eval_ns / 1e9), 2)
            prompt_ns, prompt_count = chunk.get("prompt_eval_duration"), chunk.get("prompt_eval_count")
            if isinstance(prompt_ns, int) and prompt_ns > 0 and isinstance(prompt_count, int):
                result["server_prefill_tok_s"] = round(prompt_count / (prompt_ns / 1e9), 2)
            result["server_timings"] = {key: chunk.get(key) for key in (
                "total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count",
                "eval_duration")}
            return True
        return False

    return _stream(base_url.rstrip("/") + "/api/chat", payload, {}, stall_s=stall_s, deadline_s=deadline_s,
                   handle_line=handle, clock=clock)


def chat_strata(base_url: str, payload: dict[str, Any], *, stall_s: float, deadline_s: float, api_key: str = "",
                clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Strata の /v1/chat/completions を SSE で呼ぶ。payload には stream:true を入れておく。"""

    def handle(line: str, result: dict[str, Any], state: dict[str, Any]) -> bool:
        if not line.startswith("data:"):
            return False  # ": ping" などのコメント行（届いたこと自体が stall の判定を延ばす）
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            return True
        chunk = json.loads(data)
        if chunk.get("error"):
            result["status"] = "error"
            result["error"] = json.dumps(chunk["error"], ensure_ascii=False)[:800]
            return True
        if chunk.get("usage"):
            usage = chunk["usage"]
            result["prompt_tokens"] = usage.get("prompt_tokens")
            result["completion_tokens"] = usage.get("completion_tokens")
            details = usage.get("completion_tokens_details") or {}
            if isinstance(details.get("reasoning_tokens"), int):
                result["server_reasoning_tokens"] = details["reasoning_tokens"]
        if chunk.get("timings"):
            timings = chunk["timings"]
            result["server_timings"] = timings
            result["server_decode_tok_s"] = timings.get("predicted_per_second")
            result["server_prefill_tok_s"] = timings.get("prompt_per_second")
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                state["thinking"].append(delta["reasoning_content"])
                _note_delta(state, is_content=False)
            if delta.get("content"):
                state["content"].append(delta["content"])
                _note_delta(state, is_content=True)
            if choice.get("finish_reason"):
                result["finish"] = choice["finish_reason"]
        return False

    headers = {"Authorization": f"Bearer {api_key or 'none'}"}
    return _stream(base_url.rstrip("/") + "/chat/completions", payload, headers, stall_s=stall_s,
                   deadline_s=deadline_s, handle_line=handle, clock=clock)


def get_json(url: str, timeout: float = 10.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
