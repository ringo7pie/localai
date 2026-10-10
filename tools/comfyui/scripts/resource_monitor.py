#!/usr/bin/env python3
"""ComfyUI の systemd ユニットの RAM（cgroup v2）・VRAM（nvidia-smi）・swap を 1 秒ごとに記録する。

run_workflow.py run --monitor が使う。単体でも動く:
  resource_monitor.py --seconds 60 --csv /tmp/x.csv

取るもの:
- cgroup の memory.peak / memory.swap.peak。開いた fd に書き込むと、その fd から読む値だけが今の値に戻る
  （kernel 6.12 以降。ほかの読み手と systemd の表示は変わらない）。回の始めに戻し、終わりに同じ fd で読む。
  memory.current は page cache（重みファイルの読み込みなど）を含むので、anon（memory.stat）も別に取る。
- 機体全体の swap 使用量（/proc/meminfo）と MemAvailable。
- GPU 全体の memory.used と、cgroup に属するプロセスの使用量（--query-compute-apps）。
- blender という名前のプロセスの RSS と cgroup。snap の Blender は別の scope に移ることがあり、
  そのとき comfyui.service の cgroup の値には入らない（MemoryMax も効かない）ので分けて記録する。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CGROUP_ROOT = Path("/sys/fs/cgroup")
SERVICE_NAME = "comfyui"
MIB = 1024 * 1024

CSV_FIELDS = (
    "t", "cg_current", "cg_anon", "cg_file", "cg_swap", "sys_swap_used", "mem_available",
    "gpu_used_mib", "gpu_util", "cg_gpu_mib", "blender_rss", "blender_outside_rss", "cg_procs",
)


def default_cgroup_dir(service_name: str = SERVICE_NAME) -> Path | None:
    """systemctl --user show の ControlGroup から cgroup のフォルダを出す。"""
    try:
        group = subprocess.run(
            ["systemctl", "--user", "show", service_name, "-p", "ControlGroup", "--value"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not group:
        return None
    path = CGROUP_ROOT / group.lstrip("/")
    return path if path.is_dir() else None


def parse_memory_stat(text: str) -> dict[str, int]:
    values = {}
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if value.strip().isdigit():
            values[key] = int(value)
    return values


def parse_meminfo(text: str) -> dict[str, int]:
    """/proc/meminfo を読む。値はバイト。"""
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return values


def parse_gpu_query(text: str) -> tuple[int | None, int | None]:
    """nvidia-smi --query-gpu=memory.used,utilization.gpu の 1 行目を (MiB, %) で返す。"""
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            return int(parts[0]), int(parts[1]) if parts[1].isdigit() else None
    return None, None


def parse_compute_apps(text: str) -> dict[int, int]:
    """nvidia-smi --query-compute-apps=pid,used_memory を {pid: MiB} で返す。"""
    apps = {}
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            apps[int(parts[0])] = int(parts[1])
    return apps


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    text = _read_text(path)
    return int(text.strip()) if text and text.strip().isdigit() else None


def _run(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


class LocalPeak:
    """memory.peak / memory.swap.peak を fd ごとに戻して読む。戻せない kernel では None を返す。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None
        self.global_before = _read_int(path)
        try:
            self.fd = os.open(path, os.O_RDWR)
            os.write(self.fd, b"reset")
        except OSError:
            if self.fd is not None:
                os.close(self.fd)
            self.fd = None

    def read(self) -> dict[str, int | None]:
        local = None
        if self.fd is not None:
            os.lseek(self.fd, 0, os.SEEK_SET)
            text = os.read(self.fd, 64).decode().strip()
            local = int(text) if text.isdigit() else None
            os.close(self.fd)
            self.fd = None
        return {"local_peak": local, "global_before": self.global_before, "global_after": _read_int(self.path)}


