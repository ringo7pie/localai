# gpu-watch-gui

`tools/gpu-watch.sh`（端末の TUI）を小さな GTK4 の常駐ウィンドウにしたもの。グラフは出さない。
数値だけを「項目名 / 現在値 / 60 秒最大」の並びで表示する。

センサーの読み取りはこのツールでは行わない。`gpu-watch.sh -o raw` を子プロセスとして起動し、
その出力（`INFO` / `HOST` / `FAN` / `GPU` 行）を読んで表示するだけ。取得元（RAPL・coretemp・
fan journal の所在解決）は gpu-watch.sh に 1 本化してある。「取れない値は n/a、推測で埋めない」
という扱いも gpu-watch.sh と同じ。

## 依存

portal と同じく **依存ゼロ・venv なし**。システムの `/usr/bin/python3` + `python3-gi`（GTK 4.0）を
そのまま使う。`model.py`（raw 行の解析・窓内の最大/平均・しきい値超過の edge 検出）は GTK を
import しない純 Python。GTK を import するのは `app.py` だけ。

## 起動

```bash
tools/gpu-watch-gui/run-gpu-watch-gui
```

`-n`・`-w`・`-t`・`-T`・`-i`・`-F`・`-P` を受け付ける。意味と既定値は `gpu-watch.sh -h` と同じで、
そのまま子プロセスに渡す。

```
-n SEC   サンプリング間隔（秒）。既定 1
-w SEC   窓内最大の対象期間（秒）。既定 60
-t DEG   GPU 温度アラートのしきい値（摂氏）。既定 80
-T DEG   CPU 温度アラートのしきい値（摂氏）。既定 90
-i IDX   監視する GPU。nvidia-smi -i と同じ書式。既定は全 GPU
-F UNIT  ファン PWM を読む systemd ユニット。既定 a30-fan.service。off で非表示
-P WATT  筐体ベースライン（W）。省略すると推定は出さない
--psu-efficiency RATIO  PC 全体(推定)で使う電源ユニット効率（0 より大きく 1 以下）。既定 0.90
--app-id ID             GLib アプリケーション ID。試験で別インスタンスを起動するためのもの
```

## 表示する値

- **HOST**: CPU 使用率、CPU 温度、メモリ（使用 GiB / 全体 GiB、%）、CPU 電力、PSys 電力、PC 全体電力
- **GPU**（GPU ごとに 1 ブロック）: 温度、使用率、VRAM（使用 MiB / 全体 MiB）、電力
- **FAN**: Pico H への PWM 指令値（%）とモード。stale（ログが古い）・none（ログが無い）のときは
  n/a にし、現在値のセルにマウスを乗せると理由が出る（gpu-watch.sh のコメント参照）
- 最下行: 最終更新時刻。子プロセスが（原因を問わず）落ちたら「停止中: 理由」を表示し、
  5 秒後に自動で再起動を試みる

## CPU 電力・PSys・PC 全体の電力（実測 と 推定）

Intel RAPL の `energy_uj` は既定で root 専用（CVE-2020-8694 の緩和。**この緩和は外さない**）。
そのため非 root で常駐するこの GUI は、RAPL が読める環境でだけ実測の「CPU 電力(実測)」
「PSys(実測)」を出し、読めない環境では較正データから推定した「CPU 電力(推定)」
「PSys(推定)」を出す。実測と推定は値を混同しないよう、必ず項目名に `(実測)`/`(推定)` を
付けて区別する。較正していなければ「未較正」と出し、推測値で埋めない。

### 較正の仕組み

`constraint_*_power_limit_uw` と `constraint_*_time_window_us`（PL1 の上限電力・時定数）は
RAPL の `energy_uj` と違って**一般ユーザーでも読める**。これと「CPU 負荷段階ごとに実測した
消費電力」を組み合わせて、負荷率から電力を推定する。

1. ウィンドウの「電力を較正」ボタンを押すと、`pkexec` 経由で `calibrate-power.py` を root で
   起動する（パスワード入力は pkexec のグラフィカルなダイアログで行う。このリポジトリの
   コードからは sudo/pkexec を呼ばない。較正スクリプト自身は root 専用で、非 root では
   終了コード 2 になる）。
2. `calibrate-power.py` は CPU 負荷を 0% / 25% / 50% / 75% / 100%（スレッド数換算）の
   5 段階に変え、各段階で「2 秒ならし → 5 秒計測 → 5 秒休み」してから、CPU 使用率・
   package-0 の電力・psys の電力（無ければ null）を測る。休みを挟むのは、PL1 の移動平均が
   前の段階の高負荷で絞られたまま次の段階に引き継がれるのを避けるため。
