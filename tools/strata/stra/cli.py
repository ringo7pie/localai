"""stra の CLI 本体。

`run-strata`（= venv の python）から `python -m stra.cli <サブコマンド>` として呼ばれる。
このモジュール自体は標準ライブラリのみに依存し、上流の serve/ も import しない。
素の python（.venv を持たない `uvx --with pytest pytest ...`）からも import できるようにする
（cfui/cli.py と同じ設計方針）。判定と組み立ては stra/checks.py の純粋関数に任せる。
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
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import checks, config


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


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _http_get(url: str, timeout: float) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _service_property(service_name: str, name: str) -> str | None:
    output = _run_text(["systemctl", "--user", "show", service_name, "-p", name, "--value"], timeout=10)
    return output.strip() if output is not None else None


def _service_is_active(service_name: str) -> bool:
    """モデルの systemd user ユニット（strata / strata-coder / strata-official / strata-official-iq3s / strata-swift）が
    動いているか。表示するだけで操作はしない。"""

    output = _run_text(["systemctl", "--user", "is-active", service_name], timeout=10)
    return bool(output) and output.strip() in ("active", "activating", "reloading")


def _user_manager_pid() -> int | None:
    """この利用者の systemd --user（user@UID.service の本体）の PID。"""

    output = _run_text(["systemctl", "show", f"user@{os.getuid()}.service", "-p", "MainPID", "--value"], timeout=10)
    try:
        pid = int((output or "").strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _memlock_of(pid: int | str) -> tuple[int | None, int | None] | None:
    text = _read_text(Path(f"/proc/{pid}/limits"))
    return checks.parse_memlock(text) if text is not None else None


# 手元で作る pack（tools/iq_pack.py の出力）のうち、engine と serve が読むもの。native_experts.txt は完成の印。
LOCAL_PACK_FILES = ("index.txt", "dense.bin", "tokenizer/vocab.json", "tokenizer/chat_template.jinja",
                    "native_experts.txt")


def _model_rows(spec: config.ModelSpec) -> list[checks.Row]:
    rows: list[checks.Row] = []
    fetch_command = "run-strata fetch-models" + ("" if spec.key == config.DEFAULT_MODEL else f" --model {spec.key}")
    for path_in_repo, size, _sha in spec.files:
        target = spec.model_dir / path_in_repo
        part = target.with_name(target.name + ".part")
        actual = target.stat().st_size if target.is_file() else None
        partial = part.stat().st_size if part.is_file() else None
        rows.append((f"モデル {path_in_repo}", *checks.classify_model_file(actual, size, partial, fetch_command)))
    if spec.pack_built_locally:
        present = {name: (spec.pack_dir / name).is_file() for name in LOCAL_PACK_FILES}
        ok, detail = checks.classify_pack(present, spec.key)
        header = checks.parse_native_experts_header(_read_text(spec.pack_dir / "native_experts.txt") or "")
        if ok and header is not None:
            detail += f"。エキスパート {header[0]} 個/層、合計 {header[1] / checks.GIB:.1f} GiB"
        rows.append((f"pack（手元で作る、{spec.pack_dir.name}/）", ok, detail))
    return rows


def _other_specs(spec: config.ModelSpec) -> list[config.ModelSpec]:
    return [other for other in config.MODELS.values() if other.key != spec.key]


def cmd_doctor(args: argparse.Namespace) -> int:
    spec = config.model_spec(args.model)
    rows: list[checks.Row] = []
    rows.append(("対象のモデル", True, f"{spec.key}: {spec.title}"))

    nvcc_output = _run_text([str(Path(config.CUDA_HOME) / "bin" / "nvcc"), "--version"], timeout=10)
    rows.append(("CUDA 13.2 の nvcc", *checks.classify_nvcc(nvcc_output, config.EXPECTED_NVCC_RELEASE)))
    rows.append(("venv の python が存在", config.VENV_PYTHON.is_file(), str(config.VENV_PYTHON)))
    rows.append(
        (
            f"Strata {config.STRATA_TAG} が指定コミット",
            *checks.classify_commit(_git_head(config.STRATA_DIR), config.STRATA_COMMIT),
        )
    )
    rows.append(
        (
            "llama.cpp（ggml と gguf-py）が指定コミット",
            *checks.classify_commit(_git_head(config.LLAMA_CPP_DIR), config.LLAMA_CPP_COMMIT),
        )
    )

    stamp_text = _read_text(config.BUILD_STAMP)
    try:
        stamp = json.loads(stamp_text) if stamp_text is not None else None
    except json.JSONDecodeError:
        stamp = None
    engine_size = config.ENGINE_EXE.stat().st_size if config.ENGINE_EXE.is_file() else None
    rows.append(
        (
            "engine のビルド物（engine/strata と BUILD.json）",
            *checks.classify_build_stamp(stamp, engine_size, config.STRATA_COMMIT, config.CUDA_HOME, config.CUDA_ARCH),
        )
    )
    rows.append(
        (
            f"エキスパート profile（data/{spec.expert_profile.name}）",
            spec.expert_profile.is_file(),
            str(spec.expert_profile) if spec.expert_profile.is_file() else "ありません（Strata の取得をやり直す）",
        )
    )
    rows.extend(_model_rows(spec))
    mtp_ok = _mtp_ready()
    rows.append(
        (
            "MTP の draft 層（models/mtp/rt、任意）",
            True,
            f"あります（{config.MTP_RT_DIR}）" if mtp_ok
            else "ありません（無くても動くが生成が遅い。scripts/build-mtp.sh で作る。表示のみ）",
        )
    )

    service_active = _service_is_active(spec.service_name)
    memlock_bytes = spec.recommended_memlock_bytes
    rows.append(("memlock の上限", *checks.classify_memlock(_memlock_of("self"), memlock_bytes, "この端末")))
    manager_pid = _user_manager_pid()
    if manager_pid is not None:
        rows.append(
            (
                "memlock の上限",
                *checks.classify_memlock(_memlock_of(manager_pid), memlock_bytes, "systemd --user（ユニットの上限）"),
            )
        )
    main_pid = _service_property(spec.service_name, "MainPID")
    if service_active and main_pid and main_pid != "0":
        rows.append(
            (
                "memlock の上限",
                *checks.classify_memlock(_memlock_of(main_pid), memlock_bytes, f"{spec.service_name}.service の本体"),
            )
        )

    meminfo = checks.parse_meminfo(_read_text(Path("/proc/meminfo")) or "")
    rows.append(("RAM の空き", *checks.classify_ram(meminfo, spec.min_available_ram_gib, service_active)))

    rows.append(
        (
            f"ポート（{spec.port}）",
            *checks.classify_port_status(spec.port, _port_in_use(spec.port), service_active, spec.service_name),
        )
    )

    # ここから下は表示のみ（常に OK）。
    smi = _run_text(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], timeout=10
    )
    rows.append(("VRAM", *checks.classify_vram(checks.parse_nvidia_smi_memory(smi), spec.min_free_vram_mib, service_active)))
    ollama = checks.parse_ollama_ps(_http_get(config.OLLAMA_URL + "/api/ps", timeout=5))
    rows.append(("Ollama に載っているモデル", *checks.classify_ollama(ollama)))
    if service_active:
        health_ok, health_detail = checks.classify_health(_http_get(f"http://127.0.0.1:{spec.port}/health", timeout=5))
        rows.append(("API（/health）", True, health_detail if health_ok else health_detail + "（表示のみ）"))
    unit_file = Path.home() / ".config" / "systemd" / "user" / f"{spec.service_name}.service"
    setup_hint = "setup-server.sh" if spec.key == config.DEFAULT_MODEL else f"setup-server.sh --model {spec.key}"
    rows.append(
        (
            f"systemd ユーザーユニット {spec.service_name}",
            True,
            ("稼働中" if service_active else "停止中")
            + ("" if unit_file.is_file() else f"（ユニットが未配置。{setup_hint} を実行）")
            + "（表示のみ。自動起動は設定しない方針）",
        )
    )
    for other in _other_specs(spec):
        rows.append(
            (f"同時に載せないユニット {other.service_name}", *checks.classify_other_service(
                other.service_name, _service_is_active(other.service_name)))
        )
    rows.append(("/v1/models が返すモデル名", True, spec.model_name))
    # env ファイルの値は systemd のユニットだけが読むので、ここには既定だけを出す（表示のみ）
    budget_default = spec.default_reasoning_budget_tokens
    rows.append(
        (
            "思考の予算の既定",
            True,
            (f"{budget_default} トークン" if budget_default > 0 else "なし")
            + f"（表示のみ。env ファイルの {config.REASONING_BUDGET_ENV_VAR} で変える。0 で無効）",
        )
    )

    overall, lines = checks.summarize(rows)
    for line in lines:
        print(line)
    return 0 if overall else 1


def _mtp_ready() -> bool:
    """MTP の draft 層が使える形（rt/ の experts.bin・dense.bin・dense.txt・draft_vocab.bin）であるか。"""

    return all((config.MTP_RT_DIR / name).is_file() for name in ("experts.bin", "dense.bin", "dense.txt", "draft_vocab.bin"))


def _server_config(
    max_context: int,
    extra_args: list[str],
    use_mtp: bool,
    spec: config.ModelSpec = config.RVN,
    reasoning_budget_tokens: int | None = None,
) -> dict[str, Any]:
    # None ならモデルの既定。0 は予算なしで、鍵ごと出さない（上流は 0 を無効として扱うが、JSON を短く保つ）。
    budget = spec.default_reasoning_budget_tokens if reasoning_budget_tokens is None else reasoning_budget_tokens
    # spec.server_options は Mapping（共有の値）なので、写しを作ってから足す
    server_options = dict(spec.server_options)
    if budget > 0:
        server_options["reasoning_budget_tokens"] = budget
    engine_args = checks.build_engine_args(
        pack_dir=str(spec.pack_dir),
        gguf_path=str(spec.native_gguf),
        ple_gguf=str(spec.ple_gguf),
        expert_profile=str(spec.expert_profile),
        max_context=max_context,
        mtp_dir=str(config.MTP_RT_DIR) if use_mtp else None,
        # モデル固有の速さの設定（spec）→ env の STRATA_EXTRA_ARGS と --extra の順。後ろが同じ引数を上書きできる
        extra_args=[*spec.engine_extra_args, *extra_args],
        resident_experts=spec.resident_experts,
        kv_resident=spec.kv_resident,
    )
    return checks.build_server_config(
        engine_exe=str(config.ENGINE_EXE),
        engine_args=engine_args,
        strata_dir=str(config.STRATA_DIR),
        tokenizer_dir=str(spec.tokenizer_dir),
        model_name=spec.model_name,
        engine_log=str(spec.engine_log),
        lib_dirs=[str(Path(config.CUDA_HOME) / "lib64")],
        host=config.HOST,
        port=spec.port,
        extra_options=server_options,
    )


def cmd_serve(args: argparse.Namespace) -> int:
    spec = config.model_spec(args.model)
    required = [config.VENV_PYTHON, config.ENGINE_EXE, spec.native_gguf, spec.ple_gguf, spec.pack_dir / "dense.bin",
                spec.tokenizer_dir / "vocab.json", spec.expert_profile]
    if spec.pack_built_locally:
        required.append(spec.pack_dir / "native_experts.txt")
    missing = [str(path) for path in dict.fromkeys(required) if not path.exists()]
    if missing:
        setup_hint = "setup-server.sh" if spec.key == config.DEFAULT_MODEL else f"setup-server.sh --model {spec.key}"
        print(f"足りないものがあります（先に {setup_hint} を実行してください）: " + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        max_context = checks.max_context_from_env(os.environ, config.MAX_CONTEXT_ENV_VAR, spec.default_max_context)
    except ValueError as exc:
        print(f"env ファイル（{spec.env_file}）の値が不正です: {exc}", file=sys.stderr)
        return 2
    if args.max_context is not None:
        max_context = args.max_context
    # 予算は最終的なコンテキスト長（--max-context の上書き後）と比べる
    try:
        reasoning_budget = checks.reasoning_budget_from_env(
            os.environ, config.REASONING_BUDGET_ENV_VAR, spec.default_reasoning_budget_tokens, max_context
        )
    except ValueError as exc:
        print(f"env ファイル（{spec.env_file}）の値が不正です: {exc}", file=sys.stderr)
        return 2
    extra_args = checks.extra_args_from_env(os.environ, config.EXTRA_ARGS_ENV_VAR) + list(args.extra)

    use_mtp = _mtp_ready() and not args.no_mtp
    if not use_mtp and not args.no_mtp:
        print(f"MTP の draft 層がありません（{config.MTP_RT_DIR}）。無しで起動します（生成が遅い。"
              f"scripts/build-mtp.sh で作れます）", file=sys.stderr, flush=True)
    server_config = _server_config(max_context, extra_args, use_mtp, spec, reasoning_budget)
    server_config["host"], server_config["port"] = args.host, args.port
    config.RUN_DIR.mkdir(parents=True, exist_ok=True)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    spec.server_config.write_text(json.dumps(server_config, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    command = checks.build_serve_command(
        python_bin=str(config.VENV_PYTHON), config_path=str(spec.server_config), host=args.host, port=args.port
    )
    print(f"モデル: {spec.key}（{spec.title}）", flush=True)
    print("サーバー設定: " + str(spec.server_config), flush=True)
    if reasoning_budget > 0:
        print(f"思考の予算: {reasoning_budget} トークン（{config.REASONING_BUDGET_ENV_VAR} で変更。0 で無効）", flush=True)
    else:
        print(f"思考の予算: なし（{config.REASONING_BUDGET_ENV_VAR} で設定）", flush=True)
    print("engine の引数: " + " ".join(shlex.quote(part) for part in server_config["args"]), flush=True)
    print("engine のログ: " + str(spec.engine_log), flush=True)
    print("起動します: " + " ".join(shlex.quote(part) for part in command), flush=True)
    # serve/server.py は `serve` パッケージとして読むので、Strata の直下へ移ってから exec する。
    os.chdir(config.STRATA_DIR)
    os.execv(command[0], command)
    return 0  # exec が戻ってくることは無い


def cmd_wait_ready(args: argparse.Namespace) -> int:
    """/health が loaded を返すまで待つ。strata.service / strata-coder.service / strata-official.service の ExecStartPost から呼ばれる。

    server.py は engine が READY になってから待受を始める（serve/server.py:4854-4963）ので、
    ポートが開いた時点で読み込みは終わっている。MAINPID（systemd が渡す）が消えたら、待たずに失敗する。
    """

    spec = config.model_spec(args.model)
    started = time.monotonic()
    main_pid = os.environ.get("MAINPID")
    url = f"http://127.0.0.1:{args.port}/health"
    while True:
        ok, detail = checks.classify_health(_http_get(url, timeout=5))
        elapsed = time.monotonic() - started
        if ok:
            print(f"準備ができました（{elapsed:.0f} 秒、{detail}）", flush=True)
            return 0
        if main_pid and not Path(f"/proc/{main_pid}").exists():
            print(f"サーバーの本体（PID {main_pid}）が終了しました。{spec.engine_log} を確認してください", file=sys.stderr)
            return 1
        if elapsed > args.timeout:
            print(f"{args.timeout:.0f} 秒待っても準備ができませんでした（{detail}）", file=sys.stderr)
            return 1
        time.sleep(args.interval)


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
        ["curl", "-L", "--fail", "--retry", "5", "--retry-delay", "10", "-sS", "-C", "-", "-o", str(part), url],
        check=True,
    )
    part.replace(target)


def cmd_fetch_models(args: argparse.Namespace) -> int:
    spec = config.model_spec(args.model)
    if shutil.which("curl") is None:
        print("curl がありません", file=sys.stderr)
        return 1
    failures = 0
    print(f"モデル: {spec.key}（{spec.repo} @ {spec.revision}）→ {spec.model_dir}", flush=True)
    for path_in_repo, size, sha256 in spec.files:
        target = spec.model_dir / path_in_repo
        if target.is_file() and target.stat().st_size == size and not args.verify:
            print(f"  {path_in_repo}: 既にあります（{size} バイト）")
            continue
        if not (target.is_file() and target.stat().st_size == size):
            url = checks.model_url(config.HF_BASE_URL, spec.repo, spec.revision, path_in_repo)
            print(f"  {path_in_repo}: 取得します（{size / 1024 ** 3:.2f} GiB, {url}）", flush=True)
            try:
                _download(url, target)
            except subprocess.CalledProcessError as exc:
                print(f"  {path_in_repo}: 取得に失敗しました（{exc}）。再実行すると続きから取ります", file=sys.stderr)
                failures += 1
                continue
        print(f"  {path_in_repo}: sha256 を計算しています", flush=True)
        actual_sha = _sha256_of(target)
        if actual_sha != sha256:
            # 固定したコミットから取っているので、違うのは壊れたときだけ。勝手に使わない。
            print(
                f"  {path_in_repo}: sha256 が違います（{actual_sha}、期待値 {sha256}）。{target} を消して取り直してください",
                file=sys.stderr,
            )
            failures += 1
            continue
        print(f"  {path_in_repo}: sha256 を確認しました")
    return 0 if failures == 0 else 1


class _Parser(argparse.ArgumentParser):
    """--port を省いたとき、--model で選んだモデルのポート（rvn 8082 / coder 8083 / official 8084 / official-iq3s 8085 /
    swift 8086）を入れる。"""

    def parse_known_args(self, args=None, namespace=None):  # type: ignore[override]
        parsed, rest = super().parse_known_args(args, namespace)
        if getattr(parsed, "port", 0) is None and getattr(parsed, "model", None) in config.MODELS:
            parsed.port = config.MODELS[parsed.model].port
        return parsed, rest


def _add_model_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model", choices=list(config.MODELS), default=config.DEFAULT_MODEL,
        help="対象のモデル（rvn: 汎用版 8082 / coder: コード向け版 8083 / official: 公式版（非 abliterated）8084 / "
             "official-iq3s: 公式版の IQ3_S 8085 / swift: Swift 1.5 IQ3_XXS 8086。既定 rvn）",
    )


def _gguf_tensor_names(path: Path) -> set[str]:
    """GGUF のテンソル名の一覧。上流の tools/gguf_reader.py（標準ライブラリのみ）で見出しだけを読む。"""

    tools_dir = str(config.STRATA_DIR / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import gguf_reader  # noqa: PLC0415（vendor/Strata が無い環境でも stra.cli を import できるよう、ここで読む）

    return {tensor.name for tensor in gguf_reader.GGUFFile(path).tensors}


def cmd_build_pack(args: argparse.Namespace) -> int:
    """手元で pack を作る（Coder・公式版。HF には GGUF しか無い）。上流 setup.py:4732-4737 と同じく tools/iq_pack.py を使う。

    iq_pack.py は shard 1 を受け取り、隣の shard 2 も読んで、index.txt・dense.bin・native_experts.txt（最後に書く
    完成の印）・tokenizer/（tools/strata_tokenizer.py を中から呼ぶ）を書く。エキスパートは GGUF からそのまま読む
    ので experts.bin は作らない（--experts-bin は low-RAM モード用。上流もそのときだけ作る）。
    """

    spec = config.model_spec(args.model)
    if not spec.pack_built_locally:
        print(f"{spec.key} の pack は HF から取ります（run-strata fetch-models）。作るものはありません")
        return 0
    present = {name: (spec.pack_dir / name).is_file() for name in LOCAL_PACK_FILES}
    if all(present.values()) and not args.force:
        print(f"pack: 既にあります（{spec.pack_dir}）")
        return 0
    missing = [str(path) for path in (config.VENV_PYTHON, spec.native_gguf, spec.ple_gguf) if not path.is_file()]
    if missing:
        print("足りないものがあります（先に run-strata fetch-models --model " + spec.key + "）: " + ", ".join(missing),
              file=sys.stderr)
        return 1
    # --ple-gguf に渡す shard に PLE の n-gram 表があるかを確かめる（上流 setup.py:4765 と同じ探し方）
    ple_name = "per_layer_token_embd.weight"
    if ple_name not in _gguf_tensor_names(spec.ple_gguf):
        holders = [str(path) for path in (spec.native_gguf, spec.ple_gguf) if ple_name in _gguf_tensor_names(path)]
        print(f"{spec.ple_gguf} に {ple_name} がありません（あるのは: {', '.join(holders) or 'どこにも無い'}）。"
              "stra/config.py の ple_gguf を直してください", file=sys.stderr)
        return 1
    print(f"PLE の表: {spec.ple_gguf.name} にあります（--ple-gguf）", flush=True)

    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOGS_DIR / f"build-pack-{spec.key}.log"
    command = [str(config.VENV_PYTHON), str(config.STRATA_DIR / "tools" / "iq_pack.py"),
               "--gguf", str(spec.native_gguf), "--out", str(spec.pack_dir)]
    environment = dict(os.environ, STRATA_GGUF_PY=str(config.LLAMA_CPP_DIR / "gguf-py"))
    print("pack を作ります: " + " ".join(shlex.quote(part) for part in command) + f"（ログ: {log_path}）", flush=True)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log_file:
        completed = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT, cwd=str(config.STRATA_DIR),
                                   env=environment, check=False)
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        print(f"iq_pack.py が失敗しました（終了コード {completed.returncode}、{elapsed:.0f} 秒）。{log_path} を確認してください",
              file=sys.stderr)
        return 1
    present = {name: (spec.pack_dir / name).is_file() for name in LOCAL_PACK_FILES}
    ok, detail = checks.classify_pack(present, spec.key)
    print(f"pack: {detail}（{elapsed:.0f} 秒）", flush=True)
    header = checks.parse_native_experts_header(_read_text(spec.pack_dir / "native_experts.txt") or "")
    if header is not None:
        print(f"エキスパート: {header[0]} 個/層、合計 {header[1]} バイト（{header[1] / checks.GIB:.2f} GiB）", flush=True)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="stra", description="Strata をこの A30 サーバーで動かすための CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Strata の OpenAI 互換サーバー（serve/server.py）を起動する")
    _add_model_argument(serve_parser)
    serve_parser.add_argument("--host", default=config.HOST)
    serve_parser.add_argument("--port", type=int, default=None,
                              help="待受ポート（既定はモデルごと。rvn 8082 / coder 8083 / official 8084 / official-iq3s 8085 / swift 8086）")
    serve_parser.add_argument(
        "--max-context", type=int, default=None, help=f"コンテキスト長（既定 {config.DEFAULT_MAX_CONTEXT}、env ファイルより優先）"
    )
    serve_parser.add_argument("--no-mtp", action="store_true", help="MTP の draft 層があっても使わない（比較用）")
    serve_parser.add_argument("extra", nargs=argparse.REMAINDER, help="engine に足す引数（-- の後ろに書く）")
    serve_parser.set_defaults(func=cmd_serve)

    doctor_parser = subparsers.add_parser("doctor", help="動作環境を点検する")
    _add_model_argument(doctor_parser)
    doctor_parser.set_defaults(func=cmd_doctor)

    fetch_parser = subparsers.add_parser("fetch-models", help="モデルを取得する（既にあればスキップ）")
    _add_model_argument(fetch_parser)
    fetch_parser.add_argument("--verify", action="store_true", help="既にあるファイルも sha256 を計算して確かめる")
    fetch_parser.set_defaults(func=cmd_fetch_models)

    pack_parser = subparsers.add_parser("build-pack", help="pack を手元で作る（Coder・公式版。HF に pack が無いモデル）")
    _add_model_argument(pack_parser)
    pack_parser.add_argument("--force", action="store_true", help="そろっていても作り直す")
    pack_parser.set_defaults(func=cmd_build_pack)

    wait_parser = subparsers.add_parser("wait-ready", help="API（/health）が準備できるまで待つ")
    _add_model_argument(wait_parser)
    wait_parser.add_argument("--port", type=int, default=None, help="問い合わせるポート（既定はモデルごと）")
    wait_parser.add_argument("--timeout", type=float, default=880.0, help="制限時間（秒）")
    wait_parser.add_argument("--interval", type=float, default=2.0, help="問い合わせの間隔（秒）")
    wait_parser.set_defaults(func=cmd_wait_ready)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "extra", None) and args.extra[:1] == ["--"]:
        args.extra = args.extra[1:]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
