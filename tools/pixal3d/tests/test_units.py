"""px3d の単体試験。GPU もネットワークも torch/gradio も使わない（モック試験）。

実行: uvx --with pytest pytest tools/pixal3d/tests/test_units.py -q
    （.venv には pytest を入れない。素の python + pytest だけで動く）
"""

from __future__ import annotations

from pathlib import Path
import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from px3d import config  # noqa: E402
from px3d import options  # noqa: E402
from px3d.cli import (  # noqa: E402
    build_serve_command,
    build_serve_env,
    classify_port_status,
    classify_vram_status,
    resolve_model_snapshot_dir,
    weight_files_from_pipeline_config,
)


# ---------------------------------------------------------------- options.low_vram_from_env


def test_low_vram_from_env_defaults_true_when_unset() -> None:
    assert options.low_vram_from_env({}) is True


def test_low_vram_from_env_true_values() -> None:
    for value in ("1", "true", "on", "yes", "TRUE", "On", "YES"):
        assert options.low_vram_from_env({"PIXAL3D_LOW_VRAM": value}) is True


def test_low_vram_from_env_false_values() -> None:
    for value in ("0", "false", "off", "no", "FALSE", "Off", "NO"):
        assert options.low_vram_from_env({"PIXAL3D_LOW_VRAM": value}) is False


def test_low_vram_from_env_garbage_defaults_true() -> None:
    assert options.low_vram_from_env({"PIXAL3D_LOW_VRAM": "たぶん有効"}) is True


# ---------------------------------------------------------------- options.parse_env_file


def test_parse_env_file_basic() -> None:
    text = "PIXAL3D_LOW_VRAM=1\nFOO=bar\n"
    assert options.parse_env_file(text) == {"PIXAL3D_LOW_VRAM": "1", "FOO": "bar"}


def test_parse_env_file_ignores_comments_and_blank_lines() -> None:
    text = "\n# コメント\nPIXAL3D_LOW_VRAM=0\n\n   # 別のコメント\nFOO=bar\n"
    assert options.parse_env_file(text) == {"PIXAL3D_LOW_VRAM": "0", "FOO": "bar"}


def test_parse_env_file_ignores_lines_without_equals() -> None:
    text = "not-a-kv-line\nFOO=bar\n"
    assert options.parse_env_file(text) == {"FOO": "bar"}


def test_parse_env_file_empty_text() -> None:
    assert options.parse_env_file("") == {}


# ---------------------------------------------------------------- options.read_low_vram_setting


def test_read_low_vram_setting_missing_file_returns_default(tmp_path) -> None:
    missing = tmp_path / "pixal3d.env"
    assert options.read_low_vram_setting(missing) is config.LOW_VRAM_DEFAULT


def test_read_low_vram_setting_reads_off(tmp_path) -> None:
    env_file = tmp_path / "pixal3d.env"
    env_file.write_text("PIXAL3D_LOW_VRAM=0\n", encoding="utf-8")
    assert options.read_low_vram_setting(env_file) is False


def test_read_low_vram_setting_reads_on(tmp_path) -> None:
    env_file = tmp_path / "pixal3d.env"
    env_file.write_text("PIXAL3D_LOW_VRAM=1\n", encoding="utf-8")
    assert options.read_low_vram_setting(env_file) is True


def test_read_low_vram_setting_var_missing_returns_default(tmp_path) -> None:
    env_file = tmp_path / "pixal3d.env"
    env_file.write_text("SOMETHING_ELSE=1\n", encoding="utf-8")
    assert options.read_low_vram_setting(env_file) is config.LOW_VRAM_DEFAULT


# ---------------------------------------------------------------- build_serve_command


def test_build_serve_command_low_vram_enabled() -> None:
    command = build_serve_command(
        python_bin="/tools/pixal3d/.venv/bin/python",
        host="0.0.0.0",
        port=7861,
        resolution=1024,
        low_vram=True,
    )
    assert command[0] == "/tools/pixal3d/.venv/bin/python"
    assert command[1:3] == ["-m", "px3d.ui"]
    assert "--low-vram" in command
    assert "--no-low-vram" not in command
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "7861"
    assert command[command.index("--resolution") + 1] == "1024"


def test_build_serve_command_low_vram_disabled() -> None:
    command = build_serve_command(
        python_bin="/tools/pixal3d/.venv/bin/python",
        host="127.0.0.1",
        port=9999,
        resolution=1536,
        low_vram=False,
    )
    assert "--no-low-vram" in command
    assert "--low-vram" not in command
    assert command[command.index("--port") + 1] == "9999"
    assert command[command.index("--resolution") + 1] == "1536"


# ---------------------------------------------------------------- build_serve_env


