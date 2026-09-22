"""px3d の CLI 本体。

`run-pixal3d`（= venv の python）から `python -m px3d.cli <サブコマンド>` として呼ばれる。
このモジュール自体は標準ライブラリのみに依存する。torch / gradio / pixal3d（vendor）は
モジュール先頭で import しない。重い import は関数の中（venv の python を subprocess で
呼ぶスクリプト文字列、または `serve` が exec する px3d.ui）に閉じ込め、px3d.cli 自体は
素の python（.venv を持たない `uvx --with pytest pytest ...`）からも import できるようにする
（hy3d/cli.py と同じ設計方針）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from . import config, ollama, options

# venv の python で実行する torch 確認用スクリプト。
# import に失敗した場合は import_error に理由を入れて、他のキーは省く。
_TORCH_PROBE = """
import json

result = {}
try:
    import torch
except Exception as exc:
    result["import_error"] = str(exc)
else:
    result["cuda_version"] = torch.version.cuda
    result["cuda_available"] = bool(torch.cuda.is_available())
    if result["cuda_available"]:
        try:
            result["device_name"] = torch.cuda.get_device_name(0)
        except Exception as exc:
            result["device_name"] = None
            result["device_name_error"] = str(exc)
print(json.dumps(result))
"""

# ネイティブ拡張の import 確認用スクリプト。
# どれも torch の libc10.so にリンクしている。torch を先に import しないと
# ImportError: libc10.so になる（拡張が壊れているわけではない）。
_EXTENSION_PROBE = """
import json

result = {}
try:
    import torch  # noqa: F401
except Exception as exc:
    result["import_error"] = "torch を import できません: " + str(exc)
    print(json.dumps(result))
    raise SystemExit(0)

_targets = [
    ("o_voxel", "import o_voxel"),
    ("cumesh", "import cumesh"),
    ("flex_gemm", "import flex_gemm"),
    ("nvdiffrast", "import nvdiffrast.torch"),
    ("nvdiffrec_render", "import nvdiffrec_render"),
]
for name, stmt in _targets:
    try:
        exec(stmt)
    except Exception as exc:
        result[name] = str(exc)
    else:
        result[name] = None
print(json.dumps(result))
"""

# fetch-models の実体。repo_id / config_file / dino_repo / rembg_model_name は
# cmd_fetch_models 側が先頭に代入文として付け足す（f-string での波括弧エスケープを避けるため、
# ここは通常の文字列にする）。local_dir は使わない。HF の標準キャッシュ（HF_HOME、
# snapshot_download の既定レイアウト）へ落とす方式に寄せたため
# （実機で動作確認できたのがこの方式。vendor/Pixal3D/pixal3d/pipelines/base.py の
# from_pretrained がリポジトリ ID をそのまま受けてこのキャッシュから読む）。
_FETCH_MODELS_SCRIPT_BODY = '''
import json

from huggingface_hub import snapshot_download

from px3d import config as px3d_config
from px3d.cli import resolve_model_snapshot_dir, weight_files_from_pipeline_config

# 1 段目: pipeline_mv.json だけを取得する。重みの一覧（args.models）はこの中身にしか無いため、
# ckpts/* を絞り込む allow_patterns を組み立てるにはまずこれを読む必要がある。
print("取得します（1/2）: " + config_file)
snapshot_download(repo_id=repo_id, allow_patterns=[config_file])

snapshot_dir = resolve_model_snapshot_dir(px3d_config.HF_HOME_DIR, repo_id)
if snapshot_dir is None:
    raise SystemExit(config_file + " の取得後もスナップショットが見つかりません: " + repo_id)

with open(snapshot_dir / config_file, encoding="utf-8") as fh:
    pipeline_config = json.load(fh)

weight_files = weight_files_from_pipeline_config(pipeline_config)
print(
    "取得します（2/2。既にあるファイルは snapshot_download が自動でスキップします）: "
    + str(len(weight_files)) + " ファイル"
)
snapshot_download(repo_id=repo_id, allow_patterns=weight_files)
print("完了しました: " + repo_id)

rembg_info = pipeline_config.get("args", {}).get("rembg_model")
if rembg_info:
    print("pipeline_mv.json の背景除去モデルの設定: " + json.dumps(rembg_info, ensure_ascii=False))
    print(
        "  このモデル（briaai/RMBG-2.0）はゲート付きのため使わず、"
        "px3d.rembg_override で " + rembg_model_name + " に差し替えている。"
    )

print("取得します（DINOv3 ミラー。既にあればスキップされます）: " + dino_repo)
snapshot_download(repo_id=dino_repo)
print("完了しました: DINOv3 ミラー")

print("取得します（背景除去モデル、非ゲート。既にあればスキップされます）: " + rembg_model_name)
snapshot_download(repo_id=rembg_model_name)
print("完了しました: 背景除去モデル")
'''

# generate の実体。vendor_dir / views_dir / output_path / seed / model_path / config_file /
# low_vram / resolution / rembg_model_name は cmd_generate 側が先頭に代入文として付け足す。
_GENERATE_SCRIPT_BODY = """
import sys

