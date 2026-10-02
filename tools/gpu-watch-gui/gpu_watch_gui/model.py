"""gpu-watch.sh -o raw の行を解析し、窓内の最大・平均としきい値超過の edge 検出を行う。

GTK には依存しない純 Python。app.py（GTK 層）と tests/test_units.py の両方から import する。
センサーの読み取りは一切行わない。すべて gpu-watch.sh の feeder に 1 本化してあり、
ここでは子プロセスの stdout（raw 行）を解析するだけ。

raw 行の書式は tools/gpu-watch.sh の feeder() 内の printf と対応している（変えていない）:
  INFO, key=value
  HOST, stamp, cpu%, ctemp, mem%, mem_used_mib, mem_total_mib, cpu_w, psys_w
  FAN,  stamp, pwm, mode, state(ok|stale|none), age_sec
  GPU,  stamp, index, name, temp, util, mem_used_mib, mem_total_mib, power_w
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple, Union

DEFAULT_WINDOW_SEC = 60.0

# gpu-watch.sh の load_color と同じしきい値（使用率系: 90 以上=critical / 70 以上=warning / それ未満=ok）
LOAD_CRITICAL = 90.0
LOAD_WARNING = 70.0

# PC 全体(推定) = (PSys 推定 + GPU 実測電力の合計) ÷ PSU 効率 の既定値。
# 電源ユニットの実測効率は不明なため、80 PLUS Gold 帯の代表値として仮に置く仮定値。
# 実測した値があれば --psu-efficiency で上書きする。
DEFAULT_PSU_EFFICIENCY = 0.90


def parse_scalar(text: str) -> Optional[float]:
    """"na"・空文字は n/a として None を返す。数値化できない文字列も None（推測で埋めない）。"""
    text = text.strip()
    if text == "" or text == "na":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def temp_level(value: Optional[float], limit: float) -> str:
    """gpu-watch.sh の temp_color と同じしきい値（limit 以上=critical / limit-10 以上=warning / 未満=ok）。"""
    if value is None:
        return "unknown"
    if value >= limit:
        return "critical"
    if value >= limit - 10:
        return "warning"
    return "ok"


def plain_level(value: Optional[float]) -> str:
    """しきい値を決めていない項目（VRAM・電力・ファン PWM）。値があれば普通の文字色、
    取れなければ灰色。灰色を「n/a・未較正」だけの意味にするため、正常値は灰色にしない。"""
    return "unknown" if value is None else "plain"


def load_level(value: Optional[float]) -> str:
    """gpu-watch.sh の load_color と同じしきい値（90 以上=critical / 70 以上=warning / 未満=ok）。"""
    if value is None:
        return "unknown"
    if value >= LOAD_CRITICAL:
        return "critical"
    if value >= LOAD_WARNING:
        return "warning"
    return "ok"


@dataclass
class InfoSample:
    key: str
    value: str


@dataclass
class HostSample:
    stamp: str
    cpu_pct: Optional[float]
    cpu_temp: Optional[float]
    mem_pct: Optional[float]
    mem_used_mib: Optional[float]
    mem_total_mib: Optional[float]
    cpu_w: Optional[float]
    psys_w: Optional[float]


@dataclass
class FanSample:
    stamp: str
    pwm: Optional[float]
    mode: str
    state: str
    age_sec: Optional[float]


@dataclass
class GpuSample:
    stamp: str
    index: str
    name: str
    temp: Optional[float]
    util: Optional[float]
    mem_used_mib: Optional[float]
    mem_total_mib: Optional[float]
    power_w: Optional[float]


ParsedSample = Union[InfoSample, HostSample, FanSample, GpuSample]


def parse_raw_line(line: str) -> Optional[ParsedSample]:
    """gpu-watch.sh -o raw の 1 行を解析する。認識できない行・空行は None を返す。"""
    line = line.rstrip("\n")
    if not line:
        return None
    fields = line.split(", ")
    kind = fields[0]
    if kind == "INFO" and len(fields) >= 2:
        key_value = ", ".join(fields[1:])
        if "=" not in key_value:
            return None
        key, _, value = key_value.partition("=")
        return InfoSample(key=key, value=value)
    if kind == "HOST" and len(fields) >= 9:
        return HostSample(
            stamp=fields[1],
            cpu_pct=parse_scalar(fields[2]),
            cpu_temp=parse_scalar(fields[3]),
            mem_pct=parse_scalar(fields[4]),
            mem_used_mib=parse_scalar(fields[5]),
            mem_total_mib=parse_scalar(fields[6]),
            cpu_w=parse_scalar(fields[7]),
            psys_w=parse_scalar(fields[8]),
        )
    if kind == "FAN" and len(fields) >= 6:
        return FanSample(
            stamp=fields[1],
            pwm=parse_scalar(fields[2]),
            mode=fields[3],
            state=fields[4],
            age_sec=parse_scalar(fields[5]),
        )
    if kind == "GPU" and len(fields) >= 9:
        return GpuSample(
            stamp=fields[1],
            index=fields[2],
            name=fields[3],
            temp=parse_scalar(fields[4]),
            util=parse_scalar(fields[5]),
            mem_used_mib=parse_scalar(fields[6]),
            mem_total_mib=parse_scalar(fields[7]),
            power_w=parse_scalar(fields[8]),
        )
    return None


class RollingWindow:
    """直近 window_sec 秒分の値を保持し、窓内の最大値・平均値を返す。

    n/a（None）のサンプルは母数に入れない（gpu-watch.sh の awk 側 agg() と同じ扱い）。
    """

    def __init__(self, window_sec: float = DEFAULT_WINDOW_SEC):
        self.window_sec = window_sec
        self._samples: Deque[Tuple[float, float]] = deque()

    def add(self, now: float, value: Optional[float]) -> None:
        if value is not None:
            self._samples.append((now, value))
        cutoff = now - self.window_sec
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def max(self) -> Optional[float]:
        if not self._samples:
            return None
        return max(value for _, value in self._samples)

    def avg(self) -> Optional[float]:
        if not self._samples:
            return None
        total = sum(value for _, value in self._samples)
        return total / len(self._samples)

    def __len__(self) -> int:
        return len(self._samples)


@dataclass
class AlertEvent:
    """しきい値超過の edge（入った瞬間 / 解除された瞬間）。"""

    target: str       # "CPU" または GPU の index（例 "0"）
    entered: bool      # True: 超過に入った瞬間 / False: 解除された瞬間
    value: float
    threshold: float


class AlertTracker:
    """しきい値超過の edge 検出。超過に入った瞬間だけ entered=True、
    解除された瞬間だけ entered=False の AlertEvent を返す。超過が続いている間・
    平常が続いている間は None（何度呼んでも 1 回しか発火しない）。
    """

    def __init__(self) -> None:
        self._active: Dict[str, bool] = {}

    def update(self, target: str, value: Optional[float], threshold: float) -> Optional[AlertEvent]:
        if value is None:
            return None  # n/a は判定しない（現在の状態を維持する）
        is_over = value > threshold
        was_over = self._active.get(target, False)
        if is_over == was_over:
            return None
        self._active[target] = is_over
        return AlertEvent(target=target, entered=is_over, value=value, threshold=threshold)


# ---------------------------------------------------------------------------
# 較正データ（calibrate-power.py が root で作る JSON）の検証と、そこからの電力推定。
# RAPL の energy_uj は root 専用（CVE-2020-8694 の緩和）なので、非 root で常駐する
# このツールは実測の代わりに「負荷段階ごとに実測した点」から補間した推定値を出す。
# 推定はあくまで推定であり、実測が取れるときは呼び出し側（app.py）が実測を優先する。
# ---------------------------------------------------------------------------


@dataclass
class CalibrationPoint:
    util: float
    cpu_w: Optional[float]
    psys_w: Optional[float]


@dataclass
class Calibration:
    calibrated_at: str
    cpu_model: str
    threads: int
    points: List[CalibrationPoint]  # util 昇順
    pl1_w: Optional[float]
    pl1_window_s: Optional[float]


def validate_calibration(data: object) -> Tuple[Optional["Calibration"], str]:
    """calibrate-power.py が出す JSON（dict）を検証する。壊れていれば (None, 理由) を返す。"""
    if not isinstance(data, dict):
        return None, "較正データの形式が不正です（JSON オブジェクトではない）"
    if data.get("version") != 1:
        return None, "較正データのバージョンが未対応です"

    points_raw = data.get("points")
    if not isinstance(points_raw, list) or len(points_raw) == 0:
        return None, "較正データに points がありません"

    points: List[CalibrationPoint] = []
    try:
        for raw in points_raw:
            util = float(raw["util"])
            cpu_w = raw.get("cpu_w")
            cpu_w = float(cpu_w) if cpu_w is not None else None
            psys_w = raw.get("psys_w")
            psys_w = float(psys_w) if psys_w is not None else None
            points.append(CalibrationPoint(util=util, cpu_w=cpu_w, psys_w=psys_w))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, "較正データの points の形式が不正です"
    points.sort(key=lambda point: point.util)

    try:
        cpu_model = str(data["cpu_model"])
        threads = int(data["threads"])
    except (KeyError, TypeError, ValueError):
        return None, "較正データに cpu_model / threads がありません"

    pl1_w = data.get("pl1_w")
    pl1_window_s = data.get("pl1_window_s")
    try:
        pl1_w = float(pl1_w) if pl1_w is not None else None
        pl1_window_s = float(pl1_window_s) if pl1_window_s is not None else None
    except (TypeError, ValueError):
        return None, "較正データの pl1_w / pl1_window_s の形式が不正です"

    calibration = Calibration(
        calibrated_at=str(data.get("calibrated_at", "")),
        cpu_model=cpu_model,
        threads=threads,
        points=points,
        pl1_w=pl1_w,
        pl1_window_s=pl1_window_s,
    )
    return calibration, ""


def load_calibration(path: Path) -> Tuple[Optional["Calibration"], str]:
    """較正 JSON ファイルを読み込んで検証する。読めない・壊れていれば (None, 理由)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return None, f"較正ファイルが読めません: {error}"
    try:
        data = json.loads(text)
    except ValueError as error:
        return None, f"較正ファイルの JSON が壊れています: {error}"
    return validate_calibration(data)