def test_build_serve_env_sets_expected_keys() -> None:
    env = build_serve_env(
        base_env={"PATH": "/usr/bin"},
        hf_home="/tools/pixal3d/models/hf",
        torch_home="/tools/pixal3d/models/torch",
        vendor_dir="/tools/pixal3d/vendor/Pixal3D",
        cuda_home="/usr/local/cuda-12.6",
    )
    assert env["HF_HOME"] == "/tools/pixal3d/models/hf"
    assert env["TORCH_HOME"] == "/tools/pixal3d/models/torch"
    # flash_attn を入れていないため SDPA を使う（vendor/Pixal3D/README.md が明記する代替経路）。
    assert env["ATTN_BACKEND"] == "sdpa"
    assert env["PYTHONPATH"] == "/tools/pixal3d/vendor/Pixal3D"
    assert env["CUDA_HOME"] == "/usr/local/cuda-12.6"
    assert env["PATH"].startswith("/usr/local/cuda-12.6/bin")
    assert "/usr/bin" in env["PATH"]


def test_build_serve_env_prepends_to_existing_pythonpath() -> None:
    env = build_serve_env(
        base_env={"PYTHONPATH": "/existing"},
        hf_home="/tools/pixal3d/models/hf",
        torch_home="/tools/pixal3d/models/torch",
        vendor_dir="/tools/pixal3d/vendor/Pixal3D",
        cuda_home="/usr/local/cuda-12.6",
    )
    assert env["PYTHONPATH"] == "/tools/pixal3d/vendor/Pixal3D" + ":" + "/existing"


def test_build_serve_env_does_not_mutate_base_env() -> None:
    base_env = {"PATH": "/usr/bin"}
    build_serve_env(
        base_env=base_env,
        hf_home="/x",
        torch_home="/w",
        vendor_dir="/y",
        cuda_home="/z",
    )
    assert base_env == {"PATH": "/usr/bin"}


# ---------------------------------------------------------------- weight_files_from_pipeline_config


def test_weight_files_from_pipeline_config_includes_json_and_safetensors() -> None:
    # 実機で確認した本物の pipeline_mv.json の構造を模したもの（TencentARC/Pixal3D）。
    pipeline_config = {
        "name": "Pixal3DMVImageTo3DPipeline",
        "args": {
            "models": {
                "sparse_structure_decoder": "ckpts/ss_dec_conv3d_16l8_fp16",
                "sparse_structure_flow_model": "ckpts/ss_flow_img_dit_1_3B_64_bf16_mv",
            },
            "rembg_model": {"name": "BiRefNet", "args": {"model_name": "briaai/RMBG-2.0"}},
        },
    }
    files = weight_files_from_pipeline_config(pipeline_config)

    assert config.PIPELINE_CONFIG in files
    assert "ckpts/ss_dec_conv3d_16l8_fp16.json" in files
    assert "ckpts/ss_dec_conv3d_16l8_fp16.safetensors" in files
    assert "ckpts/ss_flow_img_dit_1_3B_64_bf16_mv.json" in files
    assert "ckpts/ss_flow_img_dit_1_3B_64_bf16_mv.safetensors" in files
    assert len(files) == 5  # pipeline_mv.json + 2 モデル x (.json + .safetensors)


def test_weight_files_from_pipeline_config_dedupes_shared_paths() -> None:
    pipeline_config = {
        "args": {
            "models": {
                "model_a": "ckpts/shared",
                "model_b": "ckpts/shared",
            }
        }
    }
    files = weight_files_from_pipeline_config(pipeline_config)
    assert files == [config.PIPELINE_CONFIG, "ckpts/shared.json", "ckpts/shared.safetensors"]


def test_weight_files_from_pipeline_config_empty_models() -> None:
    assert weight_files_from_pipeline_config({"args": {"models": {}}}) == [config.PIPELINE_CONFIG]


def test_weight_files_from_pipeline_config_missing_args_key() -> None:
    assert weight_files_from_pipeline_config({}) == [config.PIPELINE_CONFIG]


# ---------------------------------------------------------------- resolve_model_snapshot_dir


def test_resolve_model_snapshot_dir_finds_single_snapshot(tmp_path) -> None:
    snapshot_dir = (
        tmp_path / "hub" / "models--TencentARC--Pixal3D" / "snapshots" / "b0cb2e1b794cab9aa0"
    )
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "pipeline_mv.json").write_text("{}", encoding="utf-8")

    found = resolve_model_snapshot_dir(tmp_path, "TencentARC/Pixal3D")
    assert found == snapshot_dir


def test_resolve_model_snapshot_dir_picks_most_recent_when_multiple(tmp_path) -> None:
    snapshots_dir = tmp_path / "hub" / "models--TencentARC--Pixal3D" / "snapshots"
    older = snapshots_dir / "older-hash"
    newer = snapshots_dir / "newer-hash"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    older_time = time.time() - 100
    os.utime(older, (older_time, older_time))

    found = resolve_model_snapshot_dir(tmp_path, "TencentARC/Pixal3D")
    assert found == newer


