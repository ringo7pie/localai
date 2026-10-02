#!/usr/bin/python3
"""CPU 負荷段階ごとの消費電力を実測し、較正データ（JSON）を stdout に出す。

root 専用（Intel RAPL の energy_uj は CVE-2020-8694 の緩和で root しか読めない。
この緩和は外さない）。sudo/pkexec はこのスクリプト自身からは呼ばない。
実機での較正は tools/gpu-watch-gui/app.py の「電力を較正」ボタンから、
利用者が pkexec 経由でパスワードを入力して行う。

段階: 負荷スレッド数 0, 25%, 50%, 75%, 100%（os.cpu_count() から算出）。
各段階は「2 秒ならし → 5 秒計測 → 5 秒休み」。ならしは負荷が定常状態になるのを待つため、
休みは PL1（長期電力制限）の移動平均が前の段階の高負荷で絞られたまま次の段階へ
引き継がれるのを避けるため（休ませてから次段階の「絞られる前」の値を測る）。

計測する値:
  CPU 使用率(%)      /proc/stat の差分
  CPU 電力(W)        package-0 の energy_uj 差分 ÷ 経過時間
  PSys 電力(W)       psys の energy_uj 差分 ÷ 経過時間（無ければ null）

負荷は os.fork した子プロセスの busy loop。SIGTERM/SIGINT を受けても、
try/finally で必ず全子プロセスを kill・wait してから終了する（プロセスを残さない）。

進捗は stderr に 1 行ずつ（例 "PROGRESS 2/5 threads=5"）、結果は stdout に JSON を 1 個。
ファイルには一切書かない（root がユーザーのホームにファイルを作らないため）。
保存は呼び出し側（app.py）が stdout の JSON を受け取って行う。
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

POWERCAP_ROOT = "/sys/class/powercap"
SETTLE_SEC = 2.0   # 負荷を掛けてから計測を始めるまでの「ならし」
MEASURE_SEC = 5.0  # 実測する時間
REST_SEC = 5.0     # 次の段階に移る前の休み（PL1 の移動平均を前段階の負荷から回復させる）

# このプロセスが fork した負荷用の子プロセス。SIGTERM/SIGINT が来てもここを見て全部 kill する。
_child_pids: List[int] = []


# ---------------------------------------------------------------------------
# root 不要の純関数（tests/test_units.py から import して試験する）
# ---------------------------------------------------------------------------

def stage_thread_counts(total_threads: int) -> List[int]:
    """0, 25%, 50%, 75%, 100% 負荷に対応するスレッド数（四捨五入）。"""
    if total_threads <= 0:
        return [0]
    fractions = (0.0, 0.25, 0.5, 0.75, 1.0)
    return [round(total_threads * fraction) for fraction in fractions]


def energy_diff_uj(prev_uj: int, cur_uj: int, max_range_uj: int) -> int:
    """energy_uj の差分。カウンタが max_energy_range_uj を超えて 0 に巻き戻った場合を補正する。"""
    diff = cur_uj - prev_uj
    if diff < 0:
        diff += max_range_uj
    return diff


def cpu_percent_from_stat_diff(prev: Tuple[int, int], cur: Tuple[int, int]) -> Optional[float]:
    """/proc/stat の (total, idle) 2 時点の差分から CPU 使用率(%)。差分が取れなければ None。"""
    d_total = cur[0] - prev[0]
    d_idle = cur[1] - prev[1]
    if d_total <= 0:
        return None
    return 100.0 * (d_total - d_idle) / d_total


# ---------------------------------------------------------------------------
# root 必須の I/O（/proc, /sys, fork）
# ---------------------------------------------------------------------------

def check_root() -> None:
    if os.geteuid() != 0:
        print(
            "calibrate-power.py: root で実行してください"
            "（RAPL の energy_uj は root 専用。CVE-2020-8694 の緩和のため）",
            file=sys.stderr,
        )
        sys.exit(2)


def read_proc_stat_cpu() -> Tuple[int, int]:
    """/proc/stat の 1 行目（全 CPU 合計）から (total, idle) を読む。"""
    with open("/proc/stat", "r", encoding="utf-8") as stat_file:
        line = stat_file.readline()
    fields = line.split()[1:]
    values = [int(field) for field in fields]
    while len(values) < 8:
        values.append(0)
    user, nice, system, idle, iowait, irq, softirq, steal = values[:8]
    idle_total = idle + iowait
    total = user + nice + system + idle + iowait + irq + softirq + steal
    return total, idle_total


def read_int(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8") as value_file:
            return int(value_file.read().strip())
    except (OSError, ValueError):
        return None


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as text_file:
            return text_file.read().strip()
    except OSError:
        return None


def find_rapl_dir(domain_name: str) -> Optional[str]:
    """powercap 配下から name ファイルが domain_name（"package-0" / "psys"）と一致し、
    energy_uj が読めるディレクトリを探す。gpu-watch.sh の find_rapl と同じ考え方。"""
    try:
        entries = sorted(os.listdir(POWERCAP_ROOT))
    except OSError:
        return None
    for entry in entries:
        if not entry.startswith("intel-rapl:"):
            continue
        dir_path = os.path.join(POWERCAP_ROOT, entry)
        if read_text(os.path.join(dir_path, "name")) != domain_name:
            continue
        energy_path = os.path.join(dir_path, "energy_uj")
        if os.access(energy_path, os.R_OK):
            return dir_path
    return None


def find_pl1_limit(package_dir: str) -> Tuple[Optional[float], Optional[float]]:
    """package-0 の constraint_*（long_term = PL1）から (pl1_w, pl1_window_s) を読む。
    見つからなければ (None, None)。"""
    for index in range(4):
        name = read_text(os.path.join(package_dir, f"constraint_{index}_name"))
        if name != "long_term":
            continue
        power_uw = read_int(os.path.join(package_dir, f"constraint_{index}_power_limit_uw"))
        window_us = read_int(os.path.join(package_dir, f"constraint_{index}_time_window_us"))
        pl1_w = power_uw / 1e6 if power_uw is not None else None
        pl1_window_s = window_us / 1e6 if window_us is not None else None
        return pl1_w, pl1_window_s
    return None, None


def read_cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as cpuinfo_file:
            for line in cpuinfo_file:
                if line.startswith("model name"):
                    return line.partition(":")[2].strip()
    except OSError:
        pass
    return "CPU"


# ---------------------------------------------------------------------------
# 負荷生成（fork した子プロセスの busy loop）
# ---------------------------------------------------------------------------

def _busy_loop() -> None:
    # 子プロセス側。親からの SIGTERM で終わる（デフォルトハンドラのまま終了して構わない）。
    while True:
        pass


def start_load(thread_count: int) -> List[int]:
    pids: List[int] = []
    for _ in range(thread_count):
        pid = os.fork()
        if pid == 0:
            # 子プロセス: busy loop に入ったら戻らない。os._exit で親の finally を実行させない。
            # 親の _signal_handler を継いだままだと、SIGTERM で sys.exit が親の finally や
            # main の続きを子の中で走らせる。既定の動作（即終了）に戻す。
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            _busy_loop()
            os._exit(0)
        pids.append(pid)
    return pids


def stop_load(pids: List[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for pid in pids:
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass


def _cleanup_all_children() -> None:
    stop_load(_child_pids)
    _child_pids.clear()


def _signal_handler(signum: int, frame: object) -> None:
    _cleanup_all_children()
    sys.exit(1)


# ---------------------------------------------------------------------------
# 計測・較正本体
# ---------------------------------------------------------------------------

def measure_stage(
    duration_sec: float,
    pkg_dir: str,
    pkg_max_uj: int,
    psys_dir: Optional[str],
    psys_max_uj: Optional[int],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """duration_sec 秒のあいだ計測し、(CPU 使用率%, CPU 電力 W, PSys 電力 W) を返す。"""
    stat_start = read_proc_stat_cpu()
    pkg_start = read_int(os.path.join(pkg_dir, "energy_uj"))
    psys_start = read_int(os.path.join(psys_dir, "energy_uj")) if psys_dir else None
    time_start = time.monotonic()

    time.sleep(duration_sec)

    time_end = time.monotonic()
    stat_end = read_proc_stat_cpu()
    pkg_end = read_int(os.path.join(pkg_dir, "energy_uj"))
    psys_end = read_int(os.path.join(psys_dir, "energy_uj")) if psys_dir else None

    elapsed = time_end - time_start
    util = cpu_percent_from_stat_diff(stat_start, stat_end)

    cpu_w: Optional[float] = None
    if elapsed > 0 and pkg_start is not None and pkg_end is not None:
        cpu_w = energy_diff_uj(pkg_start, pkg_end, pkg_max_uj) / 1e6 / elapsed

    psys_w: Optional[float] = None
    if elapsed > 0 and psys_start is not None and psys_end is not None and psys_max_uj is not None:
        psys_w = energy_diff_uj(psys_start, psys_end, psys_max_uj) / 1e6 / elapsed

    return util, cpu_w, psys_w


def run_calibration() -> dict:
    total_threads = os.cpu_count() or 1
    stages = stage_thread_counts(total_threads)

    pkg_dir = find_rapl_dir("package-0")
    if pkg_dir is None:
        print(
            "calibrate-power.py: package-0 の RAPL energy_uj が読めません"
            "（root でもこの機械には無いか、パスが想定と違います）",
            file=sys.stderr,
        )
        sys.exit(1)
    pkg_max_uj = read_int(os.path.join(pkg_dir, "max_energy_range_uj")) or 1

    psys_dir = find_rapl_dir("psys")
    psys_max_uj = read_int(os.path.join(psys_dir, "max_energy_range_uj")) if psys_dir else None

    pl1_w, pl1_window_s = find_pl1_limit(pkg_dir)

    points = []
    total_stages = len(stages)
    for stage_no, threads in enumerate(stages, start=1):
        print(f"PROGRESS {stage_no}/{total_stages} threads={threads}", file=sys.stderr)
        pids = start_load(threads)
        _child_pids.extend(pids)
        try:
            time.sleep(SETTLE_SEC)  # ならし: 負荷が定常状態になるのを待つ
            util, cpu_w, psys_w = measure_stage(MEASURE_SEC, pkg_dir, pkg_max_uj, psys_dir, psys_max_uj)
        finally:
            stop_load(pids)
            for pid in pids:
                if pid in _child_pids:
                    _child_pids.remove(pid)
        points.append({"util": util, "cpu_w": cpu_w, "psys_w": psys_w})
        # 休み: 次の段階を「PL1 の移動平均が前段階の高負荷で絞られる前」の状態で測るため。
        time.sleep(REST_SEC)

    return {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "cpu_model": read_cpu_model(),
        "threads": total_threads,
        "points": points,
        "pl1_w": pl1_w,
        "pl1_window_s": pl1_window_s,
    }


def main(argv: Optional[List[str]] = None) -> int:
    check_root()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    try:
        result = run_calibration()
    finally:
        _cleanup_all_children()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
