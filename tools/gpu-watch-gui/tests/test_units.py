"""gpu_watch_gui.model の単体試験 + gpu-watch.sh の `-o` 引数検証の試験。

GTK は import しない（model.py が GTK 非依存であることの確認も兼ねる）。
実行コマンド（システムに pytest は入っていないので uv の一時環境で走らせる）:
    uvx --with pytest pytest tools/gpu-watch-gui/tests/test_units.py -q
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parent.parent
GPU_WATCH_SH = GUI_DIR.parent / "gpu-watch.sh"
CALIBRATE_SCRIPT = GUI_DIR / "calibrate-power.py"

sys.path.insert(0, str(GUI_DIR))

from gpu_watch_gui import model  # noqa: E402  (sys.path 設定の後に import する)


def _load_calibrate_power_module():
    """calibrate-power.py はハイフン入りで通常 import できないため、ファイルパスから読む。
    import するだけでは root チェック（main 内）は走らない（純関数だけ使う）。"""
    spec = importlib.util.spec_from_file_location("calibrate_power", CALIBRATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calibrate_power = _load_calibrate_power_module()


# ---------------------------------------------------------------------------
# parse_scalar / n/a の扱い
# ---------------------------------------------------------------------------

def test_parse_scalar_normal_number():
    assert model.parse_scalar("47.0") == 47.0
    assert model.parse_scalar("8") == 8.0


def test_parse_scalar_na_and_blank_return_none():
    assert model.parse_scalar("na") is None
    assert model.parse_scalar("") is None
    assert model.parse_scalar("  ") is None


def test_parse_scalar_broken_input_returns_none_without_raising():
    assert model.parse_scalar("これは壊れた値です") is None


# ---------------------------------------------------------------------------
# parse_raw_line（HOST / FAN / GPU / INFO）
# ---------------------------------------------------------------------------

def test_parse_raw_line_host():
    line = "HOST, 2026/10/02 10:00:00.000, 6.7, 47.0, 8.7, 5574, 63969, na, na"
    sample = model.parse_raw_line(line)
    assert isinstance(sample, model.HostSample)
    assert sample.cpu_pct == 6.7
    assert sample.cpu_temp == 47.0
    assert sample.mem_pct == 8.7
    assert sample.mem_used_mib == 5574
    assert sample.mem_total_mib == 63969
    # CPU 電力・PSys 電力は RAPL が読めない環境の na → n/a（None）のまま
    assert sample.cpu_w is None
    assert sample.psys_w is None


def test_parse_raw_line_fan_ok():
    line = "FAN, 2026/10/02 10:00:00.000, 39, CONTROL, ok, 1"
    sample = model.parse_raw_line(line)
    assert isinstance(sample, model.FanSample)
    assert sample.pwm == 39
    assert sample.mode == "CONTROL"
    assert sample.state == "ok"
    assert sample.age_sec == 1


def test_parse_raw_line_fan_stale_pwm_is_na():
    # gpu-watch.sh は stale のとき fan_pwm 自体を "na" にする
    line = "FAN, 2026/10/02 10:00:00.000, na, CONTROL, stale, 42"
    sample = model.parse_raw_line(line)
    assert isinstance(sample, model.FanSample)
    assert sample.pwm is None
    assert sample.state == "stale"


def test_parse_raw_line_gpu():
    line = "GPU, 2026/10/02 10:00:00.000, 0, NVIDIA A30, 35, 0, 16, 24576, 28.91"
    sample = model.parse_raw_line(line)
    assert isinstance(sample, model.GpuSample)
    assert sample.index == "0"
    assert sample.name == "NVIDIA A30"
    assert sample.temp == 35
    assert sample.util == 0
    assert sample.mem_used_mib == 16
    assert sample.mem_total_mib == 24576
    assert sample.power_w == 28.91


def test_parse_raw_line_info():
    sample = model.parse_raw_line("INFO, rapl_note=CPU 電力: RAPL はあるが読めない")
    assert isinstance(sample, model.InfoSample)
    assert sample.key == "rapl_note"
    assert sample.value == "CPU 電力: RAPL はあるが読めない"


def test_parse_raw_line_unknown_or_blank_returns_none():
    assert model.parse_raw_line("") is None
    assert model.parse_raw_line("\n") is None
    assert model.parse_raw_line("これは知らない行です") is None
    assert model.parse_raw_line("HOST, 足りない, 行") is None


# ---------------------------------------------------------------------------
# RollingWindow（窓内の最大・平均）
# ---------------------------------------------------------------------------

def test_rolling_window_max_and_avg_within_window():
    window = model.RollingWindow(window_sec=60.0)
    window.add(0.0, 10.0)
    window.add(10.0, 20.0)
    window.add(20.0, 30.0)
    assert window.max() == 30.0
    assert window.avg() == pytest.approx(20.0)
    assert len(window) == 3


def test_rolling_window_drops_samples_older_than_window():
    window = model.RollingWindow(window_sec=60.0)
    window.add(0.0, 100.0)   # 古いサンプル。61 秒後には窓の外になる
    window.add(61.0, 10.0)
    assert len(window) == 1
    assert window.max() == 10.0
    assert window.avg() == 10.0


def test_rolling_window_ignores_none_samples_as_na():
    window = model.RollingWindow(window_sec=60.0)
    window.add(0.0, None)
    window.add(1.0, None)
    assert len(window) == 0
    assert window.max() is None
    assert window.avg() is None


def test_rolling_window_empty_returns_none():
    window = model.RollingWindow(window_sec=60.0)
    assert window.max() is None
    assert window.avg() is None


# ---------------------------------------------------------------------------
# AlertTracker（edge 検出）
# ---------------------------------------------------------------------------

def test_alert_tracker_fires_once_on_entering_over_threshold():
    tracker = model.AlertTracker()
    assert tracker.update("CPU", 95.0, 90.0).entered is True
    # 超過が続いている間は再発火しない
    assert tracker.update("CPU", 96.0, 90.0) is None
    assert tracker.update("CPU", 94.0, 90.0) is None


def test_alert_tracker_fires_once_on_clearing():
    tracker = model.AlertTracker()
    tracker.update("CPU", 95.0, 90.0)
    event = tracker.update("CPU", 85.0, 90.0)
    assert event is not None
    assert event.entered is False
    # 平常が続いている間は再発火しない
    assert tracker.update("CPU", 80.0, 90.0) is None


def test_alert_tracker_can_fire_again_after_clearing():
    tracker = model.AlertTracker()
    tracker.update("CPU", 95.0, 90.0)
    tracker.update("CPU", 85.0, 90.0)
    event = tracker.update("CPU", 95.0, 90.0)
    assert event is not None
    assert event.entered is True


def test_alert_tracker_na_value_does_not_change_state():
    tracker = model.AlertTracker()
    tracker.update("CPU", 95.0, 90.0)
    assert tracker.update("CPU", None, 90.0) is None
    # na の後も「超過中」のまま。閾値以下に戻って初めて解除イベントが出る
    event = tracker.update("CPU", 85.0, 90.0)
    assert event.entered is False


def test_alert_tracker_tracks_targets_independently():
    tracker = model.AlertTracker()
    assert tracker.update("0", 85.0, 80.0).entered is True
    assert tracker.update("1", 70.0, 80.0) is None
    assert tracker.update("1", 85.0, 80.0).entered is True


# ---------------------------------------------------------------------------
# temp_level / load_level（gpu-watch.sh の temp_color・load_color と同じしきい値）
# ---------------------------------------------------------------------------

def test_temp_level_thresholds():
    assert model.temp_level(81, 80) == "critical"
    assert model.temp_level(75, 80) == "warning"
    assert model.temp_level(60, 80) == "ok"
    assert model.temp_level(None, 80) == "unknown"


def test_load_level_thresholds():
    assert model.load_level(95) == "critical"
    assert model.load_level(75) == "warning"
    assert model.load_level(10) == "ok"
    assert model.load_level(None) == "unknown"


def test_plain_level_is_gray_only_when_missing():
    # しきい値の無い項目: 値があれば普通の文字色、n/a・未較正のときだけ灰色
    assert model.plain_level(0.0) == "plain"
    assert model.plain_level(145.7) == "plain"
    assert model.plain_level(None) == "unknown"


# ---------------------------------------------------------------------------
# GpuWatchModel（統合: raw 行を順に取り込み、状態と edge 検出をまとめて確認）
# ---------------------------------------------------------------------------

def test_gpu_watch_model_feeds_host_and_updates_window():
    gpu_model = model.GpuWatchModel(gpu_threshold=80.0, cpu_threshold=90.0, window_sec=60.0)
    gpu_model.feed_line("INFO, rapl_note=CPU 電力: RAPL はあるが読めない", now=0.0)
    gpu_model.feed_line("INFO, cpu_model=Intel Core i7-12700 (20 threads)", now=0.0)
    gpu_model.feed_line(
        "HOST, 2026/10/02 10:00:00.000, 6.7, 47.0, 8.7, 5574, 63969, na, na", now=0.0
    )
    assert gpu_model.rapl_note == "CPU 電力: RAPL はあるが読めない"
    assert gpu_model.cpu_model == "Intel Core i7-12700 (20 threads)"
    assert gpu_model.host.cpu_temp.max() == 47.0
    assert gpu_model.host.cpu_w.max() is None  # n/a は母数に入らない
    assert gpu_model.host.mem_used_mib == 5574
    assert gpu_model.last_update == 0.0


def test_gpu_watch_model_gpu_alert_event_fires_once_on_entering():
    gpu_model = model.GpuWatchModel(gpu_threshold=80.0, cpu_threshold=90.0)
    normal = gpu_model.feed_line(
        "GPU, stamp, 0, NVIDIA A30, 60, 10, 100, 24576, 30.0", now=0.0
    )
    assert normal is None
    event = gpu_model.feed_line(
        "GPU, stamp, 0, NVIDIA A30, 85, 10, 100, 24576, 30.0", now=1.0
    )
    assert event is not None
    assert event.entered is True
    assert event.target == "0"
    # 超過が続く間は再発火しない
    again = gpu_model.feed_line(
        "GPU, stamp, 0, NVIDIA A30, 86, 10, 100, 24576, 30.0", now=2.0
    )
    assert again is None


def test_gpu_watch_model_tracks_multiple_gpus_independently():
    gpu_model = model.GpuWatchModel(gpu_threshold=80.0)
    gpu_model.feed_line("GPU, stamp, 0, NVIDIA A30, 85, 10, 100, 24576, 30.0", now=0.0)
    gpu_model.feed_line("GPU, stamp, 1, NVIDIA A30, 60, 10, 100, 24576, 30.0", now=0.0)
    assert set(gpu_model.gpu_order) == {"0", "1"}
    assert gpu_model.gpus["0"].temp.max() == 85
    assert gpu_model.gpus["1"].temp.max() == 60


def test_gpu_watch_model_now_fields_reflect_latest_sample_including_na():
    gpu_model = model.GpuWatchModel()
    gpu_model.feed_line(
        "HOST, stamp, 6.7, 47.0, 8.7, 5574, 63969, na, na", now=0.0
    )
    assert gpu_model.host.cpu_temp_now == 47.0
    assert gpu_model.host.cpu_w_now is None  # n/a はそのまま None（0 などで埋めない）
    gpu_model.feed_line("GPU, stamp, 0, NVIDIA A30, 60, 10, 100, 24576, 30.0", now=0.0)
    assert gpu_model.gpus["0"].temp_now == 60
    gpu_model.feed_line("FAN, stamp, na, CONTROL, stale, 42", now=0.0)
    assert gpu_model.fan.pwm_now is None
    assert gpu_model.fan.state == "stale"


def test_gpu_watch_model_unparseable_line_is_ignored():
    gpu_model = model.GpuWatchModel()
    assert gpu_model.feed_line("これは知らない行です", now=0.0) is None
    assert gpu_model.last_update is None


# ---------------------------------------------------------------------------
# gpu-watch.sh の -o 引数検証（実際の bash を起動して確認する）
# ---------------------------------------------------------------------------

def test_gpu_watch_sh_rejects_invalid_output_mode():
    result = subprocess.run(
        [str(GPU_WATCH_SH), "-o", "xxx"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "-o" in result.stderr


def _read_raw_lines(extra_args, max_lines, deadline_sec):
    """gpu-watch.sh -o raw を起動し、行が揃うか deadline_sec 秒経つまで読む。

    -o raw は常駐ループのため、起動したプロセスは明示的に止める（残さない）。
    """
    process = subprocess.Popen(
        [str(GPU_WATCH_SH), "-o", "raw", *extra_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    lines = []
    deadline = time.monotonic() + deadline_sec
    try:
        while len(lines) < max_lines and time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip("\n"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return lines


@pytest.mark.skipif(not GPU_WATCH_SH.exists(), reason="gpu-watch.sh が見つからない")
def test_gpu_watch_sh_raw_mode_outputs_info_host_fan_gpu_lines():
    lines = _read_raw_lines(["-n", "1"], max_lines=6, deadline_sec=8.0)
    kinds = [line.split(",", 1)[0] for line in lines]
    assert "INFO" in kinds
    assert "HOST" in kinds
    assert "GPU" in kinds


# ---------------------------------------------------------------------------
# interpolate（区間線形補間。範囲内・範囲外・n/a 点の除外）
# ---------------------------------------------------------------------------

def test_interpolate_within_range():
    points = [(0.0, 10.0), (50.0, 30.0), (100.0, 60.0)]
    assert model.interpolate(points, 25.0) == pytest.approx(20.0)


def test_interpolate_out_of_range_clamps_to_edges():
    points = [(0.0, 10.0), (100.0, 60.0)]
    assert model.interpolate(points, -10.0) == 10.0
    assert model.interpolate(points, 150.0) == 60.0


def test_interpolate_empty_points_returns_none():
    assert model.interpolate([], 50.0) is None


def test_interpolate_skips_none_values():
    # util=50 の点が n/a（None）でも、残りの点だけで補間する
    points = [(0.0, 10.0), (50.0, None), (100.0, 60.0)]
    assert model.interpolate(points, 50.0) == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# 較正データの検証（calibrate-power.py の JSON を validate_calibration で検証）
# ---------------------------------------------------------------------------

def _valid_calibration_data():
    return {
        "version": 1,
        "calibrated_at": "2026-10-02T10:00:00+09:00",
        "cpu_model": "12th Gen Intel(R) Core(TM) i7-12700",
        "threads": 20,
        "points": [
            {"util": 0.0, "cpu_w": 10.0, "psys_w": 15.0},
            {"util": 100.0, "cpu_w": 90.0, "psys_w": 100.0},
        ],
        "pl1_w": 65.0,
        "pl1_window_s": 27.98,
    }


def test_validate_calibration_accepts_valid_json():
    calibration, reason = model.validate_calibration(_valid_calibration_data())
    assert calibration is not None
    assert reason == ""
    assert calibration.threads == 20
    assert calibration.pl1_w == 65.0


def test_validate_calibration_rejects_non_dict():
    calibration, reason = model.validate_calibration(["not", "a", "dict"])
    assert calibration is None
    assert reason


def test_validate_calibration_rejects_missing_points():
    calibration, reason = model.validate_calibration({"version": 1, "cpu_model": "x", "threads": 1})
    assert calibration is None
    assert reason


def test_validate_calibration_rejects_broken_point():
    data = _valid_calibration_data()
    data["points"] = [{"util": "これは数値ではない", "cpu_w": 1.0, "psys_w": None}]
    calibration, reason = model.validate_calibration(data)
    assert calibration is None
    assert reason


def test_validate_calibration_rejects_unsupported_version():
    data = _valid_calibration_data()
    data["version"] = 2
    calibration, reason = model.validate_calibration(data)
    assert calibration is None
    assert reason


def test_calibration_matches_cpu_normalizes_trademark_marks_and_thread_suffix():
    calibration, _reason = model.validate_calibration(_valid_calibration_data())
    # gpu-watch.sh 側は (R)/(TM) を落とし "(N threads)" を付けた表記で INFO に出す
    current = "12th Gen Intel Core i7-12700 (20 threads)"
    assert model.calibration_matches_cpu(calibration, current) is True


def test_calibration_matches_cpu_mismatch_when_cpu_differs():
    calibration, _reason = model.validate_calibration(_valid_calibration_data())
    current = "13th Gen Intel Core i9-13900 (32 threads)"
    assert model.calibration_matches_cpu(calibration, current) is False


def test_calibration_status_missing_ok_mismatch():
    calibration, _reason = model.validate_calibration(_valid_calibration_data())
    assert model.calibration_status(None, "12th Gen Intel Core i7-12700 (20 threads)") == "missing"
    assert model.calibration_status(calibration, "12th Gen Intel Core i7-12700 (20 threads)") == "ok"
    assert model.calibration_status(calibration, "13th Gen Intel Core i9-13900 (32 threads)") == "cpu_mismatch"


# ---------------------------------------------------------------------------
# PowerEstimator（PL1 頭打ち・PSys の差し引き）
# ---------------------------------------------------------------------------

def _sample_calibration(pl1_w=65.0, pl1_window_s=10.0):
    calibration, _reason = model.validate_calibration({
        "version": 1,
        "calibrated_at": "2026-10-02T10:00:00+09:00",
        "cpu_model": "Intel Core i7-12700",
        "threads": 20,
        "points": [
            {"util": 0.0, "cpu_w": 10.0, "psys_w": 15.0},
            {"util": 100.0, "cpu_w": 90.0, "psys_w": 100.0},
        ],
        "pl1_w": pl1_w,
        "pl1_window_s": pl1_window_s,
    })
    assert calibration is not None
    return calibration


def test_power_estimator_short_burst_can_exceed_pl1():
    estimator = model.PowerEstimator(_sample_calibration(), sample_interval_sec=1.0)
    clamped, raw = estimator.estimate_cpu_w(100.0)
    assert raw == pytest.approx(90.0)
    # 直後（EMA がまだ立ち上がっていない）は PL1(65W) を超えてよい
    assert clamped == pytest.approx(90.0)


def test_power_estimator_sustained_load_converges_to_pl1():
    estimator = model.PowerEstimator(_sample_calibration(), sample_interval_sec=1.0)
    clamped = None
    for _ in range(120):  # 時定数 10 秒の 12 倍回す。十分収束する
        clamped, _raw = estimator.estimate_cpu_w(100.0)
    assert clamped == pytest.approx(65.0)


def test_power_estimator_without_pl1_never_clamps():
    estimator = model.PowerEstimator(_sample_calibration(pl1_w=None, pl1_window_s=None), sample_interval_sec=1.0)
    clamped, raw = estimator.estimate_cpu_w(100.0)
    assert clamped == raw == pytest.approx(90.0)


def test_power_estimator_psys_subtracts_pl1_clamp_reduction():
    estimator = model.PowerEstimator(_sample_calibration(), sample_interval_sec=1.0)
    cpu_clamped = cpu_raw = None
    for _ in range(120):
        cpu_clamped, cpu_raw = estimator.estimate_cpu_w(100.0)
    reduction = cpu_raw - cpu_clamped
    assert reduction > 0  # 100% 負荷が続けば PL1 で抑えられているはず
    psys = estimator.estimate_psys_w(100.0, cpu_clamped, cpu_raw)
    raw_psys_at_100 = 100.0  # 較正点そのもの（util=100 での psys_w）
    assert psys == pytest.approx(raw_psys_at_100 - reduction)


def test_power_estimator_psys_without_cpu_clamp_uses_raw_interpolation():
    estimator = model.PowerEstimator(_sample_calibration(), sample_interval_sec=1.0)
    assert estimator.estimate_psys_w(50.0, None, None) == pytest.approx(57.5)


# ---------------------------------------------------------------------------
# estimate_system_w（PC 全体(推定) = (PSys推定 + GPU実測の合計) ÷ PSU効率）
# ---------------------------------------------------------------------------

def test_estimate_system_w_formula():
    assert model.estimate_system_w(50.0, 30.0, psu_efficiency=0.9) == pytest.approx((50.0 + 30.0) / 0.9)


def test_estimate_system_w_gpu_na_returns_none():
    assert model.estimate_system_w(50.0, None, psu_efficiency=0.9) is None


def test_estimate_system_w_psys_na_returns_none():
    assert model.estimate_system_w(None, 30.0, psu_efficiency=0.9) is None


# ---------------------------------------------------------------------------
# GpuWatchModel と較正の統合（HOST 行から CPU/PSys/PC 全体の推定が出る）
# ---------------------------------------------------------------------------

def test_gpu_watch_model_applies_calibration_to_host_feed():
    gpu_model = model.GpuWatchModel(window_sec=60.0, interval_sec=1.0, psu_efficiency=0.9)
    gpu_model.feed_line("INFO, cpu_model=Intel Core i7-12700 (20 threads)", now=0.0)
    gpu_model.set_calibration(_sample_calibration(pl1_w=None, pl1_window_s=None))
    gpu_model.feed_line("GPU, stamp, 0, NVIDIA A30, 40, 10, 100, 24576, 30.0", now=0.0)
    gpu_model.feed_line(
        "HOST, stamp, 50.0, 47.0, 8.7, 5574, 63969, na, na", now=1.0
    )
    assert gpu_model.host.cpu_w_est_now == pytest.approx(50.0)
    assert gpu_model.host.psys_w_est_now == pytest.approx(57.5)
    assert gpu_model.host.system_w_est_now == pytest.approx((57.5 + 30.0) / 0.9)
    assert gpu_model.calibration_status() == "ok"


def test_gpu_watch_model_without_calibration_estimate_is_none():
    gpu_model = model.GpuWatchModel()
    gpu_model.feed_line("HOST, stamp, 50.0, 47.0, 8.7, 5574, 63969, na, na", now=0.0)
    assert gpu_model.host.cpu_w_est_now is None
    assert gpu_model.host.psys_w_est_now is None
    assert gpu_model.host.system_w_est_now is None
    assert gpu_model.calibration_status() == "missing"


# ---------------------------------------------------------------------------
# calibrate-power.py の純関数（root 不要の部分のみ）
# ---------------------------------------------------------------------------

def test_calibrate_power_stage_thread_counts_for_20_threads():
    assert calibrate_power.stage_thread_counts(20) == [0, 5, 10, 15, 20]


def test_calibrate_power_stage_thread_counts_rounds():
    # 25%/50%/75% が割り切れない場合は Python の round()（偶数への丸め）
    assert calibrate_power.stage_thread_counts(6) == [0, 2, 3, 4, 6]


def test_calibrate_power_stage_thread_counts_zero_threads():
    assert calibrate_power.stage_thread_counts(0) == [0]


def test_calibrate_power_energy_diff_uj_normal():
    assert calibrate_power.energy_diff_uj(100, 300, 1000) == 200


def test_calibrate_power_energy_diff_uj_wraps_around_max_range():
    # cur < prev はカウンタが max_energy_range_uj を一周して 0 に巻き戻ったとみなす
    assert calibrate_power.energy_diff_uj(900, 100, 1000) == 200


def test_calibrate_power_cpu_percent_from_stat_diff():
    # user+nice+system が 30 増え、idle+iowait が 70 増えた（合計 100 増加）→ 使用率 30%
    assert calibrate_power.cpu_percent_from_stat_diff((0, 0), (100, 70)) == pytest.approx(30.0)


def test_calibrate_power_cpu_percent_from_stat_diff_no_progress_returns_none():
    assert calibrate_power.cpu_percent_from_stat_diff((100, 50), (100, 50)) is None


def test_calibrate_power_requires_root():
    # root 権限が無ければ終了コード 2 で日本語のエラーを出す（sudo/pkexec はここからは呼ばない）
    result = subprocess.run(
        [sys.executable, str(CALIBRATE_SCRIPT)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "root" in result.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
