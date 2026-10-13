# hunyuan3d

画像から 3D メッシュ（形状＋テクスチャ）を生成する [Tencent Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)
を、このリポジトリの A30 サーバー上で動かすための一式。固定コミット
`f8db63096c8282cb27354314d896feba5ba6ff8a` を `vendor/Hunyuan3D-2` に取り込んで使う。

> **公開版について。** このリポジトリは Hunyuan3D-2 の本体・重み・上流への当て物（`patches/`）を含まない。
> 本体と重みは `setup-server.sh` が導入時に取得する。上流の使用許諾（Tencent Hunyuan 3D 2.0 Community License）は
> EU・英国・韓国を対象外とするため、導入には許諾の確認（`--accept-tencent-license`）が要る。当て物を含めない
> 理由と、そのために公開版で使えない機能は「上流への当て物」、許諾の要点と帰属表示は「ライセンスの地域制限」にある。

## ポートと入口ページの関係

- **7860**: Hunyuan3D-2 の gradio UI（このツール）
- 8080: 入口ページ（`tools/portal`。ここから 7860 へ飛べる）
- 8081: Open WebUI（入口ページ導入時に 8080 から移動済み）
- 8188: ComfyUI（`tools/comfyui`）

サーバー IP は `<server-ip>`（利用者の環境の値）。起動後は `http://<server-ip>:7860` から使う。

## Qwen（Ollama）との VRAM の取り合い

A30 の VRAM は 24576 MiB しかなく、Hunyuan3D と Qwen は**生成中は同時に載らない**。
実測値（2026-09-22）:

| 状態 | VRAM |
|---|---|
| Hunyuan3D の待機時（両パイプライン常駐） | 5,365 MiB |
| Hunyuan3D の生成ピーク | 11,487 MiB |
| qwen3.8:27b 単独（コンテキスト 65536） | 22,201 MiB |

**この道具は PC 起動時に自動で立ち上がる**（`systemctl --user enable hunyuan3d`。`Linger=yes` なので
ログインしなくても起動する）。そのため次の 2 つが起きる。

1. **Qwen は載るが遅くなる。** Hunyuan3D が 5,365 MiB を占有した状態では、Qwen は GPU 配置 67%
   （残り 33% は CPU）で 14.8 tok/s。単独時の 23〜26 tok/s より約 4 割遅い。Open WebUI のチャットは
   使えるが、速度が要るときは `systemctl --user stop hunyuan3d` で止める。
2. **3D 生成のときは、Qwen を VRAM から降ろしておく必要がある。** Qwen を載せたまま生成すると VRAM が足りず、
   実測で 23.7 秒後に CUDA out of memory になった。
   - `run-hunyuan3d serve` は、起動するときに Ollama のモデルを降ろす（公開版でも同じ）。
   - 生成の**直前**に毎回自動で降ろす処理は、上流への当て物 0001 の機能で、**公開版には無い**
     （「上流への当て物」を参照）。`serve` のあとに Qwen を使い、そのまま 3D 生成を始めると CUDA out of memory に
     なるので、生成の前に `run-hunyuan3d free-vram`（下記）を実行する。当て物 0001 を当てた環境では
     自動で降り、Qwen は次のチャットで自動的に戻る（ロードに約 60 秒）。

切り替えを手で行う場合:

- VRAM を空けるだけ: `run-hunyuan3d free-vram`
- Hunyuan3D を止めて Qwen を全速で使う: `systemctl --user stop hunyuan3d`
- 自動起動をやめる: `systemctl --user disable hunyuan3d`

## 上流への当て物（patches/）

上流（`vendor/Hunyuan3D-2`）に当てる差分が 5 本ある。固定コミットに対する `git apply` 用の差分で、
手元の `patches/*.patch` に置く。**公開版（このリポジトリの公開リポジトリと履歴）には含めない。**

### 公開版に含めない理由