def _normalize_cpu_model(text: str) -> str:
    """gpu-watch.sh の cpu_model 変換（(R)/(TM) 除去・空白圧縮）と同じ正規化。
    較正データ側（/proc/cpuinfo の model name 生値）と表記を揃えて比較するために使う。"""
    text = text.replace("(R)", "").replace("(TM)", "")
    return re.sub(r"\s+", " ", text).strip()


def _strip_thread_suffix(cpu_model_with_threads: str) -> str:
    """INFO の cpu_model は "<model> (N threads)" 形式。末尾のスレッド数表記を取り除く。"""
    return re.sub(r"\s*\(\d+\s*threads\)\s*$", "", cpu_model_with_threads).strip()


def calibration_matches_cpu(calibration: "Calibration", current_cpu_model_with_threads: str) -> bool:
    """較正時の CPU と、いま gpu-watch.sh の INFO 行から来ている CPU が同じかを判定する。"""
    calibrated = _normalize_cpu_model(calibration.cpu_model)
    current = _normalize_cpu_model(_strip_thread_suffix(current_cpu_model_with_threads))
    return calibrated != "" and calibrated == current


def calibration_status(calibration: Optional["Calibration"], current_cpu_model_with_threads: str) -> str:
    """"ok" / "missing"（較正なし） / "cpu_mismatch"（CPU が較正時と違う） のいずれかを返す。"""
    if calibration is None:
        return "missing"
    if not calibration_matches_cpu(calibration, current_cpu_model_with_threads):
        return "cpu_mismatch"
    return "ok"


