"""hy3d の CLI 本体。

`run-hunyuan3d`（= venv の python）から `python -m hy3d.cli <サブコマンド>` として呼ばれる。
このモジュール自体は標準ライブラリのみに依存する。torch を使う確認（doctor）は、
venv の python を subprocess で呼び出すことで行い、hy3d 自体は素の python からも動くようにする。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from . import config, ollama

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

# ネイティブ拡張（texgen 配下のみ）の import 確認用スクリプト。
# どちらも import できなくても形状生成はできるので、doctor 側で文言を分ける。
_EXTENSION_PROBE = """
import json

result = {}
# custom_rasterizer_kernel は torch の libc10.so にリンクしている。torch を先に import しないと
# ImportError: libc10.so になる（拡張が壊れているわけではない）。上流も必ず torch を先に読む。
try:
    import torch  # noqa: F401
except Exception as exc:
    result["import_error"] = "torch を import できません: " + str(exc)
    print(json.dumps(result))
    raise SystemExit(0)
try:
    import custom_rasterizer_kernel  # noqa: F401
except Exception as exc:
    result["custom_rasterizer_kernel"] = str(exc)
else:
    result["custom_rasterizer_kernel"] = None
try:
    import mesh_processor  # noqa: F401
except Exception as exc:
    result["mesh_processor"] = str(exc)
else:
    result["mesh_processor"] = None