当て物は上流のコードの行を含む差分で、Tencent Hunyuan 3D 2.0 Community License でいう派生物（Works）に
あたる。この許諾は配布を EU・英国・韓国を除く地域（Territory）に限る（「ライセンスの地域制限」）。
GitHub は閲覧・取得できる地域を絞れないため、当て物は公開リポジトリにも履歴にも載せない。
`tools/hunyuan3d/patches/` は `.gitignore` に入れてあり、手元のファイルはそのまま残る。

### 公開版で使えない機能

`setup-server.sh` は `patches/` に当て物が無ければ当て物の工程を飛ばす。そのとき上流は固定コミットの
ままで、次の機能は無い。

| 当て物 | 内容 | 公開版（当て物なし）の状態 |
|---|---|---|
| `0001-free-vram-before-generation` | 生成の直前に Ollama のモデルを降ろす（上記 2 の理由） | 生成前に自動で降りない。`serve` の起動時の解放と、手で実行する `run-hunyuan3d free-vram` だけ |
| `0002-select-multiview-tab` | MV モードで 4 枚の入力欄と例のギャラリーが表示されない不具合を直す | 不具合が残る（下記） |
| `0003-help-tooltips-and-glossary` | 画面の説明表示（日本語のマウスオーバーと専門用語の用語集。「画面の説明表示」） | 説明は出ない。上流の英語ラベルのまま |
| `0004-show-failing-parameters` | 失敗したときに、疑わしいパラメータを表示する（「生成に失敗したときの読み方」） | 上流の Gradio 標準のエラー表示のまま |
| `0005-save-load-presets` | 画面の設定に名前を付けて保存・読み込みする（「設定の保存・読み込み」） | 設定の保存・読み込みは無い |

`0002` は上流の不具合の修正である。上流は `gr.Tabs(selected='tab_img_prompt')` と
`gr.Tabs(selected='tab_img_gallery')` を固定で指定しているが、MV モードではその 2 つが `visible=False`
になるため、非表示のタブが選択されたままになり中身が描画されない。**当て物なしの公開版では、MV
モード（このツールの構成）で 4 枚の入力欄と例のギャラリーが見えない。** 手元で直すには、
`vendor/Hunyuan3D-2/gradio_app.py` の `MultiView Prompt` タブに `id='tab_mv_prompt'` を付け、2 か所の
`selected` を MV モードのときだけ MV 用のタブ（`tab_mv_prompt` と `tab_mv_gallery`）にする。
**直した内容は当て物にして `patches/` に置くこと**（`setup-server.sh` は再実行のたびに上流を固定
コミットへ戻すため、手編集のままだと消える。下記）。

`hy3d/help_texts.py`・`hy3d/errors.py`・`hy3d/presets.py` は、0003 / 0004 / 0005 が画面へ組み込む
自作のモジュール。当て物が無い環境ではどこからも import されない。

### 手元で当て物を使う

`tools/hunyuan3d/patches/` に `NNNN-名前.patch`（固定コミットに対する差分）を置くと、`setup-server.sh` が
番号順に `git apply` する。`patches/` は `.gitignore` 済みなので、置いても公開リポジトリには載らない。

1. `tools/hunyuan3d/patches/` を作り、当て物を置く（自分で作るか、手元に残っているものを戻す）
2. `tools/hunyuan3d/setup-server.sh --accept-tencent-license` を実行する。導入済みなら、上流を固定コミットへ
   戻してから当て物を当て直す
3. `systemctl --user restart hunyuan3d`

- 当て物があるとき、`setup-server.sh` は当てる前に上流を固定コミットへ戻す（`git checkout -- .`）。
  **`vendor/Hunyuan3D-2` を手で編集していると、その編集は消える。** 戻す前に変更の一覧を表示する。
  編集は必ず当て物にしてから実行する。当て物の作り方は
  `knowledge/10-silver/resources/hunyuan3d-upstream.md` にある。
- 当て物が当たると、試験（「試験」）のうち当て物の結果を確かめるものも走る（当たっていないと SKIP）。
- **自分で作った当て物を第三者へ配布するときも、同じ地域制限（原文の §3）と Notice の同梱（§3.d）が掛かる。**

