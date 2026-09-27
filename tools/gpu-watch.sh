#!/usr/bin/env bash
# gpu-watch.sh - GPU と CPU / メモリを一定間隔で読み、現在値・最大値・移動平均を表示する。
# 温度がしきい値を超えたらアラートを出す。
#
# 取得元（すべて実測。取れない値は n/a と出し、推測で埋めない）
#   GPU        nvidia-smi
#   CPU 使用率  /proc/stat の差分
#   CPU 温度    coretemp の "Package id 0"（無ければ thermal_zone の x86_pkg_temp）
#   メモリ      /proc/meminfo（used = MemTotal - MemAvailable）
#   CPU 電力    Intel RAPL package-0 の energy_uj 差分
#   PSys 電力   Intel RAPL psys の energy_uj 差分（SoC プラットフォーム。dGPU は含まない）
#   ファン PWM  a30-fan.service の journal に出る最新の "fan PWM N%" 行
#
# ファン PWM は fan_host.py が Pico H に送った指令値で、回転数の実測ではない（TACH 未接続）。
# fan_host.py はシリアルポートを排他で開くため、Pico に直接は問い合わせない。
# journal を読むには adm か systemd-journal グループが要る。
# 最新の PWM 行が 10 秒より古ければ n/a にする。Pico は指令が 10 秒途絶えると
# 自分で 100% に戻すので、それより古い行は現在値の根拠にならない。
#
# RAPL は既定で root しか読めない（PLATYPUS 対策 CVE-2020-8694）。
# 読めるようにするには root で次を 1 度だけ実行する:
#   echo 'SUBSYSTEM=="powercap", ACTION=="add", RUN+="/bin/chmod -R g=u,o=u /sys%p"' \
#     > /etc/udev/rules.d/99-powercap.rules
#   udevadm control --reload && udevadm trigger --subsystem-match=powercap
# これは電力の副チャネル攻撃の緩和を外す変更なので、必要性を判断してから適用すること。
# 適用しない場合、CPU 電力は n/a のままで他の表示は問題なく動く。
#
# 「PC 全体の電力」を測るセンサーはこの筐体には無い（IPMI も UPS も無い）。
# 実測できるのは CPU + GPU の合計まで。筐体全体を知るにはスマートプラグか UPS が要る。
# -P に実測したベースライン（基板・RAM・ドライブ・ファン・電源損失の合計、W）を渡すと、
# CPU + GPU + ベースライン を「推定」として表示する。-P を渡さなければ推定は出さない。
set -euo pipefail

interval=1        # サンプリング間隔（秒）
window=60         # 平均・窓内最大の対象期間（秒）
threshold=80      # GPU 温度アラートのしきい値（摂氏）
cpu_threshold=90  # CPU 温度アラートのしきい値（摂氏）
gpu_index=""      # nvidia-smi -i に渡す GPU 指定。空なら全 GPU
log_file=""       # アラートの追記先
bell_mode="edge"  # edge | always | off
color_mode="auto" # auto | always | never
baseline_watt=""  # -P。筐体ベースライン（W）。指定時だけ全体推定を出す
fan_unit="a30-fan.service" # -F。ファン PWM を読む systemd ユニット。off で無効
fan_stale=10      # この秒数より古い PWM ログは n/a にする（Pico の指令途絶タイムアウト）

usage() {
  cat <<'USAGE_EOF'
使い方: gpu-watch.sh [オプション]

  -n SEC    サンプリング間隔（秒）。既定 1
  -w SEC    平均と窓内最大の対象期間（秒）。既定 60
  -t DEG    GPU 温度アラートのしきい値（摂氏）。既定 80
  -T DEG    CPU 温度アラートのしきい値（摂氏）。既定 90
  -i IDX    監視する GPU。nvidia-smi -i と同じ書式（例 0 または 0,1）。既定は全 GPU
  -l FILE   アラート発生をこのファイルに追記する
  -b MODE   ベル（端末の警告音）。edge=超過に入った時だけ / always=超過中は毎回 / off=鳴らさない。既定 edge
  -c MODE   色。auto / always / never。既定 auto
  -P WATT   筐体ベースライン（W）。CPU + GPU にこれを足した値を「全体(推定)」として出す。
            省略すると推定は出さない（推測値で埋めないため）。
            値はスマートプラグ等で実測して決めること。
  -F UNIT   ファン PWM を読む systemd ユニット。既定 a30-fan.service。off で表示しない
  -h        このヘルプ

表示する値
  HOST  CPU 使用率 / CPU 温度 / メモリ使用率 / CPU 電力 / PSys 電力
  GPU   温度 / 使用率 / VRAM / 電力
  FAN   Pico H への PWM 指令値（%）と制御モード。回転数の実測ではない
  Power CPU + GPU の実測合計。-P 指定時はそれにベースラインを足した推定も出す。

CPU 電力が n/a のとき
  Intel RAPL の energy_uj が root 専用になっている（既定の挙動）。
  スクリプト冒頭のコメントに、読めるようにする udev ルールを書いてある。
  この緩和を外すかは利用者が判断すること。

ファン PWM が n/a のとき
  journal に PWM 行が無い: サービス停止中か、journal を読む権限（adm グループ）が無い。
  最新ログが古い: fan_host.py が USB エラーなどで指令を出せていない。
    journalctl -u a30-fan.service -n 30 で原因を見る。

Ctrl-C で終了する。終了時に全期間のサマリーを表示する。
USAGE_EOF
}

