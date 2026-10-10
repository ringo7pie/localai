"""設定の読み込みと検証。

設定は ~/.config/qwen-worker/config.toml。ワーカーはこのファイルを書き換えない。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .tokens import DEFAULT_ASCII_CHARS_PER_TOKEN, DEFAULT_NON_ASCII_CHARS_PER_TOKEN

CONFIG_PATH = Path(
    os.environ.get("QWEN_WORKER_CONFIG", Path.home() / ".config" / "qwen-worker" / "config.toml")
)
STATE_DIR = Path(
    os.environ.get("QWEN_WORKER_STATE", Path.home() / ".local" / "state" / "qwen-worker")
)
TASKS_DIR = STATE_DIR / "tasks"
INFERENCE_LOCK_PATH = STATE_DIR / "inference.lock"
DEDUPE_DIR = STATE_DIR / "inflight"


class ConfigError(RuntimeError):
    """設定ファイルが読めない、または内容が不正。"""


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str
    model: str
    connect_timeout_sec: float
    read_timeout_sec: float
    structured_output: bool


@dataclass(frozen=True)
class Limits:
    job_deadline_sec: float
    max_rounds: int
    max_repair_retries: int
    lock_wait_sec: float
    max_tool_result_chars: int
    inline_diff_max_lines: int


@dataclass(frozen=True)
class Profile:
    name: str
    num_ctx: int
    num_predict: int
    think: bool
    input_budget_tokens: int
    enabled: bool
    disabled_reason: str = ""


@dataclass(frozen=True)
class WebSettings:
    """インターネットアクセスツール（web_search / fetch_url）の設定。"""

    enabled: bool
    max_searches_per_task: int
    max_fetches_per_task: int


@dataclass(frozen=True)
class SamplingSettings:
    """Ollama の options に渡すサンプリング値。名前は Ollama の対応名。"""

    temperature: float
    top_p: float
    top_k: int
    min_p: float
    presence_penalty: float
    repeat_penalty: float

    def as_options(self) -> dict[str, float | int]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "presence_penalty": self.presence_penalty,
            "repeat_penalty": self.repeat_penalty,
        }


@dataclass(frozen=True)
class ModelSamplingOverride:
    """特定モデル向けのサンプリング上書き。

    thinking / non_thinking は個別に省略できる（省略した側は
    [sampling.thinking] / [sampling.non_thinking] の既定にフォールバックする）。
    """

    thinking: SamplingSettings | None
    non_thinking: SamplingSettings | None


@dataclass(frozen=True)
class TokenEstimationSettings:
    """tokens.py の推定式に渡す、モデルごとの文字/トークン比。

    既定値は Qwen3.8 実測ベース（tokens.py 参照）。Gemma 4 など他モデルは
    未実測のため、config.toml に明示的な上書きが無い限りこの既定を使う。
    ずれる可能性があることは承知の上で使うこと（推測値を実測のように書かない）。
    """

    ascii_chars_per_token: float
    non_ascii_chars_per_token: float


@dataclass(frozen=True)
class WorkerConfig:
    ollama: OllamaSettings
    limits: Limits
    allowed_roots: tuple[Path, ...]
    denied_globs: tuple[str, ...]
    profiles: dict[str, Profile]
    sampling_thinking: SamplingSettings
    sampling_non_thinking: SamplingSettings
    model_sampling: dict[str, ModelSamplingOverride]
    token_estimation_default: TokenEstimationSettings
    token_estimation_overrides: dict[str, TokenEstimationSettings]
    web: WebSettings
    source_path: Path

    def profile(self, name: str) -> Profile:
        try:
            selected = self.profiles[name]
        except KeyError:
            known = ", ".join(sorted(self.profiles))
            raise ConfigError(f"未知のプロファイル {name!r}。使えるのは: {known}") from None
        if not selected.enabled:
            reason = selected.disabled_reason or "無効化されている"
            raise ConfigError(f"プロファイル {name!r} は使用不可: {reason}")
        return selected

    def sampling_for(self, think: bool, model: str | None = None) -> SamplingSettings:
        """モデルに応じたサンプリング値。

        model 未指定、または model 向けの上書きが無ければ [sampling.thinking] /
        [sampling.non_thinking] の既定（= 現行の Qwen 向け値）を返す。既存の
        呼び出し（model 省略）の挙動はこれまでと変わらない。
        """
        if model is not None:
            override = self.model_sampling.get(model)
            if override is not None:
                selected = override.thinking if think else override.non_thinking
                if selected is not None:
                    return selected
        return self.sampling_thinking if think else self.sampling_non_thinking

    def token_estimation_for(self, model: str) -> TokenEstimationSettings:
        """モデルに応じたトークン推定係数。上書きが無ければ既定（Qwen3.8 実測ベース）。"""
        return self.token_estimation_overrides.get(model, self.token_estimation_default)


def _require(table: dict, key: str, where: str):
    if key not in table:
        raise ConfigError(f"{where} に {key!r} がありません")
    return table[key]


def load_config(path: Path = CONFIG_PATH) -> WorkerConfig:
    if not path.is_file():
        raise ConfigError(f"設定ファイルがありません: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} の TOML が壊れています: {exc}") from exc

    ollama_table = _require(raw, "ollama", str(path))
    ollama = OllamaSettings(
        base_url=str(_require(ollama_table, "base_url", "[ollama]")).rstrip("/"),
        model=str(_require(ollama_table, "model", "[ollama]")),
        connect_timeout_sec=float(ollama_table.get("connect_timeout_sec", 10)),
        read_timeout_sec=float(ollama_table.get("read_timeout_sec", 900)),
        structured_output=bool(ollama_table.get("structured_output", False)),
    )

    limits_table = raw.get("limits", {})
    limits = Limits(
        job_deadline_sec=float(limits_table.get("job_deadline_sec", 1800)),
        max_rounds=int(limits_table.get("max_rounds", 12)),
        max_repair_retries=int(limits_table.get("max_repair_retries", 2)),
        lock_wait_sec=float(limits_table.get("lock_wait_sec", 30)),
        max_tool_result_chars=int(limits_table.get("max_tool_result_chars", 20000)),
        inline_diff_max_lines=int(limits_table.get("inline_diff_max_lines", 400)),
    )
    if ollama.read_timeout_sec >= limits.job_deadline_sec:
        raise ConfigError(
            "ollama.read_timeout_sec はジョブ期限 limits.job_deadline_sec より短くしてください "
            f"({ollama.read_timeout_sec} >= {limits.job_deadline_sec})"
        )

    roots_raw = _require(raw, "allowed_roots", str(path))
    if not isinstance(roots_raw, list) or not roots_raw:
        raise ConfigError("allowed_roots は空でない文字列の配列にしてください")
    allowed_roots: list[Path] = []
    for entry in roots_raw:
        resolved = Path(str(entry)).expanduser().resolve()
        if not resolved.is_dir():
            raise ConfigError(f"allowed_roots のパスがディレクトリではありません: {resolved}")
        allowed_roots.append(resolved)

    denied_globs = tuple(str(g) for g in raw.get("denied_globs", []))

    profiles_table = _require(raw, "profiles", str(path))
    profiles: dict[str, Profile] = {}
    for profile_name, body in profiles_table.items():
        profiles[profile_name] = Profile(
            name=profile_name,
            num_ctx=int(_require(body, "num_ctx", f"[profiles.{profile_name}]")),
            num_predict=int(_require(body, "num_predict", f"[profiles.{profile_name}]")),
            think=bool(_require(body, "think", f"[profiles.{profile_name}]")),
            input_budget_tokens=int(body.get("input_budget_tokens", 0)),
            enabled=bool(body.get("enabled", True)),
            disabled_reason=str(body.get("disabled_reason", "")),
        )
    if "standard" not in profiles:
        raise ConfigError("profiles.standard は必須です")

    sampling_table = _require(raw, "sampling", str(path))

    def parse_sampling(body: dict) -> SamplingSettings:
        return SamplingSettings(
            temperature=float(body["temperature"]),
            top_p=float(body["top_p"]),
            top_k=int(body["top_k"]),
            min_p=float(body["min_p"]),
            presence_penalty=float(body["presence_penalty"]),
            repeat_penalty=float(body["repeat_penalty"]),
        )

    def build_sampling(key: str) -> SamplingSettings:
        body = _require(sampling_table, key, "[sampling]")
        return parse_sampling(body)

    # モデルごとのサンプリング上書き。キーは Ollama のモデル名（qwen_research /
    # qwen_implement の model 引数と同じ文字列）。thinking / non_thinking を
    # 個別に省略でき、省略した側は上の [sampling.thinking] / [sampling.non_thinking]
    # （= 既存の Qwen 向け既定）にフォールバックする。未設定のモデルも同様。
    # これにより既存の Qwen の挙動（model 省略時）は一切変わらない。
    model_sampling_table = raw.get("model_sampling", {})
    model_sampling: dict[str, ModelSamplingOverride] = {}
    for model_name, body in model_sampling_table.items():
        if not isinstance(body, dict):
            raise ConfigError(f"[model_sampling.{model_name!r}] はテーブルにしてください")
        thinking_body = body.get("thinking")
        non_thinking_body = body.get("non_thinking")
        model_sampling[model_name] = ModelSamplingOverride(
            thinking=parse_sampling(thinking_body) if thinking_body else None,
            non_thinking=parse_sampling(non_thinking_body) if non_thinking_body else None,
        )

    # トークン推定係数（tokens.py）。既定は Qwen3.8 実測ベースのまま。
    # モデルごとの上書きが無ければ全モデルがこの既定を使う（= 既存の挙動を維持）。
    tokens_table = raw.get("tokens", {})
    token_estimation_default = TokenEstimationSettings(
        ascii_chars_per_token=float(
            tokens_table.get("ascii_chars_per_token", DEFAULT_ASCII_CHARS_PER_TOKEN)
        ),
        non_ascii_chars_per_token=float(
            tokens_table.get("non_ascii_chars_per_token", DEFAULT_NON_ASCII_CHARS_PER_TOKEN)
        ),
    )
    token_overrides_table = tokens_table.get("model_overrides", {})
    token_estimation_overrides: dict[str, TokenEstimationSettings] = {}
    for model_name, body in token_overrides_table.items():
        where = f"[tokens.model_overrides.{model_name}]"
        if not isinstance(body, dict):
            raise ConfigError(f"{where} はテーブルにしてください")
        token_estimation_overrides[model_name] = TokenEstimationSettings(
            ascii_chars_per_token=float(_require(body, "ascii_chars_per_token", where)),
            non_ascii_chars_per_token=float(_require(body, "non_ascii_chars_per_token", where)),
        )

    web_table = raw.get("web", {})
    web = WebSettings(
        enabled=bool(web_table.get("enabled", True)),
        max_searches_per_task=int(web_table.get("max_searches_per_task", 10)),
        max_fetches_per_task=int(web_table.get("max_fetches_per_task", 10)),
    )

    return WorkerConfig(
        ollama=ollama,
        limits=limits,
        allowed_roots=tuple(allowed_roots),
        denied_globs=denied_globs,
        profiles=profiles,
        sampling_thinking=build_sampling("thinking"),
        sampling_non_thinking=build_sampling("non_thinking"),
        model_sampling=model_sampling,
        token_estimation_default=token_estimation_default,
        token_estimation_overrides=token_estimation_overrides,
        web=web,
        source_path=path,
    )
