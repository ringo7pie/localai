"""config.py のモデル選択関連（サンプリング上書き・トークン推定・structured_output）の試験。"""

from __future__ import annotations

from pathlib import Path

from qwen_worker.config import load_config

_BASE_TOML = """
allowed_roots = ["{root}"]

[ollama]
base_url = "http://127.0.0.1:11434"
model    = "qwen3.8:27b"

[profiles.standard]
num_ctx     = 65536
num_predict = 8192
think       = true

[sampling.thinking]
temperature      = 1.0
top_p            = 0.95
top_k            = 20
min_p            = 0.0
presence_penalty = 0.0
repeat_penalty   = 1.0

[sampling.non_thinking]
temperature      = 0.7
top_p            = 0.80
top_k            = 20
min_p            = 0.0
presence_penalty = 1.5
repeat_penalty   = 1.0
"""


def _write(tmp_path: Path, extra: str = "") -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_BASE_TOML.format(root=tmp_path) + extra, encoding="utf-8")
    return config_path


_BASE_TOML_WITH_STRUCTURED_OUTPUT = """
allowed_roots = ["{root}"]

[ollama]
base_url          = "http://127.0.0.1:11434"
model             = "qwen3.8:27b"
structured_output = true

[profiles.standard]
num_ctx     = 65536
num_predict = 8192
think       = true

[sampling.thinking]
temperature      = 1.0
top_p            = 0.95
top_k            = 20
min_p            = 0.0
presence_penalty = 0.0
repeat_penalty   = 1.0

[sampling.non_thinking]
temperature      = 0.7
top_p            = 0.80
top_k            = 20
min_p            = 0.0
presence_penalty = 1.5
repeat_penalty   = 1.0
"""


def test_structured_output_defaults_to_false(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path))

    assert config.ollama.structured_output is False


def test_structured_output_explicit_true(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_BASE_TOML_WITH_STRUCTURED_OUTPUT.format(root=tmp_path), encoding="utf-8")

    config = load_config(config_path)

    assert config.ollama.structured_output is True
    assert config.ollama.model == "qwen3.8:27b"


def test_sampling_for_unknown_model_falls_back_to_qwen_default(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path))

    default_thinking = config.sampling_for(True)
    assert config.sampling_for(True, model="gemma4:e4b") == default_thinking
    assert config.sampling_for(True, model="gemma4:e4b").top_k == 20


def test_sampling_for_uses_model_override_without_changing_qwen_default(tmp_path: Path) -> None:
    config = load_config(
        _write(
            tmp_path,
            """
[model_sampling."gemma4:e4b".thinking]
temperature      = 1.0
top_p            = 0.95
top_k            = 64
min_p            = 0.0
presence_penalty = 0.0
repeat_penalty   = 1.0
""",
        )
    )

    overridden = config.sampling_for(True, model="gemma4:e4b")
    assert overridden.top_k == 64

    # Qwen 側（model 省略）は一切変わらない。
    assert config.sampling_for(True).top_k == 20
    assert config.sampling_for(True, model="qwen3.8:27b").top_k == 20


def test_sampling_for_model_override_falls_back_when_side_missing(tmp_path: Path) -> None:
    # thinking だけ上書きし、non_thinking は上書きしない。
    config = load_config(
        _write(
            tmp_path,
            """
[model_sampling."gemma4:e4b".thinking]
temperature      = 1.0
top_p            = 0.95
top_k            = 64
min_p            = 0.0
presence_penalty = 0.0
repeat_penalty   = 1.0
""",
        )
    )

    assert config.sampling_for(True, model="gemma4:e4b").top_k == 64
    assert config.sampling_for(False, model="gemma4:e4b") == config.sampling_for(False)


def test_token_estimation_default_matches_qwen_baseline(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path))

    default = config.token_estimation_for("qwen3.8:27b")
    assert default.ascii_chars_per_token == 3.2
    assert default.non_ascii_chars_per_token == 1.0
    # 上書きが無いモデルも同じ既定にフォールバックする。
    assert config.token_estimation_for("gemma4:e4b") == default


def test_token_estimation_model_override(tmp_path: Path) -> None:
    config = load_config(
        _write(
            tmp_path,
            """
[tokens.model_overrides."gemma4:e4b"]
ascii_chars_per_token     = 4.0
non_ascii_chars_per_token = 1.3
""",
        )
    )

    overridden = config.token_estimation_for("gemma4:e4b")
    assert overridden.ascii_chars_per_token == 4.0
    assert overridden.non_ascii_chars_per_token == 1.3

    # Qwen 側は既定のまま。
    default = config.token_estimation_for("qwen3.8:27b")
    assert default.ascii_chars_per_token == 3.2
    assert default.non_ascii_chars_per_token == 1.0