while getopts 'n:w:t:T:i:l:b:c:P:F:h' opt; do
  case "$opt" in
    n) interval=$OPTARG ;;
    w) window=$OPTARG ;;
    t) threshold=$OPTARG ;;
    T) cpu_threshold=$OPTARG ;;
    i) gpu_index=$OPTARG ;;
    l) log_file=$OPTARG ;;
    b) bell_mode=$OPTARG ;;
    c) color_mode=$OPTARG ;;
    P) baseline_watt=$OPTARG ;;
    F) fan_unit=$OPTARG ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

case "$interval" in ''|*[!0-9]*) echo "gpu-watch: -n は 1 以上の整数で指定する: $interval" >&2; exit 2 ;; esac
case "$window"   in ''|*[!0-9]*) echo "gpu-watch: -w は 1 以上の整数で指定する: $window" >&2; exit 2 ;; esac
case "$threshold" in ''|*[!0-9]*) echo "gpu-watch: -t は整数で指定する: $threshold" >&2; exit 2 ;; esac
case "$cpu_threshold" in ''|*[!0-9]*) echo "gpu-watch: -T は整数で指定する: $cpu_threshold" >&2; exit 2 ;; esac
[ "$interval" -ge 1 ] || { echo "gpu-watch: -n は 1 以上で指定する" >&2; exit 2; }
[ "$window" -ge 1 ]   || { echo "gpu-watch: -w は 1 以上で指定する" >&2; exit 2; }
case "$bell_mode" in edge|always|off) ;; *) echo "gpu-watch: -b は edge / always / off のいずれか: $bell_mode" >&2; exit 2 ;; esac
case "$color_mode" in auto|always|never) ;; *) echo "gpu-watch: -c は auto / always / never のいずれか: $color_mode" >&2; exit 2 ;; esac
if [ -n "$baseline_watt" ]; then
  case "$baseline_watt" in
    ''|*[!0-9.]*) echo "gpu-watch: -P は 0 以上の数値で指定する: $baseline_watt" >&2; exit 2 ;;
  esac
fi

case "$fan_unit" in
  off) fan_unit="" ;;
  *[!A-Za-z0-9@._:-]*) echo "gpu-watch: -F はユニット名か off で指定する: $fan_unit" >&2; exit 2 ;;
esac

command -v nvidia-smi >/dev/null 2>&1 || { echo "gpu-watch: nvidia-smi が見つからない" >&2; exit 1; }
if [ -n "$fan_unit" ] && ! command -v journalctl >/dev/null 2>&1; then
  echo "gpu-watch: journalctl が無いのでファン PWM は表示しない" >&2
  fan_unit=""
fi

# 窓に入るサンプル数（切り上げ、最低 1）
slots=$(( (window + interval - 1) / interval ))
[ "$slots" -ge 1 ] || slots=1

is_tty=0
if [ -t 1 ]; then is_tty=1; fi

use_color=0
if [ "$color_mode" = always ]; then
  use_color=1
elif [ "$color_mode" = auto ] && [ "$is_tty" -eq 1 ]; then
  use_color=1
fi

count_args=(--query-gpu=index --format=csv,noheader)
if [ -n "$gpu_index" ]; then count_args+=(-i "$gpu_index"); fi
gpu_count=$(nvidia-smi "${count_args[@]}" | grep -c .)
[ "$gpu_count" -ge 1 ] || { echo "gpu-watch: 対象の GPU が見つからない" >&2; exit 1; }

# ---- ホスト側センサーの所在を 1 度だけ解決する --------------------------
# coretemp の "Package id 0" を探す。無ければ x86_pkg_temp の thermal_zone。
cpu_temp_path=""
for hwmon in /sys/class/hwmon/hwmon*; do
  [ -r "$hwmon/name" ] || continue
  [ "$(cat "$hwmon/name" 2>/dev/null)" = "coretemp" ] || continue
  for label in "$hwmon"/temp*_label; do
    [ -r "$label" ] || continue
    case "$(cat "$label" 2>/dev/null)" in
      "Package id"*) cpu_temp_path="${label%_label}_input"; break ;;
    esac
  done
  [ -n "$cpu_temp_path" ] && break