3. 結果の JSON を `tools/gpu-watch-gui/state/calibration.json`（git 管理外。機械ごとの実測値
   のため）に一時ファイル→rename で保存し、即座に表示へ反映する。

### 推定の式

- **CPU 電力(推定)**: 較正点（util, cpu_w）を CPU 使用率で区間線形補間し、範囲外は端の値で
  止める。さらに PL1 頭打ちを「推定値の指数移動平均（時定数 = 較正した PL1 の
  `time_window_us`）が PL1 以上になったら、以後の推定値を PL1 以下に抑える」という形で模す。
  これにより高負荷が始まった直後の短時間は PL2 相当で PL1 を超えた値を出し、負荷が続くと
  PL1 に収束する。
- **PSys(推定)**: psys_w も同様に補間し、CPU が PL1 頭打ちで抑えられた分
  （補間した cpu_w − 抑えた後の cpu_w）を差し引く（PSys は CPU を含むプラットフォーム
  全体の電力のため）。
- **PC 全体(推定)** = (PSys 推定 + GPU 実測電力の合計) ÷ PSU 効率。GPU が 1 基でも n/a なら
  全体も n/a にする（片方だけで埋めない）。PSU 効率の既定 0.90 は実測していない仮定値
  （`--psu-efficiency` で上書きできる）。PSys は SoC プラットフォームの電力で dGPU の消費電力を
  含まないため、GPU 実測をそのまま足す設計にしている。

較正していない、または較正時と CPU が違う（CPU を載せ替えた等）ときは、これらの行に
「未較正」と出す。項目名の横のツールチップに式・較正日時・上記の仮定を出す。

色は CSS クラスで付ける（見出しや他のラベルには付けない。現在値のセルだけ）。
温度は gpu-watch.sh の `temp_color` と同じしきい値（しきい値以上=赤、しきい値-10 以上=黄、
それ未満=緑）。使用率は `load_color` と同じ（90%以上=赤、70%以上=黄）。

## 通知

GPU 温度が `-t`、CPU 温度が `-T` を**超えた瞬間だけ** `notify-send -u critical` で 1 回出す
（gpu-watch.sh の `-b edge` と同じ考え方）。しきい値以下に戻ると解除され、次に超えたときまた出る。
`notify-send` が無い・失敗しても GUI 自体は落ちない。

## 終了・二重起動

ウィンドウを閉じると子プロセス（`gpu-watch.sh -o raw`）に SIGTERM を送って終了する。
プロセスは残らない（`pgrep -af 'gpu-watch.sh -o raw'` で確認できる）。

二重起動は `Gtk.Application`（アプリ ID `jp.localai.GpuWatchGui`）の一意性で防ぐ。2 回目の起動は
新しい窓を作らず、既存の窓を前面に出す。

## 自動起動（ログイン時）

```bash
tools/gpu-watch-gui/install-autostart.sh              # 登録
tools/gpu-watch-gui/install-autostart.sh --uninstall  # 解除
```

`~/.config/autostart/gpu-watch-gui.desktop` を生成する（GNOME の仕様で autostart の登録ファイルは
ここにしか置けないため、本体はリポジトリ内に置いたまま、登録ファイル 1 個だけをここに作る）。
冪等（何度実行しても結果は同じ）。有効にするには再ログイン（または再起動）が要る。

`.desktop` には `X-GNOME-Autostart-Delay=5` を付けてある。自動ログイン直後は
`lock-after-autologin.desktop` が画面をロックする想定で、ロック解除後にはこのウィンドウが
既に表示されている状態になる。

## Wayland の制約

このマシンは GNOME / Wayland（`XDG_CURRENT_DESKTOP=ubuntu:GNOME`）。Wayland では通常のアプリから
ウィンドウの位置や「常に最前面」を指定できない。そのため、このウィンドウにはタイトルバーを
付けてあり、利用者が自分で動かせるようにしてある。

## 試験

```bash
uvx --with pytest pytest tools/gpu-watch-gui/tests/test_units.py -q
```

`model.py`（raw 行の解析、n/a の扱い、窓内の最大・平均、edge 検出、較正データの検証、
区間線形補間、PL1 頭打ち、電力推定の式）と、`calibrate-power.py` の純関数（root 不要の部分
だけ。energy_uj の巻き戻り補正、負荷段階のスレッド数算出）、`gpu-watch.sh -o` の引数検証を
確認する。GTK は import しない。

`calibrate-power.py` は root 専用（RAPL の `energy_uj` を読むため）。試験は非 root で実行して
終了コード 2 になることだけを確認し、実際の較正（root・pkexec・パスワード入力が要る）は
試験では行わない。実機での較正は GUI の「電力を較正」ボタンから利用者が行う。