## 導入

サーバー上で 1 回実行する（torch と重み合計 約23GB をダウンロードするので、実行前にディスクと
ネットワークを確認すること。**setup-server.sh はこの README を読んだ人が手で実行する**）。

```bash
tools/hunyuan3d/setup-server.sh --accept-tencent-license
```

`setup-server.sh` は、上流を取得する前に Tencent Hunyuan 3D 2.0 Community License の要約を表示する。
`--accept-tencent-license`（または環境変数 `HY3D_ACCEPT_LICENSE=1`）が無いと、**終了コード 2 で止まり、
上流の取得もモデルのダウンロードも行わない。** 付ける前に「ライセンスの地域制限」を読み、自分の利用が
Territory の内側で、条件（月間アクティブユーザー・出力の使い方）に当たらないことを確かめること。
許諾は、利用者がその条件を確認したうえで付けるもので、このスクリプトが代わりに同意するものではない。

オプション:

- `--accept-tencent-license`: 上記の許諾の確認（必須。`HY3D_ACCEPT_LICENSE=1` でも可）
- `--no-texture`: ネイティブ拡張のビルドとテクスチャ用の重み（約18GB）取得を省略し、形状生成のみにする
- `--skip-models`: 重みの取得を省略する（あとで `run-hunyuan3d fetch-models` を手で実行する）
- `--no-autostart`: PC 起動時の自動起動を有効にしない

導入後の点検: `tools/hunyuan3d/run-hunyuan3d doctor`

## 起動と停止

手動起動（フォアグラウンド。VRAM を確認してから gradio_app.py を起動する）:

```bash
tools/hunyuan3d/run-hunyuan3d serve
# テクスチャを無効化して VRAM を節約する場合
tools/hunyuan3d/run-hunyuan3d serve --no-texture
```

systemd user ユニット（`setup-server.sh` が `~/.config/systemd/user/hunyuan3d.service` を作成し、
**既定で自動起動を有効にする**。切りたいときは `setup-server.sh --no-autostart`）:

```bash
systemctl --user daemon-reload
systemctl --user start hunyuan3d
systemctl --user status hunyuan3d
systemctl --user stop hunyuan3d
```

## 4 枚の画像の撮り方（mv モード）

`tencent/Hunyuan3D-2mv` を使っているため、gradio UI には front / back / left / right の
4 枚の入力欄が出る（公開版では上流の不具合で出ない。「上流への当て物」の `0002`）。

- 正面・背面・左・右の 4 方向を、対象物を回転させずカメラを回して撮る（同一光源・同一距離が望ましい）
- 背景は黒か単色にする（背景が複雑だと形状推定の精度が落ちる）
- 4 枚全部を必ずしも用意しなくてもよいが、枚数が少ないほど背面・側面の形状精度は落ちる

## 出力の場所

`tools/hunyuan3d/outputs`（`gradio_app.py --cache-path` に渡している）。

## Python 3.11 を使う理由

`pyproject.toml` は `requires-python = ">=3.11,<3.12"` で、リポジトリ既定の Python 3.12 から
意図的に外している。Hunyuan3D-2 の実績ある pin（transformers 4.46.0、diffusers 0.30.0 など、
2024 年後半時点のバージョン）は cp312 wheel を持たないため、システム Python 3.12（かつ
`python3.12-dev` 不在でヘッダも無い）ではなく、ヘッダ同梱の **uv 管理 CPython 3.11** を使う。

## ライセンスの地域制限

Hunyuan3D-2（コード・重み・出力）は **Tencent Hunyuan 3D 2.0 Community License Agreement** のもとで
提供される。原文は上流リポジトリ直下の `LICENSE`（`setup-server.sh` の実行後は
`tools/hunyuan3d/vendor/Hunyuan3D-2/LICENSE`）で、重みの配布元（Hugging Face の `tencent/Hunyuan3D-2mv`・
`tencent/Hunyuan3D-2`）も同じ条件に従う。使用・複製・改変・配布した時点で、原文に同意したものとみなされる
（原文の冒頭）。**以下は要点で、原文が優先する。法的な助言ではない。**

