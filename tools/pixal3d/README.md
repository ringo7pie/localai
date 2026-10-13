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

サーバー IP は `<server-ip>`（例: 192.168.1.10）。起動後は `http://<server-ip>:7861` から使う。

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

## 頭頂が平らになる・足が崩れる問題と、前処理での対策

縦長の写真（人物が画面の上下いっぱい、背景は黒）で 4 視点生成すると、**頭頂が水平に切れて
平らになり、足も崩れる**ことがある。原因は上流（`vendor/Pixal3D`）の 2 つの設計にある。

1. `inference_mv.py:177` の `to_cond_tensor` が `image.resize((size, size))` するだけで、
   縦長画像を正方形へ**単純に引き伸ばす**（縦横比を保たない）。実測では、生成 GLB の
   幅/高さ比が 0.65 になった（人物なら本来 0.3 前後）。
2. `inference_mv.py:144` の `make_rembg` は「`transforms.json` が枠取りを表すので切り抜きも
   縮小もしない」設計。カメラは水平 FOV 20 度・距離 3.1192049980163574 の固定 orbit なので、
   画面の端は原点面で ±0.55、生成空間は ±0.5 しかない。つまり**画面の外周約 9% は生成空間の
   外**で、頭や足が画面の端にあると切り落とされる（実測: 生成 GLB の上端が 0.501 で生成空間の
   境界に張り付いていた）。

上流の作例画像（`vendor/Pixal3D/assets/mv_images/example/*.png`）は正方形 1024×1024 で、
物体が縦 83〜89%、上下に 5〜9% の余白を持つ構図になっている。上流の単画像経路
`Pixal3DImageTo3DPipeline.preprocess_image`
（`vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py:144`）も、alpha > 0.8 の外接矩形を
1.1 倍した正方形で切り出しており、そのまま引き伸ばしてはいない。

**対策（`px3d/framing.py` + `px3d/ui.py` の前処理）:** 4 視点それぞれの物体の外接矩形
（alpha > 0.8×255 の画素の外接矩形）から、**全視点で縮尺を揃えて**正方形キャンバス
（1024×1024）の中央へ余白付きで配置してから上流へ渡す。仰角 0 の周回カメラでは物体の高さが
どの方位でも変わらない前提を使う。

縮尺の求め方（`framing.compute_uniform_layout`）:

```
H = fill * canvas_size / max(1.0, max_i(幅_i / 高さ_i))
scale_i = H / 高さ_i
```

- `H` は「物体の高さ」の正規化先（ピクセル）。全視点の中で一番横長い視点でも、
  横幅が `fill * canvas_size` を超えないように決める。
- `scale_i` は視点ごとの縮尺。写真の解像度やズームが視点ごとに違っても、正規化後の
  物体の高さは全視点で揃う。
- 拡縮後の物体の外接矩形の中心がキャンバス中心に来るように貼り付け位置を決める。

前処理後の画像はアルファ付きで保存するため、上流の `inference_mv.load_views` 内の
`load_rgba` は背景除去をやり直さない（二重に背景除去しない）。

`px3d/framing.py` は torch / PIL / numpy を import しない純粋関数（`compute_uniform_layout` /
`build_sampler_params`）だけを置く。画素を実際に読む・PIL で描画する処理（外接矩形の検出、
リサイズと貼り付け）は numpy / PIL が要るため `px3d/ui.py` 側に置いている。

**`run-pixal3d generate`（CLI）にはこの前処理は掛からない。** CLI は準備済みの視点ディレクトリ
（`transforms.json` 付き）を上流へそのまま渡す経路なので、枠取りは利用者の責任のままになる。

## 画面の設定項目

