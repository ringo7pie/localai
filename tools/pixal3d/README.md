# pixal3d

複数視点の画像から 3D メッシュ（形状＋PBR テクスチャ）を生成する
[Pixal3D](https://github.com/TencentARC/Pixal3D)（[TRELLIS.2](https://github.com/microsoft/TRELLIS.2) 系）を、
このリポジトリの A30 サーバー上で動かすための一式。固定コミット

- Pixal3D: `f7cf38429b0bd264f1995f0f8743a88b1c728b94` を `vendor/Pixal3D` に
- TRELLIS.2: `75fbf0183001ed9876c8dbb35de6b68552ee08bd` を `vendor/TRELLIS.2` に

取り込んで使う（TRELLIS.2 は主にネイティブ拡張 `o-voxel` のビルド元。実行時に直接 import はしない）。

`tools/hunyuan3d`（もう 1 つの画像→3D ツール）と構成・語り口を揃えている。

## ポートと入口ページの関係

- **7861**: Pixal3D の gradio UI（このツール）
- 7860: Hunyuan3D-2 の gradio UI（`tools/hunyuan3d`。GPU を排他利用）
- 8080: 入口ページ（`tools/portal`。ここから 7861 へ飛べる）
- 8081: Open WebUI
- 8188: 将来の ComfyUI 用に予約

サーバー IP は `<server-ip>`。起動後は `http://<server-ip>:7861` から使う。

## Hunyuan3D との排他

A30 の VRAM は 24576 MiB しかなく、Hunyuan3D と Pixal3D は同時に動かさない前提。
入口ページ（`tools/portal`、`GPU_EXCLUSIVE_KEYS = ("hunyuan3d", "pixal3d")`）が、
どちらかを起動するときにもう片方を自動で停止する。手動で切り替える場合:

```bash
systemctl --user stop hunyuan3d   # Pixal3D を使う前に
systemctl --user stop pixal3d     # Hunyuan3D を使う前に
```

## Qwen（Ollama）との VRAM の取り合い

Hunyuan3D と同じく、生成の直前に Ollama の常駐モデルを `keep_alive=0` で降ろす
（`px3d.ollama.unload_all()`。`px3d/ui.py` の `_unload_ollama_before_generate()` と
`px3d/cli.py` の `serve` / `generate` が呼ぶ）。失敗しても生成は続ける（警告のみ）。
Qwen は次のチャットで自動的に戻る（ロードに約 60 秒）。

## 導入

サーバー上で 1 回実行する（torch と重み合計 約30GB をダウンロードするので、実行前にディスクと
ネットワークを確認すること。**setup-server.sh はこの README を読んだ人が手で実行する**）。

```bash
tools/pixal3d/setup-server.sh
```

オプション:

- `--skip-models`: 重みの取得を省略する（あとで `run-pixal3d fetch-models` を手で実行する）
- `--no-autostart`: PC 起動時の自動起動を有効にしない
- `--build-only`: venv・上流取得・torch・依存・ネイティブ拡張・自前パッケージ（px3d）までで止める。
  重みの取得・systemd ユニットの作成・doctor は行わない（拡張ビルドだけを繰り返し検証したいときに使う）

導入後の点検: `tools/pixal3d/run-pixal3d doctor`

**ネイティブ拡張のビルド（[6/10]）は、いまこのリポジトリで別途検証中。**
`setup-server.sh` の `build_native_extensions()` はいまのところ骨格のみで、実体は
`# TODO(build): 検証済みのコマンドに差し替える` の 1 行だけになっている。
対象は `vendor/extensions/{o-voxel, FlexGEMM, CuMesh, nvdiffrast, nvdiffrec}` と natten。

## 起動と停止

手動起動（フォアグラウンド。Ollama を降ろし VRAM の空きを確認してから px3d.ui を起動する）:

```bash
tools/pixal3d/run-pixal3d serve
# 低 VRAM モードを明示する場合
tools/pixal3d/run-pixal3d serve --low-vram
tools/pixal3d/run-pixal3d serve --no-low-vram
```

systemd user ユニット（`setup-server.sh` が `~/.config/systemd/user/pixal3d.service` を作成し、
**既定で自動起動を有効にする**。切りたいときは `setup-server.sh --no-autostart`）:

```bash
systemctl --user daemon-reload
systemctl --user start pixal3d
systemctl --user status pixal3d
systemctl --user stop pixal3d
```

## 4 枚の画像の向き（正面が必須の理由）

画面には「正面（0°）」「右 90°」「背面（180°）」「左 270°」の 4 枠が並ぶ。
**正面（0°）は必須**で、残り 3 枚は無くても生成できる（枚数が少ないほど背面・側面の
形状精度は落ちる）。

正面が必須なのは、Pixal3D の `inference_mv.check_main_view` が frame 0 を
「正準の正面姿勢（カメラが `(0, -d, 0)` にあり原点を見る）」だと仮定して以後の視点をすべて
frame 0 基準で配置するため。正面が無い、またはズレていると、生成結果の向きが学習時の座標系と
ズレる。4 方位のカメラ姿勢（4x4 行列）は上流同梱の
`vendor/Pixal3D/assets/mv_images/example/transforms.json` と同じ値を `px3d/config.py` に持っている
（仰角 0、水平 FOV 20 度、距離 3.1192049980163574 の固定 orbit）。

## 背景除去モデルの差し替え（RMBG-2.0 → BiRefNet）

`pipeline_mv.json`（重みの入口）の `rembg_model` は

```json
{"name": "BiRefNet", "args": {"model_name": "briaai/RMBG-2.0"}}
```

を指しているが、**`briaai/RMBG-2.0` は HF のゲート付きリポジトリで、ログインと利用規約への
同意が無いと 401 GatedRepoError になりダウンロードできない**（実機で確認済み）。

`Pixal3DImageTo3DPipeline.from_pretrained`（vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py）は

```python
pipeline.rembg_model = getattr(rembg, args['rembg_model']['name'])(**args['rembg_model']['args'])
```

を `from_pretrained` の内部で直接実行してしまうため、生成された `rembg_model` を後から
差し替えることはできない。そこで `px3d/rembg_override.py` の `force_rembg_model()` が、
`from_pretrained` を呼ぶ**前**に `pixal3d.pipelines.rembg` モジュールの `BiRefNet` 属性そのものを
差し替える（`getattr(rembg, 'BiRefNet')` は呼び出された瞬間にモジュール属性を引くため、これで効く）。
差し替え先は `vendor/Pixal3D/pixal3d/pipelines/rembg/BiRefNet.py` の `BiRefNet` クラスの既定値である
**`ZhengPeng7/BiRefNet`**（`px3d/config.py` の `REMBG_MODEL`。非ゲート・MIT ライセンス・425MB）。

vendor/ は書き換え禁止、上流への当て物（patch）も今回は作らない方針にしたため、
「呼ぶ前にモジュール属性を差し替える」というこの方式を選んだ。`px3d/ui.py`（`main()`）と
`px3d/cli.py generate` のサブプロセスは、どちらもパイプラインを作る前に必ず
`force_rembg_model(config.REMBG_MODEL)` を呼ぶ。`run-pixal3d doctor` は `HF_HOME` 配下に
`ZhengPeng7/BiRefNet` のキャッシュがあるかを確認する。

BiRefNet は `AutoModelForImageSegmentation.from_pretrained(model_name, trust_remote_code=True)`
で読み込まれる。**`trust_remote_code=True` は HF リポジトリに同梱された Python コードを
そのまま実行する**という意味なので、モデルを差し替える場合はこの点も踏まえること。

## 低 VRAM モード（PIXAL3D_LOW_VRAM）

Pixal3D の `low_vram=True` は VRAM を RAM と引き換える設定（使わない段のモデルを CPU に
退避し、必要な段だけ都度 GPU に載せる）。**既定は On**（VRAM 優先の安全側。hunyuan3d の
`HY3D_LOW_VRAM` と同じ考え方）。

切り替え方は 3 通りあり、優先順位は `serve` の CLI フラグ → 環境変数 → 既定値（On）。

1. **入口ページのスイッチ**（`tools/portal`、8080 番）— `~/.config/pixal3d/pixal3d.env` の
   `PIXAL3D_LOW_VRAM` を書き換える想定（このファイルの所有者は入口ページと同じ `mt`）
2. **env ファイルを直接編集**: `~/.config/pixal3d/pixal3d.env` の `PIXAL3D_LOW_VRAM` を
   `1`（On）/ `0`（Off）にして `systemctl --user restart pixal3d`
3. **手動起動時のフラグ**: `run-pixal3d serve --low-vram` / `run-pixal3d serve --no-low-vram`
   （env ファイルより優先する）

低 VRAM モードのとき、画面の解像度の既定値は 1024（それ以外は 1536）。

`run-pixal3d doctor` は現在の設定（env ファイルの値と、そこから決まる有効/無効）を表示する
（OK/NG の判定ではなく情報表示）。

### RAM の安全弁（MemoryMax）

`systemd/pixal3d.service.example` に `MemoryHigh=20G` / `MemoryMax=22G` を入れてある
（`tools/hunyuan3d/systemd` と同じ理由・同じ値。RAM 31GiB のうち約 9GiB をデスクトップと
入口ページに残す意図）。**超えたときに起きるのは Pixal3D サービスだけが OOM kill されることで、
デスクトップやほかのサービスを巻き込まない。**

## ライセンス

**Pixal3D 本体のコードと重みは MIT。** ただし推論時に、以下が避けられない形で混ざる。

| コンポーネント | ライセンス | 商用利用 |
|---|---|---|
| Pixal3D（コード・重み） | MIT | 可 |
| nvdiffrast / nvdiffrec | NVIDIA Source Code License（1-Way Commercial） | 非商用中心。大規模な商用利用は別途 NVIDIA との合意が必要 |
| DINOv3（`camenduru/dinov3-vitl16-pretrain-lvd1689m` 経由） | Meta 独自ライセンス | 地域制限の有無が不明（下記） |
| 背景除去（`ZhengPeng7/BiRefNet`。上流既定の差し替え先） | MIT | 可 |

- **nvdiffrast / nvdiffrec** は差分レンダラとして推論経路に組み込まれており、外せない
  （`vendor/extensions/nvdiffrast`, `vendor/extensions/nvdiffrec` の `LICENSE.txt` を参照）。
- **DINOv3** はゲート付きの `facebook/dinov3-vitl16-pretrain-lvd1689m` の代わりに、
  非ゲートのミラー `camenduru/dinov3-vitl16-pretrain-lvd1689m` を使っている
  （`vendor/Pixal3D/inference_mv.py` の `IMAGE_COND_CONFIGS` がこのミラーを直接指定）。
  ミラーを使ってもライセンスは重みの実体（Meta の DINOv3）に紐づくため変わらない。
  HF のモデルカードに `extra_gated_eu_disallowed: true` が残っており、地域制限の有無は
  上流 Issue #33 で質問されたまま回答が無い。
- **背景除去モデルは RMBG-2.0（CC BY-NC 4.0、非商用限定）を使わない。**
  `pipeline_mv.json` は既定で RMBG-2.0 を指すが、ゲート付きで取得できないため、
  上記「背景除去モデルの差し替え」の通り MIT ライセンスの `ZhengPeng7/BiRefNet` を強制している。
  副次的に、この差し替えによって非商用制約が 1 つ外れている
  （ただし `trust_remote_code=True` で HF 上のコードを実行する点は変わらず残る）。

**→ nvdiffrast / nvdiffrec と DINOv3 の制約が残るため、出力を収益化する用途には使えない前提で
運用する。収益化するなら Hunyuan3D 側（`tools/hunyuan3d`。TENCENT HUNYUAN 3D 2.0 COMMUNITY
LICENSE、EU・UK・韓国を除き商用利用可）を使う。**

## 重みの置き場

すべて `tools/pixal3d/models/` の下に閉じ込めている（`.gitignore` 済み、約 30GB）。
**プレーンなローカルディレクトリではなく、`models/hf` の HF 標準キャッシュ（`HF_HOME`）に置く。**
実機で動作確認できたのがこの方式で、`Pixal3DMVImageTo3DPipeline.from_pretrained` には
ローカルパスではなく `TencentARC/Pixal3D`（`px3d/config.py` の `MODEL_REPO`）をリポジトリ ID の
ままで渡す。`vendor/Pixal3D/pixal3d/pipelines/base.py` の `from_pretrained` は
`os.path.exists(f"{path}/{config_file}")` でローカル判定するが、`path` がリポジトリ ID の文字列
だとこれは常に偽になり、`hf_hub_download` 経由でこの HF キャッシュから読みに行く。
プレーンディレクトリへ別途展開すると、キャッシュと合わせて重み約 24GB が二重に保存されてしまう。

- `models/hf` — `HF_HOME`。`huggingface_hub` の既定キャッシュ規約（`models--org--repo/snapshots/<ハッシュ>`）
  で、次の 3 つが入る。
  - `models--TencentARC--Pixal3D` — `pipeline_mv.json`（重みの入口）と、そこが指す
    `ckpts/*.json` / `*.safetensors`（形状・テクスチャの各段の重み 7 個）
  - `models--camenduru--dinov3-vitl16-pretrain-lvd1689m` — DINOv3 ミラー
  - `models--ZhengPeng7--BiRefNet` — 背景除去モデル
  - スナップショットのハッシュは取得のたびに変わり得るため固定できない。
    `px3d/cli.py` の `resolve_model_snapshot_dir()` が `snapshots/` の下を走査して選ぶ
    （`run-pixal3d doctor` の重み確認もここを通る）。
  - 既定の `~/.cache/huggingface` のままだと Open WebUI（all-MiniLM-L6-v2）と混ざるため、
    ここへ向けている

`rm -rf tools/pixal3d/models` で完全に初期化でき、`run-pixal3d fetch-models` で戻せる
（`huggingface_hub.snapshot_download` の既定の挙動により、既にキャッシュにあるファイルは
再取得しない。冪等）。

## Python 3.10 / torch cu126 / CUDA 12.6 を選んだ理由

`pyproject.toml` は `requires-python = ">=3.10,<3.11"`。venv は uv 管理の Python 3.10、
torch は `2.6.0+cu126`。CUDA は 2 つ入っており、`/usr/local/cuda`（13.2）は Hunyuan3D 用で
触らない。Pixal3D は **`/usr/local/cuda-12.6`** を使う（`px3d/config.py` の `CUDA_HOME`、
`PATH` に `cuda-12.6/bin` を前置する）。ネイティブ拡張（o-voxel / FlexGEMM / CuMesh /
nvdiffrast / nvdiffrec / natten）をこの CUDA でビルドする。

## flash_attn と MoGe を入れていない理由

- **flash_attn は入れない。`ATTN_BACKEND=sdpa` を使う**（`vendor/Pixal3D/README.md` が
  明記する代替経路）。`vendor/Pixal3D/inference_mv.py` は
  `os.environ.setdefault("ATTN_BACKEND", "flash_attn")` なので、`px3d.cli.build_serve_env` が
  子プロセス起動前に `ATTN_BACKEND=sdpa` を設定する（`setdefault` は上書きしないため、
  先に設定しておく必要がある）。
- **MoGe は入れない。** 単視点の画角推定（`inference.py` の `get_camera_params_wild_moge`）
  にしか使わず、このツールはカメラ姿勢が既知の複数視点（`inference_mv.py`）専用にしている。
  MoGe は `trimesh==4.10.1`（このリポジトリの固定版）と依存が衝突する。

## 試験

モック試験（GPU もネットワークも使わない。標準ライブラリ + pytest だけで動く。数秒）:

```bash
uvx --with pytest pytest tools/pixal3d/tests/test_units.py -q
```

`.venv` には pytest を入れない（壊さないため。`uvx` の一時環境で実行する）。

実機試験（UI を通さず GLB を作る。GPU と重みを使い数分かかる。VRAM を使うので先にサービスを止めること）:

```bash
systemctl --user stop pixal3d
tools/pixal3d/run-pixal3d generate --views-dir tools/pixal3d/vendor/Pixal3D/assets/mv_images/example \
  --out tools/pixal3d/outputs/smoke.glb
```

## 困ったときは

```bash
tools/pixal3d/run-pixal3d doctor
```

CUDA・venv・torch・上流コミット（Pixal3D / TRELLIS.2）・ネイティブ拡張・重み・背景除去モデル・
VRAM・ポート（7861 / 8080）・低 VRAM モード設定を 1 行 1 項目で `OK` / `NG` 表示する。
`systemctl --user is-active pixal3d` の結果も表示する（表示するだけで、操作はしない）。
