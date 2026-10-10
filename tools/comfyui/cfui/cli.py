"""cfui の CLI 本体。

`run-comfyui`（= venv の python）から `python -m cfui.cli <サブコマンド>` として呼ばれる。
このモジュール自体は標準ライブラリのみに依存する。torch や ComfyUI は import しない。
重い確認は venv の python を subprocess で呼ぶスクリプト文字列に閉じ込め、cfui.cli 自体は
素の python（.venv を持たない `uvx --with pytest pytest ...`）からも import できるようにする
（px3d/cli.py と同じ設計方針）。判定は cfui/checks.py の純粋関数に任せる。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import checks, config, workflows

# venv の python で実行する torch 確認用スクリプト。最後の行に JSON を出す。
_TORCH_PROBE = """
import json

result = {}
try:
    import torch
except Exception as exc:
    result["import_error"] = str(exc)
else:
    result["version"] = torch.__version__
    result["cuda_version"] = torch.version.cuda
    result["cuda_available"] = bool(torch.cuda.is_available())
    if result["cuda_available"]:
        try:
            result["device_name"] = torch.cuda.get_device_name(0)
            result["capability"] = "%d.%d" % torch.cuda.get_device_capability(0)
        except Exception as exc:
            result["device_name"] = None
            result["device_name_error"] = str(exc)
print(json.dumps(result))
"""

# CUDA 拡張の確認用スクリプト。import に加えて、A30（sm_80）でカーネルを 1 回ずつ動かす
# （ComfyUI-Trellis2 同梱の wheel は sm_86 / sm_120 しか持たず、import は通っても
# カーネル起動で "no kernel image" になったため、import だけでは確かめにならない）。
# trellis2_node_dir / wtivo_native_dir は cmd_doctor が先頭に代入文として付け足す。
_EXTENSION_PROBE_BODY = """
import json
import sys

result = {"imports": {}, "files": {}, "kernels": {}, "wtivo": {}, "wtivo_files": {}}
try:
    import torch
except Exception as exc:
    result["import_error"] = "torch を import できません: " + str(exc)
    print(json.dumps(result))
    raise SystemExit(0)

# どれも torch の libc10.so にリンクしているので、torch を先に import しておく。
for name, statement in (
    ("cumesh", "import cumesh"),
    ("o_voxel", "import o_voxel"),
    ("flex_gemm", "import flex_gemm"),
    ("nvdiffrast", "import nvdiffrast.torch"),
):
    try:
        exec(statement)
        module = sys.modules[statement.split()[-1]]
        result["imports"][name] = None
        result["files"][name] = getattr(module, "__file__", None)
    except Exception as exc:
        result["imports"][name] = type(exc).__name__ + ": " + str(exc)

try:
    import cumesh
    result["has_quad"] = callable(getattr(cumesh.remeshing, "reconstruct_mesh_dc_quad", None))
except Exception as exc:
    result["has_quad"] = False

def _kernel(name, func):
    try:
        result["kernels"][name] = {"ok": True, "detail": str(func())}
    except Exception as exc:
        result["kernels"][name] = {"ok": False, "detail": type(exc).__name__ + ": " + str(exc).splitlines()[0][:200]}

