"""hy3d の単体試験。GPU もネットワークも使わない（モック試験）。

実行: tools/hunyuan3d/.venv/bin/python -m pytest tools/hunyuan3d/tests/test_units.py -q
    （pytest は requirements.lock.txt に入っているので、この venv にだけある）
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hy3d import config  # noqa: E402
from hy3d import ollama  # noqa: E402
from hy3d.cli import (  # noqa: E402
    build_allow_patterns,
    build_gradio_command,
    classify_port_status,
    classify_vram_status,
    low_vram_from_env,
)


class _FakeResponse:
    """urllib.request.urlopen の戻り値を模した with 文対応のダミー応答。"""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


# ---------------------------------------------------------------- build_gradio_command


def test_build_gradio_command_with_texture() -> None:
    command = build_gradio_command(
        python_bin="/tools/hunyuan3d/.venv/bin/python",
        script_path="gradio_app.py",
        host="0.0.0.0",
        port=7860,
        texture=True,
        low_vram=True,
        cache_path="/tools/hunyuan3d/outputs",
    )

    assert "--disable_tex" not in command
    assert "--texgen_model_path" in command
    texgen_index = command.index("--texgen_model_path")
    assert command[texgen_index + 1] == config.TEXGEN_REPO
    assert "--port" in command
    assert command[command.index("--port") + 1] == "7860"
    assert "--cache-path" in command
    assert command[command.index("--cache-path") + 1] == "/tools/hunyuan3d/outputs"
    assert "--model_path" in command
    assert command[command.index("--model_path") + 1] == config.SHAPE_REPO


def test_build_gradio_command_without_texture() -> None:
    command = build_gradio_command(
        python_bin="/tools/hunyuan3d/.venv/bin/python",
        script_path="gradio_app.py",
        host="127.0.0.1",
        port=9999,
        texture=False,
        low_vram=True,
        cache_path="/tmp/cache",
    )

    assert "--disable_tex" in command
    assert "--texgen_model_path" not in command
    assert command[command.index("--port") + 1] == "9999"
    assert command[command.index("--cache-path") + 1] == "/tmp/cache"
    assert command[command.index("--host") + 1] == "127.0.0.1"


def test_build_gradio_command_low_vram_enabled() -> None:
    """低 VRAM モード On では --low_vram_mode が入る（既定の挙動）。"""
    command = build_gradio_command(
        python_bin="/tools/hunyuan3d/.venv/bin/python",
        script_path="gradio_app.py",
        host="0.0.0.0",
        port=7860,
        texture=True,
        low_vram=True,
        cache_path="/tools/hunyuan3d/outputs",
    )
    assert "--low_vram_mode" in command


def test_build_gradio_command_low_vram_disabled() -> None:
    """低 VRAM モード Off では --low_vram_mode を渡さない（RAM を食い潰さないための切替）。"""
    command = build_gradio_command(
        python_bin="/tools/hunyuan3d/.venv/bin/python",
        script_path="gradio_app.py",
        host="0.0.0.0",
        port=7860,
        texture=True,
        low_vram=False,
        cache_path="/tools/hunyuan3d/outputs",
    )
    assert "--low_vram_mode" not in command


# ---------------------------------------------------------------- low_vram_from_env


def test_low_vram_from_env_defaults_true_when_unset() -> None:
    assert low_vram_from_env({}) is True


def test_low_vram_from_env_true_values() -> None:
    for value in ("1", "true", "on", "yes", "TRUE", "On", "YES"):
        assert low_vram_from_env({"HY3D_LOW_VRAM": value}) is True


def test_low_vram_from_env_false_values() -> None:
    for value in ("0", "false", "off", "no", "FALSE", "Off", "NO"):
        assert low_vram_from_env({"HY3D_LOW_VRAM": value}) is False


def test_low_vram_from_env_garbage_defaults_true() -> None:
    assert low_vram_from_env({"HY3D_LOW_VRAM": "たぶん有効"}) is True


# ---------------------------------------------------------------- ollama.loaded_models


def test_loaded_models_parses_api_ps(monkeypatch) -> None:
    payload = json.dumps(
        {
            "models": [
                {"name": "qwen3.8:27b", "size_vram": 22201000000},
                {"model": "other:latest", "size_vram": 123},
            ]
        }
    ).encode("utf-8")

    def fake_urlopen(url, timeout=None):
        assert "/api/ps" in url
        return _FakeResponse(payload)

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)

    models = ollama.loaded_models()
    assert models == [
        {"name": "qwen3.8:27b", "size_vram": 22201000000},
        {"name": "other:latest", "size_vram": 123},
    ]


def test_loaded_models_returns_empty_list_when_unreachable(monkeypatch) -> None:
    def fake_urlopen(url, timeout=None):
        raise OSError("接続できません")

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)
    assert ollama.loaded_models() == []


# ---------------------------------------------------------------- ollama.unload_all


def test_unload_all_posts_keep_alive_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        ollama,
        "loaded_models",
        lambda: [
            {"name": "model-a", "size_vram": 1},
            {"name": "model-b", "size_vram": 2},
        ],
    )

    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        return _FakeResponse(b"{}")

    monkeypatch.setattr(ollama.urllib.request, "urlopen", fake_urlopen)

    unloaded = ollama.unload_all()

    assert unloaded == ["model-a", "model-b"]
    assert len(seen_requests) == 2
    for request in seen_requests:
        assert "/api/generate" in request.full_url
        body = json.loads(request.data.decode("utf-8"))
        assert body["keep_alive"] == 0
        assert body["model"] in ("model-a", "model-b")


# ---------------------------------------------------------------- ollama.gpu_used_mib


def test_gpu_used_mib_parses_nvidia_smi_output(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "nvidia-smi"
        return subprocess.CompletedProcess(cmd, 0, stdout="22201\n", stderr="")

    monkeypatch.setattr(ollama.subprocess, "run", fake_run)
    assert ollama.gpu_used_mib() == 22201


def test_gpu_used_mib_returns_none_when_nvidia_smi_missing(monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi が見つかりません")

    monkeypatch.setattr(ollama.subprocess, "run", fake_run)
    assert ollama.gpu_used_mib() is None


# ---------------------------------------------------------------- ollama.wait_until_free


def test_wait_until_free_returns_true_when_below_threshold(monkeypatch) -> None:
    monkeypatch.setattr(ollama, "gpu_used_mib", lambda: 500)
    assert ollama.wait_until_free(threshold_mib=1024, timeout_seconds=5) is True


def test_wait_until_free_returns_false_on_timeout(monkeypatch) -> None:
    monkeypatch.setattr(ollama, "gpu_used_mib", lambda: 22000)
    assert ollama.wait_until_free(threshold_mib=1024, timeout_seconds=0) is False


# ---------------------------------------------------------------- config


def test_config_paths_point_into_tools_hunyuan3d() -> None:
    assert config.TOOL_DIR.name == "hunyuan3d"
    assert config.TOOL_DIR.parent.name == "tools"
    assert config.VENDOR_DIR == config.TOOL_DIR / "vendor" / "Hunyuan3D-2"
    assert config.MODELS_DIR == config.TOOL_DIR / "models"
    assert config.OUTPUTS_DIR == config.TOOL_DIR / "outputs"
    assert config.VENV_PYTHON == config.TOOL_DIR / ".venv" / "bin" / "python"
    assert config.PORT == 7860


def test_build_allow_patterns_narrows_to_required_files() -> None:
    """形状モデルは必要な 2 ファイルだけを落とす（同内容の .ckpt 4.93GB を避ける）。"""
    patterns = build_allow_patterns(config.SHAPE_SUBFOLDER, config.SHAPE_WEIGHT_FILES)
    assert patterns == [
        f"{config.SHAPE_SUBFOLDER}/config.yaml",
        f"{config.SHAPE_SUBFOLDER}/model.fp16.safetensors",
    ]
    assert not any(pattern.endswith(".ckpt") for pattern in patterns)
    assert not any(pattern.endswith("/*") for pattern in patterns)


def test_build_allow_patterns_falls_back_to_whole_subfolder() -> None:
    """必要なファイルが分からないもの（diffusers 形式）は subfolder ごと落とす。"""
    assert build_allow_patterns(config.DELIGHT_SUBFOLDER, None) == [
        f"{config.DELIGHT_SUBFOLDER}/*"
    ]


def test_classify_port_status() -> None:
    """自分が使っているポートは異常ではない。別のプロセスなら異常。"""
    assert classify_port_status(7860, in_use=False, service_active=False)[0] is True
    assert classify_port_status(7860, in_use=True, service_active=True)[0] is True
    assert classify_port_status(7860, in_use=True, service_active=False)[0] is False


def test_classify_vram_status() -> None:
    """稼働中なら VRAM を使っていて当然。停止中に埋まっていれば Qwen などが載っている。"""
    assert classify_vram_status(4, 1024, service_active=False)[0] is True
    assert classify_vram_status(5365, 1024, service_active=True)[0] is True
    ok, detail = classify_vram_status(22201, 1024, service_active=False)
    assert ok is False
    assert "free-vram" in detail
    assert classify_vram_status(None, 1024, service_active=False)[0] is False
