"""local-ai-task コマンド。MCP と同じ bridge.core を呼ぶ。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core
from .errors import BridgeError, DuplicateRequestError

EXAMPLES = """\
使用例:
  # 1. 前提の点検
  local-ai-task doctor

  # 2. 依頼を出す（受付だけ。すぐ task_id が返る）
  local-ai-task submit \\
      --workspace selftest \\
      --request-id fix-subtract-001 \\
      --goal "src/calc.py の subtract が足し算になっているのを直す" \\
      --acceptance "tests/test_calc.py が全て通る" \\
      --verify unittest --mode deep

  # 3. 進捗
  local-ai-task status task_xxxxxxxx

  # 4. 結果（短い。差分は --diff で本文にも入る）
  local-ai-task result task_xxxxxxxx
  local-ai-task result task_xxxxxxxx --diff

  # 5. 大きなログを範囲指定で取る
  local-ai-task artifact task_xxxxxxxx --name verify-1.log --start 1 --lines 50

  # 6. 停止 / 再開
  local-ai-task cancel task_xxxxxxxx
  local-ai-task resume task_xxxxxxxx
"""


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


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

    status_parser = sub.add_parser("status", help="状態を見る")
    _add_config_arg(status_parser)
    status_parser.add_argument("task_id")

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

        if args.command == "status":
            _print(core.status(cfg, args.task_id))
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