| 区分 | 項目 | 範囲 / 選択肢 | 既定 |
|---|---|---|---|
| 基本 | 解像度 | 1024 / 1536 | 起動時の `--resolution`（低 VRAM モードなら 1024、それ以外は 1536） |
| 基本 | シード | 0〜2147483647 | 42 |
| 基本 | 毎回ランダム | オン/オフ | オフ |
| 前処理 | 物体の大きさ（画面に占める割合） | 0.60〜0.95 | 0.85 |
| 前処理 | 背景除去 | 自動（アルファが無いときだけ）/ 常に行う | 自動 |
| 詳細 | 疎構造: 手数 / guidance strength / guidance rescale / rescale t | 1〜50 / 1.0〜10.0 / 0.0〜1.0 / 1.0〜6.0 | 12 / 7.5 / 0.7 / 5.0 |
| 詳細 | 形状: 同上 | 同上 | 12 / 7.5 / 0.5 / 3.0 |
| 詳細 | テクスチャ: 同上 | 同上 | 12 / 1.0 / 0.0 / 3.0 |
| 詳細 | max_num_tokens | 16384〜65536 | 49152 |
| 書き出し | 面数の上限（decimation_target） | 100000〜1000000 | 1000000 |
| 書き出し | テクスチャ解像度 | 1024 / 2048 / 4096 | 4096 |
| 書き出し | リメッシュ | オン/オフ | オン |

既定値は `px3d/framing.py` の `DEFAULT_SETTINGS` に集約している（`px3d/ui.py` 側に数値を
重複させない）。「既定に戻す」ボタンでいつでも戻せる。生成後の状態表示に、使った全パラメータと
前処理で求めた視点ごとの縮尺を出す（再現できるように）。

解像度と `pipeline_type` の対応（`framing.build_sampler_params`）: 1024 → `"1024_cascade"`、
1536 → `"1536_cascade"`。TRELLIS.2 の単画像デモにある 512 は、多視点パイプライン
（`vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py` の `run`）が受け付けず `ValueError` になるため出していない。

## 設定の保存・読み込み（プリセット）

「書き出し設定」の下にある「設定の保存・読み込み」欄（既定で閉じている）から、画面の
「基本」「前処理」「詳細設定」「書き出し設定」の全項目をまとめて名前を付けて保存し、
あとから呼び出せる。画像枠の中身（4 方向の入力画像）は対象外（設定値だけを保存する）。

- **保存**: 名前を入力して「保存」。同じ名前で保存し直すと上書きする。
- **読み込み**: 一覧（五十音・アルファベット順）から選んで「読み込み」。画面の全項目が
  その内容に置き換わる。一覧を選ばずに押すと何もせず、その旨を表示する。
- **削除**: 一覧から選んで「削除」（元に戻せない）。

保存先は `tools/pixal3d/presets/<名前>.json`。**`.gitignore` には入れていないので git で追跡される**
（`.venv` や `models/` と違って小さく、あなたが作る資産なので、消えては困る・他の PC へ持って
行きたいため）。実体は `px3d/presets.py`（torch / gradio を import しない純粋関数のみ）。ファイルの
中身:

```json
{
  "format": 1,
  "tool": "pixal3d",
  "saved_at": "2026-09-24T12:34:56+09:00",
  "settings": { "resolution": 1536, "seed": 42, "fill": 0.85, "...": "..." }
}
```

`settings` は `px3d/framing.py` の `DEFAULT_SETTINGS` にあるキーだけを持つ。読み込み時は
`DEFAULT_SETTINGS` を土台にファイルの値で上書きするため、**設定項目が将来増減しても古い
ファイルを読める**（保存時に無かったキーは既定値のまま、ファイルにあって現在の画面に無い
キーは無視する）。値の型・範囲が既定値の想定（画面のスライダー・選択肢の範囲）から外れて
いる項目（壊れた手編集ファイルなど）は既定値に戻し、画面に「〇〇は範囲外だったので既定値
にしました」と表示する。

