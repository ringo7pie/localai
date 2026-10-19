# qwen-model-bench

Ollama の 1 モデルを載せて、**この機体（A30、VRAM 24 GiB / RAM 62.5 GiB）で実用になるか**を
数字で出す。特定のモデル専用ではない。新しいモデルが出るたび同じ手順で比べられるようにしてある。

機体の制約は `knowledge/10-silver/areas/env.md` を Read する。

## 使い方

```bash
tools/qwen-model-bench/bench-model.sh <モデル名> [オプション]
```

| オプション | 意味 |
|---|---|
| `--num-predict N` | 生成するトークン数（既定 128）。短すぎると速度がぶれる。**300 以上を勧める** |
| `--prompt-file PATH` | プロンプトをファイルから読む（既定は内蔵の短い日本語の問い） |
| `--keep` | 計測後もモデルを VRAM に残す（既定は降ろす） |

Hunyuan3D か Pixal3D が動いていると VRAM を食い合って測る意味が無いので、**動いていたら止め方を
案内して中止する**（勝手には止めない）。計測の前に Ollama の常駐モデルをすべて降ろす。

## 測るもの

| 項目 | 取り方 |
|---|---|
| 生成速度（tok/s） | `/api/generate` の `eval_count` / `eval_duration` |
| ロード時間 | 同 `load_duration` |
| GPU 配置率 | `/api/ps` の `size_vram` / `size` |
| VRAM・RAM・swap のピーク | 生成中に 1 秒ごとに `nvidia-smi` と `free` |
| **メモリ待ちの割合** | 同 `/proc/pressure/memory` の `full avg10` |

**メモリ待ちの割合がこの道具の肝。** モデルがメモリに収まらないと、GPU 使用率が 0% のまま
進まなくなる。2026-09-24 に Pixal3D で、上限を超えて swap に張り付き、43 秒の工程が
18 分 42 秒になった前例がある（`knowledge/10-silver/resources/service-memory-limits.md` を Read する）。
速度だけ見ていると「止まっている」と誤解するので、待ちの割合を必ず併せて見る。

## 実用かどうかの目安

次のどちらかに当たれば **実用外**と判定する（スクリプトが自動で出す）。

- 生成が **5 tok/s 未満**
- メモリ待ちの割合が**平均 50% を超える**

判定はあくまで目安で、スクリプトは何も勝手に変えない。判定が出たら人が決める。

## 結果の置き場

`results/<モデル名>-<日時>.json`。モデル名の `:` と `/` は `_` に置き換える。
git で追跡する（小さく、機体の性能の記録として残す価値があるため）。

## 文脈長の上限（Modelfile、2026-10-18）

利用者の指示「A30 に収まるように、文脈長と KV キャッシュを最大に」で、Ollama の各モデルの文脈長（`num_ctx`）を
**A30（VRAM 24 GiB）に全部載る最大**にした。載るかどうかは、実際に読み込んで `ollama ps` の PROCESSOR（`100% GPU`）と
journal の `offloaded N/N layers`・`llama_kv_cache: size`、nvidia-smi で確かめた（Ollama は収まらないと黙って層を CPU に移す。
`LLAMA_ARG_FIT` 既定 on）。速さは `bench-model.sh <モデル名> --num-predict 300`（`results/*-20261018_*.json`）。

- **KV キャッシュは q8_0**（Ollama 全体の設定。`/etc/systemd/system/ollama.service.d/override.conf` に
  `OLLAMA_FLASH_ATTENTION=1` と `OLLAMA_KV_CACHE_TYPE=q8_0`。`OLLAMA_CONTEXT_LENGTH=65536` は Modelfile に値の無いモデルの既定として残す）。
  f16 の半分になり、llama-server は `--cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on` で起動する（journal で確認。ヘッド次元 256 の
  qwen35・gemma4・qwen4exp のどれでも Flash Attention が有効になった）。Ollama の FAQ は q8_0 を「very small loss in precision」としている。
- **モデルごとの上限は `modelfiles/<名前>.Modelfile`**（`FROM <同じ名前>` と `PARAMETER num_ctx N` だけ。template・ほかの PARAMETER・LICENSE は
  引き継がれる）。当て方は `ollama create <名前> -f modelfiles/<名前>.Modelfile`（同じ名前で作り直す。ID は変わるがサイズと blob は同じ）。
  元の Modelfile は `work/modelfiles-before-20261018/`（追跡しない）に控えてあり、戻すときは `ollama create <名前> -f <控え>`。
- **`gemma4:31b-ctx32k`（it-qat と同じ重みで `num_ctx 32768` に固定した派生）は消した**（`ollama rm`。重みは it-qat が持つので消えない）。
  it-qat 本体が 65536 で全部 GPU に載るようになったため。評価の記録（2026-10-08）には残る。

