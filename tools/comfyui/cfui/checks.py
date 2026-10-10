"""doctor の判定を行う純粋関数。

どれも引数だけから (ok, detail) を決め、ファイルシステム・ネットワーク・GPU に触れない。
実際に nvcc や venv の python を呼んで材料を集めるのは cfui/cli.py の役目で、ここは
その結果の読み方だけを持つ（GPU なしで試験できるように分けてある）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

Row = tuple[str, bool, str]


def parse_last_json_line(stdout: str) -> dict[str, Any] | None:
    """標準出力の最後の空でない行を JSON として読む。読めなければ None。

    venv の python で走らせる確認用スクリプトは、途中に上流のログ（print）が混ざっても
    最後の 1 行に結果の JSON を出す約束にしている。
    """

    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        parsed = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def classify_nvcc(output: str | None, expected_release: str) -> tuple[bool, str]:
    """`nvcc --version` の出力から、期待した release かを判定する。"""

    if output is None:
        return False, "nvcc を実行できませんでした"
    text = output.strip()
    if not text:
        return False, "nvcc の出力が空でした"
    detail = text.splitlines()[-1]
    return f"release {expected_release}" in text, detail


def classify_torch(
    probe: Mapping[str, Any],
    expected_version: str,
    expected_cuda: str,
    expected_gpu_substring: str,
) -> list[Row]:
    """torch の確認スクリプトの結果を、表示用の行に分ける。"""

    import_error = probe.get("import_error")
    if import_error:
        return [("torch の import", False, str(import_error))]

    rows: list[Row] = [("torch の import", True, "OK")]
    version = probe.get("version")
    rows.append(
        (f"torch の版が {expected_version}", version == expected_version, str(version or "(取得できず)"))
    )
    cuda_version = probe.get("cuda_version")
    rows.append(
        (
            f"torch.version.cuda が {expected_cuda} 系",
            isinstance(cuda_version, str) and cuda_version.startswith(expected_cuda),
            str(cuda_version or "(取得できず)"),
        )
    )
    cuda_available = bool(probe.get("cuda_available"))
    rows.append(("torch.cuda.is_available()", cuda_available, str(cuda_available)))
    device_name = str(probe.get("device_name") or "")
    capability = probe.get("capability")
    device_detail = device_name or "(取得できず)"
    if capability:
        device_detail += f"（compute capability {capability}）"
    rows.append(
        (
            f"GPU デバイス名に {expected_gpu_substring} を含む",
            cuda_available and expected_gpu_substring in device_name,
            device_detail,
        )
    )
    return rows


def classify_commit(head: str | None, expected_commit: str) -> tuple[bool, str]:
    """git の HEAD が固定コミットかを判定する。head が None なら repo が無い・読めない。"""

    if head is None:
        return False, "見つからないか git で読めません"
    if head == expected_commit:
        return True, f"HEAD={head}"
    return False, f"HEAD={head}（期待値 {expected_commit}）"


def classify_patch(state: str, patch_name: str) -> tuple[bool, str]:
    """`git apply --check` の結果（applied / applicable / conflict / missing）を読む。"""

    if state == "applied":
        return True, f"{patch_name} は当たっています"
    if state == "applicable":
        return False, f"{patch_name} はまだ当たっていません（scripts/build-wtivo.sh を実行してください）"
    if state == "missing":
        return False, f"{patch_name} の当て先がありません"
    return False, f"{patch_name} を当てられない状態です（上流の内容が変わった可能性）"


def classify_import(error: str | None, module_file: str | None = None) -> tuple[bool, str]:
    """拡張 1 本の import の結果。error が None なら成功。"""

    if error is None:
        return True, module_file or "OK"
    return False, error


def classify_wtivo_module(
    error: str | None, module_file: str | None, native_dir: str
) -> tuple[bool, str]:
    """wtivo_* の import の結果。Linux でビルドした .so が native_dir から読まれていること。"""

    if error is not None:
        return False, error
    if not module_file:
        return False, "読み込んだファイルの場所が分かりません"
    if not module_file.startswith(native_dir.rstrip("/") + "/"):
        return False, f"想定と違う場所から読まれています: {module_file}"
    if not module_file.endswith(".so"):
        return False, f"Linux の拡張（.so）ではありません: {module_file}"
    return True, module_file


def classify_apt_packages(installed: Mapping[str, bool]) -> tuple[bool, str]:
    missing = [name for name, present in installed.items() if not present]
    if not missing:
        return True, "すべて入っています（" + ", ".join(installed) + "）"
    return False, "未導入: " + ", ".join(missing) + "（sudo apt install " + " ".join(installed) + "）"


def classify_model_file(actual_size: int | None, expected_size: int) -> tuple[bool, str]:
    """モデル 1 ファイルの有無と大きさ。actual_size が None ならファイルが無い。"""

    if actual_size is None:
        return False, "ありません（run-comfyui fetch-models を実行してください）"
    if actual_size != expected_size:
        return False, f"大きさが違います: {actual_size} バイト（期待値 {expected_size}）"
    return True, f"{actual_size} バイト"


def model_url(base_url: str, repo: str, path_in_repo: str) -> str:
    """HF の resolve/main の URL を組み立てる。"""

    return f"{base_url.rstrip('/')}/{repo}/resolve/main/{path_in_repo}"


def classify_workflows(values: Mapping[str, str | None], expected_blender_path: str) -> tuple[bool, str]:
    """ワークフローごとの Blender のパスの値（読めなければ None）を判定する。"""

    problems = []
    for name, value in values.items():
        if value is None:
            problems.append(f"{name}: 無いか読めません")
        elif value != expected_blender_path:
            problems.append(f"{name}: Blender のパスが {value!r}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(values)} 本（Blender のパス = {expected_blender_path}）"


_BLENDER_VERSION_RE = re.compile(r"^Blender\s+(\d+)\.(\d+)(?:\.(\d+))?", re.MULTILINE)


def parse_blender_version(output: str) -> tuple[int, int, int] | None:
    """`blender --version` の出力（先頭行 "Blender 5.2.2 LTS" など）から版を取り出す。"""

    match = _BLENDER_VERSION_RE.search(output)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def classify_blender(output: str | None, required_major: int) -> tuple[bool, str]:
    if output is None:
        return False, "実行できませんでした"
    version = parse_blender_version(output)
    if version is None:
        first_line = output.strip().splitlines()[0] if output.strip() else "(出力なし)"
        return False, f"版を読めません: {first_line}"
    shown = ".".join(str(part) for part in version)
    if version[0] != required_major:
        return False, f"Blender {shown}（{required_major}.x を想定）"
    return True, f"Blender {shown}"


def classify_blender_launcher(resolved_path: str | None, snap_launcher: str) -> tuple[bool, str]:
    """Blender のパスが snap run 経由（シンボリックリンクの先が snap 本体）でないかを判定する。

    snap run は子を別の cgroup（snap.blender.*.scope）へ移すため、comfyui.service の
    MemoryHigh / MemoryMax が Blender に効かず、memory.peak にも入らない。
    """

    if resolved_path is None:
        return False, "パスを解決できません"
    if resolved_path == snap_launcher:
        return False, f"{snap_launcher}（snap run）経由です。comfyui の cgroup の外で動きます"
    return True, f"{resolved_path}（snap run を通らない）"


def classify_port_status(port: int, in_use: bool, service_active: bool) -> tuple[bool, str]:
    """ポートの状態を解釈する。使用中でも、それが comfyui.service なら異常ではない。"""

    if not in_use:
        return True, f"ポート {port} は空いています（起動できます）"
    if service_active:
        return True, f"ポート {port} は comfyui.service が使用中です（稼働しています）"
    return False, f"ポート {port} を別のプロセスが使用中です（手で起動した ComfyUI かもしれません）"


def classify_selftest(result: Mapping[str, Any] | None) -> tuple[bool, str]:
    """WTiVo の自己試験の結果を読む。配布元 bat と同じく watertight が真で面数 > 0 なら合格。"""

    if result is None:
        return False, "結果を読めませんでした"
    if result.get("skipped"):
        return False, "実行していません: " + str(result.get("reason") or "")
    error = result.get("error")
    if error:
        return False, str(error)
    watertight = result.get("watertight") is True
    faces_in = result.get("faces_in")
    faces_out = result.get("faces_out")
    seconds = result.get("seconds")
    detail = (
        f"穴あき球 {faces_in} 面 → {faces_out} 面, watertight={result.get('watertight')}"
        + (f", {seconds:.0f} 秒" if isinstance(seconds, (int, float)) else "")
    )
    ok = watertight and isinstance(faces_out, int) and faces_out > 0
    return ok, detail


def classify_vram_status(used_mib: int | None, threshold_mib: int, service_active: bool) -> tuple[bool, str]:
    """VRAM の状態（表示用）。ComfyUI は Qwen などと VRAM を分け合うので、NG にはしない。"""

    if used_mib is None:
        return True, "nvidia-smi の実行に失敗しました（表示のみ）"
    if service_active:
        return True, f"使用中 {used_mib} MiB（ComfyUI が稼働中）"
    if used_mib < threshold_mib:
        return True, f"使用中 {used_mib} MiB（空いています）"
    return True, f"使用中 {used_mib} MiB（Qwen など別のものが載っています。生成前に降ろすこと）"


def summarize(rows: Sequence[Row]) -> tuple[bool, list[str]]:
    """表示用の行に整え、全体の合否を返す。"""

    lines = []
    overall = True
    for label, ok, detail in rows:
        lines.append(f"{'OK' if ok else 'NG'}  {label}: {detail}")
        overall = overall and ok
    return overall, lines
