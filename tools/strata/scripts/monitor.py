#!/usr/bin/env python3
"""strata.service（--service で strata-coder なども）の RAM（cgroup v2）・VRAM・swap・PSI（/proc/pressure）を
一定間隔で JSON Lines に記録する。

実機試験で起動の時間・メモリの山・デスクトップの重さを測るために使う（標準ライブラリのみ）。
  monitor.py record --out logs/monitor-x.jsonl [--interval 1] [--seconds 0] [--service strata-coder]
      （--seconds 0 は SIGINT / SIGTERM まで）
  monitor.py summary logs/monitor-x.jsonl

取るもの:
- cgroup の memory.current / memory.peak / memory.stat の anon・file・shmem・unevictable / memory.swap.current
  （memory.current は GGUF の読み込みで増える page cache を含むので、anon と file を分けて見る。
  engine がページロックする RAM 複製は shmem として file に入る）。
- 機体全体の MemAvailable と swap の使用量（/proc/meminfo）。
- GPU 全体の memory.used（nvidia-smi）。
- /proc/pressure/{memory,io,cpu} の some / full の avg10 と total（積算の停止時間、マイクロ秒）。
  total の差が「その間にタスクが待たされた時間」。ただし機体全体の値は strata 自身の停止も含む。
- そのためデスクトップ（GNOME Shell の cgroup）の memory / io / cpu の PSI と swap も別に取る。こちらの
  total の差が「デスクトップが待たされた時間」で、重くなったかの目安になる。
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CGROUP_ROOT = Path("/sys/fs/cgroup")
SERVICE_NAME = "strata"
# GNOME Shell（Wayland）と Xwayland がいる cgroup。デスクトップが待たされた時間を見る。
DESKTOP_CGROUP = CGROUP_ROOT / "user.slice/user-1000.slice/user@1000.service/session.slice/org.gnome.Shell@wayland.service"
GIB = 1024**3


def parse_pressure(text: str) -> dict[str, float]:
    """/proc/pressure/* の "some avg10=0.00 avg60=0.00 avg300=0.00 total=123" を平らな辞書にする。"""

    values: dict[str, float] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        kind = fields[0]
        for field in fields[1:]:
            name, _, value = field.partition("=")
            try:
                values[f"{kind}_{name}"] = float(value)
            except ValueError:
                continue
    return values


def parse_kv_lines(text: str) -> dict[str, int]:
    """memory.stat のような "名前 値" の行を辞書にする。"""

    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, value = line.partition(" ")
        if value.strip().isdigit():
            values[name] = int(value)
    return values


def parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name.strip()] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return values


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    text = _read_text(path)
    return int(text.strip()) if text and text.strip().isdigit() else None


def cgroup_dir(service_name: str = SERVICE_NAME) -> Path | None:
    try:
        group = subprocess.run(
            ["systemctl", "--user", "show", service_name, "-p", "ControlGroup", "--value"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not group:
        return None
    path = CGROUP_ROOT / group.lstrip("/")
    return path if path.is_dir() else None


def gpu_used_mib() -> int | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    first = output.strip().splitlines()[0] if output.strip() else ""
    return int(first) if first.strip().isdigit() else None


def sample(started: float, service_name: str = SERVICE_NAME) -> dict[str, Any]:
    row: dict[str, Any] = {"t": round(time.monotonic() - started, 2), "wall": time.strftime("%H:%M:%S")}
    group = cgroup_dir(service_name)
    row["active"] = group is not None
    if group is not None:
        row["cg_current"] = _read_int(group / "memory.current")
        row["cg_peak"] = _read_int(group / "memory.peak")
        row["cg_swap"] = _read_int(group / "memory.swap.current")
        stat = parse_kv_lines(_read_text(group / "memory.stat") or "")
        for key in ("anon", "file", "unevictable", "shmem"):
            row[f"cg_{key}"] = stat.get(key)
    meminfo = parse_meminfo(_read_text(Path("/proc/meminfo")) or "")
    row["mem_available"] = meminfo.get("MemAvailable")
    row["swap_used"] = meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)
    row["mlocked"] = meminfo.get("Mlocked")
    row["gpu_used_mib"] = gpu_used_mib()
    for kind in ("memory", "io", "cpu"):
        for name, value in parse_pressure(_read_text(Path(f"/proc/pressure/{kind}")) or "").items():
            if name.endswith(("avg10", "total")):
                row[f"psi_{kind}_{name}"] = value
        for name, value in parse_pressure(_read_text(DESKTOP_CGROUP / f"{kind}.pressure") or "").items():
            if name.endswith(("avg10", "total")):
                row[f"desk_{kind}_{name}"] = value
    row["desk_swap"] = _read_int(DESKTOP_CGROUP / "memory.swap.current")
    return row


def cmd_record(args: argparse.Namespace) -> int:
    stop = {"flag": False}

    def on_signal(signum: int, frame: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    started = time.monotonic()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as handle:
        while not stop["flag"]:
            handle.write(json.dumps(sample(started, args.service)) + "\n")
            handle.flush()
            if args.seconds and time.monotonic() - started >= args.seconds:
                break
            time.sleep(args.interval)
    return 0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """記録の山と差分をまとめる（純粋関数）。"""

    def peak(key: str) -> Any:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return max(values) if values else None

    def low(key: str) -> Any:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return min(values) if values else None

    def delta(key: str) -> Any:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return values[-1] - values[0] if values else None

    def avg10_peak(key: str) -> Any:
        return peak(key)

    duration = rows[-1]["t"] - rows[0]["t"] if rows else 0
    result = {
        "samples": len(rows),
        "duration_s": duration,
        "cg_peak_gib": (peak("cg_peak") or 0) / GIB,
        "cg_current_max_gib": (peak("cg_current") or 0) / GIB,
        "cg_anon_max_gib": (peak("cg_anon") or 0) / GIB,
        "cg_file_max_gib": (peak("cg_file") or 0) / GIB,
        "cg_unevictable_max_gib": (peak("cg_unevictable") or 0) / GIB,
        "cg_swap_max_gib": (peak("cg_swap") or 0) / GIB,
        "mem_available_min_gib": (low("mem_available") or 0) / GIB,
        "swap_used_first_gib": (rows[0].get("swap_used") or 0) / GIB if rows else None,
        "swap_used_max_gib": (peak("swap_used") or 0) / GIB,
        "swap_used_delta_gib": (delta("swap_used") or 0) / GIB,
        "mlocked_max_gib": (peak("mlocked") or 0) / GIB,
        "gpu_used_max_mib": peak("gpu_used_mib"),
    }
    for prefix in ("psi", "desk"):
        for kind in ("memory", "io", "cpu"):
            for level in ("some", "full"):
                stall = delta(f"{prefix}_{kind}_{level}_total")
                if stall is not None:
                    result[f"{prefix}_{kind}_{level}_stall_s"] = stall / 1e6
                    result[f"{prefix}_{kind}_{level}_stall_pct"] = 100.0 * stall / 1e6 / duration if duration else None
                    result[f"{prefix}_{kind}_{level}_avg10_max"] = avg10_peak(f"{prefix}_{kind}_{level}_avg10")
    if any(isinstance(row.get("desk_swap"), int) for row in rows):
        result["desk_swap_delta_gib"] = (delta("desk_swap") or 0) / GIB
    return result


def cmd_summary(args: argparse.Namespace) -> int:
    rows = [json.loads(line) for line in Path(args.path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.from_t is not None:
        rows = [row for row in rows if row["t"] >= args.from_t]
    if args.to_t is not None:
        rows = [row for row in rows if row["t"] <= args.to_t]
    if not rows:
        print("記録がありません", file=sys.stderr)
        return 1
    for key, value in summarize(rows).items():
        print(f"{key}: {value:.2f}" if isinstance(value, float) else f"{key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--out", required=True)
    record.add_argument("--interval", type=float, default=1.0)
    record.add_argument("--seconds", type=float, default=0.0)
    record.add_argument("--service", default=SERVICE_NAME, help="cgroup を見る systemd user ユニット（既定 strata）")
    record.set_defaults(func=cmd_record)
    summary = subparsers.add_parser("summary")
    summary.add_argument("path")
    summary.add_argument("--from-t", type=float, default=None)
    summary.add_argument("--to-t", type=float, default=None)
    summary.set_defaults(func=cmd_summary)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