def interpolate(points: List[Tuple[float, Optional[float]]], x: float) -> Optional[float]:
    """x でソート済みとは限らない (x, y) 点列を区間線形補間する。範囲外は端の値で止める。
    y が None（n/a）の点は補間の対象から外す。有効な点が無ければ None。"""
    usable = sorted((px, py) for px, py in points if py is not None)
    if not usable:
        return None
    if x <= usable[0][0]:
        return usable[0][1]
    if x >= usable[-1][0]:
        return usable[-1][1]
    for (x0, y0), (x1, y1) in zip(usable, usable[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            ratio = (x - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return usable[-1][1]  # 到達しない想定だが、浮動小数の境界漏れに備える


def ema_alpha(sample_interval_sec: float, time_constant_sec: float) -> float:
    """時定数 time_constant_sec の指数移動平均を、間隔 sample_interval_sec のサンプルで
    更新するときの係数（0〜1）。alpha = 1 - exp(-dt/tau)。"""
    if time_constant_sec <= 0 or sample_interval_sec <= 0:
        return 1.0
    return 1.0 - math.exp(-sample_interval_sec / time_constant_sec)


class PowerEstimator:
    """較正データ（負荷段階ごとの実測点）から CPU 電力・PSys 電力を推定する。

    CPU 電力は PL1（長期電力制限）で頭打ちになる。短時間は PL2 相当で PL1 を超えられるが、
    負荷が続くと移動平均が PL1 に迫りクロックが落ちて PL1 以下に収束する。この挙動を
    「推定値の指数移動平均が pl1_w 以上になったら以後の推定値を pl1_w 以下に抑える」
    という形で模す（時定数は較正時に実測した constraint_0_time_window_us = pl1_window_s）。
    """

    def __init__(self, calibration: Calibration, sample_interval_sec: float = 1.0) -> None:
        self.calibration = calibration
        self.sample_interval_sec = sample_interval_sec
        # 0.0 から始める（= 起動直後は「それまで低負荷だった」とみなす安全側の仮定）。
        # これにより高負荷が来た直後の短時間は PL2 相当で PL1 を超えた値をそのまま出し、
        # 移動平均が追いついてから頭打ちが効き始める。
        self._cpu_ema: float = 0.0

    def _alpha(self) -> float:
        window = self.calibration.pl1_window_s
        if not window:
            return 1.0
        return ema_alpha(self.sample_interval_sec, window)

    def estimate_cpu_w(self, util: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        """(PL1 頭打ちを適用した推定 W, 頭打ち前の素の補間値 W) を返す。
        素の値も返すのは、PSys 側で「抑えた分」を差し引くため。"""
        if util is None:
            return None, None
        points = [(point.util, point.cpu_w) for point in self.calibration.points]
        raw = interpolate(points, util)
        if raw is None:
            return None, None
        pl1 = self.calibration.pl1_w
        if pl1 is None:
            return raw, raw
        self._cpu_ema += self._alpha() * (raw - self._cpu_ema)
        clamped = min(raw, pl1) if self._cpu_ema >= pl1 else raw
        return clamped, raw

    def estimate_psys_w(
        self, util: Optional[float], cpu_clamped: Optional[float], cpu_raw: Optional[float],
    ) -> Optional[float]:
        """PSys の推定値。CPU が PL1 頭打ちで抑えられた分 (cpu_raw - cpu_clamped) を
        PSys の補間値からも差し引く（PSys は CPU を含むプラットフォーム全体の電力のため）。"""
        if util is None:
            return None
        points = [(point.util, point.psys_w) for point in self.calibration.points]
        raw_psys = interpolate(points, util)
        if raw_psys is None:
            return None
        if cpu_clamped is not None and cpu_raw is not None:
            raw_psys -= (cpu_raw - cpu_clamped)
        return raw_psys


def estimate_system_w(
    psys_w: Optional[float], gpu_power_total_w: Optional[float],
    psu_efficiency: float = DEFAULT_PSU_EFFICIENCY,
) -> Optional[float]:
    """PC 全体(推定) = (PSys 推定 + GPU 実測電力の合計) ÷ PSU 効率。
    GPU が n/a（取れていない）なら全体も n/a にする（片方だけで埋めない）。"""
    if psys_w is None or gpu_power_total_w is None:
        return None
    if psu_efficiency <= 0:
        return None
    return (psys_w + gpu_power_total_w) / psu_efficiency


@dataclass
class HostState:
    cpu_pct: RollingWindow
    cpu_temp: RollingWindow
    mem_pct: RollingWindow
    cpu_w: RollingWindow
    psys_w: RollingWindow
    # CPU 電力・PSys 電力・PC 全体の「推定」側の窓（実測と別に持つ。実測が取れる環境では
    # app.py 側が実測を優先表示するが、推定も裏では計算し続け 60 秒最大を出せるようにする）。
    cpu_w_est: RollingWindow
    psys_w_est: RollingWindow
    system_w_est: RollingWindow
    # "_now" は直近の 1 サンプル（n/a なら None）。RollingWindow は n/a を母数に入れないため別に持つ。
    cpu_pct_now: Optional[float] = None
    cpu_temp_now: Optional[float] = None
    mem_pct_now: Optional[float] = None
    cpu_w_now: Optional[float] = None
    psys_w_now: Optional[float] = None
    cpu_w_est_now: Optional[float] = None
    psys_w_est_now: Optional[float] = None
    system_w_est_now: Optional[float] = None
    mem_used_mib: Optional[float] = None
    mem_total_mib: Optional[float] = None
    stamp: Optional[str] = None


@dataclass
class GpuState:
    temp: RollingWindow
    util: RollingWindow
    power_w: RollingWindow
    mem_used: RollingWindow
    temp_now: Optional[float] = None
    util_now: Optional[float] = None
    power_w_now: Optional[float] = None
    name: str = ""
    mem_used_mib: Optional[float] = None
    mem_total_mib: Optional[float] = None
    stamp: Optional[str] = None


@dataclass
class FanState:
    pwm: RollingWindow
    pwm_now: Optional[float] = None
    mode: str = "na"
    state: str = "none"
    age_sec: Optional[float] = None
    stamp: Optional[str] = None


class GpuWatchModel:
    """gpu-watch.sh -o raw の出力を取り込み、表示用の状態を保つ。"""

    def __init__(
        self,
        gpu_threshold: float = 80.0,
        cpu_threshold: float = 90.0,
        window_sec: float = DEFAULT_WINDOW_SEC,
        interval_sec: float = 1.0,
        psu_efficiency: float = DEFAULT_PSU_EFFICIENCY,
    ) -> None:
        self.gpu_threshold = gpu_threshold
        self.cpu_threshold = cpu_threshold
        self.window_sec = window_sec
        self.interval_sec = interval_sec
        self.psu_efficiency = psu_efficiency
        self.host = HostState(
            cpu_pct=RollingWindow(window_sec),
            cpu_temp=RollingWindow(window_sec),
            mem_pct=RollingWindow(window_sec),
            cpu_w=RollingWindow(window_sec),
            psys_w=RollingWindow(window_sec),
            cpu_w_est=RollingWindow(window_sec),
            psys_w_est=RollingWindow(window_sec),
            system_w_est=RollingWindow(window_sec),
        )
        self.gpus: Dict[str, GpuState] = {}
        self.gpu_order: List[str] = []
        self.fan = FanState(pwm=RollingWindow(window_sec))
        self.rapl_note: str = ""
        self.cpu_model: str = ""
        self._alerts = AlertTracker()
        self.last_update: Optional[float] = None
        # 較正（calibrate-power.py の JSON）。None のままなら推定は出さず n/a。
        self.calibration: Optional[Calibration] = None
        self._power_estimator: Optional[PowerEstimator] = None

    def set_calibration(self, calibration: Optional[Calibration]) -> None:
        """較正データを差し替える。PL1 頭打ちの移動平均は較正ごとにリセットする。"""
        self.calibration = calibration
        self._power_estimator = (
            PowerEstimator(calibration, sample_interval_sec=self.interval_sec)
            if calibration is not None else None
        )

    def calibration_status(self) -> str:
        """"ok" / "missing" / "cpu_mismatch"。表示側（app.py）が文言を出し分けるために使う。"""
        return calibration_status(self.calibration, self.cpu_model)

    def _gpu_state(self, index: str) -> GpuState:
        if index not in self.gpus:
            self.gpus[index] = GpuState(
                temp=RollingWindow(self.window_sec),
                util=RollingWindow(self.window_sec),
                power_w=RollingWindow(self.window_sec),
                mem_used=RollingWindow(self.window_sec),
            )
            self.gpu_order.append(index)
        return self.gpus[index]

    def feed_line(self, line: str, now: Optional[float] = None) -> Optional[AlertEvent]:
        """raw 行を 1 行取り込む。しきい値超過の edge が起きていれば AlertEvent を返す。"""
        if now is None:
            now = time.time()
        record = parse_raw_line(line)
        if record is None:
            return None

        if isinstance(record, InfoSample):
            if record.key == "rapl_note":
                self.rapl_note = record.value
            elif record.key == "cpu_model":
                self.cpu_model = record.value
            return None

        if isinstance(record, HostSample):
            self.last_update = now
            self.host.stamp = record.stamp
            self.host.cpu_pct.add(now, record.cpu_pct)
            self.host.cpu_temp.add(now, record.cpu_temp)
            self.host.mem_pct.add(now, record.mem_pct)
            self.host.cpu_w.add(now, record.cpu_w)
            self.host.psys_w.add(now, record.psys_w)
            self.host.cpu_pct_now = record.cpu_pct
            self.host.cpu_temp_now = record.cpu_temp
            self.host.mem_pct_now = record.mem_pct
            self.host.cpu_w_now = record.cpu_w
            self.host.psys_w_now = record.psys_w
            self.host.mem_used_mib = record.mem_used_mib
            self.host.mem_total_mib = record.mem_total_mib
            self._update_power_estimate(now)
            return self._alerts.update("CPU", record.cpu_temp, self.cpu_threshold)

        if isinstance(record, FanSample):
            self.fan.stamp = record.stamp
            self.fan.pwm.add(now, record.pwm)
            self.fan.pwm_now = record.pwm
            self.fan.mode = record.mode
            self.fan.state = record.state
            self.fan.age_sec = record.age_sec
            return None

        if isinstance(record, GpuSample):
            self.last_update = now
            state = self._gpu_state(record.index)
            state.name = record.name
            state.stamp = record.stamp
            state.temp.add(now, record.temp)
            state.util.add(now, record.util)
            state.power_w.add(now, record.power_w)
            state.mem_used.add(now, record.mem_used_mib)
            state.temp_now = record.temp
            state.util_now = record.util
            state.power_w_now = record.power_w
            state.mem_used_mib = record.mem_used_mib
            state.mem_total_mib = record.mem_total_mib
            return self._alerts.update(record.index, record.temp, self.gpu_threshold)

        return None

    def _gpu_power_total(self) -> Optional[float]:
        """GPU 電力の合計（実測）。1 基でも n/a なら合計も n/a（推測で埋めない）。
        GPU が 1 基も無ければ None。"""
        if not self.gpu_order:
            return None
        total = 0.0
        for index in self.gpu_order:
            power = self.gpus[index].power_w_now
            if power is None:
                return None
            total += power
        return total

    def _update_power_estimate(self, now: float) -> None:
        """較正があれば CPU 電力・PSys 電力・PC 全体の推定を計算し、_now と 60 秒窓の両方へ入れる。
        較正が無ければ推定側はすべて None のままにする（推測で埋めない）。"""
        host = self.host
        if self._power_estimator is None:
            cpu_est = psys_est = system_est = None
        else:
            cpu_est, cpu_raw = self._power_estimator.estimate_cpu_w(host.cpu_pct_now)
            psys_est = self._power_estimator.estimate_psys_w(host.cpu_pct_now, cpu_est, cpu_raw)
            system_est = estimate_system_w(psys_est, self._gpu_power_total(), self.psu_efficiency)
        host.cpu_w_est_now = cpu_est
        host.psys_w_est_now = psys_est
        host.system_w_est_now = system_est
        host.cpu_w_est.add(now, cpu_est)
        host.psys_w_est.add(now, psys_est)
        host.system_w_est.add(now, system_est)