- **地域**: 許諾は Territory（世界のうち、EU・英国（UK）・韓国を除く地域）に限られる（§1.l、§2）。
  **EU・UK・韓国は対象外**（日本は対象内）。Territory の外では、Works・出力・結果を使用・複製・改変・
  配布・表示してはならず、そうした使用は無許諾になる（§5.c）。配布も Territory 内に限る（§3 の柱書き）。
- **月間アクティブユーザー**: Tencent Hunyuan 3D 2.0 のリリース日（2025-01-21）の時点で、前の暦月の
  月間アクティブユーザー（利用者の全製品・サービスの合計）が **100 万人を超える**場合は、Tencent へ別途
  ライセンスを申請する必要があり、許諾されるまで権利を行使できない（§4。申請先は原文にある）。
- **出力の使い方**: Works や出力・結果を、**他の AI モデルの改善に使ってはならない**（§5.b。Tencent
  Hunyuan 3D 2.0 とその派生モデルは除く）。蒸留や合成データでの学習も、派生モデル（Model Derivatives）に
  あたるため同じ扱いになる（§1.g）。Tencent は出力に対する権利を主張せず、出力と、その後の使い方の責任は
  利用者が負う（§6.d）。
- **許容される使用のポリシー**: 法令と、原文の Exhibit A（Acceptable Use Policy）に従う（§5.a）。
- **配布するとき**: Works を第三者へ配布するときは、原文の写しを添え（§3.a）、改変したファイルに変更した旨を
  明記し（§3.b）、後述の Notice を含む「Notice」テキストファイルを同梱する（§3.d）。
- **サービスとして第三者へ提供するとき**: 実際の提供者の正式名称を利用者へ明示し、Tencent は提携・後援・
  推奨をしていないと明記する。Tencent の名称やロゴを、誤解を招く形で使ってはならない（§3.e）。

### 帰属表示（Notice）

> Tencent Hunyuan 3D 2.0 is licensed under the Tencent Hunyuan 3D 2.0 Community License Agreement, Copyright © 2025 Tencent. All Rights Reserved. The trademark rights of “Tencent Hunyuan” are owned by Tencent or its affiliate.

上の文言は、上流の `LICENSE` の §3.d にある Notice を原文のまま写したもの。このリポジトリは Tencent と
提携しておらず、Tencent の後援・承認を受けていない。このリポジトリ自身のライセンスと、第三者のソフトウェア・
モデルの扱いは、リポジトリ直下の `NOTICE.md` にある。

## 低 VRAM モード（HY3D_LOW_VRAM）

上流の `--low_vram_mode` は VRAM を RAM と引き換える設定（推論に使わないパイプラインを
都度 CPU 側へ退避する）。VRAM は節約できるが、RAM 31GiB の機体では過去に RAM を
食い潰してデスクトップごとハングしたことがある。**既定は On**（VRAM 優先の安全側）。

切り替え方は 3 通りあり、優先順位は `serve` の CLI フラグ → 環境変数 → 既定値（On）。

1. **入口ページのスイッチ**（`tools/portal`、8080 番）— `~/.config/hunyuan3d/hunyuan3d.env` の
   `HY3D_LOW_VRAM` を書き換える想定（このファイルの所有者は入口ページと同じ、サービスを動かす利用者）
2. **env ファイルを直接編集**: `~/.config/hunyuan3d/hunyuan3d.env` の `HY3D_LOW_VRAM` を
   `1`（On）/ `0`（Off）にして `systemctl --user restart hunyuan3d`
3. **手動起動時のフラグ**: `run-hunyuan3d serve --low-vram` / `run-hunyuan3d serve --no-low-vram`
   （env ファイルより優先する）

`run-hunyuan3d doctor` は現在の設定（env ファイルの値と、そこから決まる有効/無効）を表示する
（OK/NG の判定ではなく情報表示）。

### RAM の安全弁（MemoryMax）

