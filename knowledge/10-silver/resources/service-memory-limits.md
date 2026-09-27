# service-memory-limits

Open WebUI・Hunyuan3D・Pixal3D の systemd user ユニットに入れているメモリ上限
（`MemoryHigh` / `MemoryMax`）の決め方と、低すぎたときに何が起きたか。
毎回の運用で効く事実は `knowledge/10-silver/areas/web-services.md` にある。
機体の RAM 総量は `env.md` を Read する。

## 決め方

- 既定は **`MemoryHigh=44G` / `MemoryMax=48G`**（2026-09-24 決定）。3 サービスとも同じ値。
  Hunyuan3D と Pixal3D は入口ページが排他にするので、同時に上限いっぱいまで使うことはない。
- **推奨上限 = RAM 総量 − 14 GiB。** デスクトップ・Ollama・システムで約 10.5 GiB を使い、
  さらに Qwen が GPU に載りきらないとき約 6 GiB が RAM へ溢れる。その分を残す。
- **許容上限 = RAM 総量 − 4 GiB。** これを超える値は入口ページが受け付けない。
- `MemoryMax` を物理的な残りより大きくしても歯止めにならない。上限に届く前に機体全体の RAM が
  尽き、`systemd-oomd` がデスクトップ（GNOME Shell）ごと落とす。**上限の意味は「そのサービスだけを
  殺してデスクトップを守る」ことなので、物理的な残りより小さくないと役に立たない。**
- `MemoryHigh` を超えると絞られて遅くなるだけで、止まりはしない。止まるのは `MemoryMax` を超えたとき。

## 上限が低すぎたときの実例（2026-09-24）

RAM を増設したあとも、Pixal3D の上限が増設前の `24G` / `28G` のまま残っていた。

- Pixal3D の生成が、GPU 使用率 0% のまま進まなくなった。止まっていたのではなく、
  cgroup の `memory.high` を超えたまま swap（24 GiB）も満杯で、絞られ続けていた。
- 時間の約 82% をメモリ待ちで潰していた（cgroup の `memory.pressure` の `full avg10` が 81.79）。
- GPU をほとんど使わない最後の工程（メッシュの仕上げ）で詰まっていたため、GPU 使用率が 0% に見えた。
  この工程は通常 43 秒のところ **18 分 42 秒** かかった。
- 上限を上げると 30 秒以内に完了した。**「GPU 使用率 0%」を見たら、まず cgroup の
  `memory.events` の `high` が増え続けていないかを見る。**

## 入口ページからの変更

- 画面の各カードの「メモリ上限」欄から変える。API は `POST /api/memory/<key>/<high>/<max>`（GiB の整数）。
  必須のヘッダは起動・停止と同じ（`web-services.md` を Read する）。
- **稼働中のサービスにも再起動なしで効く。** 低 VRAM モードの切り替え（`EnvironmentFile` を使うため
  再起動が要る）とはここが違う。
- **`systemctl set-property` は恒久と `--runtime` の両方へ書く必要がある。** `--runtime`
  （`/run/user/1000/systemd/user.control/`）の方が優先度が高く、以前に `--runtime` だけで設定した値が
  残っていると、恒久設定（`~/.config/systemd/user.control/`）を書いても効かない。実際に Pixal3D で
  恒久 44/48 が `--runtime` の 44/52 に上書きされている状態を観測した。
- ユニットファイル本体（`tools/*/systemd/*.service.example` 由来）の値より、これらの drop-in が優先される。