done
if [ -z "$cpu_temp_path" ]; then
  for zone in /sys/class/thermal/thermal_zone*; do
    [ -r "$zone/type" ] || continue
    if [ "$(cat "$zone/type" 2>/dev/null)" = "x86_pkg_temp" ]; then
      cpu_temp_path="$zone/temp"; break
    fi
  done
fi
[ -n "$cpu_temp_path" ] && [ -r "$cpu_temp_path" ] || cpu_temp_path=""

# RAPL のドメインを名前で引く。読めなければ空にする（root 専用が既定のため）。
# 探索先を差し替えられるのは、RAPL が読めない機械でもこの経路を試験できるようにするため
# （偽の energy_uj を置いたディレクトリを指す）。通常は指定しない。
powercap_root=${GPU_WATCH_POWERCAP_ROOT:-/sys/class/powercap}
find_rapl() {
  local want=$1 dir
  for dir in "$powercap_root"/intel-rapl:*; do
    [ -r "$dir/name" ] || continue
    [ "$(cat "$dir/name" 2>/dev/null)" = "$want" ] || continue
    [ -r "$dir/energy_uj" ] || continue
    printf '%s\n' "$dir"
    return 0
  done
  return 1
}
rapl_pkg=$(find_rapl "package-0" || true)
rapl_psys=$(find_rapl "psys" || true)

rapl_pkg_max=0
rapl_psys_max=0
[ -n "$rapl_pkg" ]  && rapl_pkg_max=$(cat "$rapl_pkg/max_energy_range_uj" 2>/dev/null || echo 0)
[ -n "$rapl_psys" ] && rapl_psys_max=$(cat "$rapl_psys/max_energy_range_uj" 2>/dev/null || echo 0)

# RAPL が読めない理由をヘッダに 1 行出すための状態
rapl_note=""
if [ -z "$rapl_pkg" ]; then
  if [ -e "$powercap_root/intel-rapl:0/energy_uj" ]; then
    rapl_note="CPU 電力: RAPL はあるが読めない（root 専用）。-h の udev ルール参照"
  else
    rapl_note="CPU 電力: この機械に Intel RAPL が無い"
  fi
fi

cpu_model=$(awk -F': ' '/^model name/ {print $2; exit}' /proc/cpuinfo 2>/dev/null || true)
# "12th Gen Intel(R) Core(TM) i7-12700" は長いので商標表記を落として詰める
cpu_model=$(printf '%s' "$cpu_model" | sed -e 's/(R)//g' -e 's/(TM)//g' -e 's/  */ /g' -e 's/^ //' -e 's/ $//')
[ -n "$cpu_model" ] || cpu_model="CPU"
cpu_threads=$(nproc 2>/dev/null || echo 0)

# ---- フィーダー: 1 周期ごとに HOST 行 + GPU 行を出す --------------------
# nvidia-smi -l をやめて自前ループにしたのは、ホスト側の値と GPU の値を
# 同じ刻みで揃えるため。CPU 使用率と RAPL はどちらも前回との差分が要る。
gpu_query='index,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw'

