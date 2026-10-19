# env

## ハードウェア

- GPU は NVIDIA A30 1 枚。VRAM 24 GiB。compute capability 8.0（Ampere）。
- A30 に FP8 の演算器は無い。量子化は INT4 / INT8 系（GGUF の Q4_K_M・Q8_0、AWQ、GPTQ）を使う。
- RAM は 64 GB（実測 62.5 GiB）。2026-09-24 時点。以前は 32 GB で、3D 生成の低 VRAM モードが
  重みを CPU 側に置いて RAM を強く使い、足りなくなったため増設した。
- swap は 24 GiB。3D 生成の低 VRAM モードが重みを CPU 側に置き 8 GiB では足りず、2026-09-22 に
  `/swapfile-pixal3d` 16 GiB を足した。`/etc/fstab` に登録済み（変更前は `/etc/fstab.bak-pixal3d`）。
- CPU は i7-12700、20 スレッド。ディスクは / に 1.3 TB 空き（モデルの重み 46GB を置いたあと）。

## ソフトウェア

- Ubuntu 24.04.5 LTS、kernel 7.0.0-31-generic。
- NVIDIA ドライバ 595.91.07。CUDA Toolkit は **13.2 と 12.6 が並行して入っている**。
  `/usr/local/cuda` は update-alternatives の優先度（13.2=132 > 12.6=126）で 13.2 を指す。
  12.6 は Pixal3D 用に 2026-09-22 に追加した（Ubuntu 24.04 のリポジトリに 12.4 が無いため）。
- Ollama は同梱の cuda_v13 を使い、A30 を compute 8.0 として認識する。CUDA を自前リンクしないため、
  PyTorch 系の対応状況に影響されない。
- Python 3.12.3。pip は入っていない。パッケージ管理は uv を使う。
- Docker 29.8.1 が入っており `docker.service` が常時起動する。localai とは別のプロジェクト
  （ai-finance、compose でコンテナ 5 つ）がこの機体で動いている。localai のツールは Docker を使わない。
- 別プロジェクト `~/Proj/USDFormat`（Isaac Lab の強化学習 `train.py`）がこの機体の GPU と RAM を使うことがある
  （2026-10-16 に実測: VRAM 5.6 GiB・RSS 8.4 GiB・CPU 約 1.3 コアを数十分以上）。`vram-policy.sh status` は空き VRAM と Ollama しか見ないので、
  Strata・3D 生成・計測の前に `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv` で他のプロセスを確かめ、
  動いていれば起動も計測もしない（相手の学習を落とすおそれがあり、キャッシュも小さくなって比較にならない）。
- オンライン。モデルのダウンロードは可能。
- ブラウザは無い（`/usr/bin/firefox` は snap の導入を促すだけで動かない）。HTML の図を目で確かめるときは、SVG を
  `uvx --with cairosvg python` で PNG にして見る。

## モデル

- 主モデルは Qwen3.8-27B（Qwen 公式、2026-08-14 公開）。Ollama では `qwen3.8:27b`（= `latest`、Q4_K_M、17 GB）。
- アーキテクチャは qwen3_5 系。linear attention 3 層 + full attention 1 層の繰り返しで、
  KV キャッシュは full attention 層だけが持つ。モデル上限のコンテキスト長は 262144。
- bf16 の重みは 51.7 GiB。A30 には載らない。4bit 量子化が必須。Q8_0（30 GB）も載らない。
- 実測: コンテキスト長 65536 で VRAM 22201 MiB / 24576 MiB、100% GPU、生成 23〜26 tok/s（2026-09-19、Ollama 0.34.2）。
  2026-10-16 に Ollama 0.40.5・同じ重み（ブロブのダイジェストは再取得後も不変）で測り直すと、VRAM 22215 MiB、
  100% GPU、生成 34.3〜37.8 tok/s（`tools/qwen-model-bench/bench-model.sh qwen3.8:27b` の 2 回目以降、ロード済み）。
  この機体では速くなっているが、原因（Ollama 側の llama.cpp 更新か計測条件の違いか）は確かめていない。
- コンテキスト長の上限は KV キャッシュの型で決まる。f16 の KV では 65536 が上限（81920 で 9%/91% CPU/GPU、2026-09-19）。
  2026-10-18 から KV を q8_0 にし（下の「制約」）、Modelfile の `num_ctx` を **114688** にした（66/66 層が GPU、VRAM 22614 MiB、
  32.8 tok/s）。131072 は 63/66 層しか載らず 25.6 tok/s に落ちる。Ollama は収まらないと黙って層を CPU に移すので、
  判定は `ollama ps` の PROCESSOR 列（`100% GPU`）と journal の `offloaded N/N layers` で行う。
- vision・tools・thinking はいずれも動作する。API 応答で確認済み。
- 画像側の projector は clip 460.73M。vision を使っても VRAM 使用量はほぼ増えない（22201→22223 MiB）。
- 初回リクエストは 17 GB のロードに約 60 秒かかる。この間の生成速度は当てにならない。
- `OLLAMA_KEEP_ALIVE` は既定の 5 分。無操作が続くと VRAM から降り、次回また 60 秒かかる。
  延長するかは未決。延長すると VRAM 22 GB を占有し続ける。
- `/api/ps` の `expires_at` はリクエスト開始時に「今 + 5 分」で書かれ、生成中は更新されない。5 分を超える生成中は
  過去の時刻が表示されるが、生成が終わるまでモデルは降りない。異常ではない。

## 制約

- Ollama 0.40.5 を導入済み（2026-10-16 に 0.34.2 から公式 install.sh で更新。ドライバ・CUDA Toolkit には触れない。
  `ollama.service` 本体は作り直されるが `ollama.service.d/override.conf` は別ファイルなので残る）。
  systemd の `ollama.service` が enabled で常時起動する。
- `/api/tokenize` は 0.40.5 でも無い（404 を実測、2026-10-16）。
- API は http://127.0.0.1:11434。OpenAI 互換は /v1。LAN には公開していない。
- Ollama 全体の設定は /etc/systemd/system/ollama.service.d/override.conf（2026-10-18 から `OLLAMA_CONTEXT_LENGTH=65536`
  は Modelfile に値の無いモデルの既定、`OLLAMA_FLASH_ATTENTION=1`、`OLLAMA_KV_CACHE_TYPE=q8_0`。llama-server は
  `--cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on` で起動する）。変更したら daemon-reload と restart が要る。
  モデルごとの上限は Modelfile の `num_ctx`（`tools/qwen-model-bench/modelfiles/` を `ollama create` で当てる。
  qwen3.8:27b 114688、gemma4:31b-it-qat 65536、gemma4:e4b と qwen3.8-flash-next:IQ4_XS 131072。載り方と速さの実測は
  `tools/qwen-model-bench/README.md` の「文脈長の上限」を Read する）。gemma4:31b-it-qat は f16 の KV だと 65536 で 61 層のうち
  55 層しか GPU に載らず、32768 の派生 ctx32k より 5 倍遅かった（2026-10-08 の評価はその状態）。ctx32k は 2026-10-18 に消した。
- モデルの実体は /usr/share/ollama/.ollama/models。サービスは ollama ユーザーで動く。
- sudo が要る操作（systemctl、/etc 配下の編集）は、root で起動した Claude か、ユーザーが手で行う。
- リモート origin はネットワーク共有上の bare リポジトリ。共有がマウントされていないと push / fetch が失敗する。
