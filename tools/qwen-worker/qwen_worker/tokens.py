"""トークン数の推定。

Ollama 0.34.2 には /api/tokenize が無い（実測: 404）。
qwen35 のトークナイザーをローカルに持っていないため、厳密計測はできない。
ここで返すのは推定値であり、必ず estimated=True として扱う。
実測値は応答の prompt_eval_count を使う。

文字/トークン比は Qwen3.8 実測ベース（下の既定値）。他モデル（Gemma 4 など）の
トークナイザーは Qwen と別物で、この比率は未実測。config.toml の
[tokens] / [tokens.model_overrides."<モデル名>"] で上書きできる口を用意してあるが、
推測で値を入れると実測のように見えてしまうため、実測していないモデルはここにも
config.toml.example にも値を書かない。上書きが無いモデルは黙ってこの既定値を使う
（＝見積りがずれる可能性がある）。
"""

from __future__ import annotations

import json
from typing import Any

# ASCII 側はおよそ 3.6 文字/トークン、日本語など非 ASCII はおよそ 1.1 文字/トークン。
# 余裕を大きく取るため、どちらも実際より小さめの文字数で割って多めに見積もる。
DEFAULT_ASCII_CHARS_PER_TOKEN = 3.2
DEFAULT_NON_ASCII_CHARS_PER_TOKEN = 1.0


def estimate_tokens(
    text: str,
    *,
    ascii_chars_per_token: float = DEFAULT_ASCII_CHARS_PER_TOKEN,
    non_ascii_chars_per_token: float = DEFAULT_NON_ASCII_CHARS_PER_TOKEN,
) -> int:
    """テキストの推定トークン数。厳密ではない。多めに出る方向に寄せてある。

    ascii_chars_per_token / non_ascii_chars_per_token は呼び出し側（agent.py）が
    WorkerConfig.token_estimation_for(model) から解決して渡す。既定は Qwen3.8 実測値。
    """
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return int(
        ascii_chars / ascii_chars_per_token + non_ascii_chars / non_ascii_chars_per_token
    ) + 1


def estimate_messages_tokens(
    messages: list[dict[str, Any]],
    *,
    ascii_chars_per_token: float = DEFAULT_ASCII_CHARS_PER_TOKEN,
    non_ascii_chars_per_token: float = DEFAULT_NON_ASCII_CHARS_PER_TOKEN,
) -> int:
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
                total += estimate_tokens(
                    value,
                    ascii_chars_per_token=ascii_chars_per_token,
                    non_ascii_chars_per_token=non_ascii_chars_per_token,
                )
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total += estimate_tokens(
                json.dumps(tool_calls, ensure_ascii=False),
                ascii_chars_per_token=ascii_chars_per_token,
                non_ascii_chars_per_token=non_ascii_chars_per_token,
            )
    return total


def estimate_tools_tokens(
    tools: list[dict[str, Any]],
    *,
    ascii_chars_per_token: float = DEFAULT_ASCII_CHARS_PER_TOKEN,
    non_ascii_chars_per_token: float = DEFAULT_NON_ASCII_CHARS_PER_TOKEN,
) -> int:
    """ツール定義ぶんの推定トークン数。"""
    return estimate_tokens(
        json.dumps(tools, ensure_ascii=False),
        ascii_chars_per_token=ascii_chars_per_token,
        non_ascii_chars_per_token=non_ascii_chars_per_token,
    )