print(json.dumps(result))
"""


def build_gradio_command(
    *,
    python_bin: str,
    script_path: str,
    host: str,
    port: int,
    texture: bool,
    low_vram: bool,
    cache_path: str,
) -> list[str]:
    """gradio_app.py を起動するコマンド列を組み立てる純粋関数。

    ファイルシステムにもネットワークにも触れない。テストで検証するためにここへ切り出している。
    """

    command = [
        python_bin,
        script_path,
        "--model_path",
        config.SHAPE_REPO,
        "--subfolder",
        config.SHAPE_SUBFOLDER,
    ]
    if texture:
        command += ["--texgen_model_path", config.TEXGEN_REPO]
    else:
        command += ["--disable_tex"]
    if low_vram:
        command += ["--low_vram_mode"]
    command += [
        "--enable_flashvdm",
        "--host",
        host,
        "--port",
        str(port),
        "--cache-path",
        cache_path,
    ]
    return command


def low_vram_from_env(environ: Mapping[str, str]) -> bool:
    """環境変数 HY3D_LOW_VRAM から低 VRAM モードの有効/無効を読む純粋関数。

    ファイルシステムにもネットワークにも触れない。"1"/"true"/"on"/"yes"（大小文字を無視）を
    True、"0"/"false"/"off"/"no" を False とする。未設定や解釈できない値は既定（有効）にする。
    """

    raw = environ.get(config.LOW_VRAM_ENV_VAR)
    if raw is None:
        return config.LOW_VRAM_DEFAULT
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "on", "yes"):
        return True
    if normalized in ("0", "false", "off", "no"):
        return False
    return config.LOW_VRAM_DEFAULT


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


def _check_upstream_commit() -> tuple[bool, str]:
    if not config.VENDOR_DIR.is_dir():
        return False, f"上流が見つかりません: {config.VENDOR_DIR}"
    try:
        completed = subprocess.run(
            ["git", "-C", str(config.VENDOR_DIR), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"git rev-parse に失敗しました: {exc}"
    head = completed.stdout.strip()
    if head == config.UPSTREAM_COMMIT:
        return True, f"HEAD={head}"
    return False, f"HEAD={head}（期待値 {config.UPSTREAM_COMMIT}）"


def _check_shape_weights() -> tuple[bool, str]:
    base = config.MODELS_DIR / config.SHAPE_REPO / config.SHAPE_SUBFOLDER
    ok = all((base / name).is_file() for name in config.SHAPE_WEIGHT_FILES)
    return ok, str(base)


def _dir_has_files(directory: Path) -> bool:
    return directory.is_dir() and any(directory.iterdir())


def _check_texture_weights() -> tuple[bool, str]:
    base = config.MODELS_DIR / config.TEXGEN_REPO
    delight_dir = base / config.DELIGHT_SUBFOLDER
    paint_dir = base / config.TEXGEN_SUBFOLDER
    ok = _dir_has_files(delight_dir) and _dir_has_files(paint_dir)
    return ok, f"{delight_dir}, {paint_dir}"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _service_is_active() -> bool:
    """hunyuan3d.service（systemd user ユニット）が動いているか。"""

    try:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", "hunyuan3d"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return completed.stdout.strip() == "active"


def classify_port_status(port: int, in_use: bool, service_active: bool) -> tuple[bool, str]:
    """ポートの状態を doctor 向けに解釈する純粋関数。

    使用中でも、それが自分（hunyuan3d）なら異常ではない。
    """

    if not in_use:
        return True, f"ポート {port} は空いています（起動できます）"
    if service_active:
        return True, f"ポート {port} は Hunyuan3D が使用中です（稼働しています）"
    return False, f"ポート {port} を別のプロセスが使用中です"


def classify_vram_status(
    used_mib: int | None, threshold_mib: int, service_active: bool
) -> tuple[bool, str]:
    """VRAM の状態を doctor 向けに解釈する純粋関数。

    Hunyuan3D が稼働中なら、VRAM を使っているのは正常。
    止まっているのに埋まっているなら、Qwen など別のものが載っている。
    """

    if used_mib is None:
        return False, "nvidia-smi の実行に失敗しました"
    if service_active:
        return True, f"使用中 {used_mib} MiB（Hunyuan3D が稼働中）"
    if used_mib < threshold_mib:
        return True, f"使用中 {used_mib} MiB（空いています）"
    return (
        False,
        f"使用中 {used_mib} MiB（Hunyuan3D は停止中。Qwen などが載っています。"
        f"run-hunyuan3d free-vram で降ろせます）",
    )


def _read_low_vram_env_file() -> str | None:
    """低 VRAM モードの env ファイルから HY3D_LOW_VRAM の生の値を読む。

    ファイルが無い、または変数が書かれていなければ None。doctor 表示専用で、
    systemd の EnvironmentFile と同じ場所（config.LOW_VRAM_ENV_FILE）を素朴にパースするだけ。
    """

    if not config.LOW_VRAM_ENV_FILE.is_file():
        return None
    for line in config.LOW_VRAM_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == config.LOW_VRAM_ENV_VAR:
            return value.strip()
    return None


def cmd_serve(args: argparse.Namespace) -> int:
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

    if args.skip_vram_check:
        print(
            "警告: --skip-vram-check により VRAM の空き確認を省略しました。"
            "Qwen と同時に載せると OOM の恐れがあります。",
            file=sys.stderr,
        )
    else:
        ok = ollama.wait_until_free(config.VRAM_FREE_THRESHOLD_MIB, config.VRAM_WAIT_SECONDS)
        if not ok:
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
        low_vram = low_vram_from_env(os.environ)
        low_vram_source = (
            f"HY3D_LOW_VRAM={env_raw!r} に従う"
            if env_raw is not None
            else "HY3D_LOW_VRAM 未設定のため既定値"
        )
    else:
        low_vram = args.low_vram
        flag = "--low-vram" if low_vram else "--no-low-vram"
        low_vram_source = f"{flag} 指定（HY3D_LOW_VRAM={env_raw!r} より優先）"
    print(f"低 VRAM モード: {'有効' if low_vram else '無効'}（{low_vram_source}）")

    command = build_gradio_command(
        python_bin=str(config.VENV_PYTHON),
        script_path="gradio_app.py",
        host=args.host,
        port=args.port,
        texture=not args.no_texture,
        low_vram=low_vram,
        cache_path=str(config.OUTPUTS_DIR),
    )

    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    config.HF_HOME_DIR.mkdir(parents=True, exist_ok=True)
    config.U2NET_HOME_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HY3DGEN_MODELS"] = str(config.MODELS_DIR)
    # 上流は一部の重み（DINOv2 など）を実行時に HF から落とす。既定のままだと
    # Open WebUI と共有している ~/.cache/huggingface に混ざるので、このツールの下へ向ける。
    env["HF_HOME"] = str(config.HF_HOME_DIR)
    # rembg（背景除去）の u2net.onnx（168MB）も既定では ~/.u2net へ落ちる。
    env["U2NET_HOME"] = str(config.U2NET_HOME_DIR)

    print(f"起動します（cwd={config.VENDOR_DIR}）: {' '.join(command)}")
    os.chdir(config.VENDOR_DIR)
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

    venv_ok = config.VENV_PYTHON.is_file()
    results.append(("venv の python が存在", venv_ok, str(config.VENV_PYTHON)))

    torch_probe = _run_venv_python(_TORCH_PROBE, timeout=120)
    import_error = torch_probe.get("import_error")
    torch_import_ok = import_error is None
    results.append(("torch の import", torch_import_ok, import_error if import_error else "OK"))

    cuda_version = torch_probe.get("cuda_version")
    cuda_version_ok = torch_import_ok and isinstance(cuda_version, str) and cuda_version.startswith(
        "13"
    )
    results.append(
        ("torch.version.cuda が 13 系", cuda_version_ok, str(cuda_version) if cuda_version else "(取得できず)")
    )

    cuda_available = bool(torch_probe.get("cuda_available"))
    results.append(("torch.cuda.is_available()", cuda_available, str(cuda_available)))

    device_name = torch_probe.get("device_name") or ""
    device_ok = cuda_available and "A30" in device_name
    results.append(("GPU デバイス名に A30 を含む", device_ok, device_name or "(取得できず)"))

    commit_ok, commit_detail = _check_upstream_commit()
    results.append(("上流が指定コミットで checkout 済み", commit_ok, commit_detail))

    ext_probe = _run_venv_python(_EXTENSION_PROBE, timeout=60)
    rasterizer_error = ext_probe.get("custom_rasterizer_kernel")
    mesh_error = ext_probe.get("mesh_processor")
    if "import_error" in ext_probe:
        ext_ok = False
        ext_detail = f"テクスチャ生成のみ不可（確認自体が失敗）: {ext_probe['import_error']}"
    else:
        ext_ok = rasterizer_error is None and mesh_error is None
        ext_detail = (
            "OK"
            if ext_ok
            else (
                "テクスチャ生成のみ不可: "
                f"custom_rasterizer_kernel={rasterizer_error!r}, mesh_processor={mesh_error!r}"
            )
        )
    results.append(("ネイティブ拡張（custom_rasterizer_kernel / mesh_processor）", ext_ok, ext_detail))

    shape_ok, shape_detail = _check_shape_weights()
    results.append(("形状モデルの重み", shape_ok, shape_detail))

    vae_dir = config.MODELS_DIR / config.TEXGEN_REPO / config.VAE_TURBO_SUBFOLDER
    vae_ok = all((vae_dir / name).is_file() for name in config.SHAPE_WEIGHT_FILES)
    results.append(("flashvdm 用 VAE の重み", vae_ok, str(vae_dir)))

    texture_ok, texture_detail = _check_texture_weights()
    results.append(("テクスチャモデルの重み", texture_ok, texture_detail))

    service_active = _service_is_active()

    vram_ok, vram_detail = classify_vram_status(
        ollama.gpu_used_mib(), config.VRAM_FREE_THRESHOLD_MIB, service_active
    )
    results.append(("VRAM", vram_ok, vram_detail))

    port_ok, port_detail = classify_port_status(
        config.PORT, _port_in_use(config.PORT), service_active
    )
    results.append(("ポート", port_ok, port_detail))

    env_value = _read_low_vram_env_file()
    low_vram_effective = low_vram_from_env(
        {config.LOW_VRAM_ENV_VAR: env_value} if env_value is not None else {}
    )
    low_vram_state = "有効" if low_vram_effective else "無効"
    if env_value is None:
        low_vram_detail = f"{config.LOW_VRAM_ENV_FILE} が無い（既定値 {low_vram_state}）"
    else:
        low_vram_detail = f"{config.LOW_VRAM_ENV_FILE} の HY3D_LOW_VRAM={env_value!r} → {low_vram_state}"
    # OK/NG の判定ではなく情報表示。On/Off どちらも正常な設定なので常に OK にする。
    results.append(("低 VRAM モード設定", True, low_vram_detail))

    overall_ok = True
    for label, ok, detail in results:
        status = "OK" if ok else "NG"
        print(f"{status}  {label}: {detail}")
        if not ok:
            overall_ok = False
    return 0 if overall_ok else 1


def _fetch_targets(include_texture: bool) -> list[tuple[str, str, tuple[str, ...] | None]]:
    """(repo_id, subfolder, 必須ファイル名) の一覧。必須ファイル名が None なら subfolder 内全部で判定。"""

    targets: list[tuple[str, str, tuple[str, ...] | None]] = [
        (config.SHAPE_REPO, config.SHAPE_SUBFOLDER, config.SHAPE_WEIGHT_FILES),
        # --enable_flashvdm が要求する turbo VAE。テクスチャの有無に関係なく要る。
        (config.TEXGEN_REPO, config.VAE_TURBO_SUBFOLDER, config.SHAPE_WEIGHT_FILES),
    ]
    if include_texture:
        targets.append((config.TEXGEN_REPO, config.DELIGHT_SUBFOLDER, None))
        targets.append((config.TEXGEN_REPO, config.TEXGEN_SUBFOLDER, None))
    return targets


def build_allow_patterns(subfolder: str, required_files: tuple[str, ...] | None) -> list[str]:
    """snapshot_download に渡す allow_patterns を組み立てる純粋関数。

    required_files が None なら subfolder 配下を全部落とす。
    分かっているならそのファイルだけに絞る。形状モデルの subfolder には
    model.fp16.safetensors と同じ内容の model.fp16.ckpt（4.93GB）が並んでいるため、
    絞らないと倍の量をダウンロードすることになる。
    """

    if required_files is None:
        return [f"{subfolder}/*"]
    return [f"{subfolder}/{name}" for name in required_files]


def _weights_present(local_dir: Path, required_files: tuple[str, ...] | None) -> bool:
    if required_files is None:
        return _dir_has_files(local_dir)
    return all((local_dir / name).is_file() for name in required_files)


LICENSE_ACCEPT_ENV = "HY3D_ACCEPT_LICENSE"
LICENSE_ACCEPT_MESSAGE = """\
重みの取得の前に、Tencent Hunyuan 3D 2.0 Community License への同意が要ります。
  - EU・UK・韓国は使用許諾の対象外（日本は対象内）。月間アクティブユーザー 100 万人超は別途申請
  - 出力を使って、ほかの AI モデルを改善してはならない
  - 原文: vendor/Hunyuan3D-2/LICENSE（setup-server.sh が上流を取得したあとに読める）
