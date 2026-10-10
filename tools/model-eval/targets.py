"""評価する 10 の AI の定義（ローカル 8 種と Claude 2 種）。並びは HTML の表の並び。

- ollama: /api/chat に stream・think:true・options.num_predict を送る。サンプリングと num_ctx は送らない
  （各 Modelfile の既定で動かす。it-qat は num_ctx を送らないことで、ctx32k との差がそのまま測れる）。
- strata: /v1/chat/completions（SSE）に reasoning_effort:"high"・max_tokens・reasoning_budget_tokens と、
  Qwen の Modelfile と同じ temperature 1.0 / top_p 0.95 / top_k 20 を送る。
  モデル名は tools/strata/stra/config.py の MODEL_NAME（RVN）・OFFICIAL.model_name・CODER.model_name、ポートも同じ所から。
- claude: メインが Agent ツールで起動し、results/<日付>/claude/<dir>/ に保存する。ここでは表示用の定義だけ。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OLLAMA_URL = "http://127.0.0.1:11434"
# Strata に送るサンプリング（qwen3.8:27b と IQ4_XS の Modelfile の既定と同じ値）
STRATA_SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 20}


@dataclass(frozen=True)
class Target:
    key: str              # --target に渡す名前（Ollama / Strata のモデル名そのもの、Claude は sonnet / opus）
    label: str            # 表に出す名前
    family: str           # claude / ollama / strata（色分けの系統）
    backend: str          # claude / ollama / strata
    slug: str             # results/ の下のディレクトリ名
    model: str = ""       # API に渡すモデル名
    base_url: str = ""    # Ollama は 11434、Strata は 8082 / 8083 / 8084 の /v1
    unit: str = ""        # Strata の systemd user unit
    notes: str = ""       # 表に出す注記（量子化・実行環境など）
    extra: dict[str, Any] = field(default_factory=dict)


TARGETS: tuple[Target, ...] = (
    Target(key="sonnet", label="Sonnet5.5-xHigh", family="claude", backend="claude", slug="sonnet",
           notes="Claude Sonnet 5.5・effort xhigh。Agent ツールのサブエージェント（API 経由）"),
    Target(key="opus", label="Opus5.5-xHigh", family="claude", backend="claude", slug="opus",
           notes="Claude Opus 5.5・effort xhigh。Agent ツールのサブエージェント（API 経由）"),
    Target(key="qwen3.8:27b", label="qwen3.8:27b", family="ollama", backend="ollama", slug="qwen3.8-27b",
           model="qwen3.8:27b", base_url=OLLAMA_URL, notes="Q4_K_M・17 GB。Modelfile の既定 temp 1 / top_p 0.95 / top_k 20"),
    Target(key="gemma4:e4b", label="gemma4:e4b", family="ollama", backend="ollama", slug="gemma4-e4b",
           model="gemma4:e4b", base_url=OLLAMA_URL, notes="9.6 GB。Modelfile の既定 temp 1 / top_p 0.95 / top_k 64"),
    Target(key="gemma4:31b-it-qat", label="gemma4:31b-it-qat", family="ollama", backend="ollama",
           slug="gemma4-31b-it-qat", model="gemma4:31b-it-qat", base_url=OLLAMA_URL,
           notes="18 GB。num_ctx を送らない（サーバー既定 65536）。ctx32k と同じ重み"),
    Target(key="gemma4:31b-ctx32k", label="gemma4:31b-ctx32k", family="ollama", backend="ollama",
           slug="gemma4-31b-ctx32k", model="gemma4:31b-ctx32k", base_url=OLLAMA_URL,
           notes="it-qat と同じ重みで Modelfile の num_ctx 32768"),
    Target(key="qwen3.8-flash-next:IQ4_XS", label="qwen3.8-flash-next:IQ4_XS", family="ollama", backend="ollama",
           slug="qwen3.8-flash-next-IQ4_XS", model="qwen3.8-flash-next:IQ4_XS", base_url=OLLAMA_URL,
           notes="97 GB（非 abliterated）。大半を CPU 側に置く。Modelfile の既定 temp 1 / top_p 0.95 / top_k 20"),
    Target(key="strata-flash-next:IQ3_S", label="strata-flash-next:IQ3_S (RVN)", family="strata", backend="strata",
           slug="strata-rvn-IQ3_S", model="strata-flash-next:IQ3_S", base_url="http://127.0.0.1:8082/v1",
           unit="strata", notes="RVN-Qwen3.8-Flash-Next IQ3_S（abliterated）。Strata 8082"),
    Target(key="strata-official:IQ3_XXS", label="strata-official:IQ3_XXS", family="strata", backend="strata",
           slug="strata-official-IQ3_XXS", model="strata-official:IQ3_XXS", base_url="http://127.0.0.1:8084/v1",
           unit="strata-official", notes="公式 GSQ-RCO IQ3_XXS（非 abliterated）。Strata 8084"),
    Target(key="strata-flash-coder:IQ1_M", label="strata-flash-coder:IQ1_M (Coder)", family="strata", backend="strata",
           slug="strata-coder-IQ1_M", model="strata-flash-coder:IQ1_M", base_url="http://127.0.0.1:8083/v1",
           unit="strata-coder",
           notes="ISTA-DASLab の Coder GSQ-RCO IQ1_M（コード向けに各層 256 エキスパートへ間引いた版）。Strata 8083。2026-10-09 に追加で計測"),
)

BY_KEY = {target.key: target for target in TARGETS}
BY_SLUG = {target.slug: target for target in TARGETS}
LOCAL_TARGETS = tuple(target for target in TARGETS if target.backend != "claude")
CLAUDE_TARGETS = tuple(target for target in TARGETS if target.backend == "claude")

FAMILY_LABELS = {"claude": "Claude（API）", "ollama": "Ollama", "strata": "Strata"}


def get(key: str) -> Target:
    """--target の名前（key）か slug で引く。"""

    if key in BY_KEY:
        return BY_KEY[key]
    if key in BY_SLUG:
        return BY_SLUG[key]
    raise KeyError(f"unknown target: {key}（候補: {', '.join(BY_KEY)}）")
