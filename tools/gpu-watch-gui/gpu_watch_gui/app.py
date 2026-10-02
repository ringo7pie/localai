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
from pathlib import Path
from typing import Dict, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402  (gi.require_version の後に import する)

from gpu_watch_gui import model
from gpu_watch_gui.model import AlertEvent, GpuWatchModel, load_level, temp_level

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
LEVEL_CSS_CLASSES = ("level-critical", "level-warning", "level-ok", "level-unknown")

CSS = b"""
.level-critical { color: #ff4d4d; font-weight: bold; }
.level-warning  { color: #e6b800; font-weight: bold; }
.level-ok       { color: #2ecc71; }
.level-unknown  { color: #888888; }
.gpu-watch-heading { font-weight: bold; margin-top: 6px; }
.gpu-watch-status { font-style: italic; }
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


def format_scalar(value: Optional[float], unit: str, precision: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{precision}f} {unit}"


def format_mem_gib(used_mib: Optional[float], total_mib: Optional[float], pct: Optional[float]) -> str:
    if used_mib is None or total_mib is None:
        return "n/a"
    used_gib = used_mib / 1024
    total_gib = total_mib / 1024
    pct_text = f"{pct:.1f}%" if pct is not None else "n/a"
    return f"{used_gib:.1f}/{total_gib:.1f} GiB ({pct_text})"


def format_vram_mib(used_mib: Optional[float], total_mib: Optional[float]) -> str:
    if used_mib is None or total_mib is None:
        return "n/a"
    return f"{used_mib:.0f}/{total_mib:.0f} MiB"


class MetricRow:
    """「項目名 / 現在値 / 60 秒最大」の 1 行。色は現在値セルに CSS クラスで付ける。"""

    def __init__(self, grid: Gtk.Grid, row: int, label_text: str):
        self.name_label = Gtk.Label(label=label_text, xalign=0)
        self.value_label = Gtk.Label(label="n/a", xalign=1)
        self.max_label = Gtk.Label(label="n/a", xalign=1)
        self.name_label.set_margin_end(8)
        self.value_label.set_margin_end(8)
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

    def set_name(self, text: str) -> None:
        """実測/推定の切り替えなど、項目名を後から変える行のためのメソッド。"""
        self.name_label.set_label(text)


class GpuWatchWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, args: argparse.Namespace):
        super().__init__(application=application, title="GPU Watch")
        self.set_default_size(360, -1)

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
        self._calibrate_done_source_id: Optional[int] = None

        self._build_ui()
        self.connect("close-request", self._on_close_request)

        self._load_calibration_at_startup()
        self._start_feeder()
        GLib.timeout_add_seconds(1, self._on_tick)

    # ---- UI 組み立て --------------------------------------------------

    def _build_ui(self) -> None:
        self.grid = Gtk.Grid(column_spacing=12, row_spacing=2)
        self.grid.set_margin_top(8)
        self.grid.set_margin_bottom(8)
        self.grid.set_margin_start(8)
        self.grid.set_margin_end(8)
        self.set_child(self.grid)

        self._next_row = 0
        self._header_row("HOST")
        self.row_cpu = self._metric_row("CPU 使用率")
        self.row_cpu_temp = self._metric_row("CPU 温度")
        self.row_mem = self._metric_row("メモリ")
        self.row_cpu_w = self._metric_row("CPU 電力(推定)")
        self.row_psys_w = self._metric_row("PSys(推定)")
        self.row_system_w = self._metric_row("PC 全体(推定)")

        if self.args.fan_unit != "off":
            self._header_row("FAN")
            self.row_fan = self._metric_row("PWM")
        else:
            self.row_fan = None

        self._header_row("較正")
        self.calibrate_button = Gtk.Button(label="電力を較正")
        self.calibrate_button.connect("clicked", self._on_calibrate_clicked)
        self.grid.attach(self.calibrate_button, 0, self._next_row, 3, 1)
        self._next_row += 1

        self._header_row("最終更新")
        self.status_label = Gtk.Label(label="起動中...", xalign=0)
        self.status_label.add_css_class("gpu-watch-status")
        self.grid.attach(self.status_label, 0, self._next_row, 3, 1)
        self._next_row += 1

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _header_row(self, text: str) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("gpu-watch-heading")
        self.grid.attach(label, 0, self._next_row, 3, 1)
        self._next_row += 1

    def _metric_row(self, label_text: str) -> MetricRow:
        row = MetricRow(self.grid, self._next_row, label_text)
        self._next_row += 1
        return row

    def _ensure_gpu_rows(self, index: str, name: str) -> Dict[str, MetricRow]:
        if index in self._gpu_rows:
            return self._gpu_rows[index]
        self._header_row(f"GPU {index}  {name}")
        rows = {
            "temp": self._metric_row("温度"),
            "util": self._metric_row("使用率"),
            "vram": self._metric_row("VRAM"),
            "power": self._metric_row("電力"),
        }
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
        self.status_label.set_label(f"停止中: {reason}（{RESTART_DELAY_SEC} 秒後に再起動）")
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

    def _refresh_status(self) -> None:
        if self._subprocess is None:
            return  # 停止中の理由表示を上書きしない
        if self.model.last_update is None:
            self.status_label.set_label("まだ値を受け取っていません")
            return
        self.status_label.set_label(f"最終更新: {self.model.host.stamp or ''}")

    def _refresh_view(self) -> None:
        host = self.model.host
        self.row_cpu.set_values(
            format_scalar(host.cpu_pct_now, "%"), format_scalar(host.cpu_pct.max(), "%"),
            load_level(host.cpu_pct_now),
        )
        self.row_cpu_temp.set_values(
            format_scalar(host.cpu_temp_now, "C"), format_scalar(host.cpu_temp.max(), "C"),
            temp_level(host.cpu_temp_now, self.model.cpu_threshold),
        )
        self.row_mem.set_values(
            format_mem_gib(host.mem_used_mib, host.mem_total_mib, host.mem_pct_now),
            format_scalar(host.mem_pct.max(), "%"),
            load_level(host.mem_pct_now),
        )
        self._refresh_power_rows(host)

        for index in self.model.gpu_order:
            gpu = self.model.gpus[index]
            rows = self._ensure_gpu_rows(index, gpu.name)
            rows["temp"].set_values(
                format_scalar(gpu.temp_now, "C", 0), format_scalar(gpu.temp.max(), "C", 0),
                temp_level(gpu.temp_now, self.model.gpu_threshold),
            )
            rows["util"].set_values(
                format_scalar(gpu.util_now, "%", 0), format_scalar(gpu.util.max(), "%", 0),
                load_level(gpu.util_now),
            )
            rows["vram"].set_values(
                format_vram_mib(gpu.mem_used_mib, gpu.mem_total_mib),
                format_vram_mib(gpu.mem_used.max(), gpu.mem_total_mib),
                "unknown",
            )
            rows["power"].set_values(
                format_scalar(gpu.power_w_now, "W"), format_scalar(gpu.power_w.max(), "W"), "unknown",
            )

        if self.row_fan is not None:
            fan = self.model.fan
            if fan.state == "ok":
                current_text = f"{format_scalar(fan.pwm_now, '%', 0)} [{fan.mode}]"
                self.row_fan.set_tooltip("")
            elif fan.state == "stale":
                current_text = "n/a"
                self.row_fan.set_tooltip(f"最新の PWM ログが {fan.age_sec} 秒前（サービスが指令を出せていない可能性）")
            else:
                current_text = "n/a"
                self.row_fan.set_tooltip("journal に PWM ログが無い（サービス停止中か権限不足）")
            self.row_fan.set_values(current_text, format_scalar(fan.pwm.max(), "%", 0), "unknown")

        self._refresh_status()

    def _power_label_for_status(self, status: str) -> str:
        if status == "cpu_mismatch":
            return "未較正（CPU が較正時と違う）"
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
            self.row_cpu_w.set_name("CPU 電力(実測)")
            self.row_cpu_w.set_values(
                format_scalar(host.cpu_w_now, "W"), format_scalar(host.cpu_w.max(), "W"), "unknown",
            )
            self.row_cpu_w.set_tooltip("")
        else:
            self.row_cpu_w.set_name("CPU 電力(推定)")
            if status == "ok":
                self.row_cpu_w.set_values(
                    format_scalar(host.cpu_w_est_now, "W"), format_scalar(host.cpu_w_est.max(), "W"), "unknown",
                )
            else:
                self.row_cpu_w.set_values(label, label, "unknown")
            self.row_cpu_w.set_tooltip(tooltip)

        if host.psys_w_now is not None:
            self.row_psys_w.set_name("PSys(実測)")
            self.row_psys_w.set_values(
                format_scalar(host.psys_w_now, "W"), format_scalar(host.psys_w.max(), "W"), "unknown",
            )
            self.row_psys_w.set_tooltip("")
        else:
            self.row_psys_w.set_name("PSys(推定)")
            if status == "ok":
                self.row_psys_w.set_values(
                    format_scalar(host.psys_w_est_now, "W"), format_scalar(host.psys_w_est.max(), "W"), "unknown",
                )
            else:
                self.row_psys_w.set_values(label, label, "unknown")
            self.row_psys_w.set_tooltip(tooltip)

        # PC 全体はこの筐体に実測センサーが無いため、較正済みでも常に「推定」表示。
        if status == "ok":
            self.row_system_w.set_values(
                format_scalar(host.system_w_est_now, "W"), format_scalar(host.system_w_est.max(), "W"), "unknown",
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
        if self._calibrate_done_source_id is not None:
            GLib.source_remove(self._calibrate_done_source_id)
            self._calibrate_done_source_id = None
        self.calibrate_button.set_sensitive(False)
        self.status_label.set_label("較正中（約 1 分）")
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
        self.status_label.set_label("較正が完了しました")
        self._refresh_view()
        self._calibrate_done_source_id = GLib.timeout_add_seconds(
            CALIBRATE_DONE_DISPLAY_SEC, self._on_calibrate_done_timeout,
        )

    def _on_calibrate_done_timeout(self) -> bool:
        self._calibrate_done_source_id = None
        self._refresh_status()
        return GLib.SOURCE_REMOVE

    def _on_calibrate_failed(self, reason: str) -> None:
        self.calibrate_button.set_sensitive(True)
        self.status_label.set_label(reason)

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