feeder() {
  local prev_total=0 prev_idle=0 have_prev=0
  local prev_pkg=0 prev_psys=0 prev_time=0 have_energy=0
  local first=1

  while :; do
    local now_time
    now_time=${EPOCHREALTIME:-$(date +%s.%N)}
    now_time=${now_time/,/.}   # ロケールによっては小数点がカンマになる

    # --- CPU 使用率 ---
    local cpu_pct="na" line fields total idle
    line=$(head -1 /proc/stat 2>/dev/null || true)
    if [ -n "$line" ]; then
      # user nice system idle iowait irq softirq steal guest guest_nice
      read -r _ user nice system idle_v iowait irq softirq steal _rest <<<"$line" || true
      total=$(( ${user:-0} + ${nice:-0} + ${system:-0} + ${idle_v:-0} \
              + ${iowait:-0} + ${irq:-0} + ${softirq:-0} + ${steal:-0} ))
      idle=$(( ${idle_v:-0} + ${iowait:-0} ))
      if [ "$have_prev" -eq 1 ] && [ "$total" -gt "$prev_total" ]; then
        local d_total=$(( total - prev_total )) d_idle=$(( idle - prev_idle ))
        cpu_pct=$(awk -v dt="$d_total" -v di="$d_idle" 'BEGIN{ printf "%.1f", (dt>0)?100*(dt-di)/dt:0 }')
      fi
      prev_total=$total; prev_idle=$idle; have_prev=1
    fi

    # --- CPU 温度 ---
    local cpu_temp="na" raw
    if [ -n "$cpu_temp_path" ]; then
      raw=$(cat "$cpu_temp_path" 2>/dev/null || true)
      case "$raw" in
        ''|*[!0-9-]*) ;;
        *) cpu_temp=$(awk -v v="$raw" 'BEGIN{ printf "%.1f", v/1000 }') ;;
      esac
    fi

    # --- メモリ ---
    local mem_pct="na" mem_used_mib="na" mem_total_mib="na" mem_total_kb mem_avail_kb
    mem_total_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)
    mem_avail_kb=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)
    if [ -n "${mem_total_kb:-}" ] && [ -n "${mem_avail_kb:-}" ] && [ "$mem_total_kb" -gt 0 ]; then
      mem_used_mib=$(awk -v t="$mem_total_kb" -v a="$mem_avail_kb" 'BEGIN{ printf "%.0f", (t-a)/1024 }')
      mem_total_mib=$(awk -v t="$mem_total_kb" 'BEGIN{ printf "%.0f", t/1024 }')
      mem_pct=$(awk -v t="$mem_total_kb" -v a="$mem_avail_kb" 'BEGIN{ printf "%.1f", 100*(t-a)/t }')
    fi

    # --- CPU / PSys 電力（エネルギー差分 ÷ 経過時間） ---
    local cpu_w="na" psys_w="na" cur_pkg=0 cur_psys=0
    [ -n "$rapl_pkg" ]  && cur_pkg=$(cat "$rapl_pkg/energy_uj" 2>/dev/null || echo 0)
    [ -n "$rapl_psys" ] && cur_psys=$(cat "$rapl_psys/energy_uj" 2>/dev/null || echo 0)
    if [ "$have_energy" -eq 1 ]; then
      local dt
      dt=$(awk -v a="$now_time" -v b="$prev_time" 'BEGIN{ printf "%.6f", a-b }')
      if awk -v d="$dt" 'BEGIN{ exit !(d > 0) }'; then
        if [ -n "$rapl_pkg" ]; then
          cpu_w=$(awk -v c="$cur_pkg" -v p="$prev_pkg" -v m="$rapl_pkg_max" -v d="$dt" \
            'BEGIN{ e=c-p; if (e<0) e+=m; printf "%.1f", e/1e6/d }')
        fi
        if [ -n "$rapl_psys" ]; then
          psys_w=$(awk -v c="$cur_psys" -v p="$prev_psys" -v m="$rapl_psys_max" -v d="$dt" \
            'BEGIN{ e=c-p; if (e<0) e+=m; printf "%.1f", e/1e6/d }')
        fi
      fi
    fi
    prev_pkg=$cur_pkg; prev_psys=$cur_psys; prev_time=$now_time; have_energy=1

    # 初回は CPU 使用率も電力も差分が取れない。刻みを揃えるため 1 周期だけ捨てる。
    if [ "$first" -eq 1 ]; then
      first=0
      sleep "$interval"
      continue
    fi

    local stamp
    stamp=$(date '+%Y/%m/%d %H:%M:%S.%3N')
    printf 'HOST, %s, %s, %s, %s, %s, %s, %s, %s\n' \
      "$stamp" "$cpu_pct" "$cpu_temp" "$mem_pct" "$mem_used_mib" "$mem_total_mib" "$cpu_w" "$psys_w"

    # --- ファン PWM（journal の最新 "fan PWM N% [MODE]" 行） ---
    # USB エラー行などが挟まっても拾えるよう、末尾数行から PWM 行だけを選ぶ。
    if [ -n "$fan_unit" ]; then
      local fan_pwm="na" fan_mode="na" fan_state="none" fan_age="na" fan_log fan_parsed
      fan_log=$(journalctl -u "$fan_unit" -n 20 -o short-unix --no-pager -q 2>/dev/null \
                  | grep -E 'fan PWM [0-9]{1,3}% \[[A-Za-z_]+\]$' | tail -1 || true)
      if [ -n "$fan_log" ]; then
        fan_parsed=$(printf '%s\n' "$fan_log" \
          | sed -n -E 's/^([0-9]+(\.[0-9]+)?) .*fan PWM ([0-9]{1,3})% \[([A-Za-z_]+)\]$/\1 \3 \4/p')
        if [ -n "$fan_parsed" ]; then
          local fan_ts
          read -r fan_ts fan_pwm fan_mode <<<"$fan_parsed"
          fan_age=$(awk -v a="$now_time" -v b="$fan_ts" 'BEGIN{ d=a-b; if (d<0) d=0; printf "%.0f", d }')
          if [ "$fan_age" -le "$fan_stale" ]; then
            fan_state="ok"
          else
            fan_state="stale"; fan_pwm="na"
          fi
        fi
      fi
      printf 'FAN, %s, %s, %s, %s, %s\n' "$stamp" "$fan_pwm" "$fan_mode" "$fan_state" "$fan_age"
    fi

    local smi_args=(--query-gpu="$gpu_query" --format=csv,noheader,nounits)
    [ -n "$gpu_index" ] && smi_args+=(-i "$gpu_index")
    nvidia-smi "${smi_args[@]}" 2>/dev/null | while IFS= read -r gpu_line; do
      [ -n "$gpu_line" ] || continue
      printf 'GPU, %s, %s\n' "$stamp" "$gpu_line"
    done

    sleep "$interval"
  done
}