def test_resolve_model_snapshot_dir_missing_hub_returns_none(tmp_path) -> None:
    assert resolve_model_snapshot_dir(tmp_path, "TencentARC/Pixal3D") is None


def test_resolve_model_snapshot_dir_no_snapshots_returns_none(tmp_path) -> None:
    snapshots_dir = tmp_path / "hub" / "models--TencentARC--Pixal3D" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    assert resolve_model_snapshot_dir(tmp_path, "TencentARC/Pixal3D") is None


# ---------------------------------------------------------------- classify_port_status / classify_vram_status


def test_classify_port_status() -> None:
    assert classify_port_status(7861, in_use=False, service_active=False)[0] is True
    assert classify_port_status(7861, in_use=True, service_active=True)[0] is True
    assert classify_port_status(7861, in_use=True, service_active=False)[0] is False


def test_classify_vram_status() -> None:
    assert classify_vram_status(4, 1024, service_active=False)[0] is True
    assert classify_vram_status(5000, 1024, service_active=True)[0] is True
    ok, detail = classify_vram_status(22201, 1024, service_active=False)
    assert ok is False
    assert "free-vram" in detail
    assert classify_vram_status(None, 1024, service_active=False)[0] is False


# ---------------------------------------------------------------- config


def test_config_paths_point_into_tools_pixal3d() -> None:
    assert config.TOOL_DIR.name == "pixal3d"
    assert config.TOOL_DIR.parent.name == "tools"
    assert config.VENDOR_DIR == config.TOOL_DIR / "vendor" / "Pixal3D"
    assert config.TRELLIS_DIR == config.TOOL_DIR / "vendor" / "TRELLIS.2"
    assert config.MODELS_DIR == config.TOOL_DIR / "models"
    assert config.OUTPUTS_DIR == config.TOOL_DIR / "outputs"
    assert config.VENV_PYTHON == config.TOOL_DIR / ".venv" / "bin" / "python"
    assert config.HF_HOME_DIR == config.MODELS_DIR / "hf"
    assert config.PORT == 7861
    assert config.PORTAL_PORT == 8080


def test_config_low_vram_matches_portal() -> None:
    # tools/portal/portal.py の SERVICES["pixal3d"]["options"]["low_vram"] と一致させること。
    assert config.LOW_VRAM_ENV_FILE == Path.home() / ".config" / "pixal3d" / "pixal3d.env"
    assert config.LOW_VRAM_ENV_VAR == "PIXAL3D_LOW_VRAM"
    assert config.LOW_VRAM_DEFAULT is True


def test_config_rembg_model_is_non_gated() -> None:
    # briaai/RMBG-2.0（pipeline_mv.json 既定）はゲート付きのため使わない。
    assert config.REMBG_MODEL == "ZhengPeng7/BiRefNet"


def test_config_attn_backend_is_sdpa() -> None:
    # flash_attn を入れていないため（vendor/Pixal3D/README.md が明記する代替経路）。
    assert config.ATTN_BACKEND == "sdpa"


# ---------------------------------------------------------------- 既定視点（4 方位）


def test_view_azimuths_has_four_entries_front_first() -> None:
    assert config.VIEW_AZIMUTHS == ("front", "right", "back", "left")
    assert len(config.VIEW_TRANSFORM_MATRICES) == 4
    assert set(config.VIEW_TRANSFORM_MATRICES.keys()) == set(config.VIEW_AZIMUTHS)


def test_view_transform_matrix_front_matches_upstream_example() -> None:
    # vendor/Pixal3D/assets/mv_images/example/transforms.json の frame 0（azim000）と同じ値。
    distance = config.DEFAULT_CAMERA_DISTANCE
    assert config.VIEW_TRANSFORM_MATRICES["front"] == [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, -distance],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_view_transform_matrices_match_upstream_example_all_azimuths() -> None:
    distance = config.DEFAULT_CAMERA_DISTANCE
    assert config.VIEW_TRANSFORM_MATRICES["right"] == [
        [0.0, 0.0, 1.0, distance],
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    assert config.VIEW_TRANSFORM_MATRICES["back"] == [
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, distance],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    assert config.VIEW_TRANSFORM_MATRICES["left"] == [
        [0.0, 0.0, -1.0, -distance],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_default_camera_params_match_upstream_example() -> None:
    assert config.DEFAULT_CAMERA_ANGLE_X == 0.3490658503988659
    assert config.DEFAULT_CAMERA_DISTANCE == 3.1192049980163574
    assert config.DEFAULT_MESH_SCALE == 1.0
