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
- Hunyuan3D が常駐している間、Qwen は GPU 配置 66%（残りは CPU）で 14.0 tok/s。単独時の 23〜26 tok/s より
  約 4 割遅い。全速で使いたいときは Hunyuan3D を止める。

## ライセンス

TENCENT HUNYUAN 3D 2.0 COMMUNITY LICENSE に従う。EU・UK・韓国は使用許諾の対象外で、日本は対象内。
月間アクティブユーザーが 100 万人を超える場合は Tencent へ別途ライセンス申請が要る。
