"""doctor の判定と、serve が使う引数・設定の組み立てを行う純粋関数。

どれも引数だけから結果を決め、ファイルシステム・ネットワーク・GPU に触れない。
実際に nvcc・/proc・nvidia-smi・Ollama を読んで材料を集めるのは stra/cli.py の役目で、ここは
その結果の読み方だけを持つ（GPU なしで試験できるように分けてある。cfui/checks.py と同じ方針）。
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping, Sequence
from typing import Any

Row = tuple[str, bool, str]

GIB = 1024**3


def classify_nvcc(output: str | None, expected_release: str) -> tuple[bool, str]:
    """`nvcc --version` の出力から、期待した release かを判定する。"""

    if output is None:
        return False, "nvcc を実行できませんでした"
    text = output.strip()
    if not text:
        return False, "nvcc の出力が空でした"
    detail = text.splitlines()[-1]
    return f"release {expected_release}" in text, detail


def classify_commit(head: str | None, expected_commit: str) -> tuple[bool, str]:
    """git の HEAD が固定コミットかを判定する。head が None なら repo が無い・読めない。"""

    if head is None:
        return False, "見つからないか git で読めません"
    if head == expected_commit:
        return True, f"HEAD={head}"
    return False, f"HEAD={head}（期待値 {expected_commit}）"


def classify_build_stamp(
    stamp: Mapping[str, Any] | None,
    engine_size: int | None,
    expected_commit: str,
    expected_cuda: str,
    expected_arch: str,
) -> tuple[bool, str]:
    """engine/BUILD.json（setup-server.sh が書く）と engine 本体の有無から、ビルド物が今の固定に合うかを見る。"""

    if engine_size is None:
        return False, "engine/strata がありません（setup-server.sh を実行してください）"
    if stamp is None:
        return False, "engine/BUILD.json が無いか読めません（setup-server.sh --rebuild）"
    problems = []
    if stamp.get("src") != expected_commit:
        problems.append(f"src={stamp.get('src')}（期待値 {expected_commit}）")
    if stamp.get("cuda") != expected_cuda:
        problems.append(f"cuda={stamp.get('cuda')}（期待値 {expected_cuda}）")
    archs = [str(arch) for arch in stamp.get("archs") or []]
    if archs != [expected_arch]:
        problems.append(f"archs={archs}（期待値 [{expected_arch}]）")
    if problems:
        return False, "; ".join(problems) + "（setup-server.sh --rebuild）"
    return True, (
        f"{engine_size / 1024**2:.0f} MiB, version {stamp.get('version')}, sm_{expected_arch}, {expected_cuda}"
    )


def classify_model_file(
    actual_size: int | None,
    expected_size: int,
    partial_size: int | None = None,
    fetch_command: str = "run-strata fetch-models",
) -> tuple[bool, str]:
    """モデル 1 ファイルの有無と大きさ。actual_size が None ならファイルが無い。"""

    if actual_size is None:
        if partial_size is not None:
            return False, (
                f"取得の途中です（.part {partial_size / GIB:.1f} / {expected_size / GIB:.1f} GiB。"
                f"{fetch_command} で続きから取れます）"
            )
        return False, f"ありません（{fetch_command} を実行してください）"
    if actual_size != expected_size:
        return False, f"大きさが違います: {actual_size} バイト（期待値 {expected_size}）"
    if expected_size >= GIB:
        return True, f"{actual_size} バイト（{actual_size / GIB:.1f} GiB）"
    return True, f"{actual_size} バイト"


def model_url(base_url: str, repo: str, revision: str, path_in_repo: str) -> str:
    """HF の resolve URL（コミット固定）を組み立てる。"""

    return f"{base_url.rstrip('/')}/{repo}/resolve/{revision}/{path_in_repo}"


def parse_memlock(limits_text: str) -> tuple[int | None, int | None] | None:
    """/proc/<pid>/limits の "Max locked memory" 行から (soft, hard) を返す。unlimited は None。

    行が無ければ None を返す（読めなかったのと区別するため、タプルではなく None そのもの）。
    """

    for line in limits_text.splitlines():
        if not line.startswith("Max locked memory"):
            continue
        fields = line[len("Max locked memory"):].split()
        if len(fields) < 2:
            return None

        def to_bytes(value: str) -> int | None:
            return None if value == "unlimited" else int(value)

        try:
            return to_bytes(fields[0]), to_bytes(fields[1])
        except ValueError:
            return None
    return None


def format_bytes_limit(value: int | None) -> str:
    return "unlimited" if value is None else f"{value / GIB:.1f} GiB"


def classify_memlock(limits: tuple[int | None, int | None] | None, recommended_bytes: int, where: str) -> tuple[bool, str]:
    """memlock の上限を表示する（表示のみ。常に OK）。

    engine はエキスパートの RAM 複製を cudaHostRegister で固定し、固定できなかった残りを mlock で RAM に
    留める（src/core/pinned.cu:354-455）。mlock が上限で失敗しても engine は止まらず、ログに
    "mlock failed (raise ulimit -l)" と書いて続ける（src/platform/memory.cpp:119-127）。
    A30 / ドライバ 595 での実測は README の「memlock の扱い」。
    """

    if limits is None:
        return True, f"{where}: 読めませんでした（表示のみ）"
    soft, hard = limits
    shown = f"{where}: soft {format_bytes_limit(soft)} / hard {format_bytes_limit(hard)}"
    if soft is None or soft >= recommended_bytes:
        return True, shown
    return True, shown + f"（{recommended_bytes / GIB:.0f} GiB 未満。mlock の予備経路は効かない。README 参照）"


def parse_meminfo(text: str) -> dict[str, int]:
    """/proc/meminfo をバイト数の辞書にする（kB 表記はバイトに直す）。"""

    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        fields = rest.split()
        if not fields:
            continue
        try:
            number = int(fields[0])
        except ValueError:
            continue
        values[name.strip()] = number * 1024 if len(fields) > 1 and fields[1] == "kB" else number
    return values


def classify_ram(meminfo: Mapping[str, int], min_available_gib: float, service_active: bool) -> tuple[bool, str]:
    """RAM の空き（MemAvailable）。Strata が止まっているときに、起動に要る分が空いているかを見る。"""

    available = meminfo.get("MemAvailable")
    total = meminfo.get("MemTotal")
    if available is None or total is None:
        return False, "/proc/meminfo を読めませんでした"
    swap_used = meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)
    detail = (
        f"空き {available / GIB:.1f} / {total / GIB:.1f} GiB, swap 使用 {swap_used / GIB:.1f} GiB"
    )
    if service_active:
        return True, detail + "（Strata が稼働中）"
    if available >= min_available_gib * GIB:
        return True, detail
    return False, detail + f"（起動には {min_available_gib:.0f} GiB 以上の空きが要ります。ComfyUI などを止めること）"


def parse_nvidia_smi_memory(output: str | None) -> tuple[int, int] | None:
    """`nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits` の 1 行目を読む。"""

    if not output:
        return None
    first = output.strip().splitlines()[0] if output.strip() else ""
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def classify_vram(memory: tuple[int, int] | None, min_free_mib: int, service_active: bool) -> tuple[bool, str]:
    """VRAM の状態（表示のみ。常に OK）。エキスパートのキャッシュは起動時の空き VRAM で決まる。"""

    if memory is None:
        return True, "nvidia-smi の実行に失敗しました（表示のみ）"
    used, total = memory
    free = total - used
    detail = f"使用中 {used} / {total} MiB（空き {free} MiB）"
    if service_active:
        return True, detail + "（Strata が稼働中）"
    if free >= min_free_mib:
        return True, detail
    return True, detail + f"（空きが {min_free_mib} MiB 未満。起動前に Ollama などを降ろすこと）"


def parse_ollama_ps(body: str | None) -> list[tuple[str, int]] | None:
    """Ollama の /api/ps の応答から (モデル名, VRAM のバイト数) の一覧を返す。読めなければ None。"""

    if body is None:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None
    result = []
    for entry in models:
        if isinstance(entry, dict):
            result.append((str(entry.get("name") or entry.get("model") or "?"), int(entry.get("size_vram") or 0)))
    return result


def classify_ollama(models: list[tuple[str, int]] | None) -> tuple[bool, str]:
    """Ollama に載っているモデル（表示のみ。常に OK）。"""

    if models is None:
        return True, "Ollama に接続できませんでした（止まっているなら VRAM は使っていません）"
    if not models:
        return True, "載っているモデルはありません"
    shown = ", ".join(f"{name}（VRAM {size / GIB:.1f} GiB）" for name, size in models)
    return True, shown + "。Strata の起動前に降ろすこと（vram-policy.sh release）"


def classify_port_status(port: int, in_use: bool, service_active: bool, service_name: str = "strata") -> tuple[bool, str]:
    """ポートの状態を解釈する。使用中でも、それがこのモデルのユニット（service_name）なら異常ではない。"""

    if not in_use:
        if service_active:
            return True, f"ポート {port} はまだ空いています（{service_name}.service は起動中。モデルの読み込みを待っています）"
        return True, f"ポート {port} は空いています（起動できます）"
    if service_active:
        return True, f"ポート {port} は {service_name}.service が使用中です（稼働しています）"
    return False, f"ポート {port} を別のプロセスが使用中です（手で起動した Strata かもしれません）"


def classify_other_service(other_name: str, other_active: bool) -> tuple[bool, str]:
    """同時に載せられないほかのモデルのユニット（表示のみ。常に OK）。

    5 つのユニットは Conflicts= で互いを止めるので、こちらを start すると systemd がほかを止める。
    手で起動した serve はこの対象にならない。
    """

    if other_active:
        return True, (
            f"{other_name}.service が稼働中です（RAM と VRAM を使っているので、上の RAM の判定はそのぶん少なく出る。"
            f"このモデルを systemctl --user start すると、Conflicts= により {other_name} は止まる）"
        )
    return True, f"{other_name}.service は停止中です"


def classify_pack(present: Mapping[str, bool], model_key: str) -> tuple[bool, str]:
    """手元で作る pack（tools/iq_pack.py の出力）がそろっているか。present は pack 内のパス → 有無。

    native_experts.txt は iq_pack.py が最後に書く完成の印なので、それが無ければ途中で止まった pack とみなす。
    model_key は作り直しの案内に出す --model の名前（coder / official）。
    """

    missing = [name for name, ok in present.items() if not ok]
    if not missing:
        return True, "そろっています（" + ", ".join(present) + "）"
    if present.get("native_experts.txt") is False and len(missing) < len(present):
        return False, "作りかけです（足りないもの: " + ", ".join(missing) + f"。setup-server.sh --model {model_key} で作り直す）"
    return False, "ありません（足りないもの: " + ", ".join(missing) + f"。setup-server.sh --model {model_key} で作る）"


def parse_native_experts_header(text: str) -> tuple[int, int] | None:
    """pack/native_experts.txt の見出し（"... (n_expert 256, total 31234; ...)"）から (n_expert, total) を返す。"""

    first = text.splitlines()[0] if text else ""
    match = re.search(r"n_expert (\d+), total (\d+)", first)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def max_context_from_env(env: Mapping[str, str], variable: str, default: int) -> int:
    """env ファイルの STRATA_MAX_CONTEXT を読む。4096 以上 262144 以下の整数だけを受け付ける。"""

    raw = env.get(variable, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{variable}={raw!r} は整数ではありません") from exc
    if value < 4096 or value > 262144:
        raise ValueError(f"{variable}={value} は 4096 以上 262144 以下にしてください（モデルの学習長は 262144）")
    return value


def reasoning_budget_from_env(env: Mapping[str, str], variable: str, default: int, max_context: int) -> int:
    """env ファイルの STRATA_REASONING_BUDGET_TOKENS（思考の予算）を読む。0 以上 max_context 未満の整数だけを受け付ける。

    0 は予算なし。予算がコンテキスト長と同じ（以上）だと、思考で文脈を使い切って答えを書く余地が無いので受け付けない。
    """

    raw = env.get(variable, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{variable}={raw!r} は整数ではありません") from exc
    if value < 0:
        raise ValueError(f"{variable}={value} は 0 以上にしてください（0 は予算なし）")
    if value >= max_context:
        raise ValueError(
            f"{variable}={value} はコンテキスト長（{max_context}）より小さくしてください（答えを書く余地が要る）"
        )
    return value


def extra_args_from_env(env: Mapping[str, str], variable: str) -> list[str]:
    """STRATA_EXTRA_ARGS（env ファイルで設定する）をシェルと同じ規則で分ける。"""

    return shlex.split(env.get(variable, ""))


def build_engine_args(
    *,
    pack_dir: str,
    gguf_path: str,
    expert_profile: str,
    max_context: int,
    mtp_dir: str | None,
    extra_args: Sequence[str] = (),
    ple_gguf: str | None = None,
    resident_experts: bool = True,
    kv_resident: int | None = None,
) -> list[str]:
    """engine（strata --serve）の引数を組み立てる。

    元はモデルカードの起動例（--pack / --native / --ple-gguf / --expert-profile / --expert-cache auto /
    --prefill auto / --spec 4 / --kv int8）。A30（24 GiB）と RAM 62.5 GiB に合わせて変えたところ:
    - --resident-experts（low-RAM モードの resident 版）を足す。エキスパート 53.3 GiB を全部 RAM に置く
      通常のモードは「エキスパート + 約 10 GB」= 63 GB を要し、この機体では足りない。resident 版は GPU が
      持たない分だけを RAM に写す（DETAILS.md の Low-RAM mode, resident）。
    - --kv-resident（KV ストリーミング: KV を RAM に置き、VRAM には直近の N セル）は kv_resident を与えたときだけ付ける。
      2026-10-18 から汎用版（rvn）は 65536（262144 で枠が増えて 4% 速い）。ほかの 4 つは付けない（config の各注記）。
    - --max-context はモデルの上限 262144（65536 → 131072 → 262144 と実測で広げた。config.DEFAULT_MAX_CONTEXT の注記。
      env ファイルで変える）。
    - --mtp（MTP の draft 層）は、scripts/build-mtp.sh で作ってあれば付ける（mtp_dir）。カードは任意としているが、
      実測で thinking ありの 4K 入力が 42→61 tok/s になった。--spec-min-p 0.5 は上流 setup.py が --mtp と
      一緒に書く値（setup.py:4775-4777）。無ければ --spec 4 は suffix / prompt-lookup の draft だけで効く。

    既定（ple_gguf=None・resident_experts=True・kv_resident=None）は汎用版（rvn）の引数そのもの。
    分割された GGUF（Coder・公式版）は --native に shard 1、--ple-gguf に PLE の表を持つ shard を渡す（setup.py:4766-4769）。
    Coder はエキスパートが RAM に全部載るので resident_experts=False（エキスパートを全部 RAM に写す通常のモード）。
    kv_resident は上流 setup.py が RAM に余裕のあるとき 65536 以上で足す --kv-resident 32768（setup.py:4824-4826）。
    """

    mtp_args = ["--spec-min-p", "0.5", "--mtp", mtp_dir] if mtp_dir else []
    return [
        "--pack", pack_dir,
        "--native", gguf_path,
        "--ple-gguf", ple_gguf or gguf_path,
        "--expert-profile", expert_profile,
        "--expert-cache", "auto",
        "--prefill", "auto",
        "--spec", "4",
        *mtp_args,
        "--max-context", str(max_context),
        "--kv", "int8",
        *(["--kv-resident", str(kv_resident)] if kv_resident else []),
        *(["--resident-experts"] if resident_experts else []),
        *extra_args,
    ]


def build_server_config(
    *,
    engine_exe: str,
    engine_args: Sequence[str],
    strata_dir: str,
    tokenizer_dir: str,
    model_name: str,
    engine_log: str,
    lib_dirs: Sequence[str],
    host: str,
    port: int,
    extra_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """serve/server.py の --config に渡す JSON（docs/ORCA.md:53-76、setup.py:4869-4871 と同じ鍵）。

    extra_options はモデルごとに足す上流サーバーの鍵（sampling・reasoning_loop_recovery など）。
    上の基本の鍵を上書きするものは受け付けない（取り違えを早く見つけるため）。
    """

    server_config: dict[str, Any] = {
        "exe": engine_exe,
        "args": list(engine_args),
        "cwd": strata_dir,
        "tokenizer": tokenizer_dir,
        "model_name": model_name,
        "log": engine_log,
        "lib_dirs": list(lib_dirs),
        "host": host,
        "port": port,
    }
    for key, value in (extra_options or {}).items():
        if key in server_config:
            raise ValueError(f"extra_options の {key} は基本の鍵と重なります")
        server_config[key] = json.loads(json.dumps(value))
    return server_config


def build_serve_command(*, python_bin: str, config_path: str, host: str, port: int) -> list[str]:
    """上流サーバーの起動コマンド（docs/ORCA.md:75-77 の形）。"""

    return [python_bin, "-m", "serve.server", "--engine", "strata", "--config", config_path, "--host", host,
            "--port", str(port)]


def classify_health(body: str | None) -> tuple[bool, str]:
    """/health の応答を読む。loaded が真なら準備ができている。"""

    if body is None:
        return False, "応答がありません"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False, "JSON ではありません"
    if not isinstance(data, dict):
        return False, "想定と違う応答です"
    if data.get("loaded"):
        return True, f"model={data.get('model')}, max_context={data.get('max_context')}"
    return False, "まだ読み込み中です"


def summarize(rows: Sequence[Row]) -> tuple[bool, list[str]]:
    """表示用の行に整え、全体の合否を返す。"""

    lines = []
    overall = True
    for label, ok, detail in rows:
        lines.append(f"{'OK' if ok else 'NG'}  {label}: {detail}")
        overall = overall and ok
    return overall, lines
