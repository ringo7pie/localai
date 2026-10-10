"""config.py の [web] セクションの読み込みの試験。"""

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


def test_web_settings_default_when_section_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_BASE_TOML.format(root=tmp_path), encoding="utf-8")

    config = load_config(config_path)

    assert config.web.enabled is True
    assert config.web.max_searches_per_task == 10
    assert config.web.max_fetches_per_task == 10


def test_web_settings_respects_explicit_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    body = _BASE_TOML.format(root=tmp_path) + """
[web]
enabled               = false
max_searches_per_task = 3
max_fetches_per_task  = 2
"""
    config_path.write_text(body, encoding="utf-8")

    config = load_config(config_path)

    assert config.web.enabled is False
    assert config.web.max_searches_per_task == 3
    assert config.web.max_fetches_per_task == 2
