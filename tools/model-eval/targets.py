"""評価する AI の定義（ローカル 9 種と Claude。Claude は 2026-10-18 から effort 違いの 8 種）。並びは HTML の表の並び。

- ollama: /api/chat に stream・think:true・options.num_predict を送る。サンプリングと num_ctx は送らない
  （各 Modelfile の既定で動かす。文脈長は 2026-10-18 に各 Modelfile の num_ctx で A30 に載る最大にした。
  tools/qwen-model-bench/README.md の「文脈長の上限」）。gemma4:31b-ctx32k（it-qat と同じ重みで num_ctx 32768 の派生）は
  同じ日に Ollama から消した（2026-10-08 の評価の記録には残る）。
- strata: /v1/chat/completions（SSE）に reasoning_effort:"high"・max_tokens・reasoning_budget_tokens と、
  Qwen の Modelfile と同じ temperature 1.0 / top_p 0.95 / top_k 20 を送る。
  モデル名は tools/strata/stra/config.py の MODEL_NAME（RVN）・OFFICIAL.model_name・CODER.model_name・
  OFFICIAL_IQ3S.model_name・SWIFT.model_name、ポートも同じ所から。
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
    base_url: str = ""    # Ollama は 11434、Strata は 8082〜8086 の /v1
    unit: str = ""        # Strata の systemd user unit
    notes: str = ""       # 表に出す注記（量子化・実行環境など）
    extra: dict[str, Any] = field(default_factory=dict)
    added: str = ""       # 評価に足した日（results/<日付> がこれより前の集計には出さない。空ならいつも出す）
    effort: str = ""      # Claude の effort（xhigh / high / medium / low）


TARGETS: tuple[Target, ...] = (
    Target(key="sonnet", label="Sonnet5.5-xHigh", family="claude", backend="claude", slug="sonnet",
           notes="Claude Sonnet 5.5・effort xhigh。Agent ツールのサブエージェント（API 経由）", effort="xhigh"),
    Target(key="opus", label="Opus5.5-xHigh", family="claude", backend="claude", slug="opus",
           notes="Claude Opus 5.5・effort xhigh。Agent ツールのサブエージェント（API 経由）", effort="xhigh"),
    # 2026-10-18 に利用者の指示で足した effort 違い（同じ問題・同じ条件・各問 3 回）
    Target(key="sonnet-high", label="Sonnet5.5-High", family="claude", backend="claude", slug="sonnet-high",
           notes="Claude Sonnet 5.5・effort high。2026-10-18 に追加", added="2026-10-18", effort="high"),
    Target(key="opus-high", label="Opus5.5-High", family="claude", backend="claude", slug="opus-high",
           notes="Claude Opus 5.5・effort high。2026-10-18 に追加", added="2026-10-18", effort="high"),
    Target(key="sonnet-medium", label="Sonnet5.5-Medium", family="claude", backend="claude", slug="sonnet-medium",
           notes="Claude Sonnet 5.5・effort medium。2026-10-18 に追加", added="2026-10-18", effort="medium"),
    Target(key="opus-medium", label="Opus5.5-Medium", family="claude", backend="claude", slug="opus-medium",
           notes="Claude Opus 5.5・effort medium。2026-10-18 に追加", added="2026-10-18", effort="medium"),
    Target(key="sonnet-low", label="Sonnet5.5-Low", family="claude", backend="claude", slug="sonnet-low",
           notes="Claude Sonnet 5.5・effort low。2026-10-18 に追加", added="2026-10-18", effort="low"),
    Target(key="opus-low", label="Opus5.5-Low", family="claude", backend="claude", slug="opus-low",
           notes="Claude Opus 5.5・effort low。2026-10-18 に追加", added="2026-10-18", effort="low"),
    Target(key="qwen3.8:27b", label="qwen3.8:27b", family="ollama", backend="ollama", slug="qwen3.8-27b",
           model="qwen3.8:27b", base_url=OLLAMA_URL,
           notes="Q4_K_M・17 GB。Modelfile の既定 temp 1 / top_p 0.95 / top_k 20。num_ctx は 2026-10-18 から Modelfile の 114688（KV q8_0。2026-10-08 の評価は 65536）"),
    Target(key="gemma4:e4b", label="gemma4:e4b", family="ollama", backend="ollama", slug="gemma4-e4b",
           model="gemma4:e4b", base_url=OLLAMA_URL,
           notes="9.6 GB。Modelfile の既定 temp 1 / top_p 0.95 / top_k 64。num_ctx は 2026-10-18 から Modelfile の 131072（評価は 65536）"),
    Target(key="gemma4:31b-it-qat", label="gemma4:31b-it-qat", family="ollama", backend="ollama",
           slug="gemma4-31b-it-qat", model="gemma4:31b-it-qat", base_url=OLLAMA_URL,
           notes="18 GB。num_ctx を送らない（Modelfile の num_ctx 65536・KV q8_0 で全部 GPU。2026-10-08 の評価は f16 の KV で 6 層が CPU に溢れた状態）"),
    Target(key="qwen3.8-flash-next:IQ4_XS", label="qwen3.8-flash-next:IQ4_XS", family="ollama", backend="ollama",
           slug="qwen3.8-flash-next-IQ4_XS", model="qwen3.8-flash-next:IQ4_XS", base_url=OLLAMA_URL,
           notes="97 GB（非 abliterated）。大半を CPU 側に置く。Modelfile の既定 temp 1 / top_p 0.95 / top_k 20。num_ctx は 2026-10-18 から Modelfile の 131072（評価は 65536）"),
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
    # 2026-10-16 に足した 2 つ（tools/strata/stra/config.py の OFFICIAL_IQ3S・SWIFT）。計測は別途の指示で行う
    Target(key="strata-official:IQ3_S", label="strata-official:IQ3_S", family="strata", backend="strata",
           slug="strata-official-IQ3_S", model="strata-official:IQ3_S", base_url="http://127.0.0.1:8085/v1",
           unit="strata-official-iq3s",
           notes="公式 GSQ-RCO IQ3_S（IQ3_XXS より軽い量子化。非 abliterated）。Strata 8085。2026-10-16 に追加"),
    Target(key="strata-swift:IQ3_XXS", label="strata-swift:IQ3_XXS (Swift 1.5)", family="strata", backend="strata",
           slug="strata-swift-IQ3_XXS", model="strata-swift:IQ3_XXS", base_url="http://127.0.0.1:8086/v1",
           unit="strata-swift",
           notes="UkisAI の Swift 1.5（Qwen3.8-Flash-Next を思考が短く終わるように post-training した派生）の GSQ-RCO IQ3_XXS。Strata 8086。2026-10-16 に追加"),
)

BY_KEY = {target.key: target for target in TARGETS}
BY_SLUG = {target.slug: target for target in TARGETS}
LOCAL_TARGETS = tuple(target for target in TARGETS if target.backend != "claude")
CLAUDE_TARGETS = tuple(target for target in TARGETS if target.backend == "claude")
CLAUDE_KEYS = tuple(target.key for target in CLAUDE_TARGETS)
# effort ごとの Sonnet と Opus の組（2026-10-18 の比べ）
CLAUDE_EFFORT_PAIRS = (("xhigh", "sonnet", "opus"), ("high", "sonnet-high", "opus-high"),
                       ("medium", "sonnet-medium", "opus-medium"), ("low", "sonnet-low", "opus-low"))

FAMILY_LABELS = {"claude": "Claude（API）", "ollama": "Ollama", "strata": "Strata"}


def get(key: str) -> Target:
    """--target の名前（key）か slug で引く。"""

    if key in BY_KEY:
        return BY_KEY[key]
    if key in BY_SLUG:
        return BY_SLUG[key]
    raise KeyError(f"unknown target: {key}（候補: {', '.join(BY_KEY)}）")