# mawk は入力をブロックバッファするため、1 行ずつ処理させるオプションが要る。
# 付けないとフレームが出ず、入力が閉じるまで画面が止まる。
awk_ident=$(awk -W version 2>&1 | head -1 || true)
case "$awk_ident" in
  mawk*) awk_opts=(-W interactive) ;;
  *)     awk_opts=() ;;
esac

awk_prog=$(cat <<'AWK_EOF'
function cell(str, width, col,   padded) {
  padded = sprintf("%" width "s", str)
  if (use_color && col != "") return col padded "\033[0m"
  return padded
}
function tint(str, col) {
  if (use_color && col != "") return col str "\033[0m"
  return str
}
function out(str) { printf "%s%s\n", str, (tui ? "\033[K" : "") }
function rule(   bar, pos) {
  bar = ""
  for (pos = 0; pos < 70; pos++) bar = bar "-"
  return bar
}
function temp_color(value, limit) {
  if (value == "" || value == "na") return ""
  if (value >= limit) return "\033[1;31m"
  if (value >= limit - 10) return "\033[1;33m"
  return "\033[0;32m"
}
function load_color(value) {
  if (value >= 90) return "\033[1;31m"
  if (value >= 70) return "\033[1;33m"
  return "\033[0;32m"
}
function fnum(value) { return sprintf("%.1f", value) }
function fmt(value, prec) { return (prec > 0) ? sprintf("%.1f", value) : sprintf("%d", value) }
function isnum(value) { return (value ~ /^-?[0-9]+(\.[0-9]+)?$/) }

# 窓の集計。ok_buf が 0 のスロットは母数から外す（n/a を 0 として平均しない）。
function agg(name, idx, used,   slot, sum, num, top, key) {
  sum = 0; num = 0; top = ""
  for (slot = 0; slot < used; slot++) {
    key = name SUBSEP idx SUBSEP slot
    if (!ok_buf[key]) continue
    sum += val_buf[key]; num++
    if (top == "" || val_buf[key] > top) top = val_buf[key]
  }
  agg_n = num; agg_max = top
  return (num > 0) ? sum / num : ""
}
function push(name, idx, slot, value, valid,   key) {
  key = name SUBSEP idx SUBSEP slot
  val_buf[key] = valid ? value + 0 : 0
  ok_buf[key] = valid
}
function track(name, idx, value, valid) {
  if (!valid) return
  all_sum[name, idx] += value
  all_cnt[name, idx]++
  if (all_cnt[name, idx] == 1 || value > all_max[name, idx]) all_max[name, idx] = value
}

# 1 行分（now / max(win) / avg(win) / max(all)）を組み立てる
function metric_row(label, name, idx, used, unit, colfn, limit, prec,
                    row, avg, cur, valid) {
  cur = cur_val[name, idx]; valid = cur_ok[name, idx]
  avg = agg(name, idx, used)
  row = sprintf("  %-7s ", label)
  if (!valid && agg_n == 0) {
    row = row cell("n/a", 9, "") " " cell("n/a", 11, "") " " cell("n/a", 11, "") " " cell("n/a", 11, "")
    return row
  }
  if (valid) {
    row = row cell(sprintf("%s %s", fmt(cur, prec), unit), 9,
                   (colfn == "temp") ? temp_color(cur, limit) : ((colfn == "load") ? load_color(cur) : ""))
  } else {
    row = row cell("n/a", 9, "")
  }
  if (agg_n > 0) {
    row = row " " cell(sprintf("%s %s", fmt(agg_max, prec), unit), 11,
                       (colfn == "temp") ? temp_color(agg_max, limit) : "")
    row = row " " cell(sprintf("%s %s", fmt(avg, 1), unit), 11, "")
  } else {
    row = row " " cell("n/a", 11, "") " " cell("n/a", 11, "")
  }
  if (all_cnt[name, idx] > 0) {
    row = row " " cell(sprintf("%s %s", fmt(all_max[name, idx], prec), unit), 11,
                       (colfn == "temp") ? temp_color(all_max[name, idx], limit) : "")
  } else {
    row = row " " cell("n/a", 11, "")
  }
  return row
}

function render(   gpu_no, idx, used, span, header, row, alert_shown,
                   gpu_watt, gpu_watt_ok, combined, hcount) {
  if (tui) printf "\033[H"; else printf "\n"
  out(sprintf("host+gpu watch   interval %ds   window %ds   GPU>%d C  CPU>%d C",
              interval, window, threshold, cpu_threshold))
  out(sprintf("%s   samples %d", last_ts, cycles))
  if (rapl_note != "") out(tint("  " rapl_note, "\033[0;33m"))
  out(rule())

  # ---- HOST ----
  hcount = (count["H"] < slots) ? count["H"] : slots
  if (hcount > 0) {
    out("")
    out(sprintf("HOST %-42s window %d/%d samples (%ds)",
                substr(cpu_model, 1, 42), hcount, slots, hcount * interval))
    header = sprintf("  %-7s %9s %11s %11s %11s", "", "now", "max(win)", "avg(win)", "max(all)")
    out(header)
    out(metric_row("CPU",   "cpu",   "H", hcount, "%", "load", 0, 1))
    out(metric_row("CTemp", "ctemp", "H", hcount, "C", "temp", cpu_threshold, 1))
    row = metric_row("Mem",  "mem",   "H", hcount, "%", "load", 0, 1)
    if (cur_ok["memtot", "H"])
      row = row sprintf("  / %d MiB", cur_val["memtot", "H"])
    out(row)
    out(metric_row("CPwr",  "cpuw",  "H", hcount, "W", "", 0, 1))
    if (all_cnt["psys", "H"] > 0)
      out(metric_row("PSys",  "psys",  "H", hcount, "W", "", 0, 1))

    if (cur_ok["ctemp", "H"] && cur_val["ctemp", "H"] > cpu_threshold) {
      alert_shown = 1
      out("  " tint(sprintf("*** ALERT *** CPU が %d C を超過中: %.1f C  (累計 %d 回 / 直近 %s)",
                            cpu_threshold, cur_val["ctemp", "H"], over_total["CPU"], last_over["CPU"]),
                    "\033[1;37;41m"))
    } else if (over_total["CPU"] > 0) {
      alert_shown = 1
      out("  " tint(sprintf("警告履歴: CPU %d C 超過 %d 回  直近 %s  最高 %.1f C",
                            cpu_threshold, over_total["CPU"], last_over["CPU"], all_max["ctemp", "H"]),
                    "\033[1;33m"))
    }
  }

  # ---- GPU ----
  gpu_watt = 0; gpu_watt_ok = 1
  for (gpu_no = 0; gpu_no < gpu_count; gpu_no++) {
    idx = order_index[gpu_no]
    if (idx == "") continue
    used = (count[idx] < slots) ? count[idx] : slots
    if (used < 1) continue
    span = used * interval

    out("")
    out(sprintf("GPU %s  %-32s window %d/%d samples (%ds)",
                idx, gpu_name[idx], used, slots, span))
    header = sprintf("  %-7s %9s %11s %11s %11s", "", "now", "max(win)", "avg(win)", "max(all)")
    out(header)
    out(metric_row("Temp", "gtemp", idx, used, "C",   "temp", threshold, 0))
    out(metric_row("Util", "gutil", idx, used, "%",   "load", 0, 0))
    row = metric_row("VRAM", "gmem",  idx, used, "MiB", "", 0, 0)
    row = row sprintf("  / %d MiB", mem_total[idx])
    out(row)
    out(metric_row("Power", "gpwr",  idx, used, "W",   "", 0, 1))

    if (cur_ok["gpwr", idx]) gpu_watt += cur_val["gpwr", idx]; else gpu_watt_ok = 0

    if (over_total[idx] > 0) {
      alert_shown = 1
      if (cur_val["gtemp", idx] > threshold) {
        out("  " tint(sprintf("*** ALERT *** GPU %s が %d C を超過中: %d C  (累計 %d 回 / 直近 %s)",
                              idx, threshold, cur_val["gtemp", idx], over_total[idx], last_over[idx]),
                      "\033[1;37;41m"))
      } else {
        out("  " tint(sprintf("警告履歴: %d C 超過 %d 回  直近 %s  最高 %d C",
                              threshold, over_total[idx], last_over[idx], all_max["gtemp", idx]),
                      "\033[1;33m"))
      }
    }
  }

  # ---- ファン PWM ----
  if (fan_unit != "" && count["F"] > 0) {
    used = (count["F"] < slots) ? count["F"] : slots
    out("")
    out(sprintf("FAN %-40s window %d/%d samples (%ds)",
                substr(fan_unit, 1, 40), used, slots, used * interval))
    header = sprintf("  %-7s %9s %11s %11s %11s", "", "now", "max(win)", "avg(win)", "max(all)")
    out(header)
    row = metric_row("PWM", "fan", "F", used, "%", "", 0, 0)
    if (fan_state == "ok")         row = row "  [" fan_mode "]"
    else if (fan_state == "stale") row = row "  " tint(sprintf("最新の PWM ログが %s 秒前", fan_age), "\033[1;33m")
    else                           row = row "  " tint("journal に PWM ログが無い（停止中か権限不足）", "\033[1;33m")
    out(row)
    out("  ※Pico への指令値。TACH 未接続のため回転の実測ではない")
  }

  # ---- 電力の合計 ----
  out("")
  if (cur_ok["cpuw", "H"] && gpu_watt_ok) {
    combined = cur_val["cpuw", "H"] + gpu_watt
    out(sprintf("  %-7s %s", "CPU+GPU",
                tint(sprintf("%.1f W  (CPU %.1f + GPU %.1f)  ※実測の合計。筐体全体ではない",
                             combined, cur_val["cpuw", "H"], gpu_watt), "\033[1;36m")))
    if (baseline != "") {
      out(sprintf("  %-5s %s", "全体",
                  tint(sprintf("%.1f W  推定 = CPU+GPU %.1f + ベースライン %.1f",
                               combined + baseline, combined, baseline), "\033[0;36m")))
    } else {
      out(sprintf("  %-5s %s", "全体", "n/a  筐体全体を測るセンサーが無い。-P で実測ベースラインを渡すと推定を出す"))
    }
  } else {
    out(sprintf("  %-7s %s", "CPU+GPU", "n/a  CPU 電力が読めないため合計できない"))
    out(sprintf("  %-5s %s", "全体", "n/a"))
  }

  out(rule())
  if (!alert_shown) out(sprintf("しきい値（GPU %d C / CPU %d C）の超過なし。Ctrl-C で終了。", threshold, cpu_threshold))
  else              out("Ctrl-C で終了。")
  if (tui) printf "\033[J"
  fflush()
}

function summary_line(label, name, idx, unit,   n) {
  n = all_cnt[name, idx]
  if (n > 0) printf "  %-6s max %.1f %s   avg %.1f %s\n", label, all_max[name, idx], unit, all_sum[name, idx] / n, unit
  else       printf "  %-6s n/a\n", label
}

function summary(   gpu_no, idx, span) {
  printf "%s\n", (use_color ? "\033[0m" : "")
  print "=== サマリー（全期間） ==="
  if (count["H"] > 0) {
    printf "HOST  %s   サンプル %d 件 / 約 %d 秒\n", cpu_model, count["H"], count["H"] * interval
    summary_line("CPU",   "cpu",   "H", "%")
    summary_line("CTemp", "ctemp", "H", "C")
    summary_line("Mem",   "mem",   "H", "%")
    summary_line("CPwr",  "cpuw",  "H", "W")
    if (all_cnt["psys", "H"] > 0) summary_line("PSys", "psys", "H", "W")
    if (over_total["CPU"] > 0)
      printf "  CPU %d C 超過: %d 件  直近 %s\n", cpu_threshold, over_total["CPU"], last_over["CPU"]
    else
      printf "  CPU %d C 超過: なし\n", cpu_threshold
    if (all_cnt["cpuw", "H"] == 0 && rapl_note != "") printf "  %s\n", rapl_note
  }
  for (gpu_no = 0; gpu_no < gpu_count; gpu_no++) {
    idx = order_index[gpu_no]
    if (idx == "" || count[idx] < 1) continue
    span = count[idx] * interval
    printf "GPU %s  %s   サンプル %d 件 / 約 %d 秒\n", idx, gpu_name[idx], count[idx], span
    summary_line("Temp", "gtemp", idx, "C")
    summary_line("Util", "gutil", idx, "%")
    summary_line("VRAM", "gmem",  idx, "MiB")
    summary_line("Power", "gpwr", idx, "W")
    if (over_total[idx] > 0)
      printf "  %d C 超過: %d 件  直近 %s\n", threshold, over_total[idx], last_over[idx]
    else
      printf "  %d C 超過: なし\n", threshold
  }
  if (fan_unit != "" && count["F"] > 0) {
    printf "FAN %s   サンプル %d 件（PWM 指令値。回転の実測ではない）\n", fan_unit, count["F"]
    summary_line("PWM", "fan", "F", "%")
  }
  print "  筐体全体の電力は測っていない（センサーが無い）。"
  fflush()
}

BEGIN {
  FS = ", "
  row_in_cycle = 0
  cycles = 0
  known = 0
  if (baseline_raw != "") baseline = baseline_raw + 0; else baseline = ""
}

# HOST, stamp, cpu%, ctemp, mem%, mem_used, mem_total, cpu_w, psys_w
$1 == "HOST" && NF >= 9 {
  last_ts = $2
  slot = count["H"] % slots
  record("cpu",    "H", slot, $3)
  record("ctemp",  "H", slot, $4)
  record("mem",    "H", slot, $5)
  record("memtot", "H", slot, $7)
  record("cpuw",   "H", slot, $8)
  record("psys",   "H", slot, $9)
  cur_val["memused", "H"] = $6 + 0; cur_ok["memused", "H"] = isnum($6)
  count["H"]++

  if (cur_ok["ctemp", "H"] && cur_val["ctemp", "H"] > cpu_threshold) {
    over_total["CPU"]++
    last_over["CPU"] = $2
    if (!in_alert["CPU"]) {
      in_alert["CPU"] = 1
      if (log_file != "") {
        printf "%s CPU temp=%.1f C > %d C util=%s %% mem=%s %% power=%s\n",
               $2, cur_val["ctemp","H"], cpu_threshold, $3, $5,
               (cur_ok["cpuw","H"] ? sprintf("%.1f W", cur_val["cpuw","H"]) : "n/a") >> log_file
        fflush(log_file)
      }
      if (bell_mode == "edge") printf "\a"
    }
    if (bell_mode == "always") printf "\a"
  } else {
    in_alert["CPU"] = 0
  }
  next
}

# FAN, stamp, pwm, mode, state(ok|stale|none), age_sec
# HOST と GPU の間に来る。描画は GPU 行が揃った時点で行う。
$1 == "FAN" && NF >= 6 {
  slot = count["F"] % slots
  record("fan", "F", slot, $3)
  fan_mode = $4; fan_state = $5; fan_age = $6
  count["F"]++
  next
}

# GPU, stamp, index, name, temp, util, mem_used, mem_total, power
$1 == "GPU" && NF >= 9 {
  stamp = $2; idx = $3; name = $4
  if (!(idx in seen)) {
    seen[idx] = 1
    order_index[known] = idx
    known++
  }
  gpu_name[idx] = name
  mem_total[idx] = $8 + 0
  last_ts = stamp

  slot = count[idx] % slots
  record("gtemp", idx, slot, $5)
  record("gutil", idx, slot, $6)
  record("gmem",  idx, slot, $7)
  record("gpwr",  idx, slot, $9)
  count[idx]++

  if (cur_ok["gtemp", idx] && cur_val["gtemp", idx] > threshold) {
    over_total[idx]++
    last_over[idx] = stamp
    if (!in_alert[idx]) {
      in_alert[idx] = 1
      if (log_file != "") {
        printf "%s GPU %s temp=%d C > %d C util=%s %% mem=%s MiB power=%s\n",
               stamp, idx, cur_val["gtemp", idx], threshold, $6, $7,
               (cur_ok["gpwr", idx] ? sprintf("%.1f W", cur_val["gpwr", idx]) : "n/a") >> log_file
        fflush(log_file)
      }
      if (bell_mode == "edge") printf "\a"
    }
    if (bell_mode == "always") printf "\a"
  } else {
    in_alert[idx] = 0
  }

  row_in_cycle++
  if (row_in_cycle >= gpu_count) {
    row_in_cycle = 0
    cycles++
    render()
  }
  next
}

function record(name, idx, slot, raw,   valid) {
  valid = isnum(raw)
  push(name, idx, slot, raw, valid)
  cur_val[name, idx] = valid ? raw + 0 : ""
  cur_ok[name, idx] = valid
  track(name, idx, raw + 0, valid)
}

END {
  if (cycles > 0 || row_in_cycle > 0 || count["H"] > 0) summary()
}
AWK_EOF
)