設定名に使えない文字は `/ \ : * ? " < > |` の 9 つと制御文字だけで、それ以外（全角の括弧や
かぎ括弧、全角空白など）は自由に使える。「高精細（試し）」のような自然な日本語の名前を
そのまま付けられるようにするため、許可制ではなく禁止制にしてある。禁止する文字は
Windows / SMB がファイル名に使えないものに合わせた（この `presets/` は git で追跡し、
リモートが Windows / SMB（CIFS）上にあっても push できるようにするため）。
あわせて、64 文字以内、`..` と先頭の `.`、末尾の半角空白と `.` も弾く。
（`px3d/presets.py` の `validate_preset_name`。`preset_path` が解決済みパスの二重確認も行う。）

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
   `PIXAL3D_LOW_VRAM` を書き換える想定（このファイルの所有者は入口ページと同じユーザー）
2. **env ファイルを直接編集**: `~/.config/pixal3d/pixal3d.env` の `PIXAL3D_LOW_VRAM` を
   `1`（On）/ `0`（Off）にして `systemctl --user restart pixal3d`
3. **手動起動時のフラグ**: `run-pixal3d serve --low-vram` / `run-pixal3d serve --no-low-vram`
   （env ファイルより優先する）

低 VRAM モードのとき、画面の解像度の既定値は 1024（それ以外は 1536）。

`run-pixal3d doctor` は現在の設定（env ファイルの値と、そこから決まる有効/無効）を表示する
（OK/NG の判定ではなく情報表示）。

### RAM の安全弁（MemoryMax）

`systemd/pixal3d.service.example` に `MemoryHigh` / `MemoryMax` を入れてある
（`tools/hunyuan3d/systemd` と同じ理由）。2026-09-24 時点の値は `MemoryHigh=44G` /
`MemoryMax=48G`（RAM 62.5 GiB の機体向け。それ以前は 31 GiB の機体向けに `24G` / `28G` だった。
低 VRAM モードは重みを CPU に置くため RAM を強く使い、この上限が低すぎると swap に張り付いたまま
生成が数十倍遅くなった実例があるため、機体の RAM に合わせて上げてある）。**超えたときに起きるのは
Pixal3D サービスだけが OOM kill されることで、デスクトップやほかのサービスを巻き込まない。**
運用中の値は入口ページ（`tools/portal`）から変えられる。

## 生成に失敗したときの読み方

生成中に例外が起きると、画面の状態表示欄（成功時に「生成しました: ...」を出す欄と同じ場所）に、
生の英語の例外だけでなく「どの設定を下げれば直りそうか」を日本語で診断した内容を表示する。
**`gr.Error`（赤帯）は使わない**（赤帯は短い 1 行向けで、長い診断は読みにくいため）。プレビューと
ダウンロードは空になるが、前処理（4 視点を正方形へ揃える処理）まで終わっていれば、前処理後の
画像はギャラリーに残る（どの画像で失敗したかが分かるように）。**正面画像が無い・物体が検出できない
などの入力ミスは、従来どおり `gr.Error` の赤帯のまま**（利用者がその場で直せるため、診断は挟まない）。

実装は `px3d/errors.py` の 3 つの純粋関数（`classify_failure` → `diagnose` →
`format_failure_markdown`、いずれも torch / gradio を import しない）と、それを呼ぶ
`px3d/ui.py` の `_generate` の `try/except`。標準エラーへは従来どおりトレースバック全文を出す
（`traceback.print_exc()`。画面の表示と二重になるが、握りつぶさない）。

`classify_failure` が例外の文字列から判定する失敗の種類:

| 種類 | 判定条件（例外の文字列にこれを含む） | 表示される内容 |
|---|---|---|
| `cuda_oom` | `CUDA out of memory` / `OutOfMemoryError` / `CUDA error: out of memory` | VRAM を減らす設定を効きの大きい順に列挙 |
| `host_oom` | `MemoryError` / `Cannot allocate memory` / `DefaultCPUAllocator: not enough memory` / `bad_alloc` | RAM を減らす設定を効きの大きい順に列挙 + MemoryHigh/MemoryMax の話 |
| `framing` | `px3d.framing.compute_uniform_layout` が投げる ValueError（「外接矩形」「fill」「canvas_size」のいずれかを含む） | 物体の大きさ（fill）を下げる提案 |
| `unknown` | 上記のどれにも一致しない | 設定のせいにはせず、例外をそのまま見せる（推測でパラメータのせいにしない） |

