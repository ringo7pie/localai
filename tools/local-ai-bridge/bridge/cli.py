"""local-ai-task コマンド。MCP と同じ bridge.core を呼ぶ。"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from . import core
from .errors import BridgeError, DuplicateRequestError

EXAMPLES = """\
使用例:
  # 0. 作業場所を登録する（[registration] allowed_roots 配下の Git リポジトリだけ登録できる）
  local-ai-task workspace add /home/mt/Proj/localai/tools/example --id example \\
      --verify pytest --cmd "python3 -m pytest -q" --default-verify pytest

  # 1. 前提の点検
  local-ai-task doctor

  # 2. 依頼を出す（受付だけ。すぐ task_id が返る）
  local-ai-task submit \\
      --workspace selftest \\
      --request-id fix-subtract-001 \\
      --goal "src/calc.py の subtract が足し算になっているのを直す" \\
      --acceptance "tests/test_calc.py が全て通る" \\
      --verify unittest --mode deep

  # 2b. 委譲から適用・再検証まで 1 回で済ませる（Bash ツールから呼ぶときは
  #     --max-wait 540。Bash の上限 600 秒の内側に収める）
  local-ai-task run \\
      --workspace selftest \\
      --request-id fix-subtract-002 \\
      --goal "src/calc.py の subtract が足し算になっているのを直す" \\
      --acceptance "tests/test_calc.py が全て通る" \\
      --verify unittest --max-wait 540
  #     終了コード: 0 合格して適用済み / 1 不合格 / 2 設定エラー / 3 重複 / 4 時間切れ

  # 3. 進捗
  local-ai-task status task_xxxxxxxx

  # 4. 完了まで待って結果を受け取る（上限を過ぎたら状態だけ返る）
  local-ai-task wait task_xxxxxxxx --max-wait 600

  # 5. 結果（短い。差分は --diff で本文にも入る）
  local-ai-task result task_xxxxxxxx
  local-ai-task result task_xxxxxxxx --diff

  # 6. 大きなログを範囲指定で取る
  local-ai-task artifact task_xxxxxxxx --name verify-1.log --start 1 --lines 50

  # 7. 停止 / 再開
  local-ai-task cancel task_xxxxxxxx
  local-ai-task resume task_xxxxxxxx
