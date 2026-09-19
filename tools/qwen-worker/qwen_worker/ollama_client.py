"""Ollama ネイティブ /api/chat クライアント。

標準ライブラリだけで実装する（依存を mcp のみに保つため）。
stream は使わない。1 往復ごとに完全な応答を受け取ってツール呼び出しを処理する。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class OllamaError(RuntimeError):
    """Ollama への接続失敗、または HTTP エラー応答。"""


@dataclass
class ChatMetrics:
    """1 往復ぶんの計測値。

    取得できなかった値は None のままにする。0 や推測値で埋めない。
    """

    done_reason: str | None = None
    prompt_eval_count: int | None = None
    prompt_eval_cached_count: int | None = None
    eval_count: int | None = None
    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_duration_ns: int | None = None

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "ChatMetrics":
        def get_int(key: str) -> int | None:
            value = payload.get(key)
            return int(value) if isinstance(value, int) else None

        return cls(
            done_reason=payload.get("done_reason"),
            prompt_eval_count=get_int("prompt_eval_count"),
            prompt_eval_cached_count=get_int("prompt_eval_cached_count"),
            eval_count=get_int("eval_count"),
            total_duration_ns=get_int("total_duration"),
            load_duration_ns=get_int("load_duration"),
            prompt_eval_duration_ns=get_int("prompt_eval_duration"),
            eval_duration_ns=get_int("eval_duration"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "done_reason": self.done_reason,
            "prompt_eval_count": self.prompt_eval_count,
            "prompt_eval_cached_count": self.prompt_eval_cached_count,
            "eval_count": self.eval_count,
            "total_duration_ms": _ns_to_ms(self.total_duration_ns),
            "load_duration_ms": _ns_to_ms(self.load_duration_ns),
            "prompt_eval_duration_ms": _ns_to_ms(self.prompt_eval_duration_ns),
            "eval_duration_ms": _ns_to_ms(self.eval_duration_ns),
            "eval_tokens_per_sec": self.tokens_per_sec(),
        }

    def tokens_per_sec(self) -> float | None:
        if self.eval_count is None or not self.eval_duration_ns:
            return None
        return round(self.eval_count / (self.eval_duration_ns / 1e9), 2)


def _ns_to_ms(value: int | None) -> float | None:
    return None if value is None else round(value / 1e6, 1)


@dataclass
class ChatResult:
    content: str
    thinking: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metrics: ChatMetrics = field(default_factory=ChatMetrics)
    raw_message: dict[str, Any] = field(default_factory=dict)

    @property
    def hit_generation_limit(self) -> bool:
        """生成上限に達して打ち切られたか。done_reason == "length"。"""
        return self.metrics.done_reason == "length"


class OllamaChatClient:
    def __init__(self, base_url: str, model: str, read_timeout_sec: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.read_timeout_sec = read_timeout_sec

    def _post(self, path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise OllamaError(f"{url} が HTTP {exc.code} を返しました: {detail}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise OllamaError(f"{url} への接続に失敗しました: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError(f"{url} の応答が JSON ではありません: {exc}") from exc

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        think: bool,
        options: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        keep_alive: str | None = None,
        timeout: float | None = None,
    ) -> ChatResult:
        """/api/chat を 1 回呼ぶ。

        think は options の中ではなくトップレベルに置く（Ollama の API 仕様）。
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": think,
            "options": options,
        }
        if tools:
            body["tools"] = tools
        if keep_alive is not None:
            body["keep_alive"] = keep_alive

        payload = self._post("/api/chat", body, timeout or self.read_timeout_sec)
        message = payload.get("message") or {}
        return ChatResult(
            content=message.get("content") or "",
            thinking=message.get("thinking") or "",
            tool_calls=list(message.get("tool_calls") or []),
            metrics=ChatMetrics.from_response(payload),
            raw_message=message,
        )

    def version(self, timeout: float = 5.0) -> str | None:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/version", timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8")).get("version")
        except Exception:
            return None

    def running_models(self, timeout: float = 5.0) -> list[dict[str, Any]] | None:
        """/api/ps。取得できなければ None（0 や推測値で埋めない）。"""
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/ps", timeout=timeout) as resp:
                return list(json.loads(resp.read().decode("utf-8")).get("models") or [])
        except Exception:
            return None