def _cumesh_kernel():
    import cumesh
    verts = torch.tensor([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=torch.float32, device="cuda")
    faces = torch.tensor([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=torch.int32, device="cuda")
    mesh = cumesh.CuMesh()
    mesh.init(verts, faces)
    mesh.compute_vertex_normals()
    normals = mesh.read_vertex_normals()
    torch.cuda.synchronize()
    return "normals " + str(tuple(normals.shape))

def _nvdiffrast_kernel():
    import nvdiffrast.torch as dr
    context = dr.RasterizeCudaContext()
    positions = torch.tensor([[[-0.8, -0.8, 0, 1], [0.8, -0.8, 0, 1], [0, 0.8, 0, 1]]], dtype=torch.float32, device="cuda")
    triangles = torch.tensor([[0, 1, 2]], dtype=torch.int32, device="cuda")
    raster, _ = dr.rasterize(context, positions, triangles, resolution=[64, 64])
    torch.cuda.synchronize()
    return "covered pixels " + str(int((raster[..., 3] > 0).sum().item()))

def _flex_gemm_kernel():
    from flex_gemm.ops.grid_sample import grid_sample_3d
    coords = torch.tensor([[0, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 1, 1, 1]], dtype=torch.int32, device="cuda")
    feats = torch.randn(4, 8, device="cuda")
    grid = torch.rand(1, 5, 3, device="cuda")
    out = grid_sample_3d(feats, coords, torch.Size([1, 8, 4, 4, 4]), grid)
    torch.cuda.synchronize()
    return "grid_sample_3d " + str(tuple(out.shape))

if torch.cuda.is_available():
    if result["imports"].get("cumesh") is None:
        _kernel("cumesh", _cumesh_kernel)
    if result["imports"].get("nvdiffrast") is None:
        _kernel("nvdiffrast", _nvdiffrast_kernel)
    if result["imports"].get("flex_gemm") is None:
        _kernel("flex_gemm", _flex_gemm_kernel)

# Trellis2-Mesh-Encoder は ComfyUI-Trellis2 のフォルダを sys.path に足してから
# trellis2.modules.sparse の SparseTensor を読む（mesh_encoder.py:26-28, 80-83）。
sys.path.insert(0, trellis2_node_dir)
try:
    from trellis2.modules.sparse import SparseTensor
    result["trellis2_sparse"] = None
except Exception as exc:
    result["trellis2_sparse"] = type(exc).__name__ + ": " + str(exc)
sys.path.remove(trellis2_node_dir)

# WTiVo のノードは ROOT/build を sys.path に足してから wtivo_* を import する（wtivo.py:44-49, 86-89）。
sys.path.insert(0, wtivo_native_dir)
for name in ("wtivo_core", "wtivo_gpupr", "wtivo_vdb"):
    try:
        module = __import__(name)
        result["wtivo"][name] = None
        result["wtivo_files"][name] = getattr(module, "__file__", None)
    except Exception as exc:
        result["wtivo"][name] = type(exc).__name__ + ": " + str(exc)
print(json.dumps(result))
"""


def build_serve_command(
    *,
    python_bin: str,
    main_py: str,
    host: str,
    port: int,
    extra_args: list[str],
) -> list[str]:
    """ComfyUI の起動コマンドを組み立てる純粋関数。"""

    return [python_bin, main_py, "--listen", host, "--port", str(port), *extra_args]


def build_serve_env(base_env: Mapping[str, str], blender_clean_dir: Path) -> dict[str, str]:
    """ComfyUI に渡す環境変数を組み立てる純粋関数。

    LODTailor / Bake Forger / LODsmith は Blender を子プロセスで呼ぶ。利用者のアドオンが
    ヘッドレス実行を壊すことがある（配布元 README の Troubleshooting）ため、Blender の
    利用者設定・スクリプト・拡張の置き場を空のフォルダへ向ける。
    """

    env = dict(base_env)
    for variable, subdir in config.BLENDER_ENV_DIRS.items():
        env[variable] = str(blender_clean_dir / subdir)
    return env


def extra_args_from_env(env: Mapping[str, str]) -> list[str]:
    """COMFYUI_EXTRA_ARGS（env ファイルで設定する）をシェルと同じ規則で分ける。"""

    return shlex.split(env.get(config.EXTRA_ARGS_ENV_VAR, ""))


def _run_venv_python(script: str, timeout: float, args: list[str] | None = None) -> dict[str, Any]:
    """venv の python で script を -c 実行し、最後の行を JSON として読む。"""

    if not config.VENV_PYTHON.is_file():
        return {"import_error": f"venv の python がありません: {config.VENV_PYTHON}"}
    try:
        completed = subprocess.run(
            [str(config.VENV_PYTHON), "-c", script, *(args or [])],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"import_error": f"venv の python の起動に失敗しました: {exc}"}
    parsed = checks.parse_last_json_line(completed.stdout)
    if parsed is None:
        detail = completed.stderr.strip().splitlines()[-1:] or ["標準出力が空でした"]
        return {"import_error": detail[0]}
    return parsed


def _run_text(command: list[str], timeout: float) -> str | None:
    """コマンドを実行して標準出力を返す。起動できなければ None。"""

    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.SubprocessError, OSError):
        return None
    return completed.stdout


def _git_head(directory: Path) -> str | None:
    if not (directory / ".git").exists():
        return None
    output = _run_text(["git", "-C", str(directory), "rev-parse", "HEAD"], timeout=10)
    return output.strip() if output else None


def _patch_state(directory: Path, patch_file: Path) -> str:
    """パッチが当たっているか（applied / applicable / conflict / missing）。"""

    if not (directory / ".git").exists() or not patch_file.is_file():
        return "missing"
    reverse = subprocess.run(
        ["git", "-C", str(directory), "apply", "--reverse", "--check", str(patch_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if reverse.returncode == 0:
        return "applied"
    forward = subprocess.run(
        ["git", "-C", str(directory), "apply", "--check", str(patch_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    return "applicable" if forward.returncode == 0 else "conflict"


def _apt_installed(package_name: str) -> bool:
    output = _run_text(["dpkg-query", "-W", "-f=${Status}", package_name], timeout=10)
    return bool(output) and "install ok installed" in output


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _service_is_active() -> bool:
    """comfyui.service（systemd user ユニット）が動いているか。表示するだけで操作はしない。"""

    output = _run_text(["systemctl", "--user", "is-active", config.SERVICE_NAME], timeout=10)
    return bool(output) and output.strip() == "active"


def _gpu_used_mib() -> int | None:
    output = _run_text(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], timeout=10
    )
    if not output:
        return None
    try:
        return int(output.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def _workflow_blender_values() -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for file_name in config.WORKFLOW_FILES:
        path = config.WORKFLOWS_DIR / file_name
        try:
            values[file_name] = workflows.blender_path_value(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            values[file_name] = None
    return values


def _run_selftest(timeout: float) -> dict[str, Any]:
    script = config.SCRIPTS_DIR / "wtivo_selftest.py"
    try:
        completed = subprocess.run(
            [str(config.VENV_PYTHON), str(script), str(config.WTIVO_NODE_DIR)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"{timeout:.0f} 秒で終わりませんでした"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"error": f"起動できませんでした: {exc}"}
    parsed = checks.parse_last_json_line(completed.stdout)
    if parsed is None:
        tail = completed.stderr.strip().splitlines()[-1:] or ["出力がありません"]
        return {"error": tail[0]}
    return parsed


def cmd_doctor(args: argparse.Namespace) -> int:
    rows: list[checks.Row] = []

    nvcc_output = _run_text([str(Path(config.CUDA_HOME) / "bin" / "nvcc"), "--version"], timeout=10)
    rows.append(("CUDA 12.6 の nvcc", *checks.classify_nvcc(nvcc_output, config.EXPECTED_NVCC_RELEASE)))

    rows.append(("venv の python が存在", config.VENV_PYTHON.is_file(), str(config.VENV_PYTHON)))

    torch_probe = _run_venv_python(_TORCH_PROBE, timeout=120)
    rows.extend(
        checks.classify_torch(
            torch_probe,
            config.EXPECTED_TORCH_VERSION,
            config.EXPECTED_TORCH_CUDA,
            config.EXPECTED_GPU_SUBSTRING,
        )
    )

    rows.append(
        (
            f"ComfyUI {config.COMFYUI_TAG} が指定コミット",
            *checks.classify_commit(_git_head(config.COMFYUI_DIR), config.COMFYUI_COMMIT),
        )
    )
    for node_name, _url, commit in config.CUSTOM_NODES:
        rows.append(
            (
                f"custom_nodes/{node_name}",
                *checks.classify_commit(_git_head(config.CUSTOM_NODES_DIR / node_name), commit),
            )
        )
    rows.append(
        (
            "WTiVo-WatertightVoxel（姉妹 repo、ソース）",
            *checks.classify_commit(_git_head(config.WTIVO_SRC_DIR), config.WTIVO_SRC_COMMIT),
        )
    )
    for label, directory, patch_name in (
        ("パッチ（姉妹 repo、Linux でビルド）", config.WTIVO_SRC_DIR, "wtivo-src-linux-build.patch"),
        ("パッチ（姉妹 repo、wtivo_core の返り値）", config.WTIVO_SRC_DIR, "wtivo-src-core-vertices-lifetime.patch"),
        ("パッチ（WTiVo ノード）", config.WTIVO_NODE_DIR, "wtivo-node-allow-linux.patch"),
        ("パッチ（CuMesh）", config.EXTENSIONS_DIR / "CuMesh", "cumesh-eigen-include.patch"),
    ):
        state = _patch_state(directory, config.PATCHES_DIR / patch_name)
        rows.append((label, *checks.classify_patch(state, patch_name)))

    apt_status = {name: _apt_installed(name) for name in config.WTIVO_APT_PACKAGES}
    rows.append(("WTiVo のビルドに要る apt パッケージ", *checks.classify_apt_packages(apt_status)))

    probe_script = (
        f"trellis2_node_dir = {str(config.TRELLIS2_NODE_DIR)!r}\n"
        f"wtivo_native_dir = {str(config.WTIVO_NATIVE_DIR)!r}\n" + _EXTENSION_PROBE_BODY
    )
    ext_probe = _run_venv_python(probe_script, timeout=300)
    if "import_error" in ext_probe:
        rows.append(("CUDA 拡張の確認", False, f"確認自体が失敗: {ext_probe['import_error']}"))
        wtivo_ok = False
    else:
        imports = ext_probe.get("imports", {})
        files = ext_probe.get("files", {})
        for name, _statement in config.EXTENSION_IMPORTS:
            rows.append(
                (f"拡張の import（{name}）", *checks.classify_import(imports.get(name, "確認されていません"), files.get(name)))
            )
        rows.append(
            (
                "cumesh.remeshing.reconstruct_mesh_dc_quad（Quad Reconstruct 用）",
                bool(ext_probe.get("has_quad")),
                "あります" if ext_probe.get("has_quad") else "ありません（visualbruno/CuMesh ではない）",
            )
        )
        kernels = ext_probe.get("kernels", {})
        for name in ("cumesh", "nvdiffrast", "flex_gemm"):
            kernel = kernels.get(name)
            if kernel is None:
                rows.append((f"拡張の CUDA カーネル（{name}、sm_80）", False, "実行していません（import か CUDA が NG）"))
            else:
                rows.append((f"拡張の CUDA カーネル（{name}、sm_80）", bool(kernel.get("ok")), str(kernel.get("detail"))))
        trellis_error = ext_probe.get("trellis2_sparse", "確認されていません")
        rows.append(
            (
                "trellis2.modules.sparse の解決（Trellis2-Mesh-Encoder 用）",
                *checks.classify_import(trellis_error, "SparseTensor を読めました" if trellis_error is None else None),
            )
        )
        wtivo_imports = ext_probe.get("wtivo", {})
        wtivo_files = ext_probe.get("wtivo_files", {})
        wtivo_ok = True
        for name in config.WTIVO_MODULES:
            ok, detail = checks.classify_wtivo_module(
                wtivo_imports.get(name, "確認されていません"), wtivo_files.get(name), str(config.WTIVO_NATIVE_DIR)
            )
            wtivo_ok = wtivo_ok and ok
            rows.append((f"WTiVo の import（{name}）", ok, detail))

    for subdir, file_name, _repo, _path, size, _sha in config.MODEL_FILES:
        target = config.MODELS_DIR / subdir / file_name
        actual = target.stat().st_size if target.is_file() else None
        rows.append((f"モデル {subdir}/{file_name}", *checks.classify_model_file(actual, size)))

    sample = config.INPUT_DIR / config.SAMPLE_IMAGE_NAME
    rows.append(
        (
            f"サンプル画像 input/{config.SAMPLE_IMAGE_NAME}",
            sample.is_file(),
            f"{sample.stat().st_size} バイト" if sample.is_file() else "ありません（run-comfyui fetch-models）",
        )
    )

    rows.append(
        (
            "ワークフロー 4 本（user/default/workflows/PixelArtistry）",
            *checks.classify_workflows(_workflow_blender_values(), config.BLENDER_PATH),
        )
    )

    try:
        blender_resolved: str | None = str(Path(config.BLENDER_PATH).resolve(strict=True))
    except OSError:
        blender_resolved = None
    rows.append(
        (
            f"Blender の起動（{config.BLENDER_PATH} が snap run を通らない）",
            *checks.classify_blender_launcher(blender_resolved, config.BLENDER_SNAP_LAUNCHER),
        )
    )

    blender_output = _run_text([config.BLENDER_PATH, "--version"], timeout=120)
    rows.append(
        (
            f"Blender（{config.BLENDER_PATH} --version が {config.BLENDER_MAJOR_REQUIRED}.x）",
            *checks.classify_blender(blender_output, config.BLENDER_MAJOR_REQUIRED),
        )
    )

    service_active = _service_is_active()
    rows.append(
        (f"ポート（{config.PORT}）", *checks.classify_port_status(config.PORT, _port_in_use(config.PORT), service_active))
    )

    if args.skip_selftest:
        selftest = {"skipped": True, "reason": "--skip-selftest が指定されました"}
    elif not wtivo_ok:
        selftest = {"skipped": True, "reason": "wtivo_* を import できないため"}
    else:
        selftest = _run_selftest(timeout=args.selftest_timeout)
    rows.append(("WTiVo の自己試験（穴あき球 → 防水、bat の L457-484 と同条件）", *checks.classify_selftest(selftest)))

    # ここから下は表示のみ（常に OK）。
    rows.append(("VRAM", *checks.classify_vram_status(_gpu_used_mib(), config.VRAM_FREE_THRESHOLD_MIB, service_active)))
    rows.append(
        (
            f"systemd ユーザーユニット {config.SERVICE_NAME}",
            True,
            "稼働中" if service_active else "停止中（表示のみ。操作はしません。自動起動は設定しない方針）",
        )
    )

    overall, lines = checks.summarize(rows)
    for line in lines:
        print(line)
    if selftest.get("log_tail") and not checks.classify_selftest(selftest)[0]:
        print("---- 自己試験のログ末尾 ----")
        for line in selftest["log_tail"]:
            print("  " + line)
    return 0 if overall else 1


def cmd_serve(args: argparse.Namespace) -> int:
    if not config.VENV_PYTHON.is_file():
        print(f"venv の python がありません: {config.VENV_PYTHON}（先に setup-server.sh を実行してください）", file=sys.stderr)
        return 1
    main_py = config.COMFYUI_DIR / "main.py"
    if not main_py.is_file():
        print(f"ComfyUI がありません: {main_py}（先に setup-server.sh を実行してください）", file=sys.stderr)
        return 1
    for subdir in config.BLENDER_ENV_DIRS.values():
        (config.BLENDER_CLEAN_DIR / subdir).mkdir(parents=True, exist_ok=True)

    extra_args = extra_args_from_env(os.environ) + list(args.extra)
    command = build_serve_command(
        python_bin=str(config.VENV_PYTHON),
        main_py=str(main_py),
        host=args.host,
        port=args.port,
        extra_args=extra_args,
    )
    env = build_serve_env(os.environ, config.BLENDER_CLEAN_DIR)
    print("起動します: " + " ".join(shlex.quote(part) for part in command), flush=True)
    # ComfyUI は作業ディレクトリを基準に input / output / user を探すので、本体のフォルダへ移ってから exec する。
    os.chdir(config.COMFYUI_DIR)
    os.execve(command[0], command, env)
    return 0  # exec が戻ってくることは無い


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 24), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path) -> None:
    """curl で target.part へ取り（途中からの再開あり）、終わったら target へ移す。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    subprocess.run(
        ["curl", "-L", "--fail", "--retry", "3", "-sS", "-C", "-", "-o", str(part), url],
        check=True,
    )
    part.replace(target)


def cmd_fetch_models(args: argparse.Namespace) -> int:
    if shutil.which("curl") is None:
        print("curl がありません", file=sys.stderr)
        return 1
    failures = 0
    for subdir, file_name, repo, path_in_repo, size, sha256 in config.MODEL_FILES:
        target = config.MODELS_DIR / subdir / file_name
        label = f"{subdir}/{file_name}"
        if target.is_file() and target.stat().st_size == size and not args.verify:
            print(f"  {label}: 既にあります（{size} バイト）")
            continue
        if not (target.is_file() and target.stat().st_size == size):
            url = checks.model_url(config.HF_BASE_URL, repo, path_in_repo)
            print(f"  {label}: 取得します（{size / 1024 ** 3:.2f} GiB, {url}）", flush=True)
            try:
                _download(url, target)
            except subprocess.CalledProcessError as exc:
                print(f"  {label}: 取得に失敗しました（{exc}）", file=sys.stderr)
                failures += 1
                continue
        actual_sha = _sha256_of(target)
        if actual_sha != sha256:
            # 上流（resolve/main）が差し替わった可能性がある。勝手に使わず、消してやり直せる状態にする。
            print(
                f"  {label}: sha256 が違います（{actual_sha}、期待値 {sha256}）。"
                f"上流が更新された可能性があります。{target} を確認してください",
                file=sys.stderr,
            )
            failures += 1
            continue
        print(f"  {label}: sha256 を確認しました")

    sample = config.INPUT_DIR / config.SAMPLE_IMAGE_NAME
    if sample.is_file():
        print(f"  input/{config.SAMPLE_IMAGE_NAME}: 既にあります")
    else:
        print(f"  input/{config.SAMPLE_IMAGE_NAME}: 取得します（{config.SAMPLE_IMAGE_URL}）", flush=True)
        try:
            _download(config.SAMPLE_IMAGE_URL, sample)
        except subprocess.CalledProcessError as exc:
            print(f"  サンプル画像の取得に失敗しました（{exc}）", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 1


def cmd_selftest(args: argparse.Namespace) -> int:
    result = _run_selftest(timeout=args.selftest_timeout)
    ok, detail = checks.classify_selftest(result)
    print(f"{'OK' if ok else 'NG'}  WTiVo の自己試験: {detail}")
    for line in result.get("log_tail") or []:
        print("  " + line)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfui", description="ComfyUI をこの A30 サーバーで動かすための CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="ComfyUI（vendor/ComfyUI/main.py）を起動する")
    serve_parser.add_argument("--host", default=config.HOST)
    serve_parser.add_argument("--port", type=int, default=config.PORT)
    serve_parser.add_argument(
        "extra", nargs=argparse.REMAINDER, help="main.py に足す引数（-- の後ろに書く）"
    )
    serve_parser.set_defaults(func=cmd_serve)

    doctor_parser = subparsers.add_parser("doctor", help="動作環境を点検する")
    doctor_parser.add_argument(
        "--skip-selftest", action="store_true", help="WTiVo の自己試験（GPU を使う）を省く"
    )
    doctor_parser.add_argument("--selftest-timeout", type=float, default=900.0, help="自己試験の制限時間（秒）")
    doctor_parser.set_defaults(func=cmd_doctor)

    fetch_parser = subparsers.add_parser("fetch-models", help="重みとサンプル画像を取得する（既にあればスキップ）")
    fetch_parser.add_argument(
        "--verify", action="store_true", help="既にあるファイルも sha256 を計算して確かめる"
    )
    fetch_parser.set_defaults(func=cmd_fetch_models)

    selftest_parser = subparsers.add_parser("selftest", help="WTiVo の自己試験だけを行う")
    selftest_parser.add_argument("--selftest-timeout", type=float, default=900.0)
    selftest_parser.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "extra", None) and args.extra[:1] == ["--"]:
        args.extra = args.extra[1:]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
