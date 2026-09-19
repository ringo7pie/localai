# setup-inference

Ollama を導入し、`qwen3.8:27b` を A30 で動かして疎通を確認する。

## 結果

2026-09-19 完了。確定した事実はすべて areas/env.md にある。
ここには経緯と、測定の生データだけを残す。

## 経緯

- install.sh は 15:23 に unit ファイルを書いた直後で止まっていた。バイナリと ollama ユーザーは
  作成済みだったため、`systemctl daemon-reload` と `enable --now` だけで起動した。再導入はしていない。
- 内蔵 GPU（Intel UHD 770）は Ollama が自動で除外した。使うなら `OLLAMA_IGPU_ENABLE=1` が要る。

## コンテキスト長の測定（2026-09-19）

env.md の「65536 が上限」の根拠。VRAM は nvidia-smi の実測値（単位 MiB）。総量は 24576 MiB。

| num_ctx | 配置 | VRAM |
|---|---|---|
| 32768（Ollama 既定） | 100% GPU | 19987 MiB |
| 65536 | 100% GPU | 22201 MiB |
| 81920 | 9%/91% CPU/GPU | 22569 MiB |
| 131072 | 28%/72% CPU/GPU | 22533 MiB |
| 262144 | 59%/41% CPU/GPU | 22497 MiB |

65536 を超えると VRAM 使用量は約 91% で頭打ちになる。Ollama が VRAM に載せるのをやめて
層を CPU に移すためで、VRAM が余っているわけではない。判定は PROCESSOR 列で行う。
