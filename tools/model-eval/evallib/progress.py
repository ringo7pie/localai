"""進捗の状態ファイル（results/<日付>/progress.json）の読み書きと、経過・残り時間の計算。

progress.py（見る・工程の境を書く）と run_eval.py（--progress で問の送信・完了を書く）と run_local.sh（モデルの開始・終了）が使う。
書き手が複数のプロセスになるので、読み書きは progress.json.lock の flock で 1 つずつにする。

状態ファイルの形:
  {"t0": ISO, "total_hours": 18, "deadline_local": ISO|null,
   "deadline_lifted_at": ISO|null, "deadline_note": 文字列|null,      # 期限を外したとき（progress.py deadline lift）
   "phases": [{"id", "label", "planned_start_min", "planned_min", "started_at", "finished_at",
               "depends": [前の工程の id, ...]（任意）, "lane": "local"（任意。ローカルの列から残りを出す工程）}, ...],
   "lanes": {"local": {...}, "claude": {...}}, "updated_at": ISO}
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
from pathlib import Path
from typing import Any, Callable, Iterator

from . import common

DEFAULT_TOTAL_HOURS = 18.0
# モデルの切り替え（Ollama の読み込み・Strata の起動と停止）に見込む分
SWITCH_MIN = 5.0
# 1 モデルの累計時間の上限がこの分以上なら「上限なし」とみなす（run_local.sh に BUDGET_MIN=100000 などを渡したとき）
UNLIMITED_BUDGET_MIN = 10000.0
# 上限なしのとき、まだ 1 問も記録の無いモデルの 1 問に見込む分（lanes.local.est_item_min で変えられる）
DEFAULT_ITEM_MIN = 15.0
DEFAULT_PHASES: tuple[dict[str, Any], ...] = (
    {"id": "P0", "label": "実装（問題・採点器・道具）", "planned_start_min": 0, "planned_min": 210},
    {"id": "P1", "label": "ローカル 9 モデルの計測", "planned_start_min": 180, "planned_min": 675},
    {"id": "P2", "label": "Claude 2 種の計測", "planned_start_min": 180, "planned_min": 180},
    {"id": "P3", "label": "集計・所見・HTML", "planned_start_min": 855, "planned_min": 105},
)
STATE_FILE = "progress.json"
# 前の工程が終わってから始まる工程（まだ始まっていない工程の開始の見込みを、前の工程の終了の見込みから出す）。
# 状態ファイルの工程に depends があれば、そちらを使う
DEPENDS = {"P3": ("P1", "P2")}


def now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def parse_time(text: str | None) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(text) if text else None


def iso(moment: datetime.datetime) -> str:
    return moment.astimezone().isoformat(timespec="seconds")


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def empty_state() -> dict[str, Any]:
    return {"t0": None, "total_hours": DEFAULT_TOTAL_HOURS, "deadline_local": None,
            "deadline_lifted_at": None, "deadline_note": None,
            "phases": [dict(phase, started_at=None, finished_at=None) for phase in DEFAULT_PHASES],
            "lanes": {"local": {}, "claude": {}}}


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    state = common.read_json(path)
    state.setdefault("lanes", {}).setdefault("local", {})
    state["lanes"].setdefault("claude", {})
    return state


def update(path: Path, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """状態を読み、mutate で書き換えて保存する（ロックの中で）。"""

    with locked(path):
        state = load(path)
        mutate(state)
        state["updated_at"] = iso(now())
        common.write_json(path, state)
    return state


def set_lane(path: Path, lane: str, **fields: Any) -> dict[str, Any]:
    """lanes[lane] に値を足す。値が None の鍵は消す。"""

    def mutate(state: dict[str, Any]) -> None:
        target = state["lanes"].setdefault(lane, {})
        for key, value in fields.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = value

    return update(path, mutate)


def append_history(path: Path, lane: str, entry: dict[str, Any]) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        state["lanes"].setdefault(lane, {}).setdefault("history", []).append(entry)

    return update(path, mutate)


def set_phase(path: Path, phase_id: str, action: str, at: datetime.datetime | None = None) -> dict[str, Any]:
    moment = iso(at or now())

    def mutate(state: dict[str, Any]) -> None:
        for phase in state["phases"]:
            if phase["id"] == phase_id:
                if action == "start":
                    phase["started_at"] = moment
                    phase["finished_at"] = None
                elif action == "end":
                    phase["started_at"] = phase.get("started_at") or moment
                    phase["finished_at"] = moment
                else:
                    raise ValueError(f"unknown action: {action}")
                return
        raise KeyError(f"工程 {phase_id} が無い（{', '.join(phase['id'] for phase in state['phases'])}）")

    return update(path, mutate)


def add_phase(path: Path, phase_id: str, label: str, planned_min: float, depends: tuple[str, ...] = (),
              before: str | None = None, lane: str | None = None) -> dict[str, Any]:
    """工程を足す。before を渡すとその工程の前に入れ、その工程の depends に新しい工程を足す（後から始まるように）。"""

    def mutate(state: dict[str, Any]) -> None:
        phases = state["phases"]
        ids = [phase["id"] for phase in phases]
        if phase_id in ids:
            raise ValueError(f"工程 {phase_id} はもうある")
        for dep in (*depends, *((before,) if before else ())):
            if dep not in ids:
                raise KeyError(f"工程 {dep} が無い（{', '.join(ids)}）")
        entry: dict[str, Any] = {"id": phase_id, "label": label, "planned_start_min": None, "planned_min": planned_min,
                                 "started_at": None, "finished_at": None, "depends": list(depends)}
        if lane:
            entry["lane"] = lane
        if before:
            position = ids.index(before)
            later = phases[position]
            later["depends"] = [*phase_depends(later), phase_id]
            phases.insert(position, entry)
        else:
            phases.append(entry)

    return update(path, mutate)


def set_deadline_lifted(path: Path, lifted: bool, note: str | None = None,
                        at: datetime.datetime | None = None) -> dict[str, Any]:
    """全行程の期限を外す（lifted=True）か、戻す。外すと表示は「期限まで残り」の代わりに外した時刻と理由を出す。"""

    def mutate(state: dict[str, Any]) -> None:
        state["deadline_lifted_at"] = iso(at or now()) if lifted else None
        state["deadline_note"] = note if lifted else None

    return update(path, mutate)


# ------------------------------------------------------------------------------------------------ 計算


def phase_depends(phase: dict[str, Any]) -> list[str]:
    if "depends" in phase:
        return list(phase["depends"])
    return list(DEPENDS.get(phase["id"], ()))


def is_local_phase(phase: dict[str, Any]) -> bool:
    return phase["id"] == "P1" or phase.get("lane") == "local"


def budget_unlimited(lane: dict[str, Any]) -> bool:
    return float(lane.get("budget_min") or 0.0) >= UNLIMITED_BUDGET_MIN


def minutes_between(start: datetime.datetime | None, end: datetime.datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 60.0


def local_remaining_min(lane: dict[str, Any], at: datetime.datetime) -> float | None:
    """ローカルの計測が終わるまでの見込み（分）。締切があれば締切で頭打ち。

    上限あり: いまのモデルの上限の残り + 後のモデル数 ×（上限 + 切替）。
    上限なし: いまのモデルの残りの問 × 1 問の見込み（記録済みの累計 ÷ 記録済みの問。まだ無ければ est_item_min）
              + 後のモデルの残りの問（items_after。run_local.sh が書く）× est_item_min + 後のモデル数 × 切替。
    """

    if not lane or lane.get("status") == "finished":
        return 0.0 if lane.get("status") == "finished" else None
    count = lane.get("model_count")
    index = lane.get("model_index")
    if not count or not index:
        return None
    budget = float(lane.get("budget_min") or 0.0)
    spent = float(lane.get("spent_min") or 0.0)
    item_elapsed = minutes_between(parse_time(lane.get("item_started_at")), at) or 0.0
    models_after = int(count) - int(index)
    if budget_unlimited(lane):
        default_item = float(lane.get("est_item_min") or DEFAULT_ITEM_MIN)
        done = int(lane.get("done") or 0)
        per_item = spent / done if done > 0 and spent > 0 else default_item
        items_left = max(0, int(lane.get("total") or 0) - done)
        if lane.get("item_started_at") and items_left > 0:
            current_left = max(0.0, per_item - item_elapsed) + (items_left - 1) * per_item
        else:
            current_left = items_left * per_item
        left = current_left + int(lane.get("items_after") or 0) * default_item + models_after * SWITCH_MIN
    else:
        current_left = max(0.0, budget - spent - item_elapsed)
        base = float(lane.get("base_budget_min") or budget)
        left = current_left + models_after * (base + SWITCH_MIN)
    deadline = parse_time(lane.get("deadline"))
    if deadline is not None:
        left = min(left, max(0.0, minutes_between(at, deadline) or 0.0))
    return left


def build_view(state: dict[str, Any], at: datetime.datetime | None = None,
               results_dir: Path | None = None) -> dict[str, Any]:
    """表示に使う値をまとめる（--json はこれをそのまま出す）。"""

    at = at or now()
    t0 = parse_time(state.get("t0"))
    total_min = float(state.get("total_hours") or DEFAULT_TOTAL_HOURS) * 60.0
    elapsed_total = minutes_between(t0, at)
    phases_view = []
    est_ends: list[datetime.datetime] = []
    end_by_id: dict[str, datetime.datetime] = {}
    local_lane = state["lanes"].get("local") or {}
    for phase in state["phases"]:
        started = parse_time(phase.get("started_at"))
        finished = parse_time(phase.get("finished_at"))
        planned = float(phase["planned_min"])
        entry: dict[str, Any] = {"id": phase["id"], "label": phase["label"], "planned_min": planned,
                                 "started_at": phase.get("started_at"), "finished_at": phase.get("finished_at")}
        if finished is not None:
            entry["state"] = "done"
            entry["elapsed_min"] = minutes_between(started, finished)
            entry["remaining_min"] = 0.0
            est_ends.append(finished)
            end_by_id[phase["id"]] = finished
        elif started is not None:
            entry["state"] = "running"
            elapsed = minutes_between(started, at) or 0.0
            entry["elapsed_min"] = elapsed
            entry["remaining_plan_min"] = planned - elapsed
            remaining = max(0.0, planned - elapsed)
            if is_local_phase(phase):
                by_models = local_remaining_min(local_lane, at)
                entry["remaining_models_min"] = by_models
                if by_models is not None:
                    remaining = by_models
            entry["remaining_min"] = remaining
            est_ends.append(at + datetime.timedelta(minutes=remaining))
            end_by_id[phase["id"]] = est_ends[-1]
        else:
            entry["state"] = "waiting"
            entry["elapsed_min"] = None
            entry["remaining_min"] = planned
            if t0 is not None:
                planned_start = t0 + datetime.timedelta(minutes=float(phase.get("planned_start_min") or 0))
                before = [end_by_id[dep] for dep in phase_depends(phase) if dep in end_by_id]
                if before:
                    planned_start = max(before)
                start = max(planned_start, at)
                entry["planned_start_at"] = iso(start)
                est_ends.append(start + datetime.timedelta(minutes=planned))
                end_by_id[phase["id"]] = est_ends[-1]
        phases_view.append(entry)
    view: dict[str, Any] = {
        "now": iso(at), "t0": state.get("t0"), "total_min": total_min,
        "elapsed_total_min": elapsed_total,
        "remaining_total_min": None if elapsed_total is None else total_min - elapsed_total,
        "deadline_at": iso(t0 + datetime.timedelta(minutes=total_min)) if t0 else None,
        "deadline_lifted_at": state.get("deadline_lifted_at"),
        "deadline_note": state.get("deadline_note"),
        "estimated_end_at": iso(max(est_ends)) if est_ends else None,
        "estimated_remaining_min": minutes_between(at, max(est_ends)) if est_ends else None,
        "phases": phases_view,
        "local": dict(local_lane),
        "claude": dict(state["lanes"].get("claude") or {}),
        "updated_at": state.get("updated_at"),
    }
    if local_lane.get("item_started_at"):
        view["local"]["item_elapsed_min"] = minutes_between(parse_time(local_lane["item_started_at"]), at)
    active = []
    for run in (state["lanes"].get("claude") or {}).get("active") or []:
        active.append(dict(run, elapsed_min=minutes_between(parse_time(run.get("started_at")), at)))
    view["claude"]["active"] = active
    if results_dir is not None:
        view["claude"]["done"] = sum(1 for _ in common.iter_claude_records(results_dir)) if (results_dir / "claude").is_dir() else 0
    return view


def fmt_hm(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    total = int(round(abs(minutes)))
    sign = "-" if minutes < 0 and total > 0 else ""
    return f"{sign}{total // 60}:{total % 60:02d}"


def fmt_clock(text: str | None) -> str:
    moment = parse_time(text)
    return moment.strftime("%m-%d %H:%M") if moment else "—"


STATE_LABELS = {"done": "終了", "running": "進行中", "waiting": "未開始"}


def render(view: dict[str, Any]) -> str:
    lines = [f"== AI 評価の進捗（{fmt_clock(view['now'])} 現在。T0 {fmt_clock(view['t0'])}）=="]
    lines.append("")
    lines.append("[いま試験中]")
    local = view["local"]
    if local.get("status") == "finished":
        lines.append("  ローカル: 全モデル終了")
    elif local.get("target"):
        item = local.get("item")
        item_text = (f"問 {item}（{local.get('suite', '?')}、{int(local.get('done') or 0) + 1}/{local.get('total', '?')} 問目）"
                     f" この問 {fmt_hm(local.get('item_elapsed_min'))} 経過" if item else
                     f"{local.get('phase_note', '準備中（読み込み・起動）')}")
        lines.append(f"  ローカル: {local['target']}（{local.get('model_index', '?')}/{local.get('model_count', '?')} モデル目） {item_text}")
        if budget_unlimited(local):
            lines.append(f"            このモデルの累計 {float(local.get('spent_min') or 0.0):.1f} 分 / 上限なし")
        else:
            lines.append(f"            このモデルの累計 {float(local.get('spent_min') or 0.0):.1f} 分 / 上限 {float(local.get('budget_min') or 0.0):.0f} 分")
    else:
        lines.append("  ローカル: まだ始まっていない")
    claude = view["claude"]
    done = claude.get("done")
    total = claude.get("total")
    header = f"  Claude:   記録 {done if done is not None else '?'} / {total or '?'} 回"
    lines.append(header)
    for run in claude.get("active") or []:
        lines.append(f"            実行中 {run.get('model')} {run.get('item')} run{run.get('run')}（{fmt_hm(run.get('elapsed_min'))} 経過）")
    lines.append("")
    lines.append("[工程]   状態    経過 / 計画     残り")
    for phase in view["phases"]:
        state = STATE_LABELS[phase["state"]]
        if phase["state"] == "running":
            remaining = fmt_hm(phase["remaining_min"])
            over = phase.get("remaining_plan_min")
            note = f"（計画より {fmt_hm(-over)} 超過）" if over is not None and over < 0 else ""
            if phase.get("remaining_models_min") is not None:
                basis = "残りの問と 1 問の見込みから" if budget_unlimited(view["local"]) else "残りモデルと上限から"
                note += f"（{basis}。計画では {fmt_hm(max(0.0, over or 0.0))}）"
            lines.append(f"  {phase['id']:<3} {state:<4} {fmt_hm(phase['elapsed_min']):>6} / {fmt_hm(phase['planned_min']):<6} "
                         f"{remaining:>6}{note}  {phase['label']}")
        elif phase["state"] == "done":
            lines.append(f"  {phase['id']:<3} {state:<4} {fmt_hm(phase['elapsed_min']):>6} / {fmt_hm(phase['planned_min']):<6} "
                         f"{'0:00':>6}  {phase['label']}（{fmt_clock(phase['finished_at'])} 終了）")
        else:
            lines.append(f"  {phase['id']:<3} {state:<4} {'—':>6} / {fmt_hm(phase['planned_min']):<6} "
                         f"{fmt_hm(phase['remaining_min']):>6}  {phase['label']}（開始予定 {fmt_clock(phase.get('planned_start_at'))}）")
    lines.append("")
    if view.get("deadline_lifted_at"):
        reason = f"。{view['deadline_note']}" if view.get("deadline_note") else ""
        lines.append(f"[全行程] 経過 {fmt_hm(view['elapsed_total_min'])}  期限なし（当初の期限 {fmt_clock(view['deadline_at'])} は "
                     f"{fmt_clock(view['deadline_lifted_at'])} に外した{reason}）")
    else:
        lines.append(f"[全行程] 経過 {fmt_hm(view['elapsed_total_min'])} / {fmt_hm(view['total_min'])}  "
                     f"期限まで残り {fmt_hm(view['remaining_total_min'])}（期限 {fmt_clock(view['deadline_at'])}）")
    if view["phases"] and all(phase["state"] == "done" for phase in view["phases"]):
        lines.append(f"         全工程終了（{fmt_clock(view['estimated_end_at'])}）")
    else:
        lines.append(f"         見込みの残り {fmt_hm(view['estimated_remaining_min'])}（終了見込み {fmt_clock(view['estimated_end_at'])}）")
    lines.append(f"  状態ファイルの更新 {fmt_clock(view.get('updated_at'))}")
    return "\n".join(lines)