原文を読んで同意する場合は --accept-tencent-license を付けるか、環境変数 HY3D_ACCEPT_LICENSE=1 を設定してください。"""


def license_accepted(args: argparse.Namespace) -> bool:
    """重みの取得に必要な使用許諾の同意があるか（引数か環境変数）。"""
    if getattr(args, "accept_tencent_license", False):
        return True
    return os.environ.get(LICENSE_ACCEPT_ENV, "") == "1"


def cmd_fetch_models(args: argparse.Namespace) -> int:
    if not license_accepted(args):
        print(LICENSE_ACCEPT_MESSAGE, file=sys.stderr)
        return 2
    if not config.VENV_PYTHON.is_file():
        print(
            f"venv の python が見つかりません: {config.VENV_PYTHON}（setup-server.sh を実行してください）",
            file=sys.stderr,
        )
        return 1

    overall_rc = 0
    for repo_id, subfolder, required_files in _fetch_targets(not args.no_texture):
        local_subfolder_dir = config.MODELS_DIR / repo_id / subfolder
        if _weights_present(local_subfolder_dir, required_files):
            print(f"スキップ（既にあります）: {local_subfolder_dir}")
            continue

        local_repo_dir = config.MODELS_DIR / repo_id
        local_repo_dir.mkdir(parents=True, exist_ok=True)
        print(f"取得します: {repo_id}/{subfolder} -> {local_subfolder_dir}")

        allow_patterns = build_allow_patterns(subfolder, required_files)

        script = (
            "import huggingface_hub\n"
            "huggingface_hub.snapshot_download(\n"
            f"    repo_id={repo_id!r},\n"
            f"    allow_patterns={allow_patterns!r},\n"
            f"    local_dir={str(local_repo_dir)!r},\n"
            ")\n"
        )
        completed = subprocess.run([str(config.VENV_PYTHON), "-c", script])
        if completed.returncode != 0:
            print(f"失敗しました: {repo_id}/{subfolder}", file=sys.stderr)
            overall_rc = 1
    return overall_rc


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hy3d", description="Hunyuan3D-2 をこの A30 サーバーで動かすための CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="gradio_app.py を起動する")
    serve_parser.add_argument(
        "--no-texture", action="store_true", help="テクスチャ生成を無効化する（VRAM 節約。OOM の逃げ道）"
    )
    serve_parser.add_argument("--port", type=int, default=config.PORT)
    serve_parser.add_argument("--host", default=config.HOST)
    serve_parser.add_argument(
        "--skip-vram-check", action="store_true", help="VRAM の空き確認を省略して続行する"
    )
    low_vram_group = serve_parser.add_mutually_exclusive_group()
    low_vram_group.add_argument(
        "--low-vram",
        dest="low_vram",
        action="store_true",
        default=None,
        help=(
            "低 VRAM モード（--low_vram_mode）を強制的に有効にする。"
            "未指定なら HY3D_LOW_VRAM 環境変数に従う（既定は有効）"
        ),
    )
    low_vram_group.add_argument(
        "--no-low-vram",
        dest="low_vram",
        action="store_false",
        default=None,
        help="低 VRAM モードを強制的に無効にする。未指定なら HY3D_LOW_VRAM 環境変数に従う",
    )
    serve_parser.set_defaults(func=cmd_serve)

    doctor_parser = subparsers.add_parser("doctor", help="動作環境を点検する")
    doctor_parser.set_defaults(func=cmd_doctor)

    fetch_parser = subparsers.add_parser("fetch-models", help="重みを取得する（既にあればスキップ）")
    fetch_parser.add_argument(
        "--no-texture", action="store_true", help="テクスチャ用の重み（約 18GB）を取得しない"
    )
    fetch_parser.add_argument(
        "--accept-tencent-license",
        action="store_true",
        help="Tencent Hunyuan 3D 2.0 Community License に同意する（環境変数 HY3D_ACCEPT_LICENSE=1 でも同じ）",
    )
    fetch_parser.set_defaults(func=cmd_fetch_models)

    free_parser = subparsers.add_parser("free-vram", help="Ollama のモデルを解放するだけ")
    free_parser.set_defaults(func=cmd_free_vram)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