いまの値がそのパラメータの最小（これ以上下げようがない）なら、その項目は候補に出さない。
全部が最小のときは「設定はすべて最小です。入力画像の枚数を減らすか、Hunyuan3D を試してください」
と表示する。

### 効きの大きい順（実測に基づく）

`cuda_oom`（VRAM 不足）:

1. **低 VRAM モード**（画面には無く、入口ページ・env ファイルで切り替える設定。Off のときだけ
   最上位候補にする） — Off だと解像度 1536 で VRAM ピーク 23.12 GiB、1024 でも 23.32 GiB まで
   伸びて CUDA out of memory になった実測がある（A30 の VRAM は 24576 MiB）。On・解像度 1024・
   4 枚入力なら VRAM ピークは 16.8〜17.3 GiB に収まる。
2. **解像度**（1536 → 1024）
3. **max_num_tokens**（49152 → 32768 → 16384）
4. **テクスチャ解像度**（4096 → 2048 → 1024）
5. **面数の上限（decimation_target）**（1000000 → 500000）

`host_oom`（RAM 不足）:

1. **テクスチャ解像度**
2. **面数の上限（decimation_target）**
3. **リメッシュ**（Off にする）
4. **解像度**

`framing`（前処理の外接矩形計算の失敗）: **物体の大きさ（fill）** だけを候補にする（下げて余白を
増やす）。

`unknown`: 候補は出さない。元の例外の全文は、種類によらず常に画面下部の折りたたみ
（`<details>`）で見られる。

### 低 VRAM モードと入口ページのメモリ上限（MemoryHigh / MemoryMax）の関係

低 VRAM モードは VRAM 不足を RAM と引き換えに解決する設定（使わない段のモデルを CPU 側へ退避する）。
そのため `cuda_oom` を直そうとして低 VRAM モードを On にすると、今度は RAM 側の余裕が減り
`host_oom` に近づくことがある。`host_oom` の診断には、入口ページでこのサービスの `MemoryHigh` /
`MemoryMax` を上げる手も合わせて表示する（前節「RAM の安全弁（MemoryMax）」参照）。

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

## 画面の説明表示

各入力・ボタン・スライダー・チェックボックス・ラジオ・画像枠・アコーディオンに
マウスを載せると、ブラウザ標準のツールチップ（`title` 属性）で詳細説明が出る。
画面の文中に出てくる専門用語（VRAM、シード、疎構造、guidance strength など）は
点線の下線が付いたクリック可能な文字になっていて、クリックするとダイアログ
（`<dialog>` 要素。閉じるボタン・Esc・背景クリックのいずれでも閉じる）で見出しと
説明が開く。

説明文は `px3d/help_texts.py` に集約している（`TOOLTIPS` が elem_id → ツールチップ、
`GLOSSARY` が専門用語 → ダイアログの見出し・本文）。torch / gradio / PIL を
import しない純粋なデータと関数だけを置いてあるので、`px3d/ui.py` を import せず
（= GPU を使わず）試験できる。

**部品を足したら、`elem_id` と `px3d/help_texts.py` の説明も必ず足すこと。**
足し忘れると `tests/test_units.py` が落ちる（`ui.py` のソースから `elem_id="..."` と
`data-term="..."` をすべて拾い出し、`help_texts` に説明が無いものを検出する）。

注入方法: マウスオーバーの `title` 設定と専門用語クリックのダイアログはどちらも
`px3d/ui.py` が組み立てる JS（`_build_help_assets()`）で行い、
`demo.launch(css=..., js=...)`（Gradio 6.17.3 でこの版から `Blocks()` の引数から
`launch()` の引数に移った）で渡す。Gradio は画面を後から描画・再描画するため、
`title` の設定は `MutationObserver` で繰り返し、専門用語クリックは `document` への
イベント委譲にしてある（要素が作り直されても効く）。

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
