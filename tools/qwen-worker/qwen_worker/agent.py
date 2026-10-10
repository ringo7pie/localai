"""Qwen のツール呼び出しループ。

Ollama の tool_calls と、ワーカー側でのツール実行結果を往復させる。
1 回質問して答えをもらうだけではなく、Qwen 自身が検索・読み取り・編集を
要求し、その結果を見てから次の手を決める。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Limits, Profile, SamplingSettings, TokenEstimationSettings
from .ollama_client import ChatResult, OllamaChatClient, OllamaError
from .tokens import (
    DEFAULT_ASCII_CHARS_PER_TOKEN,
    DEFAULT_NON_ASCII_CHARS_PER_TOKEN,
    estimate_messages_tokens,
    estimate_tools_tokens,
)
from .worker_tools import TERMINAL_TOOLS, ToolRunner

logger = logging.getLogger("qwen_worker.agent")


class BudgetExceeded(RuntimeError):
    """入力が文脈予算を超えた。黙って切り捨てず、呼び出し側へ返す。"""


class JobDeadlineExceeded(RuntimeError):
    """ジョブ全体の期限を超えた。"""


@dataclass
class RoundRecord:
    index: int
    tool_calls: list[str]
    metrics: dict[str, Any]
    had_error: bool = False


@dataclass
class AgentResult:
    status: str  # completed / needs_review / failed
    final_payload: dict[str, Any] | None
    rounds: list[RoundRecord] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    estimated_input_tokens: int = 0
    peak_prompt_eval_count: int | None = None
    hit_round_limit: bool = False
    hit_generation_limit: bool = False

    def total_eval_tokens(self) -> int:
        return sum(r.metrics.get("eval_count") or 0 for r in self.rounds)


class QwenAgent:
    def __init__(
        self,
        client: OllamaChatClient,
        tool_runner: ToolRunner,
        tool_specs: list[dict[str, Any]],
        profile: Profile,
        sampling: SamplingSettings,
        limits: Limits,
        token_estimation: TokenEstimationSettings | None = None,
    ) -> None:
        self.client = client
        self.tool_runner = tool_runner
        self.tool_specs = tool_specs
        self.profile = profile
        self.sampling = sampling
        self.limits = limits
        # モデルごとの文字/トークン比。呼び出し側（server.py）が
        # WorkerConfig.token_estimation_for(model) で解決して渡す。
        # 省略時は tokens.py の既定（Qwen3.8 実測ベース）と同じ値になる。
        self.token_estimation = token_estimation or TokenEstimationSettings(
            ascii_chars_per_token=DEFAULT_ASCII_CHARS_PER_TOKEN,
            non_ascii_chars_per_token=DEFAULT_NON_ASCII_CHARS_PER_TOKEN,
        )

    def _options(self) -> dict[str, Any]:
        options = self.sampling.as_options()
        options["num_ctx"] = self.profile.num_ctx
        options["num_predict"] = self.profile.num_predict
        return options

    def _estimate_messages(self, messages: list[dict[str, Any]]) -> int:
        return estimate_messages_tokens(
            messages,
            ascii_chars_per_token=self.token_estimation.ascii_chars_per_token,
            non_ascii_chars_per_token=self.token_estimation.non_ascii_chars_per_token,
        )

    def _estimate_tools(self) -> int:
        return estimate_tools_tokens(
            self.tool_specs,
            ascii_chars_per_token=self.token_estimation.ascii_chars_per_token,
            non_ascii_chars_per_token=self.token_estimation.non_ascii_chars_per_token,
        )

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        deadline_monotonic: float,
    ) -> AgentResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        estimated_input = self._estimate_messages(messages) + self._estimate_tools()
        if self.profile.input_budget_tokens and estimated_input > self.profile.input_budget_tokens:
            raise BudgetExceeded(
                f"入力の推定トークン数 {estimated_input} が "
                f"プロファイル {self.profile.name} の入力予算 {self.profile.input_budget_tokens} を超えています。"
                "渡す情報を絞るか、親でタスクを分割してください。入力は勝手に切り捨てません。"
            )

        result = AgentResult(status="failed", final_payload=None, estimated_input_tokens=estimated_input)
        consecutive_errors = 0
        tools_tokens = self._estimate_tools()

        for round_index in range(1, self.limits.max_rounds + 1):
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                result.status = "failed"
                result.notes.append(f"ジョブ期限に達しました（ラウンド {round_index} の開始前）")
                return result

            # ツール結果が積もって予算を超えると、Ollama が入力の先頭を黙って
            # 切り捨てる（実測: num_ctx=65536 でも取り込みは 32770 トークンで頭打ちになり、
            # 先頭に置いたマーカーが消えた。done_reason は stop で警告も出ない）。
            # 黙って切り捨てさせず、ここで止めて親へ返す。
            conversation_tokens = self._estimate_messages(messages) + tools_tokens
            result.estimated_input_tokens = max(result.estimated_input_tokens, conversation_tokens)
            if self.profile.input_budget_tokens and conversation_tokens > self.profile.input_budget_tokens:
                result.status = "needs_review"
                result.notes.append(
                    f"ラウンド {round_index} の開始時点で会話の推定トークン数 {conversation_tokens} が "
                    f"入力予算 {self.profile.input_budget_tokens} を超えました。"
                    "Ollama に黙って切り捨てさせないため、ここで打ち切ります。"
                    "タスクを分割するか、渡す範囲を絞ってください。"
                )
                result.messages = messages
                return result

            try:
                # response_format（Ollama の format）はここでは渡さない。ツール呼び出し
                # ループの最中はモデルに report_findings / report_changes を呼ばせたい。
                # format を掛けると JSON 直接生成に寄って壊れる可能性があるため
                # （config.toml の structured_output=true でも、ここでは常に未使用）。
                chat_result = self.client.chat(
                    messages,
                    think=self.profile.think,
                    options=self._options(),
                    tools=self.tool_specs,
                    keep_alive="5m",
                    timeout=min(self.client.read_timeout_sec, remaining),
                )
            except OllamaError as exc:
                result.status = "failed"
                result.notes.append(f"Ollama 呼び出しに失敗しました: {exc}")
                return result

            record = RoundRecord(
                index=round_index,
                tool_calls=[_call_name(c) for c in chat_result.tool_calls],
                metrics=chat_result.metrics.as_dict(),
            )
            result.rounds.append(record)
            if chat_result.metrics.prompt_eval_count is not None:
                result.peak_prompt_eval_count = max(
                    result.peak_prompt_eval_count or 0, chat_result.metrics.prompt_eval_count
                )

            # モデルの発話をそのまま履歴へ戻す（thinking と tool_calls を含む）。
            messages.append(_assistant_message(chat_result))

            if chat_result.hit_generation_limit:
                result.hit_generation_limit = True
                result.notes.append(
                    f"ラウンド {round_index} で生成上限 num_predict={self.profile.num_predict} に達しました"
                    "（done_reason=length）。未完の出力を成功扱いにはしません。"
                )

            if not chat_result.tool_calls:
                # ツールを呼ばずに終わった。終了ツールを使っていないので未完とみなす。
                result.status = "needs_review"
                result.final_payload = {
                    "summary": chat_result.content.strip(),
                    "note": "モデルが終了ツールを呼ばずに応答を終えました。根拠の裏付けがありません。",
                }
                result.messages = messages
                return result

            terminal_payload = None
            for call in chat_result.tool_calls:
                name = _call_name(call)
                arguments = _call_arguments(call)

                if name in TERMINAL_TOOLS:
                    terminal_payload = arguments
                    continue

                outcome = self.tool_runner.run(name, arguments)
                if outcome.is_error:
                    record.had_error = True
                messages.append(
                    {"role": "tool", "tool_name": name, "content": outcome.text}
                )

            if terminal_payload is not None:
                result.status = "completed"
                result.final_payload = terminal_payload
                result.messages = messages
                if result.hit_generation_limit:
                    result.status = "needs_review"
                return result

            if record.had_error:
                consecutive_errors += 1
                if consecutive_errors > self.limits.max_repair_retries:
                    result.status = "needs_review"
                    result.notes.append(
                        f"ツール呼び出しの失敗が {consecutive_errors} 回続きました"
                        f"（上限 {self.limits.max_repair_retries}）。打ち切ります。"
                    )
                    result.messages = messages
                    return result
            else:
                consecutive_errors = 0

        result.hit_round_limit = True
        result.status = "needs_review"
        result.notes.append(
            f"ラウンド上限 {self.limits.max_rounds} に達しました。作業は完了していません。"
        )
        result.messages = messages
        return result


def _assistant_message(chat_result: ChatResult) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": chat_result.content}
    if chat_result.thinking:
        message["thinking"] = chat_result.thinking
    if chat_result.tool_calls:
        message["tool_calls"] = chat_result.tool_calls
    return message


def _call_name(call: dict[str, Any]) -> str:
    return str((call.get("function") or {}).get("name") or "<unnamed>")


def _call_arguments(call: dict[str, Any]) -> dict[str, Any]:
    arguments = (call.get("function") or {}).get("arguments")
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
