"""トークン数の推定。

Ollama 0.34.2 には /api/tokenize が無い（実測: 404）。
qwen35 のトークナイザーをローカルに持っていないため、厳密計測はできない。
ここで返すのは推定値であり、必ず estimated=True として扱う。
実測値は応答の prompt_eval_count を使う。
"""

from __future__ import annotations

import json
from typing import Any

# ASCII 側はおよそ 3.6 文字/トークン、日本語など非 ASCII はおよそ 1.1 文字/トークン。
# 余裕を大きく取るため、どちらも実際より小さめの文字数で割って多めに見積もる。
_ASCII_CHARS_PER_TOKEN = 3.2
_NON_ASCII_CHARS_PER_TOKEN = 1.0


def estimate_tokens(text: str) -> int:
    """テキストの推定トークン数。厳密ではない。多めに出る方向に寄せてある。"""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return int(
        ascii_chars / _ASCII_CHARS_PER_TOKEN + non_ascii_chars / _NON_ASCII_CHARS_PER_TOKEN
    ) + 1


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """会話全体の推定トークン数。

    チャットテンプレートの制御トークンぶんとして 1 メッセージあたり 8 トークンを足す。
    テンプレート込みの厳密計測ではない。
    """
    total = 0
    for message in messages:
        total += 8
        for key in ("content", "thinking", "tool_name", "role"):
            value = message.get(key)
            if isinstance(value, str):
                total += estimate_tokens(value)
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
    return total


def estimate_tools_tokens(tools: list[dict[str, Any]]) -> int:
    """ツール定義ぶんの推定トークン数。"""
    return estimate_tokens(json.dumps(tools, ensure_ascii=False))