`systemd/hunyuan3d.service.example` と実機のユニットに `MemoryHigh=44G` / `MemoryMax=48G` を
入れてある（2026-09-24 に RAM が 62.5 GiB になったのに合わせて 20G/22G から引き上げた）。
デスクトップと入口ページ、および Qwen が GPU から溢れる分に約 14 GiB を残す意図。
**運用中の値は入口ページ（`tools/portal`）の「メモリ上限」欄から変えられる。** そこで変えた値は
`systemctl set-property` の drop-in に入り、このユニットファイルの値より優先される。**超えたときに
起きるのは Hunyuan3D サービスだけが OOM kill されることで、デスクトップやほかのサービスを
巻き込まない**（ユニット単位のメモリ上限なので、cgroup の外は影響を受けない）。

対処:

- 低 VRAM モードを Off にする（VRAM に余裕を戻す代わりに、そもそも RAM を消費しないようにする）
- `run-hunyuan3d serve --no-texture` でテクスチャ生成を切る（下記）
- それでも越えるなら `MemoryMax` 自体を見直す

## テクスチャ生成が OOM したときの逃げ道

`run-hunyuan3d serve --no-texture` で形状生成のみに切り替える（`--disable_tex` を渡し、
`--texgen_model_path` を渡さない）。ネイティブ拡張（`custom_rasterizer` / `differentiable_renderer`）は
テクスチャ生成にのみ使うので、形状生成だけなら未ビルドでも動く。

## 画面の説明表示（当て物 0003。公開版には無い）

> 手元で当て物 0003 を当てた環境でだけ使える機能。公開版（当て物なし）では画面は上流のまま。

`patches/0003-help-tooltips-and-glossary.patch` が、上流の `gradio_app.py` の並び・動作・英語ラベルは
変えずに、次の 2 つを後付けで注入する。

- **マウスオーバー**: すべての入力・ボタン・スライダー・チェックボックス・ラジオ・ドロップダウン・
  画像枠・タブ・ダウンロードボタンに、日本語の詳細説明を `title` 属性として付ける。Gradio が後から
  描画・再描画するため `MutationObserver` で付け直す。
- **専門用語のクリック**: 画面下部に「専門用語の説明」という用語ボタンの行を足し、クリックすると
  `<dialog>` で見出しと本文を表示する（閉じるボタン・Esc・背景クリックで閉じる）。

説明文と用語集のデータは `hy3d/help_texts.py`（torch も gradio も import しない純粋なデータ）に
持ち、`gradio_app.py` からは `gr.Blocks(head=...)` 経由で JSON として画面へ埋め込む。外部 CDN は
使わない。データの追加・訂正は `hy3d/help_texts.py` の `TOOLTIPS` / `GLOSSARY` を編集し、
`tests/test_units.py` の `test_all_widget_labels_have_tooltips` で説明の付け忘れを検出する
（この試験は上流の `gradio_app.py` だけがあれば走る）。

## 生成に失敗したときの読み方（当て物 0004。公開版には無い）

> 手元で当て物 0004 を当てた環境でだけ使える機能。公開版（当て物なし）では、失敗は上流の Gradio 標準の
> エラー表示のまま。VRAM の目安は下の分類（CUDA out of memory / システムメモリ不足）を手で読み替える。

`patches/0004-show-failing-parameters.patch` が、`Gen Shape` / `Gen Textured Shape` / `Transform`
（書き出し）のいずれかが失敗したとき、`stats`（Mesh Statistic タブ）ではなく **Generated Mesh /
Exporting Mesh タブの出力欄**に、どのパラメータが疑わしいかを表示する。`gr.Error` の短い赤帯は
使わない（長い説明が読みにくいため）。判定は `hy3d/errors.py`（torch も gradio も import しない）が行う。

- 例外の文面から `cuda_oom`（CUDA out of memory）/ `host_oom`（システムメモリ不足）/ `unknown`
  （どちらとも判定できない）に分類する。`unknown` のときはパラメータのせいにせず、元の例外をそのまま見せる。
