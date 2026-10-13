# hunyuan3d

画像 4 枚（正面・背面・左・右）から 3D メッシュを作る Hunyuan3D-2mv について、コードから読み取れない
運用上の事実。導入と使い方の手順は `tools/hunyuan3d/README.md` を Read する。

## 構成

- 上流は GitHub の Tencent-Hunyuan/Hunyuan3D-2 を固定コミット `f8db63096c82` で `vendor/` に取り込む。
  タグが切られていないため、コミットを固定しないと再現しない。
- UI は上流同梱の `gradio_app.py`（Gradio 5.33.0）。第三者製の WebUI は使っていない。
  `--model_path` に `2mv` を含む値を渡すと `MV_MODE` が真になり、front / back / left / right の
  4 枚入力タブが出る。
- Python は uv 管理の 3.11 を使う。リポジトリ既定の 3.12 では上流の実績ある依存（numpy 1.24.4、
  pymeshlab 2022.2）に cp311 wheel しか無く、入らない。
- torch 2.12.1+cu132 / torchvision 0.27.1+cu132 を使う。このサーバーの nvcc 13.2 とバージョンが一致するため、
  CUDA 12.x を別途入れずに `custom_rasterizer`（CUDA 拡張）と `differentiable_renderer` が sm80 でビルドできる。
  2026-09-22 に gcc 13.3.0 でビルド成功を確認した。
- 重み 22GB と実行時キャッシュはすべて `tools/hunyuan3d/models/` 配下に置く。`HY3DGEN_MODELS` に加えて
  `HF_HOME` と `U2NET_HOME` もそこへ向ける。既定のままだと Open WebUI と共有している
  `~/.cache/huggingface` に混ざる。
- 上流への当て物は `tools/hunyuan3d/patches/` にあり、`setup-server.sh` が順に `git apply` する。
  当て物の理由は下の VRAM の節と、`0002` の「MV モードで非表示のタブが selected のままになり、
  4 枚の入力欄が画面に出ない」不具合の修正。
- **当て物は公開版（公開リポジトリと履歴）に含めない。** 上流のコードの行を含む派生物で、Tencent の
  許諾は配布を EU・UK・韓国以外に限る（下の「ライセンス」）が、GitHub は地域を絞れないため。
  `patches/` は `.gitignore` 済みで、手元のファイルは残る。公開版の利用者は当て物が無いまま使うので、
  当て物由来の機能（`0001` 生成前の Ollama 解放、`0003` 画面の説明、`0004` 失敗したパラメータの表示、
  `0005` 設定の保存・読み込み）は無く、`0002` の不具合（MV モードで 4 枚の入力欄が出ない）が残る。
  `setup-server.sh` は `patches/` が無ければ当て物の工程を飛ばす。この文書に書いた運用の事実は、
  当て物を当てた手元の環境のもの。

## VRAM と RAM（2026-09-22 実測）

| 状態 | VRAM | RAM |
|---|---|---|
| 待機時（形状・テクスチャ両方をロード済み） | 5,365 MiB | 15.9 GiB |
| 生成ピーク | 11,487 MiB | 未計測 |

- 生成の所要時間は形状 21.7 秒、テクスチャ 136.2 秒。入力 3 枚（front / left / back）での値。
- **`--low_vram_mode` は VRAM を RAM と引き換えにする。** 2026-09-22 に RAM 20.2 GiB まで伸びて
  カーネルの OOM killer に殺され、その 16 分後に systemd-oomd が GNOME Shell を落として
  デスクトップがハングした（当時の RAM は 31 GiB）。この事故を受けて RAM を増設し、メモリ上限も
  見直した。現在の値は `knowledge/10-silver/resources/service-memory-limits.md` を Read する。
- この事故を受けて、低 VRAM モードは On/Off を選べるようにした。既定は On。切り替え方は
  `web-services.md` を Read する。メモリ上限は既定 44G / 48G で、超えたときに落ちるのはサービスだけ。
  決め方と実例は `knowledge/10-silver/resources/service-memory-limits.md` を Read する。
- `serve` は `os.execve` でサーバに置き換わる。print は flush しないとバッファごと捨てられ、
  journalctl に起動条件（低 VRAM の有無）が残らない。
- **Qwen を VRAM に載せたままでは 3D 生成ができない。** 空き 2,051 MiB の状態で生成すると 23.7 秒で
  CUDA out of memory になる。そのため `patches/0001-free-vram-before-generation.patch` で、生成の直前に
  Ollama のモデルを `keep_alive=0` で降ろす処理を上流の `_gen_shape` に入れてある。Qwen は次のチャットで戻る。
  **公開版にはこの当て物が無い**。残るのは `run-hunyuan3d serve` の起動時の解放（`hy3d/cli.py` の
  `cmd_serve`）と、手で実行する `run-hunyuan3d free-vram` だけ。`serve` のあとに Qwen を載せたまま
  生成すると同じ OOM になるので、生成の前に `free-vram` を実行する。
- Hunyuan3D が常駐している間、Qwen は GPU 配置 66%（残りは CPU）で 14.0 tok/s。単独時の 23〜26 tok/s より
  約 4 割遅い。全速で使いたいときは Hunyuan3D を止める。

## ライセンス

TENCENT HUNYUAN 3D 2.0 COMMUNITY LICENSE に従う。EU・UK・韓国は使用許諾の対象外で、日本は対象内。
月間アクティブユーザーが 100 万人を超える場合は Tencent へ別途ライセンス申請が要る（リリース日
2025-01-21 時点の前の暦月の値。原文 §4）。原文は上流の `LICENSE`（`tools/hunyuan3d/vendor/Hunyuan3D-2/LICENSE`）。

- Territory（EU・UK・韓国を除く世界）の外では、Works・出力・結果を使用・複製・改変・配布・表示できない
  （§5.c）。配布も Territory 内に限る（§3 の柱書き）。
- Works や出力・結果を、他の AI モデルの改善に使ってはならない（§5.b）。
- 第三者へ配布するときは、原文の写しの添付（§3.a）、変更の明記（§3.b）、Notice のテキストファイルの同梱
  （§3.d）が要る。Notice の文言は `tools/hunyuan3d/README.md` の「帰属表示（Notice）」に原文のまま載せた。
- この地域制限が、当て物を公開版に含めない理由（上の「構成」）。`setup-server.sh` は、上流の取得前に
  ライセンスの要約を表示し、`--accept-tencent-license`（または環境変数 `HY3D_ACCEPT_LICENSE=1`）が無いと
  終了コード 2 で止まる。要点は `tools/hunyuan3d/README.md` の「ライセンスの地域制限」を Read する。
