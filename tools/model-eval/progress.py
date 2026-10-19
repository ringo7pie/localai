#!/usr/bin/env python3
"""評価の進捗を表示する（いま何を試験中か・工程の経過と残り・全行程の経過と残り）。状態は results/<日付>/progress.json。

  progress.py show [--date 2026-10-18] [--watch 30] [--json]       # 見る（読み取りだけ）
  progress.py init --t0 2026-10-18T15:40:41+09:00 --total-hours 18 --claude-total 54
  progress.py phase start P1 / progress.py phase end P1             # 工程の境（メインが書く）
  progress.py phase add P1b --label "..." --planned-min 160 --depends P1 --before P3 --lane local   # 工程を足す
  progress.py deadline lift --note "ユーザーの指示"                  # 全行程の期限を外す（deadline restore で戻す）
  progress.py lane local --set target=gemma4:e4b model_index=1 ...  # 試験の列（run_local.sh が書く）
  progress.py claude start --model opus --item h3 --run 2           # Claude の 1 回の開始と終了（メインが書く）
  progress.py claude end --model opus --item h3 --run 2

他の PC からは ssh <サーバー> ~/Proj/localai/tools/model-eval/progress.py show --watch 30 で見る。標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from evallib import common, progress  # noqa: E402

DEFAULT_RUN_DATE = "2026-10-18"


def state_path(args: argparse.Namespace) -> Path:
    if args.state:
        return Path(args.state).resolve()
    return common.RESULTS_ROOT / args.date / progress.STATE_FILE


def parse_value(text: str):
    """--set の値。整数・小数・true/false/null は型を付け、それ以外は文字列のまま。"""

    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none", ""):
        return None
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def cmd_init(args: argparse.Namespace) -> int:
    path = state_path(args)
    t0 = progress.parse_time(args.t0) if args.t0 else progress.now()

    def mutate(state):
        if state.get("t0") and not args.force:
            raise SystemExit(f"{path} は初期化済み（t0 {state['t0']}）。やり直すなら --force")
        fresh = progress.empty_state()
        fresh["t0"] = progress.iso(t0)
        fresh["total_hours"] = args.total_hours
        fresh["lanes"]["claude"]["total"] = args.claude_total
        state.clear()
        state.update(fresh)

    progress.update(path, mutate)
    print(f"{path} を作った（t0 {progress.iso(t0)}、全行程 {args.total_hours} 時間）")
    return 0


def cmd_phase(args: argparse.Namespace) -> int:
    if args.action == "add":
        if not args.label or args.planned_min is None:
            raise SystemExit("phase add には --label と --planned-min が要る")
        depends = tuple(dep for dep in (args.depends or "").split(",") if dep)
        progress.add_phase(state_path(args), args.phase_id, args.label, args.planned_min, depends=depends,
                           before=args.before, lane=args.lane)
        print(f"{args.phase_id} を足した（{args.planned_min:g} 分、前の工程 {', '.join(depends) or 'なし'}"
              f"{'、' + args.before + ' の前' if args.before else ''}）")
        return 0
    progress.set_phase(state_path(args), args.phase_id, args.action)
    print(f"{args.phase_id} {args.action}")
    return 0


def cmd_deadline(args: argparse.Namespace) -> int:
    lifted = args.action == "lift"
    progress.set_deadline_lifted(state_path(args), lifted, note=args.note)
    print("期限を外した" if lifted else "期限を戻した")
    return 0


def cmd_lane(args: argparse.Namespace) -> int:
    fields = {}
    for pair in args.set or []:
        key, _sep, value = pair.partition("=")
        if not key:
            raise SystemExit(f"--set は key=value: {pair}")
        fields[key] = parse_value(value)
    progress.set_lane(state_path(args), args.lane, **fields)
    return 0


def cmd_claude(args: argparse.Namespace) -> int:
    path = state_path(args)
    key = {"model": args.model, "suite": args.suite, "item": args.item, "run": args.run}

    def mutate(state):
        lane = state["lanes"].setdefault("claude", {})
        active = [run for run in lane.get("active") or []
                  if not (run.get("model") == args.model and run.get("item") == args.item and run.get("run") == args.run)]
        if args.action == "start":
            active.append(dict(key, started_at=progress.iso(progress.now())))
        else:
            lane.setdefault("history", []).append(dict(key, finished_at=progress.iso(progress.now())))
        lane["active"] = active

    progress.update(path, mutate)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = state_path(args)
    while True:
        if not path.exists():
            print(f"{path} が無い（progress.py init で作る）", file=sys.stderr)
            return 1
        view = progress.build_view(progress.load(path), results_dir=path.parent)
        if args.json:
            print(json.dumps(view, ensure_ascii=False, indent=2))
        else:
            if args.watch:
                sys.stdout.write("\033[H\033[2J")
            print(progress.render(view))
        if not args.watch:
            return 0
        sys.stdout.flush()
        time.sleep(args.watch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=DEFAULT_RUN_DATE, help=f"results/<日付>/progress.json（既定 {DEFAULT_RUN_DATE}）")
    parser.add_argument("--state", default=None, help="状態ファイルを直接指す（試験・スモーク用）")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="進捗を表示する")
    show.add_argument("--watch", type=float, default=0, help="この秒数ごとに表示し直す（Ctrl-C で止める）")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    init = sub.add_parser("init", help="状態ファイルを作る")
    init.add_argument("--t0", default=None, help="全行程の開始時刻（ISO。既定は今）")
    init.add_argument("--total-hours", type=float, default=progress.DEFAULT_TOTAL_HOURS)
    init.add_argument("--claude-total", type=int, default=54)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    phase = sub.add_parser("phase", help="工程の開始・終了を書く・工程を足す")
    phase.add_argument("action", choices=["start", "end", "add"])
    phase.add_argument("phase_id")
    phase.add_argument("--label", default=None, help="add: 工程の説明")
    phase.add_argument("--planned-min", type=float, default=None, help="add: 計画の分")
    phase.add_argument("--depends", default=None, help="add: この工程の前に終わる工程（カンマ区切り）")
    phase.add_argument("--before", default=None, help="add: この工程の前に入れ、その工程をこの工程の後から始める")
    phase.add_argument("--lane", default=None, choices=["local"], help="add: 残りをローカルの列から出す")
    phase.set_defaults(func=cmd_phase)

    deadline = sub.add_parser("deadline", help="全行程の期限を外す・戻す")
    deadline.add_argument("action", choices=["lift", "restore"])
    deadline.add_argument("--note", default=None, help="lift: 外した理由")
    deadline.set_defaults(func=cmd_deadline)

    lane = sub.add_parser("lane", help="試験の列（local / claude）に値を書く")
    lane.add_argument("lane")
    lane.add_argument("--set", nargs="*", help="key=value（値が空なら消す）")
    lane.set_defaults(func=cmd_lane)

    claude = sub.add_parser("claude", help="Claude の 1 回の開始・終了を書く")
    claude.add_argument("action", choices=["start", "end"])
    claude.add_argument("--model", required=True)
    claude.add_argument("--suite", default=None)
    claude.add_argument("--item", required=True)
    claude.add_argument("--run", type=int, required=True)
    claude.set_defaults(func=cmd_claude)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