- `cuda_oom` の疑わしい順（実測。2026-09-22 の計測に基づく）:
  1. **テクスチャ生成そのもの** — `Gen Textured Shape` を使っていた場合。実測で形状のみ 21.7 秒・
     待機時 VRAM 5,365 MiB に対し、テクスチャ込みは 136.2 秒・生成ピーク VRAM 11,487 MiB。
     `Gen Shape`（形状のみ）に切り替えるとピークが大きく下がる。
  2. **Octree Resolution** — 上げるほど VRAM と時間が増える。既定の 256 より大きければ 256 へ。
  3. **Number of Chunks** — 大きいほど一度に処理する量が増えて VRAM を使う（実測。上げるのではなく
     下げる。8000 → 4000）。
  4. **Inference Steps** — VRAM への効きは小さいが、下げれば時間が減り再試行しやすい。
  - あわせて「Qwen（Ollama）が VRAM に載っていないか」「入口ページで Pixal3D が動いていないか
    （Hunyuan3D と Pixal3D は排他）」も案内する（Qwen は当て物 0001 で生成の直前に自動で降ろす）。
- `host_oom` の疑わしい順: ① Target Face Number（書き出し時の面数） ② Octree Resolution
  ③ テクスチャ生成の有無。入口ページでこのサービスの `MemoryHigh` / `MemoryMax`
  （既定 44G/48G、`systemd/hunyuan3d.service.example` 参照）を上げる手も案内する。
- 表示には、その生成で使った設定一覧（あとから何の値で失敗したか分かるように）と、元の例外の全文を
  `<details>` で折りたたんで含める。例外の文字列は `html.escape` している。

## 設定の保存・読み込み（当て物 0005。公開版には無い）

> 手元で当て物 0005 を当てた環境でだけ使える機能。公開版（当て物なし）には、設定を保存・読み込む欄が無い。

`patches/0005-save-load-presets.patch` が、画面の左列（Advanced Options / Export タブの下）に
**「設定の保存・読み込み」**という `gr.Accordion`（既定は閉じる）を足す。上流の既存の並び・動作・
英語ラベルは変えず、後付けで足すだけ。

- 保存対象は 11 項目: Inference Steps・Guidance Scale・Seed・Randomize seed・Octree Resolution・
  Remove Background・Number of Chunks・File Type・Simplify Mesh・Include Texture・
  Target Face Number
- **保存**: 「設定名」に入力した名前で、そのときの 11 項目の値を JSON として
  `tools/hunyuan3d/presets/<設定名>.json` に書く（同名があれば上書き）
- **保存済みの設定**（`gr.Dropdown`）: 保存済みの名前の一覧。保存・削除のたびに選択肢を更新する
- **読み込み**: ドロップダウンで選んだ設定を 11 項目すべてに反映する。保存後に項目が増減していても、
  無いキーは無視し、足りないキーは既定値のまま埋める。型・範囲が外れた値（例:
  `octree_resolution=9999`）は既定値に戻し、戻した項目名を結果表示に出す
- **削除**: ドロップダウンで選んだ設定ファイルを削除する（元に戻せない）
- 失敗（設定名が不正・ファイルが無い・JSON が壊れている等）は `gr.Error` ではなく結果表示の
  `gr.Markdown` に理由を出す（当て物 0004 と同じ方針）。例外は握りつぶさず
  `traceback.print_exc()` も出す
- ロジックは `hy3d/presets.py`（torch も gradio も import しない）が持つ。
  設定名に使えない文字は `/ \ : * ? " < > |` の 9 つと制御文字だけで、それ以外（全角の括弧や
  かぎ括弧、全角空白など）は自由に使える。「高精細（試し）」のような自然な日本語の名前を
  そのまま付けられるようにするため、許可制ではなく禁止制にしてある。禁止する文字は
  Windows / SMB がファイル名に使えないものに合わせた（`presets/` を Windows や SMB 共有に置いたり
  git で別の PC へ持って行ったりしても、Windows で無効な名前で困らないようにするため）。
  あわせて、64 文字以内、`..` と先頭の `.`、末尾の半角空白と `.` も弾く。