| モデル | `num_ctx` | KV（q8_0） | 載り方 | VRAM（nvidia-smi） | 生成（300 トークン） | 補足 |
|---|---:|---:|---|---:|---:|---|
| qwen3.8:27b | **114,688** | 4,256 MiB | 66/66 層 GPU、100% | 22,614 MiB | 32.8 tok/s | 131,072 は 63/66 層（91% GPU、KV 4,864 MiB、25.6 tok/s）で不可。10-16 の 65,536（f16）は 34.3〜37.8 tok/s |
| gemma4:31b-it-qat | **65,536** | 3,358 MiB | 61/61 層 GPU、100% | 22,458 MiB | 25.4 tok/s | **f16 の KV では同じ 65,536 で 55/61 層しか載らず**（2026-10-08 の評価はこの状態。5.2 tok/s）。ctx32k が 5 倍速かった原因 |
| gemma4:e4b | **131,072**（モデルの上限） | 1,088 MiB | 43/43 層 GPU、100% | 6,100 MiB | —（10-18 は未計測） | f16 でも載る（2,048 MiB） |
| qwen3.8-flash-next:IQ4_XS | **131,072** | 2,040 MiB | dense の 49/49 層 GPU（エキスパート 92 GB は CPU。`ollama ps` は 43%） | 22,766 MiB | 8.3 tok/s | 「A30 に収まる」のは dense と KV。09-24 の 65,536 は 5.9 tok/s（300 トークン、2 回目） |

f16 のままなら上げられたのは e4b だけ（27b・IQ4_XS は 65,536 が限界。it-qat は 32,768 に下げないと載らない）。
09-19 の「65,536 が上限」（`knowledge/10-silver/archive/setup-inference.md`）は f16 の KV での値。

呼ぶ側: 評価の道具（`tools/model-eval`）・Open WebUI・local-ai-bridge は `num_ctx` を送らないので Modelfile の値で動く。
**qwen-worker は `~/.config/qwen-worker/config.toml` の `num_ctx = 65536` を送る**ので、27b を使うたびに Ollama が 114,688 ↔ 65,536 で
読み直す（約 60 秒。利用者が後で設計し直す）。

## 実測（2026-09-24）

### qwen3.8:27b

| サイズ | GPU 配置 | 生成速度 | メモリ待ち |
|---|---|---|---|
| 16.3 GiB | 100% | 33.1 tok/s（306 トークン） | 平均 0% |

`env.md` は同じモデルを 23〜26 tok/s と記録しているが、この計測では 33〜40 tok/s 出た。原因は未調査。

### qwen3.8-flash-next（125B、6B 活性の MoE）

再起動直後に、各モデルを 300 トークンで 2 回続けて測った。1 回目はページキャッシュが冷えた状態、
2 回目は温まった状態。GPU 配置はどれも 37〜43%（VRAM 約 20 GiB、残りは mmap で NVMe から読む）。

| タグ | 配布元 | Ollama 上のサイズ | 1 回目 | 2 回目 | ロード（1 回目→2 回目） |
|---|---|---|---|---|---|
| `125b-a6b-q4_K_M` | Ollama 公式 | 120 GB | 4.8 tok/s | **5.8 tok/s** | 50.8 → 32.5 秒 |
| `125b-a6b-IQ4_XS` | bartowski | 97 GB | 3.3 tok/s | 5.9 tok/s | 53.3 → 32.3 秒 |
| `125b-a6b-IQ3_XXS` | bartowski | 88 GB | 3.3 tok/s | 5.2 tok/s | 49.3 → 32.3 秒 |
| `125b-a6b-IQ2_XS` | bartowski | 77 GB | 4.2 tok/s | 6.3 tok/s | 51.0 → 31.8 秒 |
| `125b-a6b-IQ1_M` | bartowski | 72 GB | 4.8 tok/s | 6.7 tok/s | 47.9 → 31.5 秒 |

- **量子化を小さくしても速くならない。** 1bit まで落としても 2 回目で 5.2〜6.7 tok/s の幅に収まる。
  品質が最も高い公式 q4_K_M を使えばよい。
- **速度はページキャッシュに強く左右される。** ダウンロード直後（ファイルがまだキャッシュに残っていた）の
  q4_K_M は 11.8〜15.1 tok/s 出たが、再起動後は 1 回目 2.8〜4.8 tok/s、2 回目 5.8 tok/s だった。
  RAM 62.5 GiB に対し CPU 側の重みが約 30 GiB あるため、別のモデルを使うとキャッシュが追い出される。
- **この道具の「メモリ待ち」はどれも 0% だった。** 詰まっているのはメモリの回収ではなく NVMe からの読み込み
  （mmap のページフォールト）で、`/proc/pressure/memory` には出ない。`/proc/pressure/io` を測るべきだった。
- 取り込みは `import-hf-gguf.sh` で行った（Ollama は HF の分割 GGUF を直接 pull できないため、
  落とす → `llama-gguf-split --merge` → `ollama create`）。会話の扱い（`RENDERER qwen3.8` /
  `PARSER qwen3.5`）と既定値は公式 q4_K_M から写した。
