# strata-upstream

Strata の上流（`vendor/Strata`、固定コミットは `tools/strata/stra/config.py` の `STRATA_COMMIT`）を
扱ううえでの事情。日々の起動・停止・導入手順は `tools/strata/README.md` を Read する。

## v0.1.44.1 以降の engine は GGUF の形状をメタデータで検査する

- 上流のコミット `f812e9a1`（v0.1.41 系以降、v0.1.44.1 で確認）から、engine は起動時に GGUF のメタデータ
  （`qwen4exp.*`）から形状を読み、コンパイル時に決めた形状と一致するか検査する。特に
  `qwen4exp.attention.compress_ratios` は「full attention の層（`(層番号 + 1)` が `full_attention_interval`
  で割り切れる層）だけ 0 でない」ことを確かめる。一致しないと起動せず、
  `qwen4exp.attention.compress_ratios[N] = 0, but full_attention_interval = M makes layer N full attention`
  のようなログを残して終了する。v0.1.40.1 以前の engine は形状を決め打ちしていたため、この不一致を見ていなかった。
- RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored（`jimmy31chen` 配布、固定リビジョン）の GGUF は
  `compress_ratios` が 48 個すべて 0 で、この検査に落ちる。ISTA 配布の Coder・公式版の GGUF は
  インデックス 3, 7, …, 47（4 つおき）だけ 4 になっていて、そのまま動く。
- RVN 側を動かすには GGUF の該当 12 要素（int32）を 0 → 4 に書き換える。
  `tools/strata/scripts/patch_gguf_compress_ratios.py <gguf> --apply` で直し、`--revert` で戻せる
  （書く前後で対象要素以外のバイトが変わっていないことを確かめてから書く）。
  **書き換えると HF に固定した sha256 とは一致しなくなり、`run-strata fetch-models --verify` は失敗する。**
  モデルを取り直したら `--apply` をやり直す。

## モデルを切り替えて起動すると OOM で落ちることがある

- rvn / coder / official は排他（`Conflicts=`）で、片方を止めてからもう片方を起動する運用。直前に動かしていた
  モデルの GGUF が page cache に残ったまま次のモデルを起動すると、エキスパートを RAM へ複製している途中で
  `systemd-oomd` に `killed N process(es) in this unit` として落とされることがある（2026-10-16 に実機で確認）。
  メモリ上限の考え方自体は `knowledge/10-silver/resources/service-memory-limits.md` を Read する。
- 起動前に、全モデルと MTP の draft 層の GGUF の page cache を捨てると避けられる（root 不要、`tools/strata/README.md`
  の「v0.1.44.1 への更新」に同じ手順がある）:
  `os.posix_fadvise(os.open(path, os.O_RDONLY), 0, 0, os.POSIX_FADV_DONTNEED)` をモデルごとに呼ぶ。
- 2026-10-18 にも、`tools/model-eval/run_local.sh` が Coder を止めて RVN を起動したときに同じく落ちた。直前が Ollama のときは、
  Ollama の重み（`/usr/share/ollama/.ollama/models/blobs/sha256-*`。ollama 所有だが読める）の page cache も同じ呼び出しで捨てられ、
  捨ててから起動し直すと通った（buff/cache 55 GiB → 3 GiB）。`run_local.sh` はこの手順を自動では行わない。

## 0.1.40〜0.1.44 の速さの設定と文脈長 262144 の、この機体（A30・RAM 62.5 GiB・i7-12700）での実測（2026-10-17〜18）

数値と採った設定は `tools/strata/README.md` の「速さの設定と文脈長 262144」を Read する。ここには上流の記述と違った点と、判断の根拠だけを置く。

- `--adapt-async 1` は 5 モデルすべてで 4K 入力・thinking ありが 6〜14% 速い（上流の実測 +7〜11% と同じ範囲）。採った。
- 通常モード（エキスパートを全部 RAM に写す）は resident 版（`--resident-experts`）より 8〜20% 速い。エキスパートが 39.97 GiB の
  公式 IQ3_XXS と Swift 1.5 は落とせない RAM が約 42.3 GiB で MemoryHigh 50G に収まる。46.84 GiB の公式 IQ3_S と 53.3 GiB の RVN は
  収まらないので resident 版のまま。
- `--kv-grow` は通常モード限定（resident 版と KV ストリーミングでは engine が無効にする）。262144 にしても GPU のキャッシュの枠が
  131072・kv-grow なしより多く、速さは同じ範囲。131072 で kv-grow だけ足しても速さは変わらない（枠だけ増える）。
- `--kv-resident 65536`（KV ストリーミング）は resident 版と併用できる。RVN では 262144 で枠が 6549 → 7732 に増えて 4% 速く、
  RAM は +1.0 GiB。公式 IQ3_S では差 2% で RAM +2.3 GiB なので付けない。
- **`--max-context` を 131072 → 262144 にすると、KV が VRAM にあっても cgroup の落とせない RAM（shmem + anon）が約 1.9 GiB 増える**
  （RVN 43.2 → 45.1 GiB）。上流 `docs/DETAILS.md` の「low-RAM モードでは文脈長は RAM に数えない」とは合わない。原因は未確認。
- `STRATA_IQ3S_MT1=1`（IQ3_S 型のエキスパートの複数トークン用カーネル）は公式 IQ3_XXS で効かない（+1%、短い質問 −6.5%）。
- 262144 の実機確認: 公式 IQ3_XXS に 190,947 トークンの入力を送り、prefill 1,760 tok/s（最初の文字まで 109 秒）・生成 61.3 tok/s で
  正しい答えが返った。
