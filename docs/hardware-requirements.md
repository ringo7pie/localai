# 動作環境・必要な資源

動作を確かめた構成は **1 つだけ**（下の「確認済みの構成」）。ほかの構成は未検証で、`./localai doctor` が差を警告する。
数値は、各ツールの README と `knowledge/10-silver/` に記録した実測による。

## 確認済みの構成

| 項目 | 値 |
|---|---|
| GPU | NVIDIA A30 24 GB（Ampere、compute capability 8.0）1 枚 |
| CPU・RAM | Intel Core i7-12700（20 スレッド）・RAM 64 GB（実測 62.5 GiB）・swap 24 GiB |
| OS | Ubuntu 24.04 LTS（systemd の user unit を使う。`loginctl enable-linger` で非ログインでも起動） |
| ドライバ・CUDA | NVIDIA ドライバ 595 系。CUDA Toolkit 13.2 と 12.6 が並行して入る（`/usr/local/cuda` は 13.2） |
| Python | システムの 3.12。ツールごとに uv 管理の 3.10 / 3.11 / 3.12 を使う（`.venv` はツールごと） |

## ツール別

| ツール | GPU | VRAM の目安 | RAM | ディスク（取得する重みなど） | CUDA |
|---|---|---|---|---|---|
| portal・status・model-eval・gpu-watch-gui | 不要 | — | わずか | 小 | — |
| Ollama + Qwen3.8-27B（Q4_K_M） | 要 | 22 GiB（コンテキスト 65,536） | 通常 | 17 GB | 同梱（cuda_v13） |
| Strata（3 種のどれか 1 つ） | 要 | 空きをエキスパートのキャッシュに使う | **64 GB 級**（エキスパート 53.3 GiB。resident モードで 40.56 GiB を RAM に固定） | 約 100 GB（モデル 約 89 GB + MTP 約 5 GB） | 13.2（engine を sm_80 でビルド） |
| Pixal3D | 要 | 低 VRAM モードあり | 大（低 VRAM モードは重みを CPU 側に置く） | 約 30 GB | 12.6 |
| Hunyuan3D | 要 | 低 VRAM モードあり | 大 | 約 23 GB（形状のみなら約 5 GB） | 13.2 |
| ComfyUI + 防水メッシュ | 要 | — | WTiVo の処理で最大約 40 GiB | 重み 約 16 GB + torch | 12.6（WTiVo のビルド） |
| qwen-worker・local-ai-bridge | 不要（Ollama を呼ぶ） | — | 小 | 小 | — |

- **GPU を使うサービスは同時に載せられない**（24 GiB しかない）。[architecture.md](architecture.md) の排他を参照。
- A30 に FP8 の演算器は無い。量子化は INT4 / INT8 系（GGUF の Q4_K_M・Q8_0、AWQ、GPTQ）を使う。
- コンテキスト長は 65,536 が上限（81,920 で KV キャッシュが CPU に溢れ、9% / 91% の CPU / GPU になる）。
- 初回のリクエストは 17 GB のロードに約 60 秒かかる。

## GPU が無い・足りないとき

| 状況 | できること |
|---|---|
| GPU なし | 入口ページ（portal）の閲覧、評価レポートと文書の閲覧、GPU を使わない試験（`./localai test`）。モデルの推論はできない |
| VRAM 16 GB 級 | 未検証。Ollama の小さいモデル（例: gemma4:e4b は 9.6 GB）は動く見込みだが、Qwen3.8-27B・Strata・3D 生成は VRAM の取り合いで動かない可能性が高い |
| VRAM 24 GB の別のカード（RTX 3090 / 4090 など） | 未検証。Ampere 以降なら動く見込みだが、実機の確認が無いので保証しない。CUDA のビルド（sm_80 固定）は `CMAKE_CUDA_ARCHITECTURES` の変更が要る |
| Windows・macOS | 非対応（systemd・CUDA・bash を前提にする）。他の PC からの利用（SSH トンネル）は Windows の PowerShell 版のスクリプトがあるが、実機では未検証 |

## 守りの資源（RAM の歯止め）

3D 生成の低 VRAM モードは、重みを CPU 側に置くため RAM を強く使う。この機体では RAM 32 GB のときに
デスクトップごとハングしたため、RAM を 64 GB に増やし、Open WebUI・Hunyuan3D・Pixal3D の user unit に
`MemoryHigh=44G` / `MemoryMax=48G`（cgroup）を入れている。上限の目安は「RAM 総量 − 14 GiB」。
決め方と、低すぎたときの実例は `knowledge/10-silver/resources/service-memory-limits.md`。
