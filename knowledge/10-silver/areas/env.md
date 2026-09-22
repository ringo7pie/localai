# env

## ハードウェア

- GPU は NVIDIA A30 1 枚。VRAM 24 GiB。compute capability 8.0（Ampere）。
- A30 に FP8 の演算器は無い。量子化は INT4 / INT8 系（GGUF の Q4_K_M・Q8_0、AWQ、GPTQ）を使う。
- RAM は 32 GB（実測 31 GiB）。CPU オフロードに使える余地は小さい。
- CPU は i7-12700、20 スレッド。ディスクは / に 1.5 TB 空き。

## ソフトウェア

- Ubuntu 24.04.5 LTS、kernel 7.0.0-31-generic。
- NVIDIA ドライバ 595.91.07、CUDA 13.2。Ollama は同梱の cuda_v13 を使い、A30 を compute 8.0 と
  して認識する。CUDA を自前リンクしないため、PyTorch 系の対応状況に影響されない。
- Python 3.12.3。pip は入っていない。パッケージ管理は uv を使う。docker は無い。
- オンライン。モデルのダウンロードは可能。

## モデル

- 主モデルは Qwen3.8-27B（Qwen 公式、2026-08-14 公開）。Ollama では `qwen3.8:27b`（= `latest`、Q4_K_M、17 GB）。
- アーキテクチャは qwen3_5 系。linear attention 3 層 + full attention 1 層の繰り返しで、
  KV キャッシュは full attention 層だけが持つ。モデル上限のコンテキスト長は 262144。
- bf16 の重みは 51.7 GiB。A30 には載らない。4bit 量子化が必須。Q8_0（30 GB）も載らない。
- 実測: コンテキスト長 65536 で VRAM 22201 MiB / 24576 MiB、100% GPU、生成 23〜26 tok/s。
- 65536 を超えると KV キャッシュが CPU に溢れる（81920 で 9%/91% CPU/GPU）。65536 が上限。
- vision・tools・thinking はいずれも動作する。API 応答で確認済み。
- 画像側の projector は clip 460.73M。vision を使っても VRAM 使用量はほぼ増えない（22201→22223 MiB）。
- 初回リクエストは 17 GB のロードに約 60 秒かかる。この間の生成速度は当てにならない。
- `OLLAMA_KEEP_ALIVE` は既定の 5 分。無操作が続くと VRAM から降り、次回また 60 秒かかる。
  延長するかは未決。延長すると VRAM 22 GB を占有し続ける。
- `/api/ps` の `expires_at` はリクエスト開始時に「今 + 5 分」で書かれ、生成中は更新されない。5 分を超える生成中は
  過去の時刻が表示されるが、生成が終わるまでモデルは降りない。異常ではない。

## 制約

- Ollama 0.34.2 を導入済み。systemd の `ollama.service` が enabled で常時起動する。
- API は http://127.0.0.1:11434。OpenAI 互換は /v1。LAN には公開していない。
- コンテキスト長は /etc/systemd/system/ollama.service.d/override.conf の
  `OLLAMA_CONTEXT_LENGTH` で設定する。変更したら daemon-reload と restart が要る。
- モデルの実体は /usr/share/ollama/.ollama/models。サービスは ollama ユーザーで動く。
- sudo が要る操作（systemctl、/etc 配下の編集）は、root で起動した Claude か、ユーザーが手で行う。
- リモート origin は /mnt/nas 配下の bare リポジトリ。/mnt/nas は //<nas>/<share> の
  CIFS マウントで、マウントされていないと push / fetch が失敗する。
- /mnt/nas は fstab の `x-systemd.automount` だが、`mnt-nas.automount` が `mount-start-limit-hit` で止まることがある。
  復旧は sudo が要る（`systemctl reset-failed mnt-nas.automount` か `mount /mnt/nas`）。利用者が行う。