"""


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _build_verify_profiles(names: list[str], raw_cmds: list[str]) -> dict[str, list[str]]:
    """--verify と --cmd の対をシェル風文字列から argv 配列の辞書へ組み立てる。

    --cmd はシェルを介さず argv として実行するための配列を作るためだけに
    shlex.split する（サブプロセスをシェル経由で起動するわけではない）。
    """
    if len(names) != len(raw_cmds):
        raise BridgeError("--verify と --cmd は同じ回数だけ指定してください。")
    profiles: dict[str, list[str]] = {}
    for name, raw_cmd in zip(names, raw_cmds):
        if name in profiles:
            raise BridgeError(f"--verify {name} が重複しています。")
        parts = shlex.split(raw_cmd)
        if not parts:
            raise BridgeError(f"--cmd が空です（--verify {name}）。")
        profiles[name] = parts
    return profiles


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=None, help="bridge.toml のパス")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-ai-task",
        description="クラウドから作業 PC の OpenCode 経由でローカル Qwen へ実装を委譲する",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor_parser = sub.add_parser("doctor", help="接続・設定・作業場所の点検")
    _add_config_arg(doctor_parser)
    doctor_parser.add_argument("--json", action="store_true", help="JSON で出す")

    submit_parser = sub.add_parser("submit", help="依頼を受け付けて task_id を返す")
    _add_config_arg(submit_parser)
    submit_parser.add_argument("--workspace", required=True, help="登録済みの workspace_id")
    submit_parser.add_argument("--request-id", required=True, help="重複受付を防ぐ識別子")
    submit_parser.add_argument("--client-id", default="cli", help="依頼元の識別子")
    submit_parser.add_argument("--goal", required=True, help="目的")
    submit_parser.add_argument("--scope", action="append", default=[], help="変更可能範囲（複数可）")
    submit_parser.add_argument("--forbid", action="append", default=[], help="変更禁止事項（複数可）")
    submit_parser.add_argument("--acceptance", action="append", default=[], help="合格条件（複数可）")
    submit_parser.add_argument("--base-commit", default=None, help="基準コミット（既定は HEAD）")
    submit_parser.add_argument("--verify", default=None, help="検証プロファイル名")
    submit_parser.add_argument("--mode", default="deep", choices=core.MODES, help="実行モード")
    submit_parser.add_argument(
        "--on-dirty",
        default="wait",
        choices=core.ON_DIRTY,
        help="元ツリーに未コミット変更があるときの扱い",
    )
    submit_parser.add_argument("--max-seconds", type=int, default=None, help="総実行時間の上限")

    run_parser = sub.add_parser(
        "run", help="委譲・完了待ち・判定・適用・再検証を 1 回で行う"
    )
    _add_config_arg(run_parser)
    run_parser.add_argument("--workspace", required=True, help="登録済みの workspace_id")
    run_parser.add_argument("--request-id", required=True, help="重複受付を防ぐ識別子")
    run_parser.add_argument("--client-id", default="cli", help="依頼元の識別子")
    run_parser.add_argument("--goal", required=True, help="目的")
    run_parser.add_argument("--scope", action="append", default=[], help="変更可能範囲（複数可）")
    run_parser.add_argument("--forbid", action="append", default=[], help="変更禁止事項（複数可）")
    run_parser.add_argument("--acceptance", action="append", default=[], help="合格条件（複数可）")
    run_parser.add_argument("--base-commit", default=None, help="基準コミット（既定は HEAD）")
    run_parser.add_argument("--verify", default=None, help="検証プロファイル名")
    run_parser.add_argument("--mode", default="deep", choices=core.MODES, help="実行モード")
    run_parser.add_argument(
        "--on-dirty",
        default="wait",
        choices=core.ON_DIRTY,
        help="元ツリーに未コミット変更があるときの扱い",
    )
    run_parser.add_argument(
        "--max-wait", type=int, default=None, help="待つ秒数の上限（既定は設定値）"
    )
    run_parser.add_argument(
        "--no-apply", action="store_true", help="判定だけ行い、作業ツリーへ適用しない"
    )

    status_parser = sub.add_parser("status", help="状態を見る")
    _add_config_arg(status_parser)
    status_parser.add_argument("task_id")

    wait_parser = sub.add_parser("wait", help="完了まで待って結果を返す")
    _add_config_arg(wait_parser)
    wait_parser.add_argument("task_id")
    wait_parser.add_argument(
        "--max-wait", type=int, default=None, help="待つ秒数の上限（既定は設定値）"
    )
    wait_parser.add_argument("--no-diff", action="store_true", help="差分本文を入れない")

    result_parser = sub.add_parser("result", help="結果を短く返す")
    _add_config_arg(result_parser)
    result_parser.add_argument("task_id")
    result_parser.add_argument("--diff", action="store_true", help="差分本文も入れる")

    artifact_parser = sub.add_parser("artifact", help="登録済み成果物を行範囲で取り出す")
    _add_config_arg(artifact_parser)
    artifact_parser.add_argument("task_id")
    artifact_parser.add_argument("--name", required=True, help="diff / result / verify-N.log など")
    artifact_parser.add_argument("--start", type=int, default=1)
    artifact_parser.add_argument("--lines", type=int, default=200)

    cancel_parser = sub.add_parser("cancel", help="そのタスクだけを止める")
    _add_config_arg(cancel_parser)
    cancel_parser.add_argument("task_id")

    resume_parser = sub.add_parser("resume", help="task_id を指定して再開する")
    _add_config_arg(resume_parser)
    resume_parser.add_argument("task_id")

    list_parser = sub.add_parser("list", help="最近のタスク")
    _add_config_arg(list_parser)
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--state", default=None)

    workspace_parser = sub.add_parser(
        "workspace", help="作業場所の登録・一覧・照会・削除"
    )
    workspace_sub = workspace_parser.add_subparsers(
        dest="workspace_command", required=True
    )

    workspace_add_parser = workspace_sub.add_parser(
        "add",
        help="許可ルート（[registration] allowed_roots）配下の Git リポジトリを登録する",
    )
    _add_config_arg(workspace_add_parser)
    workspace_add_parser.add_argument("path", help="登録するリポジトリのパス")
    workspace_add_parser.add_argument(
        "--id",
        dest="workspace_id",
        default=None,
        help="workspace_id（省略時はディレクトリ名から生成する）",
    )
    workspace_add_parser.add_argument(
        "--verify",
        action="append",
        default=[],
        metavar="NAME",
        help="検証プロファイル名。--cmd と同じ順番・同じ回数だけ指定する（複数回可）",
    )
    workspace_add_parser.add_argument(
        "--cmd",
        action="append",
        default=[],
        metavar="\"CMD ARGS...\"",
        help=(
            "実行コマンドを 1 個のシェル風文字列として渡す"
            "（例: \"python3 -m pytest -q\"）。shlex.split で argv 配列に分解して"
            "登録するだけで、シェルは介さず実行される。"
        ),
    )
    workspace_add_parser.add_argument(
        "--default-verify",
        dest="default_verify",
        default=None,
        help="既定の検証プロファイル名（--verify で指定した名前のいずれか）",
    )
    workspace_add_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="登録せず、判定結果と検出候補だけ表示する",
    )

    workspace_list_parser = workspace_sub.add_parser("list", help="登録済みの作業場所一覧")
    _add_config_arg(workspace_list_parser)

    workspace_which_parser = workspace_sub.add_parser(
        "which", help="パスがどの workspace 配下か調べる"
    )
    _add_config_arg(workspace_which_parser)
    workspace_which_parser.add_argument("path")

    workspace_remove_parser = workspace_sub.add_parser(
        "remove", help="workspace の登録を削除する"
    )
    _add_config_arg(workspace_remove_parser)
    workspace_remove_parser.add_argument("workspace_id")

    return parser


def _render_doctor(report: dict) -> int:
    print(f"設定: {report['config_path']}")
    worst = 0
    for item in report["checks"]:
        mark = {True: "OK  ", False: "NG  ", None: "未取得"}[item["ok"]]
        print(f"  [{mark}] {item['name']}: {item['detail']}")
        if item["ok"] is False:
            worst = 1
    for warning in report["warnings"]:
        print(f"  [警告] {warning}")
    total = report["summary"]
    print(f"合計: OK {total['ok']} / NG {total['ng']} / 未取得 {total['unknown']}")
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cfg = core.load_config(args.config)
    except BridgeError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "doctor":
            report = core.doctor(cfg)
            if args.json:
                _print(report)
                return 0 if report["summary"]["ng"] == 0 else 1
            return _render_doctor(report)

        if args.command == "workspace":
            if args.workspace_command == "add":
                verify_profiles = _build_verify_profiles(args.verify, args.cmd)
                if (
                    args.default_verify is not None
                    and args.default_verify not in verify_profiles
                ):
                    raise BridgeError(
                        f"--default-verify {args.default_verify!r} は"
                        " --verify で指定されていません。"
                    )
                _print(
                    core.workspace_add(
                        cfg,
                        path=args.path,
                        workspace_id=args.workspace_id,
                        verify_profiles=verify_profiles,
                        default_verify=args.default_verify,
                        dry_run=args.dry_run,
                    )
                )
                return 0
            if args.workspace_command == "list":
                _print(core.workspace_list(cfg))
                return 0
            if args.workspace_command == "which":
                found = core.workspace_which(cfg, args.path)
                if found is None:
                    return 1
                print(found)
                return 0
            if args.workspace_command == "remove":
                _print(core.workspace_remove(cfg, args.workspace_id))
                return 0

        if args.command == "submit":
            overrides = {"max_job_seconds": args.max_seconds} if args.max_seconds else None
            _print(
                core.submit(
                    cfg,
                    request_id=args.request_id,
                    client_id=args.client_id,
                    workspace_id=args.workspace,
                    goal=args.goal,
                    allowed_scope=args.scope,
                    forbidden=args.forbid,
                    acceptance=args.acceptance,
                    base_commit=args.base_commit,
                    verify_profile=args.verify,
                    mode=args.mode,
                    on_dirty=args.on_dirty,
                    budget_overrides=overrides,
                )
            )
            return 0

        if args.command == "run":
            report = core.run_task(
                cfg,
                request_id=args.request_id,
                client_id=args.client_id,
                workspace_id=args.workspace,
                goal=args.goal,
                allowed_scope=args.scope,
                forbidden=args.forbid,
                acceptance=args.acceptance,
                base_commit=args.base_commit,
                verify_profile=args.verify,
                mode=args.mode,
                on_dirty=args.on_dirty,
                max_wait_sec=args.max_wait,
                apply=not args.no_apply,
            )
            _print(report)
            if report.get("judged_ok"):
                return 0
            if report.get("timed_out"):
                return 4
            return 1

        if args.command == "status":
            _print(core.status(cfg, args.task_id))
            return 0
        if args.command == "wait":
            _print(
                core.wait_for_task(
                    cfg,
                    args.task_id,
                    max_wait_sec=args.max_wait,
                    include_diff=not args.no_diff,
                )
            )
            return 0
        if args.command == "result":
            _print(core.result(cfg, args.task_id, include_diff=args.diff))
            return 0
        if args.command == "artifact":
            _print(core.get_artifact(cfg, args.task_id, args.name, args.start, args.lines))
            return 0
        if args.command == "cancel":
            _print(core.cancel(cfg, args.task_id))
            return 0
        if args.command == "resume":
            _print(core.resume(cfg, args.task_id))
            return 0
        if args.command == "list":
            _print(core.list_tasks(cfg, limit=args.limit, state=args.state))
            return 0
    except DuplicateRequestError as exc:
        print(f"重複: {exc}", file=sys.stderr)
        print(json.dumps({"task_id": exc.task_id}, ensure_ascii=False), file=sys.stderr)
        return 3
    except BridgeError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
