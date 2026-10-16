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