cleanup() {
  if [ -n "${feeder_pid:-}" ]; then
    kill "$feeder_pid" 2>/dev/null || true
  fi
  if [ "$is_tty" -eq 1 ]; then
    printf '\033[?25h'
  fi
  if [ "$use_color" -eq 1 ]; then
    printf '\033[0m'
  fi
}
trap cleanup EXIT

if [ "$is_tty" -eq 1 ]; then printf '\033[?25l\033[2J'; fi

exec 3< <(feeder)
feeder_pid=$!

# Ctrl-C はフィーダー側だけに効かせる。awk は入力が閉じてから END でサマリーを出す。
trap '' INT
trap 'kill "$feeder_pid" 2>/dev/null || true' TERM HUP

awk ${awk_opts[@]+"${awk_opts[@]}"} \
    -v interval="$interval" -v window="$window" -v slots="$slots" \
    -v threshold="$threshold" -v cpu_threshold="$cpu_threshold" \
    -v gpu_count="$gpu_count" \
    -v use_color="$use_color" -v tui="$is_tty" \
    -v bell_mode="$bell_mode" -v log_file="$log_file" \
    -v cpu_model="$cpu_model ($cpu_threads threads)" \
    -v rapl_note="$rapl_note" -v baseline_raw="$baseline_watt" \
    -v fan_unit="$fan_unit" \
    "$awk_prog" <&3 &
awk_pid=$!

awk_status=0
while :; do
  if wait "$awk_pid"; then
    awk_status=0
    break
  fi
  awk_status=$?
  if [ "$awk_status" -gt 128 ] && kill -0 "$awk_pid" 2>/dev/null; then
    continue
  fi
  break
done

exec 3<&-
exit 0
