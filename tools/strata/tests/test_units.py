"""stra と scripts/ の単体試験。GPU もネットワークも使わない。

実行: uvx --with pytest pytest tools/strata/tests -q
    （.venv には pytest を入れない。素の python + pytest だけで動く）
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import re
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))
sys.path.insert(0, str(TOOL_DIR / "scripts"))

import bench_api  # noqa: E402
import monitor  # noqa: E402
import pytest  # noqa: E402
from stra import checks, config  # noqa: E402
from stra.cli import _server_config, build_parser  # noqa: E402

GIB = 1024**3


# ---------------------------------------------------------------- 判定（checks）


def test_classify_nvcc() -> None:
    output = "nvcc: NVIDIA (R) Cuda compiler driver\nCuda compilation tools, release 13.2, V13.2.86\nBuild cuda_13.2.r13.2/compiler.37953736_0\n"
    assert checks.classify_nvcc(output, "13.2") == (True, "Build cuda_13.2.r13.2/compiler.37953736_0")
    assert checks.classify_nvcc(output.replace("13.2", "12.6"), "13.2")[0] is False
    assert checks.classify_nvcc(None, "13.2") == (False, "nvcc を実行できませんでした")
    assert checks.classify_nvcc("  ", "13.2") == (False, "nvcc の出力が空でした")


def test_classify_commit() -> None:
    assert checks.classify_commit("abc", "abc") == (True, "HEAD=abc")
    assert checks.classify_commit("def", "abc")[0] is False
    assert checks.classify_commit(None, "abc")[0] is False


def test_classify_build_stamp() -> None:
    stamp = {"src": config.STRATA_COMMIT, "cuda": config.CUDA_HOME, "archs": [80], "version": "0.1.44.1"}
    ok, detail = checks.classify_build_stamp(stamp, 51836336, config.STRATA_COMMIT, config.CUDA_HOME, "80")
    assert ok and "sm_80" in detail and "0.1.44.1" in detail
    assert checks.classify_build_stamp(stamp, None, config.STRATA_COMMIT, config.CUDA_HOME, "80")[0] is False
    assert checks.classify_build_stamp(None, 1, config.STRATA_COMMIT, config.CUDA_HOME, "80")[0] is False
    old = dict(stamp, src="0" * 40)
    ok, detail = checks.classify_build_stamp(old, 1, config.STRATA_COMMIT, config.CUDA_HOME, "80")
    assert not ok and "--rebuild" in detail
    other_cuda = dict(stamp, cuda="/usr/local/cuda-12.6", archs=[86])
    ok, detail = checks.classify_build_stamp(other_cuda, 1, config.STRATA_COMMIT, config.CUDA_HOME, "80")
    assert not ok and "cuda=" in detail and "archs=" in detail


def test_classify_model_file_and_url() -> None:
    assert checks.classify_model_file(10, 10) == (True, "10 バイト")
    assert "GiB" in checks.classify_model_file(2 * GIB, 2 * GIB)[1]
    assert checks.classify_model_file(9, 10)[0] is False
    ok, detail = checks.classify_model_file(None, 10 * GIB, partial_size=4 * GIB)
    assert not ok and "途中" in detail and "4.0 / 10.0" in detail
    assert "fetch-models" in checks.classify_model_file(None, 10)[1]
    assert (
        checks.model_url("https://huggingface.co/", "a/b", "c" * 40, "pack/dense.bin")
        == "https://huggingface.co/a/b/resolve/" + "c" * 40 + "/pack/dense.bin"
    )


def test_parse_memlock() -> None:
    limits = (
        "Limit                     Soft Limit           Hard Limit           Units     \n"
        "Max open files            1024                 524288               files     \n"
        "Max locked memory         8384606208           8384606208           bytes     \n"
    )
    assert checks.parse_memlock(limits) == (8384606208, 8384606208)
    assert checks.parse_memlock("Max locked memory         unlimited            unlimited            bytes\n") == (None, None)
    assert checks.parse_memlock("Max open files 1 2 files\n") is None


def test_classify_memlock_is_informational() -> None:
    low = checks.classify_memlock((8384606208, 8384606208), 48 * GIB, "この端末")
    assert low[0] is True and "7.8 GiB" in low[1] and "README" in low[1]
    assert checks.classify_memlock((None, None), 48 * GIB, "x") == (True, "x: soft unlimited / hard unlimited")
    assert checks.classify_memlock(None, 48 * GIB, "x")[0] is True


def test_parse_meminfo_and_classify_ram() -> None:
    meminfo = checks.parse_meminfo(
        "MemTotal:       65536000 kB\nMemAvailable:   52428800 kB\nSwapTotal:      25165824 kB\nSwapFree:       24117248 kB\nHugePages_Total:       0\n"
    )
    assert meminfo["MemTotal"] == 65536000 * 1024
    assert meminfo["HugePages_Total"] == 0
    ok, detail = checks.classify_ram(meminfo, 44, service_active=False)
    assert ok and "50.0 / 62.5 GiB" in detail and "swap 使用 1.0 GiB" in detail
    assert checks.classify_ram(meminfo, 60, service_active=False)[0] is False
    assert checks.classify_ram(meminfo, 60, service_active=True)[0] is True
    assert checks.classify_ram({}, 44, service_active=False)[0] is False


def test_vram_and_ollama_are_informational() -> None:
    assert checks.parse_nvidia_smi_memory("16, 24576\n") == (16, 24576)
    assert checks.parse_nvidia_smi_memory("") is None
    assert checks.parse_nvidia_smi_memory("x, y") is None
    assert checks.classify_vram((16, 24576), 20000, False) == (True, "使用中 16 / 24576 MiB（空き 24560 MiB）")
    busy = checks.classify_vram((22000, 24576), 20000, False)
    assert busy[0] is True and "降ろす" in busy[1]
    assert checks.classify_vram(None, 20000, False)[0] is True

    body = json.dumps({"models": [{"name": "qwen3.8:27b", "size_vram": 22 * GIB}]})
    models = checks.parse_ollama_ps(body)
    assert models == [("qwen3.8:27b", 22 * GIB)]
    ok, detail = checks.classify_ollama(models)
    assert ok and "qwen3.8:27b" in detail and "22.0 GiB" in detail
    assert checks.classify_ollama([]) == (True, "載っているモデルはありません")
    assert checks.classify_ollama(None)[0] is True
    assert checks.parse_ollama_ps("not json") is None
    assert checks.parse_ollama_ps(None) is None


def test_classify_port_status() -> None:
    assert checks.classify_port_status(8082, False, False)[0] is True
    assert "読み込み" in checks.classify_port_status(8082, False, True)[1]
    assert checks.classify_port_status(8082, True, True)[0] is True
    assert checks.classify_port_status(8082, True, False)[0] is False


def test_max_context_from_env() -> None:
    assert checks.max_context_from_env({}, "STRATA_MAX_CONTEXT", 65536) == 65536
    assert checks.max_context_from_env({"STRATA_MAX_CONTEXT": " 131072 "}, "STRATA_MAX_CONTEXT", 65536) == 131072
    for bad in ("abc", "1024", "300000"):
        with pytest.raises(ValueError):
            checks.max_context_from_env({"STRATA_MAX_CONTEXT": bad}, "STRATA_MAX_CONTEXT", 65536)


def test_reasoning_budget_from_env() -> None:
    variable = "STRATA_REASONING_BUDGET_TOKENS"
    # 空・未設定は既定
    assert checks.reasoning_budget_from_env({}, variable, 32768, 131072) == 32768
    assert checks.reasoning_budget_from_env({variable: "  "}, variable, 0, 131072) == 0
    assert checks.reasoning_budget_from_env({variable: " 32768 "}, variable, 0, 131072) == 32768
    # 0 は予算なし（既定が 32768 でも env の 0 で無効にできる）
    assert checks.reasoning_budget_from_env({variable: "0"}, variable, 32768, 131072) == 0
    assert checks.reasoning_budget_from_env({variable: "131071"}, variable, 0, 131072) == 131071
    # 整数でない・負・文脈長以上は ValueError（予算が文脈長と同じだと答えの余地が無い）
    for bad in ("abc", "1.5", "-1", "131072", "200000"):
        with pytest.raises(ValueError, match=variable):
            checks.reasoning_budget_from_env({variable: bad}, variable, 32768, 131072)


def test_extra_args_from_env() -> None:
    assert checks.extra_args_from_env({}, "STRATA_EXTRA_ARGS") == []
    assert checks.extra_args_from_env({"STRATA_EXTRA_ARGS": "--stats --adapt-async 1"}, "STRATA_EXTRA_ARGS") == [
        "--stats", "--adapt-async", "1",
    ]


def test_build_engine_args_follow_model_card_and_resident_mode() -> None:
    engine_args = checks.build_engine_args(
        pack_dir="/m/pack", gguf_path="/m/x.gguf", expert_profile="/s/data/expert-profile.bin", max_context=65536,
        mtp_dir=None, extra_args=["--stats"],
    )
    pairs = dict(zip(engine_args[::2], engine_args[1::2]))
    # モデルカードの起動例（README.md:56-62）と同じ値
    assert pairs["--pack"] == "/m/pack"
    assert pairs["--native"] == "/m/x.gguf" and pairs["--ple-gguf"] == "/m/x.gguf"
    assert pairs["--expert-profile"] == "/s/data/expert-profile.bin"
    assert (pairs["--expert-cache"], pairs["--prefill"], pairs["--spec"], pairs["--kv"]) == ("auto", "auto", "4", "int8")
    assert pairs["--max-context"] == "65536"
    # RAM 62.5 GiB に合わせた変更: resident の low-RAM モード、KV は VRAM（--kv-resident なし）
    assert "--resident-experts" in engine_args
    assert "--kv-resident" not in engine_args
    assert "--mtp" not in engine_args and "--spec-min-p" not in engine_args
    assert engine_args[-1] == "--stats"


def test_build_engine_args_with_mtp() -> None:
    engine_args = checks.build_engine_args(
        pack_dir="/m/pack", gguf_path="/m/x.gguf", expert_profile="/p", max_context=131072, mtp_dir="/m/mtp/rt",
    )
    pairs = dict(zip(engine_args[::2], engine_args[1::2]))
    # 上流 setup.py が --mtp と一緒に書く値（setup.py:4775-4777）
    assert pairs["--mtp"] == "/m/mtp/rt" and pairs["--spec-min-p"] == "0.5" and pairs["--spec"] == "4"
    assert pairs["--max-context"] == "131072"
    assert engine_args.count("--mtp") == 1


def test_build_server_config_and_command() -> None:
    server_config = checks.build_server_config(
        engine_exe="/s/engine/strata", engine_args=["--pack", "p"], strata_dir="/s", tokenizer_dir="/m/pack/tokenizer",
        model_name="strata-flash-next:IQ3_S", engine_log="/l/e.log", lib_dirs=["/usr/local/cuda-13.2/lib64"],
        host="0.0.0.0", port=8082,
    )
    # docs/ORCA.md:53-76 と setup.py が書く鍵
    assert set(server_config) == {"exe", "args", "cwd", "tokenizer", "model_name", "log", "lib_dirs", "host", "port"}
    command = checks.build_serve_command(python_bin="/v/python", config_path="/r/c.json", host="0.0.0.0", port=8082)
    assert command == [
        "/v/python", "-m", "serve.server", "--engine", "strata", "--config", "/r/c.json", "--host", "0.0.0.0", "--port", "8082",
    ]


def test_server_config_uses_tool_paths() -> None:
    server_config = _server_config(65536, [], use_mtp=True)
    assert server_config["exe"] == str(config.ENGINE_EXE)
    assert server_config["cwd"] == str(config.STRATA_DIR)
    assert server_config["port"] == 8082 and server_config["host"] == "0.0.0.0"
    assert server_config["lib_dirs"] == ["/usr/local/cuda-13.2/lib64"]
    assert str(config.GGUF_PATH) in server_config["args"]
    assert str(config.MTP_RT_DIR) in server_config["args"]
    assert "--mtp" not in _server_config(65536, [], use_mtp=False)["args"]


def test_default_context_was_widened() -> None:
    # 65536 から始め、実測で 131072（2026-10-07）→ モデルの上限 262144（2026-10-18）に広げた（config.DEFAULT_MAX_CONTEXT の注記）
    assert config.DEFAULT_MAX_CONTEXT == 262144
    assert all(spec.default_max_context == 262144 for spec in config.MODELS.values())


def test_classify_health() -> None:
    assert checks.classify_health(json.dumps({"loaded": True, "model": "m", "max_context": 65536})) == (
        True, "model=m, max_context=65536",
    )
    assert checks.classify_health(json.dumps({"loaded": False}))[0] is False
    assert checks.classify_health(None)[0] is False
    assert checks.classify_health("<html>")[0] is False


def test_summarize() -> None:
    overall, lines = checks.summarize([("a", True, "x"), ("b", False, "y")])
    assert overall is False
    assert lines == ["OK  a: x", "NG  b: y"]


def test_parser_defaults() -> None:
    parser = build_parser()
    serve = parser.parse_args(["serve"])
    assert (serve.host, serve.port, serve.max_context, serve.no_mtp) == ("0.0.0.0", 8082, None, False)
    wait = parser.parse_args(["wait-ready"])
    assert wait.port == 8082 and wait.timeout < 900
    assert parser.parse_args(["fetch-models", "--verify"]).verify is True


# ---------------------------------------------------------------- 定数と直値の食い違い


def test_model_files_table() -> None:
    names = [path for path, _size, _sha in config.MODEL_FILES]
    assert config.GGUF_NAME in names and "pack/dense.bin" in names and "pack/tokenizer/vocab.json" in names
    assert len(set(names)) == len(names)
    for path, size, sha256 in config.MODEL_FILES:
        assert size > 0, path
        assert re.fullmatch(r"[0-9a-f]{64}", sha256), path
    assert re.fullmatch(r"[0-9a-f]{40}", config.MODEL_REVISION)
    # pack/native_experts.txt の見出しの total と同じ（48 層 x 512 エキスパート x 2329600 バイト）
    assert config.EXPERT_BYTES == 48 * 512 * 2329600


def test_model_name_fits_open_webui() -> None:
    assert len(config.MODEL_NAME) <= 28


def test_setup_script_pins_match_config() -> None:
    text = (TOOL_DIR / "setup-server.sh").read_text(encoding="utf-8")
    for line in (
        f'STRATA_URL="{config.STRATA_URL}"',
        f'STRATA_TAG="{config.STRATA_TAG}"',
        f'STRATA_COMMIT="{config.STRATA_COMMIT}"',
        f'STRATA_ENGINE_VERSION="{config.STRATA_ENGINE_VERSION}"',
        f'LLAMA_CPP_URL="{config.LLAMA_CPP_URL}"',
        f'LLAMA_CPP_COMMIT="{config.LLAMA_CPP_COMMIT}"',
        f'CUDA_HOME_DIR="{config.CUDA_HOME}"',
        f'CUDA_ARCH="{config.CUDA_ARCH}"',
    ):
        assert line in text.splitlines(), line
    assert "set -euo pipefail" in text
    # 上流の自動導入と違い、sudo も enable も使わない
    assert not re.search(r"^\s*sudo ", text, flags=re.MULTILINE)
    assert "systemctl --user enable" not in text


def test_llama_cpp_pin_matches_upstream_setup_when_vendor_exists() -> None:
    upstream = config.STRATA_DIR / "setup.py"
    if not upstream.is_file():
        pytest.skip("vendor/Strata がありません")
    text = upstream.read_text(encoding="utf-8")
    assert f'LLAMA_CPP_COMMIT = "{config.LLAMA_CPP_COMMIT}"' in text
    cmake = (config.STRATA_DIR / "CMakeLists.txt").read_text(encoding="utf-8")
    assert f"project(strata VERSION {config.STRATA_ENGINE_VERSION} " in cmake


def test_service_example() -> None:
    text = config.SERVICE_EXAMPLE.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in (
        "EnvironmentFile=-%h/.config/strata/strata.env",
        "ExecStart=@REPO_ROOT@/tools/strata/run-strata serve",
        "Restart=on-failure",
        "TimeoutStartSec=900",
        "LimitMEMLOCK=infinity",
    ):
        assert line in lines, line
    limits = {}
    for line in lines:
        match = re.fullmatch(r"(MemoryHigh|MemoryMax)=(\d+)G", line)
        if match:
            limits[match.group(1)] = int(match.group(2))
    assert set(limits) == {"MemoryHigh", "MemoryMax"}
    assert limits["MemoryHigh"] < limits["MemoryMax"] <= 58
    # MemoryHigh は実測で決めた値（落とせない分 約 43.5 GiB より上）。MemoryMax は 2026-10-09 の利用者の指示で 54 → 58
    assert (limits["MemoryHigh"], limits["MemoryMax"]) == (50, 58)
    # wait-ready の制限時間は TimeoutStartSec より短い
    match = re.search(r"wait-ready --timeout (\d+)", text)
    assert match and int(match.group(1)) < 900


# ---------------------------------------------------------------- scripts


def test_monitor_parse_and_summarize() -> None:
    pressure = monitor.parse_pressure(
        "some avg10=1.50 avg60=0.20 avg300=0.00 total=2000000\nfull avg10=0.50 avg60=0.10 avg300=0.00 total=1000000\n"
    )
    assert pressure["some_avg10"] == 1.5 and pressure["full_total"] == 1000000.0
    rows = [
        {"t": 0.0, "cg_peak": 1 * GIB, "swap_used": 0, "psi_memory_some_total": 0.0, "psi_memory_some_avg10": 0.0},
        {"t": 10.0, "cg_peak": 3 * GIB, "swap_used": GIB, "psi_memory_some_total": 2e6, "psi_memory_some_avg10": 4.0},
    ]
    summary = monitor.summarize(rows)
    assert summary["cg_peak_gib"] == 3.0
    assert summary["swap_used_delta_gib"] == 1.0
    assert summary["psi_memory_some_stall_s"] == 2.0
    assert summary["psi_memory_some_stall_pct"] == 20.0
    assert summary["psi_memory_some_avg10_max"] == 4.0


def test_build_mtp_script_uses_upstream_steps() -> None:
    text = (TOOL_DIR / "scripts" / "build-mtp.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    # 上流 setup.py:4753-4757 と同じ 3 段と、既定の draft の語彙（cjk = data/draft_vocab.bin）
    for fragment in ("mtp_fetch.py\" fetch", "mtp_pack.py\" --src", "--experts q2_0", "mtp_rt.py\" --gguf",
                     "data/draft_vocab.bin"):
        assert fragment in text, fragment


def test_bench_long_prompt_varies_by_nonce() -> None:
    first = bench_api.build_long_prompt(5600, 1)
    second = bench_api.build_long_prompt(5600, 2)
    assert len(first) >= 5600
    # 会話のキャッシュに先頭を使い回されないよう、先頭が変わる
    assert first[:20] != second[:20]


# ---------------------------------------------------------------- モデル別の設定（rvn / coder / official）


def test_model_specs_table() -> None:
    assert set(config.MODELS) == {"rvn", "coder", "official", "official-iq3s", "swift"} and config.DEFAULT_MODEL == "rvn"
    rvn, coder = config.MODELS["rvn"], config.MODELS["coder"]
    # rvn は以前からのモジュール直下の定数と同じ値（既存の呼び出し元の互換）
    assert (rvn.model_dir, rvn.native_gguf, rvn.ple_gguf, rvn.pack_dir) == (
        config.MODEL_DIR, config.GGUF_PATH, config.GGUF_PATH, config.PACK_DIR,
    )
    assert (rvn.files, rvn.revision, rvn.repo) == (config.MODEL_FILES, config.MODEL_REVISION, config.MODEL_REPO)
    assert (rvn.model_name, rvn.port, rvn.service_name) == (config.MODEL_NAME, 8082, "strata")
    assert (rvn.server_config, rvn.engine_log, rvn.env_file) == (config.SERVER_CONFIG, config.ENGINE_LOG, config.ENV_FILE)
    assert rvn.tokenizer_dir == config.TOKENIZER_DIR and rvn.expert_profile == config.EXPERT_PROFILE
    # 2026-10-18 から KV ストリーミング（--kv-resident 65536。262144 で枠が増えて 4% 速い。config の RVN の注記）
    assert rvn.resident_experts is True and rvn.kv_resident == 65536 and rvn.pack_built_locally is False
    # coder（依頼で決めた名前・ポート・置き場）
    assert coder.model_dir == config.MODELS_DIR / "Qwen3.8-Flash-Next-Coder-IQ1_M"
    assert (coder.model_name, coder.port, coder.service_name) == ("strata-flash-coder:IQ1_M", 8083, "strata-coder")
    assert coder.env_file == Path.home() / ".config" / "strata" / "strata-coder.env"
    assert coder.expert_profile == config.STRATA_DIR / "data" / "expert-profile-coder.bin"
    assert coder.server_config == config.RUN_DIR / "strata-server-coder.json"
    assert coder.service_example == TOOL_DIR / "systemd" / "strata-coder.service.example"
    assert coder.pack_built_locally is True and coder.pack_dir == coder.model_dir / "pack"
    # 5 つのモデルは別の名前・ポート・ユニット・設定ファイル・ログ・置き場を使う（同じ engine を共有する）
    for attribute in ("model_name", "port", "service_name", "server_config", "engine_log", "env_file", "model_dir",
                      "pack_dir", "service_example"):
        values = [getattr(spec, attribute) for spec in config.MODELS.values()]
        assert len(set(values)) == len(values), attribute
    for spec in config.MODELS.values():
        assert len(spec.model_name) <= 28, spec.key
        assert spec.min_available_ram_gib > 0 and spec.recommended_memlock_bytes > 0
        assert spec.min_free_vram_mib == config.MIN_FREE_VRAM_MIB
    # 実測で決めた Coder の起動の形: 通常のモード（全部 RAM）、KV は VRAM、文脈長はモデルの上限 262144
    assert (coder.resident_experts, coder.kv_resident, coder.default_max_context) == (False, None, 262144)
    assert coder.min_available_ram_gib == 30


def test_coder_files_are_the_pinned_shards() -> None:
    coder = config.CODER
    assert coder.repo == "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF"
    assert coder.revision == "5348543e0147355ac9cbcb031184a3546350988e"
    names = [path for path, _size, _sha in coder.files]
    assert names == ["README.md", "IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf",
                     "IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf"]
    for path, size, sha256 in coder.files:
        assert size > 0 and re.fullmatch(r"[0-9a-f]{64}", sha256), path
    # --native は shard 1、--ple-gguf は PLE の表を持つ shard 2（gguf_reader で確かめた）
    assert coder.native_gguf == coder.model_dir / names[1]
    assert coder.ple_gguf == coder.model_dir / names[2]
    # 画像用の mmproj は取らない
    assert not any("mmproj" in name for name in names)
    sizes = {path: size for path, size, _sha in coder.files}
    assert sizes[names[1]] == 29608446496 and sizes[names[2]] == 28800138432
    # 手元で作った pack の native_experts.txt の total（48 層 x 256 エキスパート）
    assert coder.expert_bytes == 25146163200
    if (coder.pack_dir / "native_experts.txt").is_file():
        header = checks.parse_native_experts_header((coder.pack_dir / "native_experts.txt").read_text(encoding="utf-8"))
        assert header == (256, coder.expert_bytes)


def test_model_spec_lookup() -> None:
    assert config.model_spec("coder") is config.CODER and config.model_spec("rvn") is config.RVN
    assert config.model_spec("official") is config.OFFICIAL
    assert config.model_spec("official-iq3s") is config.OFFICIAL_IQ3S and config.model_spec("swift") is config.SWIFT
    with pytest.raises(ValueError):
        config.model_spec("qwen")


def test_build_engine_args_for_split_gguf_without_resident() -> None:
    engine_args = checks.build_engine_args(
        pack_dir="/c/pack", gguf_path="/c/s1.gguf", ple_gguf="/c/s2.gguf", expert_profile="/s/data/expert-profile-coder.bin",
        max_context=131072, mtp_dir="/m/rt", resident_experts=False, kv_resident=32768,
    )
    pairs = dict(zip(engine_args[::2], engine_args[1::2]))
    assert pairs["--native"] == "/c/s1.gguf" and pairs["--ple-gguf"] == "/c/s2.gguf"
    assert "--resident-experts" not in engine_args
    assert engine_args[engine_args.index("--kv-resident") + 1] == "32768"
    no_stream = checks.build_engine_args(
        pack_dir="/c/pack", gguf_path="/c/s1.gguf", ple_gguf="/c/s2.gguf", expert_profile="/p", max_context=131072,
        mtp_dir=None, resident_experts=False, kv_resident=None,
    )
    assert "--kv-resident" not in no_stream and "--resident-experts" not in no_stream


def test_rvn_server_config_final_args() -> None:
    # 汎用版の engine の引数（README の「最終の起動引数」）。2026-10-18 に --kv-resident 65536 と --adapt-async 1 を足した
    server_config = _server_config(262144, [], use_mtp=True)
    assert server_config == _server_config(262144, [], True, config.RVN)
    assert server_config["args"] == [
        "--pack", str(config.PACK_DIR), "--native", str(config.GGUF_PATH), "--ple-gguf", str(config.GGUF_PATH),
        "--expert-profile", str(config.EXPERT_PROFILE), "--expert-cache", "auto", "--prefill", "auto",
        "--spec", "4", "--spec-min-p", "0.5", "--mtp", str(config.MTP_RT_DIR), "--max-context", "262144",
        "--kv", "int8", "--kv-resident", "65536", "--resident-experts", "--adapt-async", "1",
    ]
    assert (server_config["model_name"], server_config["port"]) == ("strata-flash-next:IQ3_S", 8082)
    assert server_config["log"] == str(config.ENGINE_LOG) and server_config["tokenizer"] == str(config.TOKENIZER_DIR)


def test_coder_server_config() -> None:
    coder = config.CODER
    server_config = _server_config(131072, ["--stats"], True, coder)
    args = server_config["args"]
    pairs = dict(zip(args[::2], args[1::2]))
    assert pairs["--pack"] == str(coder.pack_dir)
    assert pairs["--native"] == str(coder.native_gguf) and pairs["--ple-gguf"] == str(coder.ple_gguf)
    assert pairs["--expert-profile"] == str(config.STRATA_DIR / "data" / "expert-profile-coder.bin")
    assert pairs["--mtp"] == str(config.MTP_RT_DIR) and pairs["--max-context"] == "131072"
    assert ("--resident-experts" in args) is coder.resident_experts
    assert ("--kv-resident" in args) is (coder.kv_resident is not None)
    assert args[-1] == "--stats"
    assert server_config["model_name"] == "strata-flash-coder:IQ1_M" and server_config["port"] == 8083
    assert server_config["tokenizer"] == str(coder.pack_dir / "tokenizer")
    assert server_config["log"] == str(config.LOGS_DIR / "strata-coder-engine.log")
    assert server_config["exe"] == str(config.ENGINE_EXE) and server_config["cwd"] == str(config.STRATA_DIR)


def test_server_config_puts_model_engine_extra_args_before_env_extras() -> None:
    # ModelSpec.engine_extra_args（モデル固有の速さの設定）は、env の STRATA_EXTRA_ARGS / serve --extra より前に置く
    # （後ろのものが同じ引数を上書きできる）。無いモデルでは何も足さない
    spec = dataclasses.replace(config.CODER, engine_extra_args=("--adapt-async", "1", "--kv-grow"))
    args = _server_config(262144, ["--stats"], True, spec)["args"]
    assert args[-4:] == ["--adapt-async", "1", "--kv-grow", "--stats"]
    assert args[args.index("--max-context") + 1] == "262144"
    plain = _server_config(262144, [], True, dataclasses.replace(config.CODER, engine_extra_args=()))["args"]
    assert plain[-2:] == ["--kv", "int8"]
    for model in config.MODELS.values():
        assert isinstance(model.engine_extra_args, tuple), model.key


def test_speed_settings_adopted_20261018() -> None:
    # 2026-10-17〜18 の計測で採った速さの設定（README の「速さの設定と文脈長 262144」）
    adopted = {
        "rvn": (True, 65536, ("--adapt-async", "1")),
        "coder": (False, None, ("--adapt-async", "1", "--kv-grow")),
        "official": (False, None, ("--adapt-async", "1", "--kv-grow")),
        "official-iq3s": (True, None, ("--adapt-async", "1")),
        "swift": (False, None, ("--adapt-async", "1", "--kv-grow")),
    }
    assert set(adopted) == set(config.MODELS)
    for key, (resident, kv_resident, extra) in adopted.items():
        spec = config.MODELS[key]
        assert (spec.resident_experts, spec.kv_resident, spec.engine_extra_args) == (resident, kv_resident, extra), key
        # --kv-grow は通常モード（全エキスパートが RAM）で KV ストリーミングが無いときだけ効く（上流 docs/DETAILS.md）
        if "--kv-grow" in extra:
            assert spec.resident_experts is False and spec.kv_resident is None, key
        args = _server_config(262144, [], True, spec)["args"]
        assert args[args.index("--max-context") + 1] == "262144"
        assert args[-len(extra):] == list(extra), key


def test_parser_model_option() -> None:
    parser = build_parser()
    assert parser.parse_args(["serve"]).model == "rvn"
    coder_serve = parser.parse_args(["serve", "--model", "coder"])
    assert (coder_serve.model, coder_serve.port) == ("coder", 8083)
    assert parser.parse_args(["serve", "--model", "coder", "--port", "9000"]).port == 9000
    wait = parser.parse_args(["wait-ready", "--model", "coder", "--timeout", "880"])
    assert (wait.port, wait.timeout) == (8083, 880.0)
    assert parser.parse_args(["wait-ready"]).port == 8082
    assert parser.parse_args(["doctor", "--model", "coder"]).model == "coder"
    assert parser.parse_args(["fetch-models", "--model", "coder", "--verify"]).model == "coder"
    assert parser.parse_args(["build-pack", "--model", "coder"]).force is False
    official_serve = parser.parse_args(["serve", "--model", "official"])
    assert (official_serve.model, official_serve.port) == ("official", 8084)
    assert parser.parse_args(["wait-ready", "--model", "official"]).port == 8084
    assert parser.parse_args(["build-pack", "--model", "official"]).model == "official"
    # 2026-10-16 に足した 2 つ（公式版 IQ3_S 8085・Swift 1.5 8086）
    assert parser.parse_args(["serve", "--model", "official-iq3s"]).port == 8085
    assert parser.parse_args(["wait-ready", "--model", "official-iq3s"]).port == 8085
    assert parser.parse_args(["serve", "--model", "swift"]).port == 8086
    assert parser.parse_args(["wait-ready", "--model", "swift"]).port == 8086
    assert parser.parse_args(["build-pack", "--model", "swift"]).model == "swift"
    with pytest.raises(SystemExit):
        parser.parse_args(["serve", "--model", "qwen"])


def test_classify_pack_and_header() -> None:
    names = ("index.txt", "dense.bin", "tokenizer/vocab.json", "tokenizer/chat_template.jinja", "native_experts.txt")
    assert checks.classify_pack({name: True for name in names}, "coder")[0] is True
    half = {name: name != "native_experts.txt" for name in names}
    ok, detail = checks.classify_pack(half, "coder")
    assert not ok and "作りかけ" in detail and "native_experts.txt" in detail and "--model coder" in detail
    ok, detail = checks.classify_pack({name: False for name in names}, "coder")
    assert not ok and "ありません" in detail and "--model coder" in detail
    # 案内の --model は対象のモデルに合わせる（公式版も手元で pack を作る）
    ok, detail = checks.classify_pack({name: False for name in names}, "official")
    assert not ok and "--model official" in detail and "--model coder" not in detail
    header = ("# strata native experts v3: layer gu_type d_type offset blob_bytes gate_off up_off down_off [shard] "
              "(n_expert 256, total 25082265600; absolute offsets in x.gguf, or in the named shard beside it)\n0 IQ3_S\n")
    assert checks.parse_native_experts_header(header) == (256, 25082265600)
    assert checks.parse_native_experts_header("") is None
    assert checks.parse_native_experts_header("0 IQ3_S 1 2\n") is None


def test_classify_other_service_and_port_names() -> None:
    ok, detail = checks.classify_other_service("strata", True)
    assert ok and "Conflicts=" in detail and "strata" in detail
    assert checks.classify_other_service("strata-coder", False) == (True, "strata-coder.service は停止中です")
    assert "strata-coder.service" in checks.classify_port_status(8083, True, True, "strata-coder")[1]
    assert checks.classify_port_status(8083, True, False, "strata-coder")[0] is False
    assert "fetch-models --model coder" in checks.classify_model_file(None, 10, None, "run-strata fetch-models --model coder")[1]


def test_doctor_model_rows_for_local_pack(tmp_path: Path) -> None:
    import dataclasses

    from stra import cli

    spec = dataclasses.replace(
        config.CODER, model_dir=tmp_path, pack_dir=tmp_path / "pack", files=(("x.gguf", 4, "0" * 64),),
    )
    (tmp_path / "x.gguf").write_bytes(b"GGUF")
    rows = cli._model_rows(spec)
    assert rows[0] == ("モデル x.gguf", True, "4 バイト")
    assert rows[-1][0].startswith("pack") and rows[-1][1] is False
    for name in cli.LOCAL_PACK_FILES:
        target = spec.pack_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# strata native experts v3: (n_expert 256, total 1073741824; x)\n", encoding="utf-8")
    ok, detail = cli._model_rows(spec)[-1][1:]
    assert ok and "256 個/層" in detail and "1.0 GiB" in detail
    # 公式版の pack の行は、取得の案内も作り直しの案内も --model official を指す
    official = dataclasses.replace(
        config.OFFICIAL, model_dir=tmp_path / "o", pack_dir=tmp_path / "o" / "pack", files=(("y.gguf", 4, "0" * 64),),
    )
    rows = cli._model_rows(official)
    assert rows[0][1] is False and "fetch-models --model official" in rows[0][2]
    assert rows[-1][0] == "pack（手元で作る、pack/）" and rows[-1][1] is False and "--model official" in rows[-1][2]


def test_coder_service_example() -> None:
    text = config.CODER.service_example.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in (
        "Conflicts=strata.service strata-official.service strata-official-iq3s.service strata-swift.service",
        # 停止を起動より先にするための順序（片側だけ。汎用版の側に After=strata-coder.service は書かない）
        "After=network.target strata.service",
        "EnvironmentFile=-%h/.config/strata/strata-coder.env",
        "ExecStart=@REPO_ROOT@/tools/strata/run-strata serve --model coder",
        "ExecStartPost=@REPO_ROOT@/tools/strata/run-strata wait-ready --model coder --timeout 880",
        "Restart=on-failure",
        "TimeoutStartSec=900",
        "LimitMEMLOCK=infinity",
    ):
        assert line in lines, line
    assert not any(line.startswith("WantedBy=") and "strata.service" in line for line in lines)
    limits = {}
    for line in lines:
        match = re.fullmatch(r"(MemoryHigh|MemoryMax)=(\d+)G", line)
        if match:
            limits[match.group(1)] = int(match.group(2))
    assert set(limits) == {"MemoryHigh", "MemoryMax"}
    assert limits["MemoryHigh"] < limits["MemoryMax"] <= 58
    # 実測で決めた値（落とせない分 約 26.2 GiB より上。32/36 と 40/44 で差が無く、間を取った）
    assert (limits["MemoryHigh"], limits["MemoryMax"]) == (36, 40)
    assert limits["MemoryHigh"] > config.CODER.expert_bytes / GIB + 2
    # 汎用版のユニットからも Coder・公式版・公式版 IQ3_S・Swift を止める（systemd の側で同時に載せない）
    rvn_lines = config.SERVICE_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "Conflicts=strata-coder.service strata-official.service strata-official-iq3s.service strata-swift.service" in rvn_lines
    assert not any(line.startswith("After=") and "strata-coder" in line for line in rvn_lines)


def _setup_model_cases(text: str) -> dict[str, list[str]]:
    """setup-server.sh のモデルごとの case（2 字下げの `rvn)` から `;;` まで）の行。引数の case（`--model)` など）は拾わない。"""

    blocks: dict[str, list[str]] = {}
    for match in re.finditer(r"^  ([a-z][a-z0-9-]*)\)\n(.*?)^    ;;", text, flags=re.MULTILINE | re.DOTALL):
        blocks[match.group(1)] = [line.strip() for line in match.group(2).splitlines()]
    return blocks


def test_setup_script_model_names_match_config() -> None:
    text = (TOOL_DIR / "setup-server.sh").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    for spec in config.MODELS.values():
        assert f'SERVICE_NAME="{spec.service_name}"' in lines, spec.key
        assert f'MODEL_PORT="{spec.port}"' in lines, spec.key
        assert f'ENV_NAME="{spec.env_file.name}"' in lines, spec.key
        assert f"{spec.key})" in lines, spec.key
    assert 'MODEL_KEY="rvn"' in lines
    # pack を手元で作るか（[6/8] の build-pack）は、モデルごとの case の PACK_BUILT_LOCALLY と config が一致する
    blocks = _setup_model_cases(text)
    assert set(blocks) == set(config.MODELS)
    for spec in config.MODELS.values():
        expected = "true" if spec.pack_built_locally else "false"
        assert f"PACK_BUILT_LOCALLY={expected}" in blocks[spec.key], spec.key
        assert f'SERVICE_NAME="{spec.service_name}"' in blocks[spec.key], spec.key
    assert '"$RUNNER" build-pack --model "$MODEL_KEY"' in lines
    # 2 モデル前提の案内が残っていない
    assert "rvn か coder" not in text


def test_bench_repeat_metrics() -> None:
    looping = " ".join(["Let me check the eviction order once more and verify the test case again."] * 400)
    assert bench_api.repeat_coverage(looping) > 0.9
    varied = " ".join(f"step {index} adds value {index * 7} to the cache and then reads key {index}." for index in range(400))
    assert bench_api.repeat_coverage(varied) < 0.25
    assert bench_api.repeat_coverage("short text") == 0.0
    count, sentence = bench_api.max_sentence_repeats("同じ文をここで何度も繰り返して書きます。\n" * 5 + "別の文がひとつだけあります。")
    assert count == 5 and sentence == "同じ文をここで何度も繰り返して書きます"
    assert bench_api.max_sentence_repeats("短い。") == (0, "")


def test_server_options_per_model() -> None:
    # 汎用版も #728 の回復を入れる（2026-10-07、8082 が上限まで thinking のまま答えなかったため）。sampling は入れない
    assert dict(config.RVN.server_options) == {"reasoning_loop_recovery": "recover"}
    rvn_config = _server_config(131072, [], True)
    # 汎用版は思考の予算 32768 も入る（2026-10-07 の実測。0 で答えが出ない問題が 32768 で解けた）
    assert set(rvn_config) == {
        "exe", "args", "cwd", "tokenizer", "model_name", "log", "lib_dirs", "host", "port", "reasoning_loop_recovery",
        "reasoning_budget_tokens",
    }
    assert rvn_config["reasoning_loop_recovery"] == "recover" and "sampling" not in rvn_config
    assert rvn_config["reasoning_budget_tokens"] == 32768 == config.RVN.default_reasoning_budget_tokens
    # Coder は #728 の回復だけを入れる（サンプリングの既定は入れない。実測で日本語の課題が崩れたため）
    coder_config = _server_config(131072, [], True, config.CODER)
    assert dict(config.CODER.server_options) == {"reasoning_loop_recovery": "recover"}
    assert coder_config["reasoning_loop_recovery"] == "recover" and "sampling" not in coder_config
    # Coder は思考の予算を付けない（既定 0。鍵そのものが無い）
    assert config.CODER.default_reasoning_budget_tokens == 0
    assert "reasoning_budget_tokens" not in coder_config
    # 上流サーバーが受け付ける値（serve/server.py:4935-4941）
    assert coder_config["reasoning_loop_recovery"] in (False, "stop", "recover")
    # 写しなので、組み立てた設定を書き換えても元は変わらない
    source = {"sampling": {"temperature": 1.0}}
    nested = checks.build_server_config(
        engine_exe="e", engine_args=[], strata_dir="s", tokenizer_dir="t", model_name="m", engine_log="l",
        lib_dirs=[], host="h", port=1, extra_options=source,
    )
    nested["sampling"]["temperature"] = 0.0
    assert source["sampling"]["temperature"] == 1.0
    with pytest.raises(ValueError):
        checks.build_server_config(
            engine_exe="e", engine_args=[], strata_dir="s", tokenizer_dir="t", model_name="m", engine_log="l",
            lib_dirs=[], host="h", port=1, extra_options={"port": 2},
        )


def test_reasoning_budget_override_in_server_config() -> None:
    # 0 なら鍵が消える（env で無効にしたとき）。None は spec の既定
    assert "reasoning_budget_tokens" not in _server_config(131072, [], True, config.RVN, reasoning_budget_tokens=0)
    assert _server_config(131072, [], True, config.RVN, reasoning_budget_tokens=None)["reasoning_budget_tokens"] == 32768
    assert _server_config(131072, [], True, config.RVN, reasoning_budget_tokens=16384)["reasoning_budget_tokens"] == 16384
    # Coder に env で予算を足すこともできる。ほかの鍵（#728 の回復）は残る
    coder_with_budget = _server_config(131072, [], True, config.CODER, reasoning_budget_tokens=8192)
    assert coder_with_budget["reasoning_budget_tokens"] == 8192
    assert coder_with_budget["reasoning_loop_recovery"] == "recover"
    # 上流が読む値の型（serve/server.py の reasoning_budget: 真偽値でない整数）
    assert isinstance(_server_config(131072, [], True)["reasoning_budget_tokens"], int)
    # spec.server_options は写しを作ってから足すので、呼んだあとも元のまま（鍵が混ざらない）
    assert dict(config.RVN.server_options) == {"reasoning_loop_recovery": "recover"}
    assert dict(config.CODER.server_options) == {"reasoning_loop_recovery": "recover"}


# ---------------------------------------------------------------- 公式版（official、非 abliterated の IQ3_XXS）


def test_official_files_are_the_pinned_shards() -> None:
    official = config.OFFICIAL
    assert official.repo == "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
    assert official.revision == "ed59f92082b1e93c0e96d60a8b11aab089b52f09"
    assert official.model_dir == config.MODELS_DIR / "Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS"
    names = [path for path, _size, _sha in official.files]
    assert names == ["README.md", "IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf",
                     "IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf"]
    for path, size, sha256 in official.files:
        assert size > 0 and re.fullmatch(r"[0-9a-f]{64}", sha256), path
    # 他の量子化・画像用の mmproj・tensor-allocation などは取らない
    assert not any("mmproj" in name or name.startswith(("IQ3_S/", "IQ2_XS/", "Q2_0/")) for name in names)
    by_name = {path: (size, sha256) for path, size, sha256 in official.files}
    assert by_name[names[0]] == (15693, "71496aac3c9126085519dbe3aa82e46eb9f5749ee122b089a66182a94b0db6a3")
    assert by_name[names[1]] == (47039860096, "219ea929900dfa9ef091f3aa473fdba6874b65fcb36526d7d851ac9e95856d15")
    # shard 2（PLE の n-gram 表）は Coder の shard 2 と同じファイル（大きさと sha256 が一致。ハードリンクで置ける）
    coder_shard2 = config.CODER.files[2]
    assert by_name[names[2]] == (coder_shard2[1], coder_shard2[2])
    # --native は shard 1、--ple-gguf は shard 2。pack は手元で作り、profile は汎用版と同じもの
    assert official.native_gguf == official.model_dir / names[1]
    assert official.ple_gguf == official.model_dir / names[2]
    assert official.pack_built_locally is True and official.pack_dir == official.model_dir / "pack"
    assert official.tokenizer_dir == official.model_dir / "pack" / "tokenizer"
    assert official.expert_profile == config.EXPERT_PROFILE == config.RVN.expert_profile
    # TODO の仮置き（tensor-allocation の型から見積もった 48 層 x 512 エキスパートの合計）。pack を作ったら、
    # native_experts.txt の total と一致しなければ下の照合が落ちる（そのときは config.py の値を直す）
    assert official.expert_bytes == 42912972800
    if (official.pack_dir / "native_experts.txt").is_file():
        header = checks.parse_native_experts_header(
            (official.pack_dir / "native_experts.txt").read_text(encoding="utf-8"))
        assert header == (512, official.expert_bytes)


def test_official_spec_values() -> None:
    official = config.OFFICIAL
    # 依頼で決めた名前・ポート・ユニット（ほかの 2 つと重ならない）
    assert (official.key, official.model_name, official.port, official.service_name) == (
        "official", "strata-official:IQ3_XXS", 8084, "strata-official",
    )
    assert len(official.model_name) <= 28
    assert official.env_file == Path.home() / ".config" / "strata" / "strata-official.env"
    assert official.server_config == config.RUN_DIR / "strata-server-official.json"
    assert official.engine_log == config.LOGS_DIR / "strata-official-engine.log"
    assert official.service_example == TOOL_DIR / "systemd" / "strata-official.service.example"
    assert "公式" in official.title and "IQ3_XXS" in official.title
    # 2026-10-17 の実測で通常のモードにした（resident 版より 8〜20% 速い。config の OFFICIAL の注記）。KV は VRAM（RVN は
    # KV ストリーミング）。doctor の RAM の目安は落とせない分 約 42.3 GiB + 4 GiB の 46（RVN は 50）
    rvn = config.RVN
    assert official.resident_experts is False and rvn.resident_experts is True
    assert official.kv_resident is None and official.min_available_ram_gib == 46
    for attribute in ("default_max_context", "recommended_memlock_bytes", "min_free_vram_mib"):
        assert getattr(official, attribute) == getattr(rvn, attribute), attribute
    # #728 の回復は RVN と同じ。思考の予算は RVN より大きい 65536（収束に 32,768 を超える thinking が要った実測）。
    # sampling の既定は入れない
    assert official.default_reasoning_budget_tokens == 65536 > rvn.default_reasoning_budget_tokens
    assert dict(official.server_options) == {"reasoning_loop_recovery": "recover"}


def test_official_server_config() -> None:
    official = config.OFFICIAL
    server_config = _server_config(131072, [], True, official)
    args = server_config["args"]
    pairs = dict(zip(args[::2], args[1::2]))
    assert pairs["--pack"] == str(official.pack_dir)
    assert pairs["--native"] == str(official.native_gguf) and pairs["--ple-gguf"] == str(official.ple_gguf)
    assert pairs["--expert-profile"] == str(config.STRATA_DIR / "data" / "expert-profile.bin")
    assert pairs["--mtp"] == str(config.MTP_RT_DIR) and pairs["--max-context"] == "131072"
    assert pairs["--kv"] == "int8" and pairs["--spec"] == "4"
    assert ("--resident-experts" in args) is official.resident_experts
    assert ("--kv-resident" in args) is (official.kv_resident is not None)
    # 上流サーバーへの鍵（基本の鍵 + #728 の回復 + 思考の予算 65536。sampling は無い）
    assert set(server_config) == {
        "exe", "args", "cwd", "tokenizer", "model_name", "log", "lib_dirs", "host", "port", "reasoning_loop_recovery",
        "reasoning_budget_tokens",
    }
    assert server_config["reasoning_loop_recovery"] == "recover"
    assert server_config["reasoning_budget_tokens"] == 65536
    assert (server_config["model_name"], server_config["port"]) == ("strata-official:IQ3_XXS", 8084)
    assert server_config["tokenizer"] == str(official.pack_dir / "tokenizer")
    assert server_config["log"] == str(config.LOGS_DIR / "strata-official-engine.log")
    assert server_config["exe"] == str(config.ENGINE_EXE) and server_config["cwd"] == str(config.STRATA_DIR)
    # JSON に書ける（serve が run/strata-server-official.json に書く形）。env の 0 で予算の鍵が消える
    assert json.loads(json.dumps(server_config, ensure_ascii=False)) == server_config
    assert "reasoning_budget_tokens" not in _server_config(131072, [], True, official, reasoning_budget_tokens=0)
    # 組み立てたあとも spec の server_options は元のまま
    assert dict(official.server_options) == {"reasoning_loop_recovery": "recover"}


def _unit_names(text: str, key: str) -> set[str]:
    """ユニットファイルの `key=` の行に並ぶユニット名（Conflicts= / After= など）。"""

    names: set[str] = set()
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            names.update(line.split("=", 1)[1].split())
    return names


def test_service_examples_conflict_with_each_other() -> None:
    units = {spec.service_name: spec.service_example.read_text(encoding="utf-8") for spec in config.MODELS.values()}
    assert set(units) == {"strata", "strata-coder", "strata-official", "strata-official-iq3s", "strata-swift"}
    model_units = {f"{name}.service" for name in units}
    # どのユニットの Conflicts= も、ほかの 4 つをちょうど指す（同時に載せない）
    for name, text in units.items():
        assert _unit_names(text, "Conflicts") == model_units - {f"{name}.service"}, name
    # 停止を起動より先にする順序: どの 2 つの間にも After= がちょうど片側だけにあり、輪にならない一方向
    # （strata → strata-coder → strata-official → strata-official-iq3s → strata-swift）
    after = {name: _unit_names(text, "After") & model_units for name, text in units.items()}
    for first, second in itertools.combinations(units, 2):
        assert (f"{second}.service" in after[first]) != (f"{first}.service" in after[second]), (first, second)
    assert after == {
        "strata": set(),
        "strata-coder": {"strata.service"},
        "strata-official": {"strata.service", "strata-coder.service"},
        "strata-official-iq3s": {"strata.service", "strata-coder.service", "strata-official.service"},
        "strata-swift": {"strata.service", "strata-coder.service", "strata-official.service", "strata-official-iq3s.service"},
    }
    # どれも自動起動の依存で互いを引き込まない
    for name, text in units.items():
        assert not (_unit_names(text, "WantedBy") | _unit_names(text, "Wants") | _unit_names(text, "Requires")) & model_units


def test_official_service_example() -> None:
    text = config.OFFICIAL.service_example.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in (
        "Conflicts=strata.service strata-coder.service strata-official-iq3s.service strata-swift.service",
        "After=network.target strata.service strata-coder.service",
        "EnvironmentFile=-%h/.config/strata/strata-official.env",
        "ExecStart=@REPO_ROOT@/tools/strata/run-strata serve --model official",
        "ExecStartPost=@REPO_ROOT@/tools/strata/run-strata wait-ready --model official --timeout 880",
        "Restart=on-failure",
        "TimeoutStartSec=900",
        "LimitMEMLOCK=infinity",
        "WantedBy=default.target",
    ):
        assert line in lines, line
    assert "port 8084" in lines[1]
    limits = {}
    for line in lines:
        match = re.fullmatch(r"(MemoryHigh|MemoryMax)=(\d+)G", line)
        if match:
            limits[match.group(1)] = int(match.group(2))
    # 実測で決める前の仮置き（汎用版と同じ値）。見込みのエキスパートより上。MemoryMax は 2026-10-09 の利用者の指示で 54 → 58
    assert (limits["MemoryHigh"], limits["MemoryMax"]) == (50, 58)
    assert config.OFFICIAL.expert_bytes / GIB + 2 < limits["MemoryHigh"] < limits["MemoryMax"] <= 58
    match = re.search(r"wait-ready --model official --timeout (\d+)", text)
    assert match and int(match.group(1)) < 900


# ---------------------------------------------------------------- 公式版 IQ3_S と Swift 1.5（2026-10-16 に追加）


def _unit_limits(text: str) -> dict[str, int]:
    limits = {}
    for line in text.splitlines():
        match = re.fullmatch(r"(MemoryHigh|MemoryMax)=(\d+)G", line)
        if match:
            limits[match.group(1)] = int(match.group(2))
    return limits


def test_official_iq3s_files_are_the_pinned_shards() -> None:
    spec = config.OFFICIAL_IQ3S
    # 公式版（IQ3_XXS）と同じリポジトリ・同じ固定リビジョン
    assert (spec.repo, spec.revision) == (config.OFFICIAL.repo, config.OFFICIAL.revision)
    assert spec.model_dir == config.MODELS_DIR / "Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S"
    names = [path for path, _size, _sha in spec.files]
    assert names == ["README.md", "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
                     "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf"]
    for path, size, sha256 in spec.files:
        assert size > 0 and re.fullmatch(r"[0-9a-f]{64}", sha256), path
    by_name = {path: (size, sha256) for path, size, sha256 in spec.files}
    # README と shard 2 は公式版と同じファイル（shard 2 はハードリンクで置く）。shard 1 だけが IQ3_S のもの
    official_by_name = {path: (size, sha256) for path, size, sha256 in config.OFFICIAL.files}
    assert by_name["README.md"] == official_by_name["README.md"]
    assert by_name[names[2]] == official_by_name[config.OFFICIAL_SHARD2]
    assert by_name[names[1]] == (54817524224, "4c1eb2ceb4915e1192f4f386021897bde56a97f40a0bb78bb86465e0f7d2aca3")
    assert spec.native_gguf == spec.model_dir / names[1] and spec.ple_gguf == spec.model_dir / names[2]
    assert spec.pack_built_locally is True and spec.pack_dir == spec.model_dir / "pack"
    assert spec.expert_profile == config.EXPERT_PROFILE
    # 仮置き（上流コミュニティの実測の experts.bin の大きさ）。pack を作ったら native_experts.txt の total と照合する
    assert spec.expert_bytes == 50292326400
    if (spec.pack_dir / "native_experts.txt").is_file():
        header = checks.parse_native_experts_header((spec.pack_dir / "native_experts.txt").read_text(encoding="utf-8"))
        assert header == (512, spec.expert_bytes)


def test_official_iq3s_spec_values_and_server_config() -> None:
    spec = config.OFFICIAL_IQ3S
    assert (spec.key, spec.model_name, spec.port, spec.service_name) == (
        "official-iq3s", "strata-official:IQ3_S", 8085, "strata-official-iq3s",
    )
    assert spec.env_file == Path.home() / ".config" / "strata" / "strata-official-iq3s.env"
    assert spec.server_config == config.RUN_DIR / "strata-server-official-iq3s.json"
    assert spec.engine_log == config.LOGS_DIR / "strata-official-iq3s-engine.log"
    assert spec.service_example == TOOL_DIR / "systemd" / "strata-official-iq3s.service.example"
    assert "IQ3_S" in spec.title and "公式" in spec.title
    # エキスパート 46.84 GiB は通常のモード（+10 GB）では収まらないので、RVN と同じ resident 版。ほかは公式版と同じ
    assert spec.resident_experts is True and spec.kv_resident is None
    for attribute in ("default_max_context", "min_available_ram_gib", "recommended_memlock_bytes", "min_free_vram_mib",
                      "default_reasoning_budget_tokens"):
        assert getattr(spec, attribute) == getattr(config.OFFICIAL, attribute), attribute
    assert dict(spec.server_options) == {"reasoning_loop_recovery": "recover"}
    server_config = _server_config(131072, [], True, spec)
    pairs = dict(zip(server_config["args"][::2], server_config["args"][1::2]))
    assert pairs["--native"] == str(spec.native_gguf) and pairs["--ple-gguf"] == str(spec.ple_gguf)
    assert "--resident-experts" in server_config["args"] and "--kv-resident" not in server_config["args"]
    assert (server_config["model_name"], server_config["port"]) == ("strata-official:IQ3_S", 8085)
    assert server_config["reasoning_budget_tokens"] == 65536 and server_config["reasoning_loop_recovery"] == "recover"


def test_swift_files_are_the_pinned_shards() -> None:
    spec = config.SWIFT
    assert spec.repo == "ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
    assert spec.revision == "99bb8f7f95c7aa7b24a36a7786a4f657b30f5d3d"
    assert spec.model_dir == config.MODELS_DIR / "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS"
    names = [path for path, _size, _sha in spec.files]
    # HF のリポジトリはルート直下に GGUF を置く。ライセンスの 3 ファイルも取る（Swift Open License v1.0 と元の Qwen のもの）
    assert names == ["README.md", "LICENSE", "LICENSE-QWEN", "NOTICE",
                     "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf",
                     "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf"]
    for path, size, sha256 in spec.files:
        assert size > 0 and re.fullmatch(r"[0-9a-f]{64}", sha256), path
    assert not any("mmproj" in name or "IQ3_S" in name or "IQ2_XS" in name or "Q2_0" in name for name in names)
    by_name = {path: (size, sha256) for path, size, sha256 in spec.files}
    assert by_name[names[4]] == (39785790560, "3bddaa667c750f63baca766df9433e1afd35a139f401c5ca5e7ff560ceff3d23")
    assert by_name[names[5]] == (36180282560, "b0b15f782af71eb471909d2f3313b2927c324962f86c084325c247cd411a0160")
    # shard 2 は元の Qwen の shard 2（PLE の表）とは別物。--native と --ple-gguf はどちらも shard 1（表は shard 1 にある）
    assert by_name[names[5]] != (config.OFFICIAL.files[2][1], config.OFFICIAL.files[2][2])
    assert spec.native_gguf == spec.model_dir / names[4] and spec.ple_gguf == spec.native_gguf
    assert spec.pack_built_locally is True and spec.pack_dir == spec.model_dir / "pack"
    assert spec.expert_profile == config.EXPERT_PROFILE
    # 仮置き（公式版 IQ3_XXS と同じ allocation profile）。pack を作ったら native_experts.txt の total と照合する
    assert spec.expert_bytes == config.OFFICIAL.expert_bytes
    if (spec.pack_dir / "native_experts.txt").is_file():
        header = checks.parse_native_experts_header((spec.pack_dir / "native_experts.txt").read_text(encoding="utf-8"))
        assert header == (512, spec.expert_bytes)


def test_swift_spec_values_and_server_config() -> None:
    spec = config.SWIFT
    assert (spec.key, spec.model_name, spec.port, spec.service_name) == ("swift", "strata-swift:IQ3_XXS", 8086, "strata-swift")
    assert spec.env_file == Path.home() / ".config" / "strata" / "strata-swift.env"
    assert spec.server_config == config.RUN_DIR / "strata-server-swift.json"
    assert spec.engine_log == config.LOGS_DIR / "strata-swift-engine.log"
    assert spec.service_example == TOOL_DIR / "systemd" / "strata-swift.service.example"
    assert "Swift 1.5" in spec.title and "IQ3_XXS" in spec.title
    # 公式版（IQ3_XXS）と同じ量子化・同じ大きさ・同じ通常モード（2026-10-18 の実測で resident 版より 8〜12% 速い。config の SWIFT の注記）
    assert spec.resident_experts is False
    for attribute in ("kv_resident", "default_max_context", "min_available_ram_gib",
                      "recommended_memlock_bytes", "min_free_vram_mib", "default_reasoning_budget_tokens"):
        assert getattr(spec, attribute) == getattr(config.OFFICIAL, attribute), attribute
    assert dict(spec.server_options) == {"reasoning_loop_recovery": "recover"}
    server_config = _server_config(131072, [], True, spec)
    pairs = dict(zip(server_config["args"][::2], server_config["args"][1::2]))
    assert pairs["--native"] == pairs["--ple-gguf"] == str(spec.native_gguf)
    assert pairs["--expert-profile"] == str(config.EXPERT_PROFILE) and pairs["--mtp"] == str(config.MTP_RT_DIR)
    assert (server_config["model_name"], server_config["port"]) == ("strata-swift:IQ3_XXS", 8086)
    assert server_config["reasoning_budget_tokens"] == 65536 and server_config["reasoning_loop_recovery"] == "recover"
    assert json.loads(json.dumps(server_config, ensure_ascii=False)) == server_config


@pytest.mark.parametrize("key", ["official-iq3s", "swift"])
def test_new_service_examples(key: str) -> None:
    spec = config.MODELS[key]
    text = spec.service_example.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in (
        f"EnvironmentFile=-%h/.config/strata/{spec.env_file.name}",
        f"ExecStart=@REPO_ROOT@/tools/strata/run-strata serve --model {key}",
        f"ExecStartPost=@REPO_ROOT@/tools/strata/run-strata wait-ready --model {key} --timeout 880",
        "Restart=on-failure",
        "TimeoutStartSec=900",
        "LimitMEMLOCK=infinity",
        "WantedBy=default.target",
    ):
        assert line in lines, line
    assert f"port {spec.port}" in lines[1]
    # 実測で決める前の仮置き（汎用版・公式版と同じ 50 / 58）。見込みのエキスパートより上
    limits = _unit_limits(text)
    assert (limits["MemoryHigh"], limits["MemoryMax"]) == (50, 58)
    assert spec.expert_bytes / GIB + 2 < limits["MemoryHigh"] < limits["MemoryMax"] <= 58
    match = re.search(rf"wait-ready --model {key} --timeout (\d+)", text)
    assert match and int(match.group(1)) < 900


def test_model_help_lists_every_model(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    # argparse の折り返しで語が切れないよう、端末の幅を広げてから --help を読む
    monkeypatch.setenv("COLUMNS", "300")
    for command in ("serve", "doctor"):
        with pytest.raises(SystemExit):
            build_parser().parse_args([command, "--help"])
        help_text = capsys.readouterr().out
        for spec in config.MODELS.values():
            assert f"{spec.key}:" in help_text and str(spec.port) in help_text, (command, spec.key)
