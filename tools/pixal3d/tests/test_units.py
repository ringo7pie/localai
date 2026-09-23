"""px3d の単体試験。GPU もネットワークも torch/gradio も使わない（モック試験）。

実行: uvx --with pytest pytest tools/pixal3d/tests/test_units.py -q
    （.venv には pytest を入れない。素の python + pytest だけで動く）
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from px3d import config  # noqa: E402
from px3d import options  # noqa: E402
from px3d import framing  # noqa: E402
from px3d import help_texts  # noqa: E402
from px3d import errors  # noqa: E402
from px3d import presets  # noqa: E402
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


# ---------------------------------------------------------------- framing.compute_uniform_layout


def test_compute_uniform_layout_tall_bbox_keeps_aspect_ratio() -> None:
    # 縦長（幅 400 × 高さ 1000）の外接矩形 1 つ。潰さず、指定した fill に収める。
    bboxes = {"front": (0, 0, 400, 1000)}
    layout = framing.compute_uniform_layout(bboxes, canvas_size=1024, fill=0.85)
    scale = layout["front"]["scale"]
    assert 1000 * scale == pytest.approx(0.85 * 1024)
    assert 400 * scale == pytest.approx(400 * scale)  # 幅は縦横比どおり
    assert (400 * scale) / (1000 * scale) == pytest.approx(400 / 1000)


def test_compute_uniform_layout_wide_bbox_fits_by_width() -> None:
    # 横長の物体（幅 1000 × 高さ 400）→ 横幅が fill*canvas に収まり、高さはそれより小さい。
    bboxes = {"front": (0, 0, 1000, 400)}
    layout = framing.compute_uniform_layout(bboxes, canvas_size=1024, fill=0.85)
    scale = layout["front"]["scale"]
    assert 1000 * scale == pytest.approx(0.85 * 1024)
    assert 400 * scale < 0.85 * 1024


def test_compute_uniform_layout_same_scale_across_views_different_widths() -> None:
    # 4 視点で幅が違う（正面が広く側面が狭い）が高さは同じ → 全視点で scale が同じ。
    bboxes = {
        "front": (0, 0, 600, 900),
        "right": (0, 0, 300, 900),
        "back": (0, 0, 600, 900),
        "left": (0, 0, 300, 900),
    }
    layout = framing.compute_uniform_layout(bboxes, canvas_size=1024, fill=0.85)
    scales = {view["scale"] for view in layout.values()}
    assert len(scales) == 1


def test_compute_uniform_layout_normalizes_different_photo_resolutions() -> None:
    # 同じ物体を 2 倍の解像度で撮った視点が混ざる → 正規化後の物体の高さが全視点で等しい。
    bboxes = {
        "front": (0, 0, 400, 1000),
        "right": (0, 0, 800, 2000),  # 同じ物体を 2 倍の解像度で撮った想定
    }
    layout = framing.compute_uniform_layout(bboxes, canvas_size=1024, fill=0.85)
    heights_after_scale = {
        view: (bboxes[view][3] - bboxes[view][1]) * layout[view]["scale"] for view in bboxes
    }
    assert heights_after_scale["front"] == pytest.approx(heights_after_scale["right"])


def test_compute_uniform_layout_centers_bbox_on_canvas() -> None:
    # 外接矩形の中心がキャンバス中心（512, 512）に来る（貼り付け位置から逆算して ±1 ピクセル）。
    bboxes = {"front": (100, 200, 500, 1200)}
    canvas_size = 1024
    layout = framing.compute_uniform_layout(bboxes, canvas_size=canvas_size, fill=0.85)
    scale = layout["front"]["scale"]
    paste_x, paste_y = layout["front"]["paste_offset"]
    center_x = (100 + 500) / 2.0
    center_y = (200 + 1200) / 2.0
    assert paste_x + center_x * scale == pytest.approx(canvas_size / 2, abs=1)
    assert paste_y + center_y * scale == pytest.approx(canvas_size / 2, abs=1)


def test_compute_uniform_layout_largest_side_within_fill() -> None:
    # 一番大きい辺が fill*canvas を超えない（全視点）。
    bboxes = {
        "front": (0, 0, 600, 900),
        "right": (0, 0, 300, 950),
        "back": (0, 0, 700, 850),
        "left": (0, 0, 300, 900),
    }
    canvas_size = 1024
    fill = 0.85
    layout = framing.compute_uniform_layout(bboxes, canvas_size=canvas_size, fill=fill)
    for view, bbox in bboxes.items():
        width = (bbox[2] - bbox[0]) * layout[view]["scale"]
        height = (bbox[3] - bbox[1]) * layout[view]["scale"]
        assert max(width, height) <= fill * canvas_size + 1e-6


def test_compute_uniform_layout_rejects_fill_out_of_range() -> None:
    with pytest.raises(ValueError):
        framing.compute_uniform_layout({"front": (0, 0, 10, 10)}, canvas_size=1024, fill=0.49)
    with pytest.raises(ValueError):
        framing.compute_uniform_layout({"front": (0, 0, 10, 10)}, canvas_size=1024, fill=1.0)


def test_compute_uniform_layout_rejects_empty_bboxes() -> None:
    with pytest.raises(ValueError):
        framing.compute_uniform_layout({}, canvas_size=1024, fill=0.85)


def test_compute_uniform_layout_rejects_zero_width_bbox() -> None:
    with pytest.raises(ValueError):
        framing.compute_uniform_layout({"front": (0, 0, 0, 10)}, canvas_size=1024, fill=0.85)
    with pytest.raises(ValueError):
        framing.compute_uniform_layout({"front": (0, 0, 10, 0)}, canvas_size=1024, fill=0.85)


def test_compute_uniform_layout_rejects_non_positive_canvas_size() -> None:
    with pytest.raises(ValueError):
        framing.compute_uniform_layout({"front": (0, 0, 10, 10)}, canvas_size=0, fill=0.85)


# ---------------------------------------------------------------- framing.build_sampler_params


def test_build_sampler_params_matches_upstream_defaults() -> None:
    params = framing.build_sampler_params(framing.DEFAULT_SETTINGS)
    assert params["sparse_structure_sampler_params"] == {
        "steps": 12, "guidance_strength": 7.5, "guidance_rescale": 0.7, "rescale_t": 5.0,
    }
    assert params["shape_slat_sampler_params"] == {
        "steps": 12, "guidance_strength": 7.5, "guidance_rescale": 0.5, "rescale_t": 3.0,
    }
    assert params["tex_slat_sampler_params"] == {
        "steps": 12, "guidance_strength": 1.0, "guidance_rescale": 0.0, "rescale_t": 3.0,
    }
    assert params["max_num_tokens"] == 49152


def test_build_sampler_params_pipeline_type_by_resolution() -> None:
    for resolution, expected in ((1024, "1024_cascade"), (1536, "1536_cascade")):
        settings = dict(framing.DEFAULT_SETTINGS, resolution=resolution)
        assert framing.build_sampler_params(settings)["pipeline_type"] == expected


# ---------------------------------------------------------------- 画面の説明表示（help_texts）
#
# px3d/ui.py は torch / gradio / pixal3d を import するため、ここではモジュールを
# import せず、ソースをテキストとして読んで elem_id と data-term を抜き出す
# （px3d/ui.py の docstring と CLAUDE.md の方針どおり、この試験は torch なしで走る）。

_UI_SOURCE = (Path(__file__).resolve().parents[1] / "px3d" / "ui.py").read_text(encoding="utf-8")

_ELEM_ID_RE = re.compile(r'elem_id="([^"]+)"')
_LITERAL_DATA_TERM_RE = re.compile(r'data-term=\\?"([^"\\]+)"')
_TERM_SPAN_CALL_RE = re.compile(r"""_term_span\(\s*['"]([^'"]+)['"]""")
_TERMS_LEGEND_CALL_RE = re.compile(r"_terms_legend\(\s*\[(.*?)\]\s*\)", re.S)
_QUOTED_RE = re.compile(r"""['"]([^'"]+)['"]""")


def _ui_elem_ids() -> list[str]:
    return _ELEM_ID_RE.findall(_UI_SOURCE)


def _ui_glossary_terms() -> set[str]:
    """ui.py が data-term として使っている専門用語を、書き方によらず抜き出す。

    `_term_span(term, label)` / `_terms_legend([term, ...])` を通した動的な
    生成と、`data-term="..."` の直書きの両方を拾う（どちらも term は python の
    文字列リテラルとしてソースにそのまま現れるため、テキスト検索で拾える）。
    """

    terms: set[str] = set()
    # data-term="{term}" は _term_span() の定義そのもの（f-string のプレース
    # ホルダ）なので、実際の用語ではない置換前の文字列を除く。
    terms.update(
        term for term in _LITERAL_DATA_TERM_RE.findall(_UI_SOURCE) if "{" not in term
    )
    terms.update(_TERM_SPAN_CALL_RE.findall(_UI_SOURCE))
    for legend_args in _TERMS_LEGEND_CALL_RE.findall(_UI_SOURCE):
        terms.update(_QUOTED_RE.findall(legend_args))
    return terms


def test_ui_elem_ids_found_at_least_expected_components() -> None:
    # 4 画像枠 + 基本 3 + 前処理 2 + サンプラー 13 + 書き出し 3 + ボタン 2 +
    # アコーディオン 2 = 29 個以上。
    assert len(set(_ui_elem_ids())) >= 29


def test_ui_elem_ids_all_have_tooltips() -> None:
    missing = help_texts.missing_tooltips(_ui_elem_ids())
    assert missing == [], f"title 未設定の elem_id があります: {missing}"


def test_ui_elem_ids_are_unique() -> None:
    elem_ids = _ui_elem_ids()
    assert len(elem_ids) == len(set(elem_ids)), "elem_id が重複しています"


def test_ui_glossary_terms_all_have_entries() -> None:
    terms = _ui_glossary_terms()
    assert terms, "ui.py から専門用語が 1 つも見つかりませんでした"
    missing = help_texts.missing_glossary_terms(sorted(terms))
    assert missing == [], f"GLOSSARY に無い用語が ui.py で使われています: {missing}"


def test_ui_glossary_terms_found_at_least_expected_count() -> None:
    # 依頼で明示された用語（VRAM、低 VRAM モード、シード、解像度、背景除去、
    # 物体の大きさ、疎構造、形状 SLat、テクスチャ SLat、手数、guidance strength、
    # guidance rescale、rescale t、max_num_tokens、decimation、テクスチャ解像度、
    # リメッシュ、PBR テクスチャ、GLB、frame 0）の 20 種類がすべて画面のどこかで
    # クリックできること。
    assert len(_ui_glossary_terms()) >= 20


def test_help_texts_tooltips_are_non_empty_and_not_too_short() -> None:
    for elem_id, text in help_texts.TOOLTIPS.items():
        assert text.strip(), f"{elem_id} の説明が空です"
        assert len(text) >= 20, f"{elem_id} の説明が短すぎます: {text!r}"


def test_help_texts_glossary_entries_have_title_and_body() -> None:
    assert help_texts.GLOSSARY
    for term, entry in help_texts.GLOSSARY.items():
        assert entry.get("title", "").strip(), f"{term} の title が空です"
        assert entry.get("body", "").strip(), f"{term} の body が空です"


def test_help_texts_glossary_json_round_trips() -> None:
    decoded = json.loads(help_texts.glossary_json())
    assert decoded == help_texts.GLOSSARY


def test_help_texts_missing_tooltips_reports_gap() -> None:
    assert help_texts.missing_tooltips(["front_input", "no_such_elem_id"]) == ["no_such_elem_id"]


def test_help_texts_missing_glossary_terms_reports_gap() -> None:
    assert help_texts.missing_glossary_terms(["VRAM", "no-such-term"]) == ["no-such-term"]


# ---------------------------------------------------------------- errors.classify_failure


def test_classify_failure_cuda_oom_variants() -> None:
    assert errors.classify_failure("CUDA out of memory. Tried to allocate 2.00 GiB") == "cuda_oom"
    assert (
        errors.classify_failure(
            "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 GiB "
            "(GPU 0; 23.69 GiB total capacity; ...)"
        )
        == "cuda_oom"
    )
    assert errors.classify_failure("RuntimeError: CUDA error: out of memory") == "cuda_oom"


def test_classify_failure_host_oom_variants() -> None:
    assert errors.classify_failure("MemoryError") == "host_oom"
    assert (
        errors.classify_failure(
            "DefaultCPUAllocator: not enough memory: you tried to allocate 42949672960 bytes."
        )
        == "host_oom"
    )
    assert errors.classify_failure("OSError: [Errno 12] Cannot allocate memory") == "host_oom"
    assert (
        errors.classify_failure("terminate called after throwing an instance of 'std::bad_alloc'")
        == "host_oom"
    )


def test_classify_failure_framing() -> None:
    assert (
        errors.classify_failure("front の外接矩形の幅または高さが 0 以下です: (0, 0, 0, 10)")
        == "framing"
    )


def test_classify_failure_unknown_for_unrelated_text() -> None:
    assert (
        errors.classify_failure("RuntimeError: mat1 and mat2 shapes cannot be multiplied") == "unknown"
    )


# ---------------------------------------------------------------- errors.diagnose (cuda_oom)

_ALL_MINIMUM_SETTINGS = {
    "resolution": 1024,
    "max_num_tokens": 16384,
    "texture_size": 1024,
    "decimation_target": 100000,
    "remesh": False,
    "fill": 0.60,
    "low_vram": True,
}


def test_diagnose_cuda_oom_low_vram_off_is_top_suspect() -> None:
    settings = dict(_ALL_MINIMUM_SETTINGS, low_vram=False, resolution=1536)
    diagnosis = errors.diagnose("cuda_oom", settings)
    assert diagnosis["suspects"][0]["label"] == "低 VRAM モード"


def test_diagnose_cuda_oom_low_vram_on_top_suspect_is_resolution() -> None:
    settings = dict(_ALL_MINIMUM_SETTINGS, low_vram=True, resolution=1536)
    diagnosis = errors.diagnose("cuda_oom", settings)
    assert diagnosis["suspects"][0]["label"] == "解像度"


def test_diagnose_cuda_oom_suspects_ordered_by_effectiveness() -> None:
    settings = dict(
        _ALL_MINIMUM_SETTINGS,
        low_vram=False,
        resolution=1536,
        max_num_tokens=49152,
        texture_size=4096,
        decimation_target=1000000,
    )
    diagnosis = errors.diagnose("cuda_oom", settings)
    labels = [suspect["label"] for suspect in diagnosis["suspects"]]
    assert labels == [
        "低 VRAM モード",
        "解像度",
        "max_num_tokens",
        "テクスチャ解像度",
        "面数の上限（decimation_target）",
    ]


def test_diagnose_cuda_oom_all_minimum_has_no_suspects_and_notes_it() -> None:
    diagnosis = errors.diagnose("cuda_oom", _ALL_MINIMUM_SETTINGS)
    assert diagnosis["suspects"] == []
    assert "最小" in diagnosis["note"]
    assert "Hunyuan3D" in diagnosis["note"]


# ---------------------------------------------------------------- errors.diagnose (host_oom)


def test_diagnose_host_oom_top_suspect_is_texture_size() -> None:
    settings = dict(_ALL_MINIMUM_SETTINGS, texture_size=4096)
    diagnosis = errors.diagnose("host_oom", settings)
    assert diagnosis["suspects"][0]["label"] == "テクスチャ解像度"
    assert "MemoryHigh" in diagnosis["note"]
    assert "MemoryMax" in diagnosis["note"]


def test_diagnose_host_oom_suspects_ordered_by_effectiveness() -> None:
    settings = dict(
        _ALL_MINIMUM_SETTINGS,
        texture_size=4096,
        decimation_target=1000000,
        remesh=True,
        resolution=1536,
    )
    diagnosis = errors.diagnose("host_oom", settings)
    labels = [suspect["label"] for suspect in diagnosis["suspects"]]
    assert labels == [
        "テクスチャ解像度",
        "面数の上限（decimation_target）",
        "リメッシュ",
        "解像度",
    ]


def test_diagnose_host_oom_all_minimum_still_mentions_memory_limits() -> None:
    diagnosis = errors.diagnose("host_oom", _ALL_MINIMUM_SETTINGS)
    assert diagnosis["suspects"] == []
    assert "MemoryHigh" in diagnosis["note"]
    assert "MemoryMax" in diagnosis["note"]


# ---------------------------------------------------------------- errors.diagnose (framing)


def test_diagnose_framing_has_only_fill_suspect() -> None:
    diagnosis = errors.diagnose("framing", {"fill": 0.85})
    assert len(diagnosis["suspects"]) == 1
    assert diagnosis["suspects"][0]["label"] == "物体の大きさ（fill）"
    assert diagnosis["suspects"][0]["current"] == 0.85
    assert diagnosis["suspects"][0]["suggested"] < 0.85


def test_diagnose_framing_fill_already_minimum_has_no_suspects() -> None:
    diagnosis = errors.diagnose("framing", {"fill": 0.60})
    assert diagnosis["suspects"] == []
    assert "最小" in diagnosis["note"]


# ---------------------------------------------------------------- errors.diagnose (unknown)


def test_diagnose_unknown_has_no_suspects_and_does_not_blame_settings() -> None:
    diagnosis = errors.diagnose("unknown", _ALL_MINIMUM_SETTINGS)
    assert diagnosis["suspects"] == []
    blamed_labels = (
        "解像度",
        "テクスチャ解像度",
        "max_num_tokens",
        "面数の上限",
        "リメッシュ",
        "低 VRAM モード",
        "物体の大きさ",
    )
    combined_text = diagnosis["headline"] + diagnosis["note"]
    for label in blamed_labels:
        assert label not in combined_text, f"unknown なのに {label} のせいにしています"


# ---------------------------------------------------------------- errors.format_failure_markdown


def test_format_failure_markdown_includes_suspects_and_original_exception() -> None:
    settings = dict(_ALL_MINIMUM_SETTINGS, low_vram=False, resolution=1536)
    diagnosis = errors.diagnose("cuda_oom", settings)
    error_text = "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 GiB"
    markdown = errors.format_failure_markdown(diagnosis, error_text)
    assert diagnosis["suspects"], "この設定なら suspects が出るはず"
    for suspect in diagnosis["suspects"]:
        assert suspect["label"] in markdown
        assert str(suspect["current"]) in markdown
        assert str(suspect["suggested"]) in markdown
    assert error_text in markdown


def test_format_failure_markdown_unknown_still_shows_exception_text() -> None:
    diagnosis = errors.diagnose("unknown", _ALL_MINIMUM_SETTINGS)
    error_text = "RuntimeError: mat1 and mat2 shapes cannot be multiplied"
    markdown = errors.format_failure_markdown(diagnosis, error_text)
    assert error_text in markdown


# ---------------------------------------------------------------- ui.py が診断を呼んでいること


def test_generate_source_wraps_body_in_try_except_and_calls_errors() -> None:
    match = re.search(r"\ndef _generate\(.*?(?=\ndef [a-zA-Z_]+\()", _UI_SOURCE, re.S)
    assert match, "_generate 関数が見つかりません"
    body = match.group(0)
    assert "try:" in body
    assert "except Exception" in body
    assert "errors.classify_failure(" in body
    assert "errors.diagnose(" in body
    assert "errors.format_failure_markdown(" in body


# ---------------------------------------------------------------- presets.validate_preset_name


def test_validate_preset_name_accepts_japanese_and_alnum_names() -> None:
    assert presets.validate_preset_name("高精細設定") is None
    assert presets.validate_preset_name("preset_01 (v2)") is None
    assert presets.validate_preset_name("あ" * 64) is None


def test_validate_preset_name_rejects_empty_and_whitespace_only() -> None:
    assert presets.validate_preset_name("") is not None
    assert presets.validate_preset_name("   ") is not None
    assert presets.validate_preset_name(None) is not None


def test_validate_preset_name_rejects_too_long() -> None:
    reason = presets.validate_preset_name("あ" * 65)
    assert reason is not None
    assert "64" in reason


def test_validate_preset_name_rejects_slash() -> None:
    reason = presets.validate_preset_name("a/b")
    assert reason is not None
    assert "/" in reason


def test_validate_preset_name_rejects_backslash() -> None:
    reason = presets.validate_preset_name("a\\b")
    assert reason is not None
    assert "\\" in reason


def test_validate_preset_name_rejects_dotdot() -> None:
    reason = presets.validate_preset_name("..")
    assert reason is not None
    assert ".." in reason


def test_validate_preset_name_rejects_leading_dot() -> None:
    reason = presets.validate_preset_name(".hidden")
    assert reason is not None


def test_validate_preset_name_rejects_control_characters() -> None:
    reason = presets.validate_preset_name("abc\x00def")
    assert reason is not None


def test_validate_preset_name_allows_percent_and_other_safe_symbols() -> None:
    """`%` のように Windows / SMB で問題にならない記号は使えること。

    `%2f` は文字列としての「/」の表現に過ぎず、ファイルシステムは「/」として解釈しない
    （実際に presets/ の外を指さないことは preset_path 側の試験で確かめている）。
    """
    assert presets.validate_preset_name("設定%2f") is None
    assert presets.validate_preset_name("設定 100%") is None


# ---------------------------------------------------------------- presets.preset_path


def test_preset_path_default_dir_points_into_tool_dir() -> None:
    assert presets._presets_dir() == config.TOOL_DIR / "presets"


def test_preset_path_is_inside_presets_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    path = presets.preset_path("設定A")
    assert path.parent == tmp_path.resolve()
    assert path.name == "設定A.json"


def test_preset_path_keeps_percent_encoded_slash_inside_presets_dir(tmp_path, monkeypatch) -> None:
    """`%2f` を名前にしても presets/ の外は指さないこと。

    ファイルシステムは `%2f` を「/」として解釈しないため、ディレクトリを抜けることはない。
    名前の検証で弾くのではなく、パスが presets/ 直下に収まることで安全を担保している。
    """
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    resolved = presets.preset_path("%2f").resolve()
    assert resolved.parent == tmp_path.resolve()
    assert resolved.name == "%2f.json"


def test_preset_path_blocks_escape_even_if_name_validation_is_bypassed(tmp_path, monkeypatch) -> None:
    # validate_preset_name をすり抜ける細工があっても、preset_path 単体の防御
    # （解決済みパスが presets ディレクトリ直下かの確認）が効くことを確認する。
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    monkeypatch.setattr(presets, "validate_preset_name", lambda name: None)
    with pytest.raises(ValueError):
        presets.preset_path("../escape")
    with pytest.raises(ValueError):
        presets.preset_path("../../../../etc/passwd")


# ---------------------------------------------------------------- presets.save_preset / load_preset


def test_save_and_load_preset_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    settings = dict(framing.DEFAULT_SETTINGS, seed=123, fill=0.7)
    path = presets.save_preset("試験用", settings)
    assert path.exists()

    result = presets.load_preset("試験用")
    assert result["ignored"] == []
    assert result["settings"] == dict(framing.DEFAULT_SETTINGS, seed=123, fill=0.7)


def test_save_preset_keeps_only_default_settings_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    settings = dict(framing.DEFAULT_SETTINGS, low_vram=True, extra_junk="x")
    path = presets.save_preset("フィルタ試験", settings)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["format"] == 1
    assert saved["tool"] == "pixal3d"
    assert "saved_at" in saved
    assert set(saved["settings"].keys()) == set(framing.DEFAULT_SETTINGS.keys())


def test_save_preset_overwrites_existing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    presets.save_preset("上書き試験", dict(framing.DEFAULT_SETTINGS, seed=1))
    presets.save_preset("上書き試験", dict(framing.DEFAULT_SETTINGS, seed=2))
    assert presets.load_preset("上書き試験")["settings"]["seed"] == 2
    assert len(presets.list_presets()) == 1


def test_load_preset_ignores_unknown_keys_and_fills_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "tool": "pixal3d",
        "saved_at": "2026-01-01T00:00:00+09:00",
        "settings": {"seed": 7, "no_such_key": "x"},
    }
    (tmp_path / "部分.json").write_text(json.dumps(payload), encoding="utf-8")

    result = presets.load_preset("部分")
    assert result["settings"]["seed"] == 7
    assert result["settings"]["fill"] == framing.DEFAULT_SETTINGS["fill"]
    assert "no_such_key" not in result["settings"]
    assert result["ignored"] == []


def test_load_preset_out_of_range_values_fall_back_to_default_and_are_reported(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "tool": "pixal3d",
        "saved_at": "x",
        "settings": {"fill": 5.0, "resolution": 999, "texture_size": "abc"},
    }
    (tmp_path / "壊れ値.json").write_text(json.dumps(payload), encoding="utf-8")

    result = presets.load_preset("壊れ値")
    assert result["settings"]["fill"] == framing.DEFAULT_SETTINGS["fill"]
    assert result["settings"]["resolution"] == framing.DEFAULT_SETTINGS["resolution"]
    assert result["settings"]["texture_size"] == framing.DEFAULT_SETTINGS["texture_size"]
    assert set(result["ignored"]) == {"fill", "resolution", "texture_size"}


def test_load_preset_rejects_bool_disguised_as_int_or_float(tmp_path, monkeypatch) -> None:
    # bool は int のサブクラスなので、True/False が誤って範囲チェックを通り抜けないこと。
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {"settings": {"seed": True, "fill": False}}
    (tmp_path / "bool試験.json").write_text(json.dumps(payload), encoding="utf-8")

    result = presets.load_preset("bool試験")
    assert set(result["ignored"]) == {"seed", "fill"}
    assert result["settings"]["seed"] == framing.DEFAULT_SETTINGS["seed"]
    assert result["settings"]["fill"] == framing.DEFAULT_SETTINGS["fill"]


def test_load_preset_missing_file_raises_file_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        presets.load_preset("無い設定")


def test_load_preset_broken_json_raises_value_error_in_japanese(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "壊れJSON.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        presets.load_preset("壊れJSON")
    assert re.search(r"[ぁ-んァ-ヶ一-龥]", str(excinfo.value)), "日本語のメッセージではありません"


def test_load_preset_settings_not_dict_raises_value_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "settings無し.json").write_text(json.dumps({"format": 1}), encoding="utf-8")

    with pytest.raises(ValueError):
        presets.load_preset("settings無し")


# ---------------------------------------------------------------- presets.list_presets / delete_preset


def test_list_presets_returns_sorted_names(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    for name in ("う設定", "あ設定", "い設定"):
        presets.save_preset(name, framing.DEFAULT_SETTINGS)
    assert presets.list_presets() == ["あ設定", "い設定", "う設定"]


def test_list_presets_missing_dir_returns_empty_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path / "no-such-dir")
    assert presets.list_presets() == []


def test_delete_preset_removes_file_and_returns_true_then_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "_presets_dir", lambda: tmp_path)
    presets.save_preset("消す設定", framing.DEFAULT_SETTINGS)
    assert presets.delete_preset("消す設定") is True
    assert presets.delete_preset("消す設定") is False


def test_delete_preset_missing_returns_false_without_creating_dir(tmp_path, monkeypatch) -> None:
    missing_dir = tmp_path / "not-created-yet"
    monkeypatch.setattr(presets, "_presets_dir", lambda: missing_dir)
    assert presets.delete_preset("無い設定") is False
    assert not missing_dir.exists()


# ---------------------------------------------------------------- ui.py が px3d.presets を使っていること


def test_ui_source_load_preset_outputs_setting_inputs() -> None:
    assert "outputs=setting_inputs" in _UI_SOURCE


def test_ui_source_calls_presets_module_functions() -> None:
    for call in (
        "presets.save_preset(",
        "presets.load_preset(",
        "presets.delete_preset(",
        "presets.list_presets(",
    ):
        assert call in _UI_SOURCE, f"ui.py が {call} を呼んでいません"


def test_validate_preset_name_allows_natural_japanese_names() -> None:
    """日本語で自然に打つ名前が通ること。

    許可文字を絞り込む方式にすると「高精細（試し）」のような全角括弧・全角空白・かぎ括弧が
    弾かれて使いものにならない。危ない文字だけを弾く方式にしてある。
    """
    for name in ("高精細（試し）", "ドレス用　高品質", "夜間バッチ「標準」", "fast-draft", "試作 v2"):
        assert presets.validate_preset_name(name) is None, name


def test_validate_preset_name_rejects_windows_invalid_characters() -> None:
    """Windows / SMB で使えない文字を弾くこと。

    presets/ は git で追跡し、リモートは CIFS マウント（/mnt/nas）にある。Windows で無効な
    ファイル名だと push できなくなるため、この場で弾く。
    """
    for name in ("a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"):
        assert presets.validate_preset_name(name) is not None, name
    assert presets.validate_preset_name("末尾に空白 ") is not None
    assert presets.validate_preset_name("末尾にドット.") is not None