- 保存先は `tools/hunyuan3d/presets/<名前>.json`。`.gitignore` には入れていない（重みや出力と違って
  小さく、あなたが作る資産なので、消えては困る・他の PC へ持って行きたいため）。**公開リポジトリの
  作業コピーで `presets/` を push すると、設定名がそのまま公開される。** 公開したくない名前を付けた
  ときは、`presets/` を自分の `.git/info/exclude` に書いて追跡から外す。

## 試験

モック試験（GPU もネットワークも使わない。数秒）:

```bash
tools/hunyuan3d/.venv/bin/python -m pytest tools/hunyuan3d/tests/test_units.py -q
# venv が無い公開版の作業コピーでも、hy3d は標準ライブラリだけなので uv の一時環境で走る
uvx --with pytest pytest tools/hunyuan3d/tests/test_units.py -q
```

上流の `gradio_app.py` を読む試験は、上流（`vendor/Hunyuan3D-2`）が取得されていなければ SKIP になる。
当て物の結果（説明表示・失敗の診断・設定の保存と読み込みの組み込み）を確かめる試験は、当て物が当たって
いなければ SKIP になる（公開版には当て物が無いので、普通の状態）。失敗にはならない。

公開版の状態（上流が無い）を再現して全体を流すときは、環境変数 `HY3D_TEST_VENDOR_DIR` に存在しない
パスを渡す。当て物の無い上流を置いたディレクトリを渡せば、「上流はあるが当て物は無い」状態になる:

```bash
HY3D_TEST_VENDOR_DIR=/存在しないパス tools/hunyuan3d/.venv/bin/python -m pytest tools/hunyuan3d/tests/test_units.py -q
```

実機試験（4 ビュー → GLB まで実際に通す。GPU と重みを使い数分かかる。
VRAM を使うので先にサービスを止めること）:

```bash
systemctl --user stop hunyuan3d
tools/hunyuan3d/.venv/bin/python tools/hunyuan3d/tests/test_generate_real.py
# 形状だけ確かめる
tools/hunyuan3d/.venv/bin/python tools/hunyuan3d/tests/test_generate_real.py --no-texture
```

上流が同梱している例画像（`vendor/Hunyuan3D-2/assets/example_mv_images/2`、front / left / back）を
入力に使い、`outputs/smoke/` へ GLB を書く。段階ごとの所要時間と VRAM のピークを表示する。
gradio UI 側でも同じ例画像が Examples として選べるので、手で試すときはそれを使うのが早い。

## 重みと実行時キャッシュの置き場

すべて `tools/hunyuan3d/models/` の下に閉じ込めている（`.gitignore` 済み、約 22GB）。

- `models/tencent/Hunyuan3D-2mv/hunyuan3d-dit-v2-mv/` — 形状モデル
- `models/tencent/Hunyuan3D-2/hunyuan3d-vae-v2-0-turbo/` — `--enable_flashvdm` が使う VAE
- `models/tencent/Hunyuan3D-2/hunyuan3d-delight-v2-0/`, `hunyuan3d-paint-v2-0-turbo/` — テクスチャ
- `models/hf` — `HF_HOME`。上流が実行時に落とすもの。既定のままだと Open WebUI と共有している
  `~/.cache/huggingface` に混ざるため、ここへ向けている
- `models/u2net` — `U2NET_HOME`。rembg（背景除去）の u2net.onnx（168MB）

`rm -rf tools/hunyuan3d/models` で完全に初期化でき、`run-hunyuan3d fetch-models` で戻せる。

## 困ったときは

```bash
tools/hunyuan3d/run-hunyuan3d doctor
```

venv・torch・CUDA・上流コミット・ネイティブ拡張・重み・VRAM・ポートの空きを 1 行 1 項目で
`OK` / `NG` 表示する。ネイティブ拡張が NG でも「テクスチャ生成のみ不可」であることが文言でわかる。
