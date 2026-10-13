"""hy3d の単体試験。GPU もネットワークも使わない（モック試験）。

実行: tools/hunyuan3d/.venv/bin/python -m pytest tools/hunyuan3d/tests/test_units.py -q
    （pytest は requirements.lock.txt に入っているので、この venv にだけある。
    hy3d は標準ライブラリだけなので、`uvx --with pytest pytest <このファイル> -q` でも走る）

公開版は上流への当て物（patches/）を含まず、上流（vendor/）も setup-server.sh を実行するまで無い。
上流のソースを読む試験は、上流が無ければ SKIP、当て物が当たっていなければ当て物の結果を確かめる
試験だけ SKIP にする（失敗にはしない）。公開版の状態を再現して全体を流すには、環境変数
HY3D_TEST_VENDOR_DIR に存在しないパス（または当て物の無い上流）を渡す:

    HY3D_TEST_VENDOR_DIR=/存在しないパス tools/hunyuan3d/.venv/bin/python -m pytest \
        tools/hunyuan3d/tests/test_units.py -q
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hy3d import config  # noqa: E402
from hy3d import errors  # noqa: E402
from hy3d import help_texts  # noqa: E402
from hy3d import ollama  # noqa: E402
from hy3d import presets  # noqa: E402
from hy3d import cli  # noqa: E402
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


# ---------------------------------------------------------------- help_texts / 画面の説明表示


# 当て物が当たった gradio_app.py にだけ現れる目印（当て物ごと）。公開版には当て物が無いので、
# これが無い上流では、当て物の結果を確かめる試験を SKIP にする。
PATCH_MARKER_HELP = "def _localai_build_glossary_html"  # 0003 説明表示
PATCH_MARKER_ERRORS = "def _localai_build_error_html"  # 0004 失敗したパラメータの表示
PATCH_MARKER_PRESETS = "from hy3d import presets as _localai_presets"  # 0005 設定の保存・読み込み

# 公開版の状態（上流が無い・当て物が無い）を再現して試験全体を流すための差し替え口。
VENDOR_DIR_OVERRIDE_ENV = "HY3D_TEST_VENDOR_DIR"


def _vendor_dir() -> Path:
    override = os.environ.get(VENDOR_DIR_OVERRIDE_ENV)
    if override:
        return Path(override)
    return config.VENDOR_DIR


def _gradio_app_source() -> str:
    """上流の gradio_app.py を読む。上流が取得されていなければ、その試験を SKIP にする。"""

    path = _vendor_dir() / "gradio_app.py"
    if not path.is_file():
        pytest.skip(f"上流の gradio_app.py が無い（{path}）。setup-server.sh で上流を取得すると走る")
    return path.read_text(encoding="utf-8")


def _patched_gradio_app_source(marker: str, patch_label: str) -> str:
    """当て物が当たった gradio_app.py を読む。当たっていなければ、その試験を SKIP にする。"""

    source = _gradio_app_source()
    if marker not in source:
        pytest.skip(
            f"上流に当て物（{patch_label}）が当たっていない。公開版は当て物を含まない"
            "（手元の patches/ に置いて setup-server.sh を実行すると当たる）"
        )
    return source


def _widget_labels(source: str) -> list[str]:
    """gradio_app.py の label='...' とボタンの value='...' を抜き出す（重複は除く）。"""

    labels = re.findall(r"label=(['\"])(.*?)\1", source)
    button_values = re.findall(r"gr\.Button\(\s*value=(['\"])(.*?)\1", source)
    seen: dict[str, None] = {}
    for _, text in labels + button_values:
        seen.setdefault(text, None)
    return list(seen.keys())


def test_all_widget_labels_have_tooltips() -> None:
    """画面のすべての入力・ボタン・スライダーに説明の付け忘れが無いこと。"""

    source = _gradio_app_source()
    labels = _widget_labels(source)
    assert labels, "gradio_app.py からラベルが 1 件も抽出できていない（正規表現を見直す）"
    assert help_texts.missing_tooltips(labels) == []


def _render_glossary_html() -> str:
    """gradio_app.py 中の _localai_build_glossary_html だけを取り出して実行する。

    torch を import する残りのコードは実行しない（この試験は GPU もネットワークも使わない）。
    """

    source = _patched_gradio_app_source(PATCH_MARKER_HELP, "0003 説明表示")
    match = re.search(
        r"(def _localai_build_glossary_html.*?)\n\ndef get_example_img_list",
        source,
        re.S,
    )
    assert match, "_localai_build_glossary_html が見つからない"
    namespace: dict[str, object] = {"_localai_help_texts": help_texts, "html": __import__("html")}
    exec(match.group(1), namespace)  # noqa: S102 - 自前のソースを試験のためだけに実行する
    return namespace["_localai_build_glossary_html"]()


def test_glossary_terms_used_in_ui_are_all_defined() -> None:
    """画面の用語ボタン（data-term）はすべて GLOSSARY にあること。"""

    rendered = _render_glossary_html()
    terms_in_ui = re.findall(r'data-term="([^"]+)"', rendered)
    assert terms_in_ui, "gradio_app.py に data-term を持つ用語ボタンが見つからない"
    for term in terms_in_ui:
        # html.escape で埋め込まれるため、比較のため元に戻す。
        unescaped = (
            term.replace("&quot;", '"')
            .replace("&#x27;", "'")
            .replace("&gt;", ">")
            .replace("&lt;", "<")
            .replace("&amp;", "&")
        )
        assert unescaped in help_texts.GLOSSARY


def test_tooltips_and_glossary_are_not_empty() -> None:
    assert len(help_texts.TOOLTIPS) > 0
    assert len(help_texts.GLOSSARY) > 0
    for label, body in help_texts.TOOLTIPS.items():
        assert isinstance(label, str) and label
        assert isinstance(body, str) and len(body) > 0
    for term, entry in help_texts.GLOSSARY.items():
        assert isinstance(term, str) and term
        assert entry.get("title")
        assert entry.get("body")


def test_glossary_json_and_tooltips_json_round_trip() -> None:
    parsed_glossary = json.loads(help_texts.glossary_json())
    assert parsed_glossary == help_texts.GLOSSARY

    parsed_tooltips = json.loads(help_texts.tooltips_json())
    assert parsed_tooltips == help_texts.TOOLTIPS


def test_missing_tooltips_detects_gaps() -> None:
    assert help_texts.missing_tooltips(["未定義のラベル"]) == ["未定義のラベル"]
    assert help_texts.missing_tooltips(list(help_texts.TOOLTIPS.keys())) == []


# ---------------------------------------------------------------- hy3d.errors（失敗の診断）


def test_classify_failure_detects_cuda_oom() -> None:
    text = (
        "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB "
        "(GPU 0; 23.69 GiB total capacity)"
    )
    assert errors.classify_failure(text) == "cuda_oom"
    assert errors.classify_failure("torch.OutOfMemoryError: ...") == "cuda_oom"
    assert errors.classify_failure("CUDA error: out of memory") == "cuda_oom"


def test_classify_failure_detects_host_oom() -> None:
    assert errors.classify_failure("MemoryError") == "host_oom"
    assert errors.classify_failure("OSError: [Errno 12] Cannot allocate memory") == "host_oom"
    assert (
        errors.classify_failure("RuntimeError: DefaultCPUAllocator: not enough memory: you tried to allocate")
        == "host_oom"
    )
    assert errors.classify_failure("std::bad_alloc") == "host_oom"


def test_classify_failure_unknown_when_no_marker_matches() -> None:
    assert errors.classify_failure("ValueError: invalid literal for int() with base 10") == "unknown"


def test_diagnose_cuda_oom_textured_leads_with_texture_generation() -> None:
    settings = {
        "Octree Resolution": 384,
        "Number of Chunks": 8000,
        "Inference Steps": 30,
    }
    diagnosis = errors.diagnose("cuda_oom", settings, textured=True)
    assert diagnosis["suspects"], "suspects が空になっている"
    assert "Textured" in diagnosis["suspects"][0]["label"] or "テクスチャ" in diagnosis["suspects"][0]["label"]


def test_diagnose_cuda_oom_shape_only_leads_with_octree_resolution() -> None:
    settings = {
        "Octree Resolution": 384,
        "Number of Chunks": 8000,
        "Inference Steps": 30,
    }
    diagnosis = errors.diagnose("cuda_oom", settings, textured=False)
    assert diagnosis["suspects"], "suspects が空になっている"
    assert "Octree Resolution" in diagnosis["suspects"][0]["label"]


def test_diagnose_cuda_oom_num_chunks_suggests_lowering_not_raising() -> None:
    """実測: Number of Chunks は大きいほど VRAM を使う。上げる提案は誤り。"""

    settings = {"Number of Chunks": 8000}
    diagnosis = errors.diagnose("cuda_oom", settings, textured=False)
    chunk_suspects = [s for s in diagnosis["suspects"] if "Number of Chunks" in s["label"]]
    assert len(chunk_suspects) == 1
    suspect = chunk_suspects[0]
    assert suspect["current"] == 8000
    assert suspect["suggested"] < suspect["current"], "Number of Chunks を上げる提案になっている"


def test_diagnose_cuda_oom_all_minimal_has_no_suspects_but_notes_guidance() -> None:
    settings = {
        "Octree Resolution": 256,
        "Number of Chunks": 4000,
        "Inference Steps": 10,
    }
    diagnosis = errors.diagnose("cuda_oom", settings, textured=False)
    assert diagnosis["suspects"] == []
    assert diagnosis["note"], "全部最小のときに案内が無い"


def test_diagnose_host_oom_all_minimal_has_no_suspects_but_notes_guidance() -> None:
    settings = {
        "Target Face Number": 10000,
        "Octree Resolution": 256,
    }
    diagnosis = errors.diagnose("host_oom", settings, textured=False)
    assert diagnosis["suspects"] == []
    assert diagnosis["note"], "全部最小のときに案内が無い"


def test_diagnose_unknown_has_no_suspects_and_does_not_blame_settings() -> None:
    diagnosis = errors.diagnose("unknown", {"Octree Resolution": 512, "Number of Chunks": 200000}, textured=True)
    assert diagnosis["suspects"] == []
    blamed_terms = ("Octree Resolution", "Number of Chunks", "Inference Steps", "Target Face Number")
    for term in blamed_terms:
        assert term not in diagnosis["headline"]
        assert term not in diagnosis["note"]


def test_format_failure_markdown_includes_label_current_suggested_and_original_exception() -> None:
    settings = {"Octree Resolution": 384, "Number of Chunks": 8000}
    diagnosis = errors.diagnose("cuda_oom", settings, textured=False)
    error_text = "Traceback (most recent call last):\nRuntimeError: CUDA out of memory. Tried to allocate 512.00 MiB"
    markdown = errors.format_failure_markdown(diagnosis, settings, error_text)

    assert "Octree Resolution" in markdown
    assert "384" in markdown
    assert "256" in markdown
    assert "CUDA out of memory" in markdown
    assert "Tried to allocate 512.00 MiB" in markdown


# ---------------------------------------------------------------- gradio_app.py が失敗を診断すること


def _slice_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_generation_entry_points_diagnose_failures_on_exception() -> None:
    source = _patched_gradio_app_source(PATCH_MARKER_ERRORS, "0004 失敗したパラメータの表示")

    generation_all_src = _slice_between(source, "def generation_all(", "def shape_generation(")
    shape_generation_src = _slice_between(source, "def shape_generation(", "def build_app():")
    on_export_click_src = _slice_between(source, "def on_export_click(", "confirm_export.click(")

    for name, snippet in (
        ("generation_all", generation_all_src),
        ("shape_generation", shape_generation_src),
        ("on_export_click", on_export_click_src),
    ):
        assert "try:" in snippet, f"{name} に try が無い"
        assert "except" in snippet, f"{name} に except が無い"
        assert (
            "_localai_errors" in snippet
            or "errors.diagnose" in snippet
            or "_localai_build_error_html" in snippet
        ), f"{name} が hy3d.errors による診断を呼んでいない"

    assert "html.escape" in source, "gradio_app.py に html.escape の使用が見つからない"


# ---------------------------------------------------------------- hy3d.presets（設定の保存・読み込み）


@pytest.fixture()
def _isolated_presets_dir(monkeypatch):
    """presets.PRESETS_DIR を一時ディレクトリへ差し替え、本物の presets/ を汚さない。

    pytest 標準の tmp_path ではなく tempfile を直接使う（サンドボックスでは
    USER と実プロセスの uid がずれていることがあり、tmp_path 内部の所有者チェックが
    誤検知で失敗するため）。
    """

    with tempfile.TemporaryDirectory() as raw_dir:
        tmp_dir = Path(raw_dir)
        monkeypatch.setattr(presets, "PRESETS_DIR", tmp_dir)
        yield tmp_dir


def test_validate_preset_name_accepts_japanese_and_alnum_names() -> None:
    assert presets.validate_preset_name("標準設定") is None
    assert presets.validate_preset_name("preset_01 (v2)") is None
    assert presets.validate_preset_name("a" * 64) is None


def test_validate_preset_name_rejects_empty_or_whitespace_only() -> None:
    assert presets.validate_preset_name("") is not None
    assert presets.validate_preset_name("   ") is not None


def test_validate_preset_name_rejects_too_long() -> None:
    reason = presets.validate_preset_name("a" * 65)
    assert reason is not None
    assert "64" in reason


def test_validate_preset_name_rejects_path_escape_attempts() -> None:
    for bad_name in ("a/b", "..", ".hidden", "a\\b"):
        reason = presets.validate_preset_name(bad_name)
        assert reason is not None, f"{bad_name!r} が弾かれていない"


def test_preset_path_stays_inside_presets_dir(_isolated_presets_dir) -> None:
    path = presets.preset_path("テスト設定")
    assert path.parent == _isolated_presets_dir.resolve()
    assert path.name == "テスト設定.json"


def test_save_and_load_preset_round_trip(_isolated_presets_dir) -> None:
    path = presets.save_preset("マイ設定", presets.DEFAULT_SETTINGS)
    assert path.exists()

    result = presets.load_preset("マイ設定")
    assert result["settings"] == presets.DEFAULT_SETTINGS
    assert result["ignored"] == []


def test_load_preset_ignores_unknown_keys_and_fills_missing_with_defaults(_isolated_presets_dir) -> None:
    path = presets.preset_path("部分設定")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "tool": "hunyuan3d",
        "saved_at": "2026-01-01T00:00:00+00:00",
        "settings": {"num_steps": 12, "not_a_real_key": "x"},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = presets.load_preset("部分設定")
    assert "not_a_real_key" not in result["settings"]
    assert result["settings"]["num_steps"] == 12
    assert result["settings"]["seed"] == presets.DEFAULT_SETTINGS["seed"]
    assert result["ignored"] == []


def test_load_preset_falls_back_to_default_for_out_of_range_values(_isolated_presets_dir) -> None:
    path = presets.preset_path("範囲外設定")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "tool": "hunyuan3d",
        "saved_at": "2026-01-01T00:00:00+00:00",
        "settings": {
            "octree_resolution": 9999,
            "num_steps": -1,
            "file_type": "exe",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = presets.load_preset("範囲外設定")
    assert result["settings"]["octree_resolution"] == presets.DEFAULT_SETTINGS["octree_resolution"]
    assert result["settings"]["num_steps"] == presets.DEFAULT_SETTINGS["num_steps"]
    assert result["settings"]["file_type"] == presets.DEFAULT_SETTINGS["file_type"]
    assert set(result["ignored"]) == {"octree_resolution", "num_steps", "file_type"}


def test_list_presets_returns_sorted_names(_isolated_presets_dir) -> None:
    presets.save_preset("banana", presets.DEFAULT_SETTINGS)
    presets.save_preset("apple", presets.DEFAULT_SETTINGS)
    assert presets.list_presets() == ["apple", "banana"]


def test_list_presets_empty_when_dir_absent(_isolated_presets_dir) -> None:
    assert presets.list_presets() == []


def test_delete_preset_returns_true_then_false(_isolated_presets_dir) -> None:
    presets.save_preset("消す設定", presets.DEFAULT_SETTINGS)
    assert presets.delete_preset("消す設定") is True
    assert presets.delete_preset("消す設定") is False


def test_load_preset_raises_value_error_on_broken_json(_isolated_presets_dir) -> None:
    path = presets.preset_path("壊れた設定")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError):
        presets.load_preset("壊れた設定")


def test_load_preset_raises_file_not_found_when_missing(_isolated_presets_dir) -> None:
    with pytest.raises(FileNotFoundError):
        presets.load_preset("存在しない設定")


def test_default_settings_match_gradio_app_source() -> None:
    """DEFAULT_SETTINGS が gradio_app.py の実際の既定値からズレていないこと。"""

    source = _gradio_app_source()

    # num_steps: 'turbo' in args.subfolder で 5/30 に分岐するが、このサーバーの
    # config.SHAPE_SUBFOLDER は 'turbo' を含まないため実際の既定値は 30。
    assert "value=5 if 'turbo' in args.subfolder else 30" in source
    assert "turbo" not in config.SHAPE_SUBFOLDER
    assert presets.DEFAULT_SETTINGS["num_steps"] == 30

    assert "cfg_scale = gr.Number(value=5.0, label='Guidance Scale', min_width=100)" in source
    assert presets.DEFAULT_SETTINGS["cfg_scale"] == 5.0

    assert "value=1234," in source
    assert presets.DEFAULT_SETTINGS["seed"] == 1234

    assert 'randomize_seed = gr.Checkbox(label="Randomize seed", value=True, min_width=100)' in source
    assert presets.DEFAULT_SETTINGS["randomize_seed"] is True

    assert "octree_resolution = gr.Slider(maximum=512, minimum=16, value=256, label='Octree Resolution')" in source
    assert presets.DEFAULT_SETTINGS["octree_resolution"] == 256

    assert "check_box_rembg = gr.Checkbox(value=True, label='Remove Background', min_width=100)" in source
    assert presets.DEFAULT_SETTINGS["check_box_rembg"] is True

    assert "num_chunks = gr.Slider(maximum=5000000, minimum=1000, value=8000," in source
    assert presets.DEFAULT_SETTINGS["num_chunks"] == 8000

    assert "file_type = gr.Dropdown(label='File Type', choices=SUPPORTED_FORMATS," in source
    assert "SUPPORTED_FORMATS = ['glb', 'obj', 'ply', 'stl']" in source
    assert presets.DEFAULT_SETTINGS["file_type"] == "glb"
    assert set(presets.SETTING_RANGES["file_type"]["choices"]) == {"glb", "obj", "ply", "stl"}

    assert "reduce_face = gr.Checkbox(label='Simplify Mesh', value=False, min_width=100)" in source
    assert presets.DEFAULT_SETTINGS["reduce_face"] is False

    assert "export_texture = gr.Checkbox(label='Include Texture', value=False," in source
    assert presets.DEFAULT_SETTINGS["export_texture"] is False

    assert "target_face_num = gr.Slider(maximum=1000000, minimum=100, value=10000," in source
    assert presets.DEFAULT_SETTINGS["target_face_num"] == 10000

    assert "MAX_SEED = int(1e7)" in source
    assert presets.SETTING_RANGES["seed"]["max"] == int(1e7)


def test_gradio_app_calls_hy3d_presets_for_save_load_delete() -> None:
    """gradio_app.py が hy3d.presets の保存・読み込み・削除を実際に呼んでいること。"""

    source = _patched_gradio_app_source(PATCH_MARKER_PRESETS, "0005 設定の保存・読み込み")
    assert "from hy3d import presets as _localai_presets" in source
    assert "_localai_presets.save_preset(" in source
    assert "_localai_presets.load_preset(" in source
    assert "_localai_presets.delete_preset(" in source
    assert "_localai_presets.list_presets(" in source


def test_preset_ui_widgets_have_tooltips() -> None:
    """新しく足した「設定の保存・読み込み」欄の部品にも説明の付け忘れが無いこと。"""

    source = _patched_gradio_app_source(PATCH_MARKER_PRESETS, "0005 設定の保存・読み込み")
    labels = _widget_labels(source)
    for label in ("設定の保存・読み込み", "設定名", "保存済みの設定", "保存", "読み込み", "削除"):
        assert label in labels, f"{label} が gradio_app.py から抽出できていない"
    assert help_texts.missing_tooltips(labels) == []


def test_validate_preset_name_allows_natural_japanese_names() -> None:
    """日本語で自然に打つ名前が通ること。

    許可文字を絞り込む方式にすると「高精細（試し）」のような全角括弧・全角空白・かぎ括弧が
    弾かれて使いものにならない。危ない文字だけを弾く方式にしてある。
    """
    for name in ("高精細（試し）", "ドレス用　高品質", "夜間バッチ「標準」", "fast-draft", "試作 v2"):
        assert presets.validate_preset_name(name) is None, name


def test_validate_preset_name_rejects_windows_invalid_characters() -> None:
    """Windows / SMB で使えない文字を弾くこと。

    presets/ を Windows や SMB 共有（CIFS）に置いても困らないよう、Windows で無効な
    ファイル名はこの場で弾く。
    """
    for name in ("a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"):
        reason = presets.validate_preset_name(name)
        assert reason is not None, name
    assert presets.validate_preset_name("末尾に空白 ") is not None
    assert presets.validate_preset_name("末尾にドット.") is not None


# ---------------------------------------------------------------- 公開版（上流なし・当て物なし）でも壊れないこと
#
# 公開版は patches/ を含まず、vendor/ も setup-server.sh を実行するまで無い。patches/ や vendor/ を
# 退避せず、パスを一時ディレクトリへ差し替えて、その状態でも hy3d と試験が壊れないことを確かめる。


@pytest.fixture()
def _vendor_dir_in_tmp(monkeypatch):
    """config.VENDOR_DIR を空の一時ディレクトリへ差し替える（上流が取得されていない状態）。

    tmp_path ではなく tempfile を使う理由は _isolated_presets_dir と同じ。
    """

    monkeypatch.delenv(VENDOR_DIR_OVERRIDE_ENV, raising=False)
    with tempfile.TemporaryDirectory() as raw_dir:
        vendor_dir = Path(raw_dir) / "Hunyuan3D-2"
        monkeypatch.setattr(config, "VENDOR_DIR", vendor_dir)
        yield vendor_dir


def _write_gradio_app_stub(vendor_dir: Path, text: str) -> None:
    vendor_dir.mkdir(parents=True, exist_ok=True)
    (vendor_dir / "gradio_app.py").write_text(text, encoding="utf-8")


def test_gradio_app_source_skips_when_vendor_is_absent(_vendor_dir_in_tmp) -> None:
    """上流（vendor/）が無い公開版では、上流のソースを読む試験が失敗でなく SKIP になる。"""

    assert not _vendor_dir_in_tmp.exists()
    with pytest.raises(pytest.skip.Exception):
        _gradio_app_source()
    with pytest.raises(pytest.skip.Exception):
        _patched_gradio_app_source(PATCH_MARKER_HELP, "0003 説明表示")


def test_patch_dependent_checks_skip_on_unpatched_upstream(_vendor_dir_in_tmp) -> None:
    """当て物が当たっていない上流（公開版の利用者の環境）では、当て物の結果を確かめる試験だけ SKIP になる。"""

    _write_gradio_app_stub(_vendor_dir_in_tmp, "import gradio as gr\nMV_MODE = True\n")

    # 上流そのものを読む試験は走る。
    assert "MV_MODE" in _gradio_app_source()
    for marker, label in (
        (PATCH_MARKER_HELP, "0003 説明表示"),
        (PATCH_MARKER_ERRORS, "0004 失敗したパラメータの表示"),
        (PATCH_MARKER_PRESETS, "0005 設定の保存・読み込み"),
    ):
        with pytest.raises(pytest.skip.Exception):
            _patched_gradio_app_source(marker, label)


def test_patch_dependent_checks_run_when_patches_are_applied(_vendor_dir_in_tmp) -> None:
    """当て物が当たっていれば SKIP にならず、当て物の結果を確かめる試験が走る（常に SKIP にはしない）。"""

    stub = "\n".join([PATCH_MARKER_HELP, PATCH_MARKER_ERRORS, PATCH_MARKER_PRESETS, ""])
    _write_gradio_app_stub(_vendor_dir_in_tmp, stub)

    assert _patched_gradio_app_source(PATCH_MARKER_HELP, "0003 説明表示") == stub
    assert _patched_gradio_app_source(PATCH_MARKER_ERRORS, "0004 失敗したパラメータの表示") == stub
    assert _patched_gradio_app_source(PATCH_MARKER_PRESETS, "0005 設定の保存・読み込み") == stub


def test_hy3d_does_not_read_patches_directory() -> None:
    """hy3d が patches/ を実行時に読まないこと。読むと公開版（patches/ が無い）で壊れる。

    patches/ を読むのは setup-server.sh だけ。hy3d/*.py に "patches" というパス要素が
    入っていないことを、文字列定数の走査で確かめる（コメントと docstring は対象外）。
    """

    package_dir = Path(config.__file__).resolve().parent
    offenders = []
    for source_path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "patches":
                offenders.append(f"{source_path.name}:{node.lineno}")
    assert offenders == []


def test_doctor_reports_ng_without_vendor(_vendor_dir_in_tmp) -> None:
    """上流が無い公開版でも、doctor の上流確認は例外にならず NG と理由を返す。"""

    ok, detail = cli._check_upstream_commit()
    assert ok is False
    assert "上流が見つかりません" in detail


def test_serve_stops_with_guidance_without_vendor(_vendor_dir_in_tmp, monkeypatch, capsys) -> None:
    """上流が無い公開版で serve しても、例外にならず setup-server.sh を案内して終了コード 1 を返す。"""

    # Ollama・nvidia-smi には触れない。
    monkeypatch.setattr(ollama, "loaded_models", lambda: [])
    monkeypatch.setattr(ollama, "unload_all", lambda: [])
    args = cli.build_parser().parse_args(["serve", "--skip-vram-check"])

    assert cli.cmd_serve(args) == 1
    assert "setup-server.sh" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 重みの取得の前の使用許諾の確認（Tencent Hunyuan 3D 2.0 Community License）
# --------------------------------------------------------------------------


def test_fetch_models_refuses_without_license_acceptance(monkeypatch, capsys) -> None:
    """同意が無ければ、何も取得せず終了コード 2 で止まり、条件の要約を出す。"""
    monkeypatch.delenv("HY3D_ACCEPT_LICENSE", raising=False)
    args = argparse.Namespace(no_texture=True, accept_tencent_license=False)

    assert cli.cmd_fetch_models(args) == 2

    captured = capsys.readouterr()
    assert "EU・UK・韓国" in captured.err
    assert "--accept-tencent-license" in captured.err


def test_license_accepted_by_flag_or_environment(monkeypatch) -> None:
    monkeypatch.delenv("HY3D_ACCEPT_LICENSE", raising=False)
    assert cli.license_accepted(argparse.Namespace(accept_tencent_license=True)) is True
    assert cli.license_accepted(argparse.Namespace(accept_tencent_license=False)) is False
    monkeypatch.setenv("HY3D_ACCEPT_LICENSE", "1")
    assert cli.license_accepted(argparse.Namespace(accept_tencent_license=False)) is True
    monkeypatch.setenv("HY3D_ACCEPT_LICENSE", "yes")
    assert cli.license_accepted(argparse.Namespace(accept_tencent_license=False)) is False