class ResourceMonitor(threading.Thread):
    def __init__(
        self, cgroup_dir: Path | None, main_pid: int | None = None, interval: float = 1.0,
        csv_path: Path | None = None, guard_bytes: int | None = None, on_guard: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.cgroup_dir = cgroup_dir
        self.main_pid = main_pid
        self.interval = interval
        self.csv_path = csv_path
        self.guard_bytes = guard_bytes
        self.on_guard = on_guard
        self.guard_reason: str | None = None
        self.samples: list[dict[str, Any]] = []
        self.blender_cgroups: set[str] = set()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.before = self._snapshot()
        self.peak_memory = LocalPeak(cgroup_dir / "memory.peak") if cgroup_dir else None
        self.peak_swap = LocalPeak(cgroup_dir / "memory.swap.peak") if cgroup_dir else None
        self.after: dict[str, Any] | None = None

    def _snapshot(self) -> dict[str, Any]:
        meminfo = parse_meminfo(_read_text(Path("/proc/meminfo")) or "")
        snapshot = {
            "time": time.time(),
            "sys_swap_used": meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0),
            "mem_available": meminfo.get("MemAvailable"),
        }
        if self.cgroup_dir:
            snapshot["cg_current"] = _read_int(self.cgroup_dir / "memory.current")
            snapshot["cg_swap"] = _read_int(self.cgroup_dir / "memory.swap.current")
            snapshot["cg_peak_global"] = _read_int(self.cgroup_dir / "memory.peak")
        return snapshot

    def cgroup_pids(self) -> list[int]:
        if not self.cgroup_dir:
            return []
        text = _read_text(self.cgroup_dir / "cgroup.procs") or ""
        return [int(line) for line in text.split() if line.isdigit()]

    def _blender_processes(self, cgroup_pids: set[int]) -> tuple[int, int]:
        """blender の RSS の合計を、cgroup の中と外に分けて返す。"""
        inside = outside = 0
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            comm = _read_text(entry / "comm")
            if not comm or "blender" not in comm.lower():
                continue
            status = parse_meminfo(_read_text(entry / "status") or "")
            rss = status.get("VmRSS", 0)
            group = (_read_text(entry / "cgroup") or "").strip()
            self.blender_cgroups.add(group.split("::", 1)[-1])
            if int(entry.name) in cgroup_pids:
                inside += rss
            else:
                outside += rss
        return inside, outside

    def sample(self) -> dict[str, Any]:
        now = time.time()
        pids = self.cgroup_pids()
        pid_set = set(pids)
        row: dict[str, Any] = {"t": now, "cg_procs": len(pids)}
        if self.cgroup_dir:
            stat = parse_memory_stat(_read_text(self.cgroup_dir / "memory.stat") or "")
            row["cg_current"] = _read_int(self.cgroup_dir / "memory.current")
            row["cg_anon"] = stat.get("anon")
            row["cg_file"] = stat.get("file")
            row["cg_swap"] = _read_int(self.cgroup_dir / "memory.swap.current")
        meminfo = parse_meminfo(_read_text(Path("/proc/meminfo")) or "")
        row["sys_swap_used"] = meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)
        row["mem_available"] = meminfo.get("MemAvailable")
        gpu_used, gpu_util = parse_gpu_query(_run([
            "nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits",
        ]))
        row["gpu_used_mib"] = gpu_used
        row["gpu_util"] = gpu_util
        apps = parse_compute_apps(_run([
            "nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits",
        ]))
        row["cg_gpu_mib"] = sum(used for pid, used in apps.items() if pid in pid_set)
        row["blender_rss"], row["blender_outside_rss"] = self._blender_processes(pid_set)
        return row

    def _check_guard(self, row: dict[str, Any]) -> None:
        if not self.guard_bytes or self.guard_reason:
            return
        demand = (row.get("cg_anon") or 0) + (row.get("cg_swap") or 0) + (row.get("blender_outside_rss") or 0)
        if demand > self.guard_bytes:
            self.guard_reason = (
                f"anon+swap(+cgroup 外の blender) = {demand / 1024**3:.1f} GiB > {self.guard_bytes / 1024**3:.1f} GiB"
            )
            if self.on_guard:
                self.on_guard(self.guard_reason)

    def run(self) -> None:
        writer = None
        handle = None
        if self.csv_path:
            handle = self.csv_path.open("w", newline="", encoding="utf-8")
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
        try:
            while not self._stop_event.is_set():
                started = time.monotonic()
                row = self.sample()
                with self._lock:
                    self.samples.append(row)
                if writer:
                    writer.writerow(row)
                    handle.flush()
                self._check_guard(row)
                self._stop_event.wait(max(0.0, self.interval - (time.monotonic() - started)))
        finally:
            if handle:
                handle.close()

    def stop(self) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=30)
        self.after = self._snapshot()

    def terminate_children(self, main_pid: int | None) -> list[int]:
        """cgroup の中で ComfyUI 本体以外のプロセス（WTiVo の子プロセス・Blender）に SIGTERM を送る。"""
        stopped = []
        for pid in self.cgroup_pids():
            if pid == main_pid:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
            except OSError:
                pass
        return stopped

    def peaks_between(self, start: float, end: float) -> dict[str, Any]:
        """ノードの実行中（start〜end）の標本から、ピークを出す（1 秒刻みなので短いノードは取りこぼす）。"""
        with self._lock:
            window = [row for row in self.samples if start - self.interval <= row["t"] <= end + self.interval]
        return {
            "peak_gpu_used_mib": max((row.get("gpu_used_mib") or 0 for row in window), default=None),
            "peak_cg_anon_gib": _gib(max((row.get("cg_anon") or 0 for row in window), default=None)),
            "peak_blender_rss_gib": _gib(max((row.get("blender_rss", 0) + row.get("blender_outside_rss", 0)
                                              for row in window), default=None)),
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self.samples)

        def peak(key: str) -> Any:
            return max((row.get(key) or 0 for row in samples), default=None)

        before = self.before
        after = self.after or self._snapshot()
        memory_peak = self.peak_memory.read() if self.peak_memory else {}
        swap_peak = self.peak_swap.read() if self.peak_swap else {}
        return {
            "samples": len(samples),
            "cgroup": str(self.cgroup_dir) if self.cgroup_dir else None,
            "cg_memory_peak_gib": _gib(memory_peak.get("local_peak")),
            "cg_memory_peak_global_before_gib": _gib(memory_peak.get("global_before")),
            "cg_memory_peak_global_after_gib": _gib(memory_peak.get("global_after")),
            "cg_swap_peak_gib": _gib(swap_peak.get("local_peak")),
            "cg_current_before_gib": _gib(before.get("cg_current")),
            "cg_current_after_gib": _gib(after.get("cg_current")),
            "sampled_cg_current_peak_gib": _gib(peak("cg_current")),
            "sampled_cg_anon_peak_gib": _gib(peak("cg_anon")),
            "sampled_cg_swap_peak_gib": _gib(peak("cg_swap")),
            "gpu_used_peak_mib": peak("gpu_used_mib"),
            "cg_gpu_peak_mib": peak("cg_gpu_mib"),
            "blender_rss_peak_gib": _gib(peak("blender_rss")),
            "blender_outside_cgroup_rss_peak_gib": _gib(peak("blender_outside_rss")),
            "blender_cgroups": sorted(self.blender_cgroups),
            "sys_swap_used_before_gib": _gib(before.get("sys_swap_used")),
            "sys_swap_used_after_gib": _gib(after.get("sys_swap_used")),
            "sys_swap_used_peak_gib": _gib(peak("sys_swap_used")),
            "sys_swap_delta_gib": _gib((after.get("sys_swap_used") or 0) - (before.get("sys_swap_used") or 0)),
            "mem_available_min_gib": _gib(min((row.get("mem_available") or 0 for row in samples), default=None)),
        }


def _gib(value: int | None) -> float | None:
    return None if value is None else round(value / 1024**3, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComfyUI の RAM・VRAM・swap を一定時間記録する")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--csv")
    args = parser.parse_args(argv)
    monitor = ResourceMonitor(default_cgroup_dir(), interval=args.interval, csv_path=Path(args.csv) if args.csv else None)
    monitor.start()
    time.sleep(args.seconds)
    monitor.stop()
    print(json.dumps(monitor.summary(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
