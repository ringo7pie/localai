#!/usr/bin/env python3
"""gpu-watch.sh の値を見るだけの小さな常駐ウィンドウ（GTK4）。

センサーの読み取りは一切行わない。tools/gpu-watch.sh を `-o raw` で子プロセスとして起動し、
その出力（INFO/HOST/FAN/GPU 行）を gpu_watch_gui.model で解析して表示するだけ。
取れない値（n/a）は推測で埋めず、そのまま n/a と出す。

GTK を import するのはこのファイルだけ（model.py は GTK 非依存の純 Python）。
子プロセスの stdout は GLib の非同期読み（Gio.Subprocess + Gio.DataInputStream.read_line_async）
で読み、UI スレッドをブロックしない。窓を閉じたら子プロセスへ SIGTERM を送って終了する。
子プロセスが（原因を問わず）落ちたら最下行に理由を表示し、5 秒後に再起動を試みる。

起動方法は run-gpu-watch-gui を使う（システムの /usr/bin/python3 を使い、venv は作らない）。
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402  (gi.require_version の後に import する)

from gpu_watch_gui import model
from gpu_watch_gui.model import AlertEvent, GpuWatchModel, load_level, plain_level, temp_level

APP_ID = "jp.localai.GpuWatchGui"
GUI_DIR = Path(__file__).resolve().parent.parent
GPU_WATCH_SH = GUI_DIR.parent / "gpu-watch.sh"
CALIBRATE_SCRIPT = GUI_DIR / "calibrate-power.py"
# 較正の保存先。root で作る calibrate-power.py が利用者のホームにファイルを作らないよう、
# JSON は stdout 経由で受け取り、保存はここ（非 root のこのプロセス）が行う。
STATE_DIR = GUI_DIR / "state"
CALIBRATION_FILE = STATE_DIR / "calibration.json"

RESTART_DELAY_SEC = 5
CALIBRATE_DONE_DISPLAY_SEC = 5
FAILURE_DISPLAY_SEC = 15  # 失敗の理由は読めるよう長めに残す（全文はツールチップ）
VALUE_WIDTH_CHARS = 7  # 「未較正」「21% 13G」「3.5/24G」が収まる幅
MAX_WIDTH_CHARS = 5
ESTIMATE_PREFIX = "≈"  # 推定値の印。項目名に (推定) と書くと横幅が伸びるため値の頭に付ける
LEVEL_CSS_CLASSES = ("level-critical", "level-warning", "level-ok", "level-unknown", "level-plain")

CSS = b"""
.level-critical { color: #ff4d4d; font-weight: bold; }
.level-warning  { color: #e6b800; font-weight: bold; }
.level-ok       { color: #2ecc71; }
.level-unknown  { color: #888888; }
.level-plain    { }
.gpu-watch-colhead { font-size: smaller; }
separator.gpu-watch-separator { background: #808080; min-height: 1px; }
.gpu-watch-status { font-size: smaller; }
button.gpu-watch-calibrate { padding: 0 6px; min-height: 0; font-size: smaller; }
"""


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """-n・-w・-t・-T・-i・-F・-P を gpu-watch.sh と同じ既定値で受け取る。"""
    parser = argparse.ArgumentParser(description="gpu-watch.sh の値を見る小さな常駐ウィンドウ")
    parser.add_argument("-n", dest="interval", type=int, default=1, metavar="SEC",
                        help="サンプリング間隔（秒）。既定 1")
    parser.add_argument("-w", dest="window", type=int, default=60, metavar="SEC",
                        help="窓内最大の対象期間（秒）。既定 60")
    parser.add_argument("-t", dest="gpu_threshold", type=int, default=80, metavar="DEG",
                        help="GPU 温度アラートのしきい値（摂氏）。既定 80")
    parser.add_argument("-T", dest="cpu_threshold", type=int, default=90, metavar="DEG",
                        help="CPU 温度アラートのしきい値（摂氏）。既定 90")
    parser.add_argument("-i", dest="gpu_index", default="", metavar="IDX",
                        help="監視する GPU（nvidia-smi -i と同じ書式）。既定は全 GPU")
    parser.add_argument("-F", dest="fan_unit", default="a30-fan.service", metavar="UNIT",
                        help="ファン PWM を読む systemd ユニット。既定 a30-fan.service。off で無効")
    parser.add_argument("-P", dest="baseline_watt", default=None, metavar="WATT",
                        help="筐体ベースライン（W）。省略すると推定は出さない")
    parser.add_argument("--psu-efficiency", dest="psu_efficiency", type=float,
                        default=model.DEFAULT_PSU_EFFICIENCY, metavar="RATIO",
                        help="PC 全体(推定)で使う電源ユニット効率（0 より大きく 1 以下）。既定 0.90")
    parser.add_argument("--app-id", dest="app_id", default=APP_ID, metavar="ID",
                        help="GLib アプリケーション ID。既定時の二重起動防止を避け、"
                             "試験で別インスタンスを起動するためのもの")
    args = parser.parse_args(argv)
    if not (0 < args.psu_efficiency <= 1):
        parser.error(f"--psu-efficiency は 0 より大きく 1 以下で指定する: {args.psu_efficiency}")
    return args


def build_feeder_argv(args: argparse.Namespace) -> list:
    """gpu-watch.sh -o raw の起動コマンドライン（受け取った引数をそのまま渡す）。"""
    argv = [
        str(GPU_WATCH_SH), "-o", "raw",
        "-n", str(args.interval), "-w", str(args.window),
        "-t", str(args.gpu_threshold), "-T", str(args.cpu_threshold),
        "-F", args.fan_unit,
    ]
    if args.gpu_index:
        argv += ["-i", args.gpu_index]
    if args.baseline_watt is not None:
        argv += ["-P", str(args.baseline_watt)]
    return argv


def notify_critical(summary: str, body: str) -> None:
    """失敗しても落ちない（デスクトップ通知は付加機能で、本体の表示を止めてはいけない）。"""
    try:
        subprocess.Popen(
            ["notify-send", "-u", "critical", summary, body],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def format_scalar(value: Optional[float], unit: str, precision: int = 0, prefix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{prefix}{value:.{precision}f}{unit}"


def format_mem(used_mib: Optional[float], pct: Optional[float]) -> str:
    """「21% 13G」。詳しい値（小数・全体量）はツールチップに出す。"""
    if used_mib is None or pct is None:
        return "n/a"
    return f"{pct:.0f}% {used_mib / 1024:.0f}G"


def format_vram(used_mib: Optional[float], total_mib: Optional[float]) -> str:
    """「3.5/24G」。MiB の値はツールチップに出す。"""
    if used_mib is None or total_mib is None:
        return "n/a"
    return f"{used_mib / 1024:.1f}/{total_mib / 1024:.0f}G"


def format_gib(used_mib: Optional[float]) -> str:
    if used_mib is None:
        return "n/a"
    return f"{used_mib / 1024:.1f}G"


def stamp_time_part(stamp: Optional[str]) -> str:
    """gpu-watch.sh の "2026/10/02 10:40:25.135" から "10:40:25" だけを取り出す。"""
    if not stamp:
        return ""
    parts = stamp.split()
    clock = parts[1] if len(parts) >= 2 else parts[0]
    return clock.split(".")[0]


class MetricRow:
    """「項目名 / 現在値 / 60 秒最大」の 1 行。色は現在値セルに CSS クラスで付ける。"""

    def __init__(self, grid: Gtk.Grid, row: int, label_text: str):
        self.name_label = Gtk.Label(label=label_text, xalign=0)
        self.value_label = Gtk.Label(label="n/a", xalign=1)
        self.max_label = Gtk.Label(label="n/a", xalign=1)
        self.value_label.set_width_chars(VALUE_WIDTH_CHARS)
        self.max_label.set_width_chars(MAX_WIDTH_CHARS)
        grid.attach(self.name_label, 0, row, 1, 1)
        grid.attach(self.value_label, 1, row, 1, 1)
        grid.attach(self.max_label, 2, row, 1, 1)

    def set_values(self, current_text: str, max_text: str, level: str) -> None:
        self.value_label.set_label(current_text)
        self.max_label.set_label(max_text)
        for css_class in LEVEL_CSS_CLASSES:
            self.value_label.remove_css_class(css_class)
        self.value_label.add_css_class(f"level-{level}")

    def set_tooltip(self, text: str) -> None:
        self.value_label.set_tooltip_text(text or None)

    def set_name_tooltip(self, text: str) -> None:
        self.name_label.set_tooltip_text(text or None)

    def set_name(self, text: str) -> None:
        """実測/推定の切り替えなど、項目名を後から変える行のためのメソッド。"""
        self.name_label.set_label(text)


class GpuWatchWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, args: argparse.Namespace):
        super().__init__(application=application, title="GPU Watch")
        # 中身の自然な大きさに合わせる。値の列は幅を固定しているので伸び縮みしない。
        self.set_resizable(False)

        self.args = args
        self.model = GpuWatchModel(
            gpu_threshold=float(args.gpu_threshold),
            cpu_threshold=float(args.cpu_threshold),
            window_sec=float(args.window),
            interval_sec=float(args.interval),
            psu_efficiency=float(args.psu_efficiency),
        )

        self._subprocess: Optional[Gio.Subprocess] = None
        self._stdout_stream: Optional[Gio.DataInputStream] = None
        self._stderr_stream: Optional[Gio.DataInputStream] = None
        self._last_stderr_line = ""
        self._restart_source_id: Optional[int] = None
        self._shutting_down = False
        self._gpu_rows: Dict[str, Dict[str, MetricRow]] = {}
        self._gpu_headings: Dict[str, Gtk.Label] = {}
        self._calibrate_process: Optional[Gio.Subprocess] = None
        # 一定時間だけ最下行に残すメッセージ（較正の完了・失敗）。毎秒の「更新」で消さないため。
        self._held_message: Optional[str] = None
        self._held_until = 0.0

        self._build_ui()
        self.connect("close-request", self._on_close_request)

        self._load_calibration_at_startup()
        self._start_feeder()
        GLib.timeout_add_seconds(1, self._on_tick)

    # ---- UI 組み立て --------------------------------------------------

    def _build_ui(self) -> None:
        # 縦に詰めるため見出し行（HOST / FAN / 較正 / 最終更新）は置かない。
        # 表の下に「較正ボタン + 状態 1 行」を別の箱で置く。GPU の行は値が届いてから表に足すので、
        # 表と最下行を分けておかないと GPU の行が最下行より下に並んでしまう。
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.set_margin_top(6)
        outer.set_margin_bottom(6)
        outer.set_margin_start(8)
        outer.set_margin_end(8)
        self.set_child(outer)

        self.grid = Gtk.Grid(column_spacing=8, row_spacing=0)
        outer.append(self.grid)

        self._next_row = 0
        for column, text_value in enumerate(("", "現在", f"最大{self.args.window}s")):
            head = Gtk.Label(label=text_value, xalign=1)
            head.add_css_class("gpu-watch-colhead")
            self.grid.attach(head, column, self._next_row, 1, 1)
        self._next_row += 1

        # 並びは「PC 全体 ─ CPU 系 ─ GPU 系」。区切り線で 3 つに分ける。
        self.row_system_w = self._metric_row("PC 全体")
        self._separator_row()

        self.row_cpu = self._metric_row("CPU")
        self.row_cpu_temp = self._metric_row("CPU 温度")
        self.row_mem = self._metric_row("メモリ")
        self.row_cpu_w = self._metric_row("CPU 電力")
        self.row_psys_w = self._metric_row("PSys")
        for row in (self.row_cpu_w, self.row_psys_w, self.row_system_w):
            row.set_name_tooltip(f"値の頭の {ESTIMATE_PREFIX} は推定値。付いていなければ実測")
        self.row_cpu.set_name_tooltip("CPU 使用率")
        self._separator_row()

        # GPU の行は値が届いてから、この位置（ファンの行の手前）に差し込む。
        # ファンは A30 を冷やすファン（a30-fan.service）なので GPU 系の最後に置く。
        self._gpu_insert_row = self._next_row
        if self.args.fan_unit != "off":
            self.row_fan = self._metric_row("ファン")
            self.row_fan.set_name_tooltip("A30 のファン。Pico H への PWM 指令値で、回転数の実測ではない")
        else:
            self.row_fan = None

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.calibrate_button = Gtk.Button(label="較正")
        self.calibrate_button.add_css_class("gpu-watch-calibrate")
        self.calibrate_button.set_tooltip_text("電力の推定式を作り直す（pkexec でパスワードを聞かれる。約 1 分）")
        self.calibrate_button.connect("clicked", self._on_calibrate_clicked)
        bottom.append(self.calibrate_button)

        self.status_label = Gtk.Label(label="起動中", xalign=0)
        self.status_label.add_css_class("gpu-watch-status")
        self.status_label.set_hexpand(True)
        # 長い理由でウィンドウが横に伸びないよう省略する。全文はツールチップ。
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.set_max_width_chars(14)
        bottom.append(self.status_label)
        outer.append(bottom)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _metric_row(self, label_text: str) -> MetricRow:
        row = MetricRow(self.grid, self._next_row, label_text)
        self._next_row += 1
        return row

    def _separator_row(self) -> None:
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("gpu-watch-separator")
        separator.set_margin_top(3)
        separator.set_margin_bottom(3)
        self.grid.attach(separator, 0, self._next_row, 3, 1)
        self._next_row += 1

    def _gpu_metric_row(self, label_text: str) -> MetricRow:
        """GPU 系の行を、ファンの行より前に差し込む（Gtk.Grid.insert_row で下の行をずらす）。"""
        self.grid.insert_row(self._gpu_insert_row)
        row = MetricRow(self.grid, self._gpu_insert_row, label_text)
        self._gpu_insert_row += 1
        self._next_row += 1
        return row

    def _ensure_gpu_rows(self, index: str, name: str) -> Dict[str, MetricRow]:
        if index in self._gpu_rows:
            return self._gpu_rows[index]
        # 見出し行の代わりに項目名へ GPU 番号を入れ、GPU 名はツールチップに出す。
        prefix = f"GPU{index}"
        rows = {
            "util": self._gpu_metric_row(prefix),
            "temp": self._gpu_metric_row(f"{prefix} 温度"),
            "vram": self._gpu_metric_row("VRAM" if index == "0" else f"VRAM{index}"),
            "power": self._gpu_metric_row(f"{prefix} 電力"),
        }
        for row in rows.values():
            row.set_name_tooltip(f"GPU {index}: {name}")
        self._gpu_rows[index] = rows
        return rows

    # ---- 子プロセス（gpu-watch.sh -o raw）の起動・読み取り --------------

    def _start_feeder(self) -> None:
        argv = build_feeder_argv(self.args)
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        )
        try:
            self._subprocess = launcher.spawnv(argv)
        except GLib.Error as error:
            self._on_feeder_died(f"起動に失敗: {error.message}")
            return

        self._last_stderr_line = ""
        self._stdout_stream = Gio.DataInputStream.new(self._subprocess.get_stdout_pipe())
        self._stderr_stream = Gio.DataInputStream.new(self._subprocess.get_stderr_pipe())
        self._read_stdout_line()
        self._read_stderr_line()
        self._subprocess.wait_async(None, self._on_subprocess_exited)

    def _read_stdout_line(self) -> None:
        if self._stdout_stream is None:
            return
        self._stdout_stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_stdout_line)

    def _on_stdout_line(self, stream: Gio.DataInputStream, result: Gio.AsyncResult) -> None:
        try:
            line_bytes, _length = stream.read_line_finish(result)
        except GLib.Error:
            return  # ストリームが閉じた。_on_subprocess_exited 側で停止扱いにする
        if not line_bytes:
            return  # EOF。子プロセスの終了は wait_async 側で検知する
        line = line_bytes.decode("utf-8", errors="replace")
        event = self.model.feed_line(line)
        self._refresh_view()
        if event is not None:
            self._handle_alert(event)
        self._read_stdout_line()

    def _read_stderr_line(self) -> None:
        if self._stderr_stream is None:
            return
        self._stderr_stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_stderr_line)

    def _on_stderr_line(self, stream: Gio.DataInputStream, result: Gio.AsyncResult) -> None:
        try:
            line_bytes, _length = stream.read_line_finish(result)
        except GLib.Error:
            return
        if not line_bytes:
            return
        self._last_stderr_line = line_bytes.decode("utf-8", errors="replace").strip()
        self._read_stderr_line()

    def _on_subprocess_exited(self, subprocess_obj: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        try:
            subprocess_obj.wait_finish(result)
        except GLib.Error:
            pass
        if self._shutting_down:
            return
        exit_status = subprocess_obj.get_exit_status()
        reason = f"gpu-watch.sh が終了しました（終了コード {exit_status}）"
        if self._last_stderr_line:
            reason += f": {self._last_stderr_line}"
        self._on_feeder_died(reason)

    def _on_feeder_died(self, reason: str) -> None:
        if self._shutting_down:
            return
        self._subprocess = None
        self._stdout_stream = None
        self._stderr_stream = None
        self._set_status(f"停止中（{RESTART_DELAY_SEC}秒後に再起動）", f"停止中: {reason}")
        if self._restart_source_id is None:
            self._restart_source_id = GLib.timeout_add_seconds(RESTART_DELAY_SEC, self._on_restart_timeout)

    def _on_restart_timeout(self) -> bool:
        self._restart_source_id = None
        if not self._shutting_down:
            self._start_feeder()
        return GLib.SOURCE_REMOVE

    def _stop_feeder(self) -> None:
        self._shutting_down = True
        if self._restart_source_id is not None:
            GLib.source_remove(self._restart_source_id)
            self._restart_source_id = None
        if self._subprocess is not None:
            try:
                self._subprocess.send_signal(15)  # SIGTERM。gpu-watch.sh 自身の trap が feeder も止める
            except GLib.Error:
                pass
            self._subprocess = None

    def _on_close_request(self, window: Gtk.ApplicationWindow) -> bool:
        self._stop_feeder()
        return False  # 既定の「閉じる」処理を継続させる

    # ---- 表示の更新 -----------------------------------------------------

    def _on_tick(self) -> bool:
        self._refresh_status()
        return GLib.SOURCE_CONTINUE

    def _set_status(self, text: str, detail: str = "") -> None:
        self.status_label.set_label(text)
        self.status_label.set_tooltip_text(detail or text)

    def _hold_message(self, text: str, seconds: float) -> None:
        self._held_message = text
        self._held_until = time.monotonic() + seconds
        self._set_status(text)

    def _refresh_status(self) -> None:
        if self._calibrate_process is not None:
            self._set_status("較正中（約1分）")
            return
        if self._held_message is not None:
            if time.monotonic() < self._held_until:
                self._set_status(self._held_message)
                return
            self._held_message = None
        if self._subprocess is None:
            return  # 停止中の理由表示を上書きしない
        if self.model.last_update is None:
            self._set_status("値の受信待ち")
            return
        stamp = self.model.host.stamp or ""
        self._set_status(f"更新 {stamp_time_part(stamp)}", f"最終更新: {stamp}")

    def _refresh_view(self) -> None:
        host = self.model.host
        self.row_cpu.set_values(
            format_scalar(host.cpu_pct_now, "%"), format_scalar(host.cpu_pct.max(), "%"),
            load_level(host.cpu_pct_now),
        )
        self.row_cpu_temp.set_values(
            format_scalar(host.cpu_temp_now, "℃"), format_scalar(host.cpu_temp.max(), "℃"),
            temp_level(host.cpu_temp_now, self.model.cpu_threshold),
        )
        self.row_mem.set_values(
            format_mem(host.mem_used_mib, host.mem_pct_now),
            format_scalar(host.mem_pct.max(), "%"),
            load_level(host.mem_pct_now),
        )
        if host.mem_used_mib is not None and host.mem_total_mib is not None:
            self.row_mem.set_tooltip(f"{host.mem_used_mib / 1024:.1f} / {host.mem_total_mib / 1024:.1f} GiB")
        self._refresh_power_rows(host)

        for index in self.model.gpu_order:
            gpu = self.model.gpus[index]
            rows = self._ensure_gpu_rows(index, gpu.name)
            rows["temp"].set_values(
                format_scalar(gpu.temp_now, "℃"), format_scalar(gpu.temp.max(), "℃"),
                temp_level(gpu.temp_now, self.model.gpu_threshold),
            )
            rows["util"].set_values(
                format_scalar(gpu.util_now, "%"), format_scalar(gpu.util.max(), "%"),
                load_level(gpu.util_now),
            )
            rows["vram"].set_values(
                format_vram(gpu.mem_used_mib, gpu.mem_total_mib),
                format_gib(gpu.mem_used.max()),
                plain_level(gpu.mem_used_mib),
            )
            if gpu.mem_used_mib is not None and gpu.mem_total_mib is not None:
                rows["vram"].set_tooltip(f"{gpu.mem_used_mib:.0f} / {gpu.mem_total_mib:.0f} MiB")
            rows["power"].set_values(
                format_scalar(gpu.power_w_now, "W"), format_scalar(gpu.power_w.max(), "W"), plain_level(gpu.power_w_now),
            )

        if self.row_fan is not None:
            fan = self.model.fan
            if fan.state == "ok":
                # 普段は CONTROL しか出ない。それ以外のモードのときだけ値に添えて目立たせる。
                current_text = format_scalar(fan.pwm_now, "%")
                if fan.mode != "CONTROL":
                    current_text += f" {fan.mode}"
                self.row_fan.set_tooltip(f"モード {fan.mode}")
            elif fan.state == "stale":
                current_text = "n/a"
                self.row_fan.set_tooltip(f"最新の PWM ログが {fan.age_sec} 秒前（サービスが指令を出せていない可能性）")
            else:
                current_text = "n/a"
                self.row_fan.set_tooltip("journal に PWM ログが無い（サービス停止中か権限不足）")
            self.row_fan.set_values(
                current_text, format_scalar(fan.pwm.max(), "%"),
                plain_level(fan.pwm_now if fan.state == "ok" else None),
            )

        self._refresh_status()

    def _power_label_for_status(self, status: str) -> str:
        if status == "cpu_mismatch":
            return "要再較正"  # CPU が較正時と違う。理由はツールチップ
        return "未較正"

    def _calibration_tooltip_text(self) -> str:
        """「較正ボタンを押す」の案内と、推定式・仮定・較正日時をまとめたツールチップ文。"""
        calibration = self.model.calibration
        lines = ["較正ボタンを押すと、負荷段階ごとの実測から推定式を作ります。"]
        if self.model.rapl_note:
            lines.append(self.model.rapl_note)
        lines.append("CPU 電力(推定) = 較正点を CPU 使用率で区間線形補間し、PL1 で頭打ち")
        lines.append("PSys(推定) = 補間値 − (CPU が PL1 で抑えられた分)")
        lines.append(f"PC 全体(推定) = (PSys推定 + GPU実測の合計) ÷ PSU効率({self.model.psu_efficiency:.2f})")
        lines.append("仮定: PSU 効率は実測していない既定値。PSys に dGPU の電力は含まれない前提")
        lines.append(f"較正日時: {calibration.calibrated_at if calibration is not None else '未較正'}")
        return "\n".join(lines)

    def _refresh_power_rows(self, host) -> None:
        """CPU 電力・PSys・PC 全体の 3 行。RAPL の実測が取れる環境ではそちらを優先し、
        取れない環境・未較正なら推定（無ければ「未較正」）を出す。混同しないよう
        項目名に (実測)/(推定) を付け、較正ボタンの案内はツールチップにまとめる。"""
        status = self.model.calibration_status()
        tooltip = self._calibration_tooltip_text()
        label = self._power_label_for_status(status)

        if host.cpu_w_now is not None:
            self.row_cpu_w.set_values(
                format_scalar(host.cpu_w_now, "W"), format_scalar(host.cpu_w.max(), "W"), plain_level(host.cpu_w_now),
            )
            self.row_cpu_w.set_tooltip("")
        else:
            if status == "ok":
                self.row_cpu_w.set_values(
                    format_scalar(host.cpu_w_est_now, "W", prefix=ESTIMATE_PREFIX),
                    format_scalar(host.cpu_w_est.max(), "W", prefix=ESTIMATE_PREFIX),
                    plain_level(host.cpu_w_est_now),
                )
            else:
                self.row_cpu_w.set_values(label, label, "unknown")
            self.row_cpu_w.set_tooltip(tooltip)

        if host.psys_w_now is not None:
            self.row_psys_w.set_values(
                format_scalar(host.psys_w_now, "W"), format_scalar(host.psys_w.max(), "W"), plain_level(host.psys_w_now),
            )
            self.row_psys_w.set_tooltip("")
        else:
            if status == "ok":
                self.row_psys_w.set_values(
                    format_scalar(host.psys_w_est_now, "W", prefix=ESTIMATE_PREFIX),
                    format_scalar(host.psys_w_est.max(), "W", prefix=ESTIMATE_PREFIX),
                    plain_level(host.psys_w_est_now),
                )
            else:
                self.row_psys_w.set_values(label, label, "unknown")
            self.row_psys_w.set_tooltip(tooltip)

        # PC 全体はこの筐体に実測センサーが無いため、較正済みでも常に「推定」表示。
        if status == "ok":
            self.row_system_w.set_values(
                format_scalar(host.system_w_est_now, "W", prefix=ESTIMATE_PREFIX),
                format_scalar(host.system_w_est.max(), "W", prefix=ESTIMATE_PREFIX),
                plain_level(host.system_w_est_now),
            )
        else:
            self.row_system_w.set_values(label, label, "unknown")
        self.row_system_w.set_tooltip(tooltip)

    # ---- 較正（root で calibrate-power.py を pkexec 経由で実行） -------------

    def _load_calibration_at_startup(self) -> None:
        if not CALIBRATION_FILE.exists():
            return
        calibration, _reason = model.load_calibration(CALIBRATION_FILE)
        if calibration is not None:
            self.model.set_calibration(calibration)

    def _on_calibrate_clicked(self, button: Gtk.Button) -> None:
        self._held_message = None
        self.calibrate_button.set_sensitive(False)
        argv = ["pkexec", "/usr/bin/python3", str(CALIBRATE_SCRIPT)]
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        )
        try:
            process = launcher.spawnv(argv)
        except GLib.Error as error:
            self._on_calibrate_failed(f"較正の起動に失敗しました: {error.message}")
            return
        self._calibrate_process = process
        self._refresh_status()
        process.communicate_utf8_async(None, None, self._on_calibrate_done)

    def _on_calibrate_done(self, process: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        self._calibrate_process = None
        try:
            _success, stdout_text, stderr_text = process.communicate_utf8_finish(result)
        except GLib.Error as error:
            self._on_calibrate_failed(f"較正の実行中にエラーが起きました: {error.message}")
            return

        exit_status = process.get_exit_status()
        if exit_status == 126:
            self._on_calibrate_failed("較正をキャンセルしたか、認証に失敗しました")
            return
        if exit_status == 127:
            self._on_calibrate_failed(f"較正スクリプトが見つかりません: {CALIBRATE_SCRIPT}")
            return
        if exit_status != 0:
            stderr_lines = (stderr_text or "").strip().splitlines()
            reason = stderr_lines[-1] if stderr_lines else ""
            suffix = f": {reason}" if reason else ""
            self._on_calibrate_failed(f"較正に失敗しました（終了コード {exit_status}）{suffix}")
            return

        try:
            data = json.loads(stdout_text)
        except (TypeError, ValueError):
            self._on_calibrate_failed("較正結果の JSON が壊れています")
            return
        calibration, reason = model.validate_calibration(data)
        if calibration is None:
            self._on_calibrate_failed(f"較正結果が不正です: {reason}")
            return

        try:
            self._save_calibration(data)
        except OSError as error:
            self._on_calibrate_failed(f"較正結果の保存に失敗しました: {error}")
            return

        self.model.set_calibration(calibration)
        self.calibrate_button.set_sensitive(True)
        self._hold_message("較正が完了しました", CALIBRATE_DONE_DISPLAY_SEC)
        self._refresh_view()

    def _on_calibrate_failed(self, reason: str) -> None:
        self.calibrate_button.set_sensitive(True)
        self._hold_message(reason, FAILURE_DISPLAY_SEC)

    def _save_calibration(self, data: dict) -> None:
        """一時ファイル→rename で保存する（書き込み途中の壊れた JSON を読まないため）。"""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = STATE_DIR / "calibration.json.tmp"
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.rename(CALIBRATION_FILE)

    def _handle_alert(self, event: AlertEvent) -> None:
        if not event.entered:
            return
        if event.target == "CPU":
            summary = "CPU 温度が超過しました"
            body = f"{event.value:.1f} C > {event.threshold:.0f} C"
        else:
            summary = f"GPU {event.target} 温度が超過しました"
            body = f"{event.value:.0f} C > {event.threshold:.0f} C"
        notify_critical(summary, body)


class GpuWatchApplication(Gtk.Application):
    def __init__(self, args: argparse.Namespace):
        super().__init__(application_id=args.app_id)
        self.args = args
        self.window: Optional[GpuWatchWindow] = None

    def do_activate(self) -> None:  # noqa: N802 (GObject の仮想メソッド名)
        if self.window is None:
            self.window = GpuWatchWindow(self, self.args)
            # SIGTERM/SIGINT（systemd や timeout コマンドからの終了要求）でも
            # ウィンドウを閉じた時と同じく子プロセスを止めてから終了する。
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_term_signal)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_term_signal)
        self.window.present()

    def _on_term_signal(self) -> bool:
        if self.window is not None:
            self.window._stop_feeder()
        self.quit()
        return GLib.SOURCE_REMOVE


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    if not GPU_WATCH_SH.exists():
        print(f"gpu-watch-gui: gpu-watch.sh が見つかりません: {GPU_WATCH_SH}")
        return 1
    application = GpuWatchApplication(args)
    return application.run([])


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