sys.path.insert(0, vendor_dir)
import inference_mv

# pipeline_mv.json の rembg_model（briaai/RMBG-2.0、ゲート付き）を、非ゲートの
# rembg_model_name に強制する。run_inference の内部で init_pipeline（= from_pretrained）が
# 呼ばれるより前に実行する必要がある（px3d/rembg_override.py の docstring を参照）。
from px3d.rembg_override import force_rembg_model

force_rembg_model(rembg_model_name)

inference_mv.run_inference(
    views_dir=views_dir,
    output_path=output_path,
    seed=seed,
    model_path=model_path,
    config_file=config_file,
    low_vram=low_vram,
    resolution=resolution,
)
"""


def build_serve_command(
    *,
    python_bin: str,
    host: str,
    port: int,
    resolution: int,
    low_vram: bool,
) -> list[str]:
    """px3d.ui を起動するコマンド列を組み立てる純粋関数。

    ファイルシステムにもネットワークにも触れない。テストで検証するためにここへ切り出している。
    """

    command = [
        python_bin,
        "-m",
        "px3d.ui",
        "--host",
        host,
        "--port",
        str(port),
        "--resolution",
        str(resolution),
    ]
    command.append("--low-vram" if low_vram else "--no-low-vram")
    return command


def build_serve_env(
    *,
    base_env: Mapping[str, str],
    hf_home: str,
    torch_home: str,
    vendor_dir: str,
    cuda_home: str,
) -> dict[str, str]:
    """px3d.ui（と generate のサブプロセス）に渡す環境変数を組み立てる純粋関数。

    base_env を書き換えず、新しい dict を返す。ファイルシステムにもネットワークにも触れない。
    """

    env = dict(base_env)
    env["HF_HOME"] = hf_home
    env["TORCH_HOME"] = torch_home
    # flash_attn を入れていないため SDPA を使う（vendor/Pixal3D/README.md が明記する代替経路）。
    # inference_mv.py は os.environ.setdefault("ATTN_BACKEND", "flash_attn") なので、
    # setdefault に上書きされないよう、ここで先に設定しておく必要がある。
    env["ATTN_BACKEND"] = config.ATTN_BACKEND
    # vendor/Pixal3D は pip install されていない（ソースのまま）ので、import pixal3d / import
    # inference_mv のために PYTHONPATH を通す。
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        vendor_dir if not existing_pythonpath else f"{vendor_dir}{os.pathsep}{existing_pythonpath}"
    )
    env["CUDA_HOME"] = cuda_home
    cuda_bin = str(Path(cuda_home) / "bin")
    existing_path = env.get("PATH", "")
    env["PATH"] = f"{cuda_bin}{os.pathsep}{existing_path}" if existing_path else cuda_bin
    return env


def weight_files_from_pipeline_config(pipeline_config: dict) -> list[str]:
    """pipeline_mv.json の中身から、落とすべきファイルの相対パス一覧を返す純粋関数。

    ファイルシステムにもネットワークにも触れない。models.from_pretrained は
    f"{path}.json" と f"{path}.safetensors" の両方を見る
    （vendor/Pixal3D/pixal3d/models/__init__.py の from_pretrained）。
    pipeline_mv.json 自体もローカル判定に要る（Pipeline.from_pretrained の
    os.path.exists(f"{path}/{config_file}")）ため、先頭に含める。
    重複は順序を保ったまま取り除く（同じ ckpts パスを複数の model キーが指すことがある）。
    """

    files = [config.PIPELINE_CONFIG]
    models = pipeline_config.get("args", {}).get("models", {})
    for relative_path in models.values():
        files.append(f"{relative_path}.json")
        files.append(f"{relative_path}.safetensors")

    seen: set[str] = set()
    deduped: list[str] = []
    for name in files:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _run_venv_python(script: str, timeout: float) -> dict[str, Any]:
    """venv の python で script を -c 実行し、最後の行を JSON として読む。"""

    if not config.VENV_PYTHON.is_file():
        return {"import_error": f"venv の python がありません: {config.VENV_PYTHON}"}
    try:
        completed = subprocess.run(
            [str(config.VENV_PYTHON), "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"import_error": f"venv の python の起動に失敗しました: {exc}"}

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        detail = completed.stderr.strip() or "標準出力が空でした"
        return {"import_error": detail}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        detail = completed.stderr.strip() or lines[-1]
        return {"import_error": detail}


def _check_git_commit(directory: Path, expected_commit: str) -> tuple[bool, str]:
    if not directory.is_dir():
        return False, f"見つかりません: {directory}"
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"git rev-parse に失敗しました: {exc}"
    head = completed.stdout.strip()
    if head == expected_commit:
        return True, f"HEAD={head}"
    return False, f"HEAD={head}（期待値 {expected_commit}）"


def _check_cuda_nvcc() -> tuple[bool, str]:
    nvcc_path = Path(config.CUDA_HOME) / "bin" / "nvcc"
    if not nvcc_path.is_file():
        return False, f"{nvcc_path} が見つかりません"
    try:
        completed = subprocess.run(
            [str(nvcc_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"nvcc の実行に失敗しました: {exc}"
    output = completed.stdout.strip()
    ok = "release 12.6" in output
    detail = output.splitlines()[-1] if output else "(出力なし)"
    return ok, detail


def resolve_model_snapshot_dir(hf_home_dir: Path, repo_id: str) -> Path | None:
    """HF キャッシュ（hf_home_dir）から repo_id のスナップショットディレクトリを 1 つ選ぶ。

    huggingface_hub の既定キャッシュレイアウトは
    {hf_home_dir}/hub/models--{org}--{repo}/snapshots/{commit_hash}/ で、commit_hash は
    取得のたびに変わり得るため固定できない。snapshots/ の下を走査して 1 つ選ぶ。
    通常は 1 個しか無い想定だが、複数あれば最も新しく更新されたものを選ぶ。
    ファイルシステムを読むだけで、書き込みもネットワークにも触れない。
    見つからなければ None を返す。
    """

    snapshots_dir = hf_home_dir / "hub" / ("models--" + repo_id.replace("/", "--")) / "snapshots"
    if not snapshots_dir.is_dir():
        return None
    candidates = [entry for entry in snapshots_dir.iterdir() if entry.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: entry.stat().st_mtime)


def _check_weights() -> tuple[bool, str]:
    snapshot_dir = resolve_model_snapshot_dir(config.HF_HOME_DIR, config.MODEL_REPO)
    if snapshot_dir is None:
        return False, (
            f"{config.HF_HOME_DIR} に {config.MODEL_REPO} のスナップショットがありません"
            "（run-pixal3d fetch-models を実行してください）"
        )
    config_path = snapshot_dir / config.PIPELINE_CONFIG
    if not config_path.is_file():
        return False, f"{config_path} がありません（run-pixal3d fetch-models を実行してください）"
    try:
        pipeline_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"{config_path} を読めません: {exc}"
    required = weight_files_from_pipeline_config(pipeline_config)
    missing = [name for name in required if not (snapshot_dir / name).is_file()]
    if missing:
        shown = ", ".join(missing[:5])
        more = f" ほか {len(missing) - 5} 件" if len(missing) > 5 else ""
        return False, f"不足: {shown}{more}（run-pixal3d fetch-models を実行してください）"
    return True, f"{len(required)} ファイル確認済み（{snapshot_dir}）"


def _check_hf_cache_model(repo_id: str) -> tuple[bool, str]:
    """HF_HOME 配下のキャッシュ（models--org--repo）にモデルがあるかを確認する。

    snapshot_download / transformers の from_pretrained が使うのと同じキャッシュ規約
    （huggingface_hub の既定レイアウト）で判定する。ローカル local_dir を明示して落とす
    ckpts/* とは別（そちらは _check_weights が見る）。
    """

    cache_dir = config.HF_HOME_DIR / "hub" / ("models--" + repo_id.replace("/", "--"))
    if cache_dir.is_dir() and any(cache_dir.iterdir()):
        return True, f"{cache_dir} を確認しました"
    return False, f"{cache_dir} がありません（run-pixal3d fetch-models を実行してください）"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _service_is_active() -> bool:
    """pixal3d.service（systemd user ユニット）が動いているか。表示するだけで操作はしない。"""

    try:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", "pixal3d"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return completed.stdout.strip() == "active"


def classify_port_status(port: int, in_use: bool, service_active: bool) -> tuple[bool, str]:
    """ポートの状態を doctor 向けに解釈する純粋関数。

    使用中でも、それが自分（Pixal3D）なら異常ではない。
    """

    if not in_use:
        return True, f"ポート {port} は空いています（起動できます）"
    if service_active:
        return True, f"ポート {port} は Pixal3D が使用中です（稼働しています）"
    return False, f"ポート {port} を別のプロセスが使用中です"


def classify_vram_status(
    used_mib: int | None, threshold_mib: int, service_active: bool
) -> tuple[bool, str]:
    """VRAM の状態を doctor 向けに解釈する純粋関数。

    Pixal3D が稼働中なら、VRAM を使っているのは正常。
    止まっているのに埋まっているなら、Qwen など別のものが載っている。
    """

    if used_mib is None:
        return False, "nvidia-smi の実行に失敗しました"
    if service_active:
        return True, f"使用中 {used_mib} MiB（Pixal3D が稼働中）"
    if used_mib < threshold_mib:
        return True, f"使用中 {used_mib} MiB（空いています）"
    return (
        False,
        f"使用中 {used_mib} MiB（Pixal3D は停止中。Qwen などが載っています。"
        f"run-pixal3d free-vram で降ろせます）",
    )


def _free_ollama_and_wait(skip_vram_check: bool) -> int:
    """Ollama を降ろし、VRAM の空きを待つ。serve と generate の共通処理。"""

    print("Ollama の常駐モデル:")
    before = ollama.loaded_models()
    if before:
        for model in before:
            print(f"  - {model['name']} (size_vram={model['size_vram']})")
    else:
        print("  (なし)")

    try:
        unloaded = ollama.unload_all()
    except RuntimeError as exc:
        print(f"Ollama のモデルを解放できませんでした: {exc}", file=sys.stderr)
        print("  Ollama の状態を確認してください: systemctl status ollama", file=sys.stderr)
        return 1
    if unloaded:
        print(f"解放しました: {', '.join(unloaded)}")

    if skip_vram_check:
        print(
            "警告: --skip-vram-check により VRAM の空き確認を省略しました。"
            "Qwen と同時に載せると OOM の恐れがあります。",
            file=sys.stderr,
        )
        return 0

    ok = ollama.wait_until_free(config.VRAM_FREE_THRESHOLD_MIB, config.VRAM_WAIT_SECONDS)
    if ok:
        return 0

    used = ollama.gpu_used_mib()
    still_loaded = ollama.loaded_models()
    print("VRAM を確保できませんでした。中止します。", file=sys.stderr)
    print(
        f"  使用中 VRAM: {used} MiB（閾値 {config.VRAM_FREE_THRESHOLD_MIB} MiB 未満が必要）",
        file=sys.stderr,
    )
    if still_loaded:
        print("  Ollama に残っているモデル:", file=sys.stderr)
        for model in still_loaded:
            print(f"    - {model['name']}", file=sys.stderr)
    else:
        print(
            "  Ollama にモデルは残っていません（他のプロセスが VRAM を使っています）",
            file=sys.stderr,
        )
    return 1


def cmd_serve(args: argparse.Namespace) -> int:
    rc = _free_ollama_and_wait(args.skip_vram_check)
    if rc != 0:
        return rc

    if not config.VENDOR_DIR.is_dir():
        print(
            f"上流が見つかりません: {config.VENDOR_DIR}（setup-server.sh を実行してください）",
            file=sys.stderr,
        )
        return 1
    if not config.VENV_PYTHON.is_file():
        print(
            f"venv の python が見つかりません: {config.VENV_PYTHON}（setup-server.sh を実行してください）",
            file=sys.stderr,
        )
        return 1

    env_raw = os.environ.get(config.LOW_VRAM_ENV_VAR)
    if args.low_vram is None:
        low_vram = options.low_vram_from_env(os.environ)
        low_vram_source = (
            f"{config.LOW_VRAM_ENV_VAR}={env_raw!r} に従う"
            if env_raw is not None
            else f"{config.LOW_VRAM_ENV_VAR} 未設定のため既定値"
        )
    else:
        low_vram = args.low_vram
        flag = "--low-vram" if low_vram else "--no-low-vram"
        low_vram_source = f"{flag} 指定（{config.LOW_VRAM_ENV_VAR}={env_raw!r} より優先）"
    print(f"低 VRAM モード: {'有効' if low_vram else '無効'}（{low_vram_source}）")

    resolution = args.resolution if args.resolution is not None else (1024 if low_vram else 1536)
    print(f"既定の解像度: {resolution}（画面から変更できます）")

    command = build_serve_command(
        python_bin=str(config.VENV_PYTHON),
        host=args.host,
        port=args.port,
        resolution=resolution,
        low_vram=low_vram,
    )

    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    config.HF_HOME_DIR.mkdir(parents=True, exist_ok=True)
    config.TORCH_HOME_DIR.mkdir(parents=True, exist_ok=True)

    env = build_serve_env(
        base_env=os.environ,
        hf_home=str(config.HF_HOME_DIR),
        torch_home=str(config.TORCH_HOME_DIR),
        vendor_dir=str(config.VENDOR_DIR),
        cuda_home=config.CUDA_HOME,
    )

    print(f"起動します: {' '.join(command)}")
    # execve はプロセスを置き換えるので、ここまでの print がバッファに残っていると
    # そのまま捨てられる（systemd 配下では stdout が端末でないためバッファされる）。
    # journalctl に起動条件が残らず、あとから追えなくなるので必ず流しておく。
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(command[0], command, env)
    # execve が成功すればここには戻らない。
    return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    results: list[tuple[str, bool, str]] = []

    nvcc_ok, nvcc_detail = _check_cuda_nvcc()
    results.append(("CUDA 12.6 の nvcc", nvcc_ok, nvcc_detail))

    venv_ok = config.VENV_PYTHON.is_file()
    results.append(("venv の python が存在", venv_ok, str(config.VENV_PYTHON)))

    torch_probe = _run_venv_python(_TORCH_PROBE, timeout=120)
    import_error = torch_probe.get("import_error")
    torch_import_ok = import_error is None
    results.append(("torch の import", torch_import_ok, import_error if import_error else "OK"))

    cuda_version = torch_probe.get("cuda_version")
    cuda_version_ok = torch_import_ok and isinstance(cuda_version, str) and cuda_version.startswith(
        "12.6"
    )
    results.append(
        ("torch.version.cuda が 12.6 系", cuda_version_ok, str(cuda_version) if cuda_version else "(取得できず)")
    )

    cuda_available = bool(torch_probe.get("cuda_available"))
    results.append(("torch.cuda.is_available()", cuda_available, str(cuda_available)))

    device_name = torch_probe.get("device_name") or ""
    device_ok = cuda_available and "A30" in device_name
    results.append(("GPU デバイス名に A30 を含む", device_ok, device_name or "(取得できず)"))

    commit_ok, commit_detail = _check_git_commit(config.VENDOR_DIR, config.UPSTREAM_COMMIT)
    results.append(("Pixal3D が指定コミットで checkout 済み", commit_ok, commit_detail))

    trellis_ok, trellis_detail = _check_git_commit(config.TRELLIS_DIR, config.TRELLIS_COMMIT)
    results.append(("TRELLIS.2 が指定コミットで checkout 済み", trellis_ok, trellis_detail))

    ext_probe = _run_venv_python(_EXTENSION_PROBE, timeout=60)
    if "import_error" in ext_probe:
        ext_ok = False
        ext_detail = f"確認自体が失敗: {ext_probe['import_error']}"
    else:
        ext_names = ("o_voxel", "cumesh", "flex_gemm", "nvdiffrast", "nvdiffrec_render")
        failed = {name: ext_probe.get(name) for name in ext_names if ext_probe.get(name) is not None}
        ext_ok = not failed
        ext_detail = "OK" if ext_ok else ", ".join(f"{name}={reason!r}" for name, reason in failed.items())
    results.append(("ネイティブ拡張（o_voxel / cumesh / flex_gemm / nvdiffrast / nvdiffrec_render）", ext_ok, ext_detail))

    weights_ok, weights_detail = _check_weights()
    results.append(("重み（pipeline_mv.json と ckpts）", weights_ok, weights_detail))

    # pipeline_mv.json の rembg_model（briaai/RMBG-2.0）はゲート付きで使わないため、
    # px3d.rembg_override で強制している config.REMBG_MODEL の方の有無を確認する。
    rembg_ok, rembg_detail = _check_hf_cache_model(config.REMBG_MODEL)
    results.append((f"背景除去モデル（{config.REMBG_MODEL}）", rembg_ok, rembg_detail))

    service_active = _service_is_active()

    vram_ok, vram_detail = classify_vram_status(
        ollama.gpu_used_mib(), config.VRAM_FREE_THRESHOLD_MIB, service_active
    )
    results.append(("VRAM", vram_ok, vram_detail))

    port_ok, port_detail = classify_port_status(
        config.PORT, _port_in_use(config.PORT), service_active
    )
    results.append(("ポート（7861）", port_ok, port_detail))

    portal_in_use = _port_in_use(config.PORTAL_PORT)
    portal_detail = (
        f"ポート {config.PORTAL_PORT} は応答しています"
        if portal_in_use
        else f"ポート {config.PORTAL_PORT} は応答していません（入口ページ未起動。Pixal3D の動作には必須ではない）"
    )
    # 入口ページは pixal3d が制御するものではないので、OK/NG の判定はせず常に情報表示にする。
    results.append(("入口ページ（8080）の待受", True, portal_detail))

    low_vram_effective = options.read_low_vram_setting()
    low_vram_state = "有効" if low_vram_effective else "無効"
    if config.LOW_VRAM_ENV_FILE.is_file():
        low_vram_detail = f"{config.LOW_VRAM_ENV_FILE} から → {low_vram_state}"
    else:
        low_vram_detail = f"{config.LOW_VRAM_ENV_FILE} が無い（既定値 {low_vram_state}）"
    # OK/NG の判定ではなく情報表示。On/Off どちらも正常な設定なので常に OK にする。
    results.append(("低 VRAM モード設定", True, low_vram_detail))

    results.append(
        (
            "systemd ユーザーユニット pixal3d",
            True,
            "稼働中" if service_active else "停止中（表示のみ。操作はしません）",
        )
    )

    overall_ok = True
    for label, ok, detail in results:
        status = "OK" if ok else "NG"
        print(f"{status}  {label}: {detail}")
        if not ok:
            overall_ok = False
    return 0 if overall_ok else 1


def cmd_fetch_models(args: argparse.Namespace) -> int:
    if not config.VENV_PYTHON.is_file():
        print(
            f"venv の python が見つかりません: {config.VENV_PYTHON}（setup-server.sh を実行してください）",
            file=sys.stderr,
        )
        return 1

    config.HF_HOME_DIR.mkdir(parents=True, exist_ok=True)
    config.TORCH_HOME_DIR.mkdir(parents=True, exist_ok=True)

    # DINOv3 の公式リポジトリ（facebook/dinov3-vitl16-pretrain-lvd1689m）はゲート付きで、
    # inference_mv.py の IMAGE_COND_CONFIGS はこのミラーを直接使っている。
    dino_repo = "camenduru/dinov3-vitl16-pretrain-lvd1689m"

    header = (
        f"repo_id = {config.MODEL_REPO!r}\n"
        f"config_file = {config.PIPELINE_CONFIG!r}\n"
        f"dino_repo = {dino_repo!r}\n"
        f"rembg_model_name = {config.REMBG_MODEL!r}\n"
    )
    script = header + _FETCH_MODELS_SCRIPT_BODY

    env = dict(os.environ)
    # Pixal3D 本体・DINOv3 ミラー・背景除去モデルのいずれも snapshot_download 経由で
    # HF の標準キャッシュに落とすので、実行時（serve/generate）と同じ場所を指す必要がある。
    env["HF_HOME"] = str(config.HF_HOME_DIR)

    print(
        f"重みを取得します（{config.MODEL_REPO} → {config.HF_HOME_DIR} の HF キャッシュ）。"
        "合計約 30GB あります。既にキャッシュにあるファイルは再取得しません。"
    )
    completed = subprocess.run([str(config.VENV_PYTHON), "-c", script], env=env)
    if completed.returncode != 0:
        print("失敗しました", file=sys.stderr)
    return completed.returncode


def cmd_free_vram(args: argparse.Namespace) -> int:
    before = ollama.loaded_models()
    if not before:
        print("Ollama にモデルは載っていません")
        return 0
    for model in before:
        print(f"解放します: {model['name']}")
    unloaded = ollama.unload_all()
    print(f"解放しました: {', '.join(unloaded) if unloaded else '(なし)'}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    rc = _free_ollama_and_wait(args.skip_vram_check)
    if rc != 0:
        return rc

    if not config.VENV_PYTHON.is_file():
        print(
            f"venv の python が見つかりません: {config.VENV_PYTHON}（setup-server.sh を実行してください）",
            file=sys.stderr,
        )
        return 1

    low_vram = args.low_vram if args.low_vram is not None else options.low_vram_from_env(os.environ)
    resolution = args.resolution if args.resolution is not None else (1024 if low_vram else 1536)

    out_path = args.out
    if out_path is None:
        config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(config.OUTPUTS_DIR / f"{timestamp}.glb")

    config.HF_HOME_DIR.mkdir(parents=True, exist_ok=True)
    config.TORCH_HOME_DIR.mkdir(parents=True, exist_ok=True)
    env = build_serve_env(
        base_env=os.environ,
        hf_home=str(config.HF_HOME_DIR),
        torch_home=str(config.TORCH_HOME_DIR),
        vendor_dir=str(config.VENDOR_DIR),
        cuda_home=config.CUDA_HOME,
    )

    header = (
        f"vendor_dir = {str(config.VENDOR_DIR)!r}\n"
        f"views_dir = {args.views_dir!r}\n"
        f"output_path = {out_path!r}\n"
        f"seed = {args.seed!r}\n"
        # リポジトリ ID をそのまま渡し、HF_HOME のキャッシュから読ませる
        # （vendor/Pixal3D/pixal3d/pipelines/base.py の from_pretrained。理由は px3d/ui.py 参照）。
        f"model_path = {config.MODEL_REPO!r}\n"
        f"config_file = {config.PIPELINE_CONFIG!r}\n"
        f"low_vram = {low_vram!r}\n"
        f"resolution = {resolution!r}\n"
        f"rembg_model_name = {config.REMBG_MODEL!r}\n"
    )
    script = header + _GENERATE_SCRIPT_BODY

    print(f"生成します: {args.views_dir} -> {out_path}（低 VRAM: {low_vram}, 解像度: {resolution}）")
    completed = subprocess.run([str(config.VENV_PYTHON), "-c", script], env=env)
    return completed.returncode


def _add_low_vram_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--low-vram",
        dest="low_vram",
        action="store_true",
        default=None,
        help=(
            "低 VRAM モードを強制的に有効にする。"
            f"未指定なら {config.LOW_VRAM_ENV_VAR} 環境変数に従う（既定は有効）"
        ),
    )
    group.add_argument(
        "--no-low-vram",
        dest="low_vram",
        action="store_false",
        default=None,
        help=f"低 VRAM モードを強制的に無効にする。未指定なら {config.LOW_VRAM_ENV_VAR} 環境変数に従う",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="px3d", description="Pixal3D をこの A30 サーバーで動かすための CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="px3d.ui（gradio）を起動する")
    serve_parser.add_argument("--host", default=config.HOST)
    serve_parser.add_argument("--port", type=int, default=config.PORT)
    serve_parser.add_argument(
        "--resolution",
        type=int,
        choices=(1024, 1536),
        default=None,
        help="既定の解像度。未指定なら低 VRAM モードのとき 1024、それ以外は 1536",
    )
    serve_parser.add_argument(
        "--skip-vram-check", action="store_true", help="VRAM の空き確認を省略して続行する"
    )
    _add_low_vram_flags(serve_parser)
    serve_parser.set_defaults(func=cmd_serve)

    doctor_parser = subparsers.add_parser("doctor", help="動作環境を点検する")
    doctor_parser.set_defaults(func=cmd_doctor)

    fetch_parser = subparsers.add_parser("fetch-models", help="重みを取得する（既にあればスキップ）")
    fetch_parser.set_defaults(func=cmd_fetch_models)

    free_parser = subparsers.add_parser("free-vram", help="Ollama のモデルを解放するだけ")
    free_parser.set_defaults(func=cmd_free_vram)

    generate_parser = subparsers.add_parser(
        "generate", help="UI を通さず views-dir から GLB を作る（実機試験と退避路）"
    )
    generate_parser.add_argument(
        "--views-dir",
        default=str(config.VENDOR_DIR / "assets" / "mv_images" / "example"),
        help="transforms.json と画像が入ったディレクトリ（既定: 上流同梱の例）",
    )
    generate_parser.add_argument(
        "--out", default=None, help="出力 GLB のパス（既定: outputs/ へ日時入りで保存）"
    )
    generate_parser.add_argument("--seed", type=int, default=42)
    generate_parser.add_argument(
        "--resolution",
        type=int,
        choices=(1024, 1536),
        default=None,
        help="未指定なら低 VRAM モードのとき 1024、それ以外は 1536",
    )
    generate_parser.add_argument(
        "--skip-vram-check", action="store_true", help="VRAM の空き確認を省略して続行する"
    )
    _add_low_vram_flags(generate_parser)
    generate_parser.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
