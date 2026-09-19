"""設定の読み込みと検証。

設定は ~/.config/qwen-worker/config.toml。ワーカーはこのファイルを書き換えない。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

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
class WorkerConfig:
    ollama: OllamaSettings
    limits: Limits
    allowed_roots: tuple[Path, ...]
    denied_globs: tuple[str, ...]
    profiles: dict[str, Profile]
    sampling_thinking: SamplingSettings
    sampling_non_thinking: SamplingSettings
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

    def sampling_for(self, think: bool) -> SamplingSettings:
        return self.sampling_thinking if think else self.sampling_non_thinking


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

    def build_sampling(key: str) -> SamplingSettings:
        body = _require(sampling_table, key, "[sampling]")
        return SamplingSettings(
            temperature=float(body["temperature"]),
            top_p=float(body["top_p"]),
            top_k=int(body["top_k"]),
            min_p=float(body["min_p"]),
            presence_penalty=float(body["presence_penalty"]),
            repeat_penalty=float(body["repeat_penalty"]),
        )

    return WorkerConfig(
        ollama=ollama,
        limits=limits,
        allowed_roots=tuple(allowed_roots),
        denied_globs=denied_globs,
        profiles=profiles,
        sampling_thinking=build_sampling("thinking"),
        sampling_non_thinking=build_sampling("non_thinking"),
        source_path=path,
    )
