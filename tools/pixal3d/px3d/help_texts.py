"""Pixal3D 画面（px3d/ui.py）のマウスオーバー説明と専門用語集。

torch / gradio / PIL のいずれも import しない純粋なデータと関数だけを置く
（config.py / options.py / framing.py と同じ設計方針。`uvx --with pytest` の
一時環境で torch なしで試験が走ることを前提にしている）。

## この 2 つの辞書の役割

- `TOOLTIPS`: `px3d/ui.py` の各部品に付けた `elem_id` → マウスを載せたときに出す
  詳細説明（ブラウザ標準の `title` 属性として注入する）。
- `GLOSSARY`: 画面の文中に埋め込んだ `data-term="..."` の値 → クリックしたときに
  ダイアログへ出す見出しと本文。

`px3d/ui.py` に部品や用語を足したときは、必ずこの 2 つの辞書にも足すこと。
足し忘れは `tests/test_units.py` が検出する（`missing_tooltips` / `data-term` の
突き合わせ）。

## 説明文の根拠について

ここに書く数値・挙動は、コード（`vendor/Pixal3D/`、`vendor/TRELLIS.2/`）と
これまでの実測から分かることだけにする。上流の内部実装まで踏み込む説明は、
根拠になったファイル・実測条件を本文中に書く。
"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# マウスオーバー説明（elem_id → title 属性に入れる文章）
# ---------------------------------------------------------------------------

TOOLTIPS: dict[str, str] = {
    # ---- 4 視点の画像枠 ------------------------------------------------
    "front_input": (
        "正面（0°）の画像。4 枠のうち**唯一の必須項目**です。Pixal3D の "
        "check_main_view が frame 0 を正面前提で扱い、以後の視点をすべて frame 0 "
        "基準で配置するため、ここが無い・ズレていると出力全体の向きが崩れます。"
    ),
    "right_input": (
        "右 90° の画像。無くても生成できますが、右側面の形状・テクスチャの精度が"
        "落ちます。撮影時の物体の大きさ・向きは正面と揃えてください（同じ縮尺に"
        "自動で揃えますが、極端に離れた距離から撮ると輪郭の検出精度が落ちます）。"
    ),
    "back_input": (
        "背面 180° の画像。無くても生成できますが、背面の形状・テクスチャの精度が"
        "落ちます（背面だけが無いと背中側がのっぺりした推測形状になりやすい）。"
    ),
    "left_input": (
        "左 270° の画像。無くても生成できますが、左側面の形状・テクスチャの精度が"
        "落ちます。右と左の両方があると側面の対称性の精度が上がります。"
    ),
    # ---- 基本 -----------------------------------------------------------
    "resolution_input": (
        "生成に使うパイプラインの種類（1024_cascade / 1536_cascade）。多視点パイプ"
        "ラインはこの 2 つしか受け付けません（単画像用の 512 / 1024 はここでは使えま"
        "せん）。1536 の方が高精細ですが VRAM を多く使います。低 VRAM モードでは"
        "既定が 1024 になります（実測: 4 枚・1024・低 VRAM で VRAM ピーク約"
        "16.8〜17.3 GiB、所要約 150〜200 秒。低 VRAM を切ると 1024 でも VRAM が"
        "23 GiB を超え CUDA out of memory になりました）。"
    ),
    "seed_input": (
        "乱数のシード（0〜2147483647）。同じ入力画像・同じ設定・同じシードなら同じ"
        "結果になります。値を変えると同じ入力でも別の形状・テクスチャの候補が出ます。"
        "「毎回ランダム」がオンのときは、生成のたびにここへ実際に使ったシードが"
        "書き戻されます（再現用）。"
    ),
    "randomize_seed_input": (
        "オンにすると、生成のたびにシードを 0〜2147483647 の乱数で決め直します"
        "（このときシード欄の値は無視されます）。結果を再現したいときはオフにして"
        "シードを固定してください。"
    ),
    # ---- 前処理 -----------------------------------------------------------
    "fill_input": (
        "前処理で物体をキャンバスに収める大きさ（0.60〜0.95）。既定 0.85 は上流の"
        "作例画像（縦 83〜89%）に合わせた値です。カメラは水平 FOV 20 度・距離"
        "3.1192、生成空間は原点面で ±0.5 なのに対し画面の端は ±0.55 相当（画面外周"
        "約 9% は生成空間の外）なので、0.91 を超えるとここからはみ出して頭や足が"
        "切れます。小さくしすぎると物体が小さく写り過ぎて細部の精度が落ちます。"
    ),
    "bg_removal_input": (
        "背景除去の方式。「自動」はアルファ（透過）が無い画像だけ背景を除去し、"
        "既にアルファ付きの画像はそのまま使います。「常に行う」はアルファの有無に"
        "関わらず毎回背景除去モデル（BiRefNet）を通します。背景が単色でない写真や、"
        "透過済みのつもりが実は不完全な画像のときは「常に行う」を試してください。"
    ),
    # ---- 詳細設定（サンプラー）：疎構造 ------------------------------------
    "ss_steps_input": (
        "疎構造（sparse structure）段のサンプリング手数（1〜50、既定 12）。"
        "拡散サンプリングの反復回数で、多いほど 1 回の生成にかかる時間が伸びます"
        "（vendor/Pixal3D の FlowEulerSampler.sample が steps 回の Euler 積分を"
        "行う実装）。既定の 12 は上流 CLI の既定値をそのまま踏襲しています。"
    ),
    "ss_guidance_strength_input": (
        "疎構造段の guidance strength（CFG、1.0〜10.0、既定 7.5）。条件あり予測と"
        "条件なし予測を `guidance_strength * 条件あり + (1-guidance_strength) * "
        "条件なし` で混ぜる重みです"
        "（vendor/Pixal3D/pixal3d/pipelines/samplers/classifier_free_guidance_mixin.py）。"
        "1 なら純粋に条件あり予測のみ、大きくするほど入力画像への忠実さが増しますが"
        "上げすぎると破綻しやすくなります。"
    ),
    "ss_guidance_rescale_input": (
        "疎構造段の guidance rescale（0.0〜1.0、既定 0.7）。guidance strength を"
        "上げたときに信号が過度に飽和するのを抑える補正で、条件あり予測の標準偏差に"
        "合わせて出力を再スケールします（同じ classifier_free_guidance_mixin.py の"
        "実装）。0 なら補正なし、1 に近いほど強く補正します。"
    ),
    "ss_rescale_t_input": (
        "疎構造段の rescale t（1.0〜6.0、既定 5.0）。サンプリングの時刻列 t を "
        "`rescale_t * t / (1 + (rescale_t-1) * t)` で歪める係数です"
        "（vendor/Pixal3D/pixal3d/pipelines/samplers/flow_euler.py の "
        "FlowEulerSampler.sample）。1.0 なら歪めず均等割り、大きくするほどサンプリ"
        "ング序盤（ノイズが多い段階）に手数を厚く配分します。"
    ),
    # ---- 詳細設定（サンプラー）：形状 SLat --------------------------------
    "shape_steps_input": (
        "形状（shape SLat）段のサンプリング手数（1〜50、既定 12）。形状 SLat は"
        "メッシュの形（ジオメトリ）を決める潜在表現で、その段のサンプリング反復"
        "回数です。意味は疎構造段の手数と同じで、多いほど時間がかかります。"
    ),
    "shape_guidance_strength_input": (
        "形状段の guidance strength（既定 7.5）。意味は疎構造段と同じ CFG の"
        "混合重みで、形状 SLat の生成に対して働きます。"
    ),
    "shape_guidance_rescale_input": (
        "形状段の guidance rescale（既定 0.5）。意味は疎構造段と同じ CFG 補正で、"
        "形状 SLat の生成に対して働きます。"
    ),
    "shape_rescale_t_input": (
        "形状段の rescale t（既定 3.0）。意味は疎構造段と同じ時刻スケジュールの"
        "歪め係数で、形状 SLat の生成に対して働きます。"
    ),
    # ---- 詳細設定（サンプラー）：テクスチャ SLat --------------------------
    "tex_steps_input": (
        "テクスチャ（tex SLat）段のサンプリング手数（1〜50、既定 12）。テクスチャ"
        "SLat は色・質感（PBR テクスチャの元になる潜在表現）を決める段で、その"
        "サンプリング反復回数です。"
    ),
    "tex_guidance_strength_input": (
        "テクスチャ段の guidance strength（既定 1.0）。他の 2 段（既定 7.5）より"
        "かなり低い値が上流の既定になっています。guidance_strength=1 は"
        "「条件あり予測のみを使い CFG 補間をしない」という意味です"
        "（classifier_free_guidance_mixin.py の `if guidance_strength == 1` 分岐）。"
    ),
    "tex_guidance_rescale_input": (
        "テクスチャ段の guidance rescale（既定 0.0）。0 は補正なしという意味です"
        "（既定でテクスチャ段は guidance_strength=1 のため CFG 補間自体が働かず、"
        "この値の影響も出ません）。"
    ),
    "tex_rescale_t_input": (
        "テクスチャ段の rescale t（既定 3.0）。意味は疎構造段と同じ時刻スケジュール"
        "の歪め係数で、テクスチャ SLat の生成に対して働きます。"
    ),
    "max_num_tokens_input": (
        "パイプラインに渡す最大トークン数（16384〜65536、既定 49152）。"
        "run_mv の max_num_tokens 引数にそのまま渡します。値を大きくするほど複雑な"
        "形状・細部を扱える余地が増えますが、VRAM 使用量と所要時間も増えます。"
        "小さくしすぎると複雑な形状で情報が欠落することがあります。"
    ),
    # ---- 書き出し設定 ------------------------------------------------------
    "decimation_target_input": (
        "書き出す GLB の目標頂点数（100000〜1000000、既定 1000000）。"
        "o_voxel.postprocess.to_glb の decimation_target 引数（'target number of "
        "vertices for mesh simplification'）で、生成した密なメッシュをこの数まで"
        "間引きます。小さくするほどファイルが軽くなりますが、細部が失われます。"
    ),
    "texture_size_input": (
        "書き出す GLB のテクスチャ解像度（1024 / 2048 / 4096、既定 4096）。"
        "o_voxel.postprocess.to_glb の texture_size 引数（'size of the texture for "
        "baking'）です。大きいほど質感は精細になりますが、ファイルサイズと焼き込み"
        "の処理時間が増えます。"
    ),
    "remesh_input": (
        "オンにすると o_voxel.postprocess.to_glb がリメッシュ（remesh_band=1, "
        "remesh_project=0 で再メッシュ化）を行ってから UV 展開・テクスチャ焼き込み"
        "をします。三角形の分布が整い、UV 展開の破綻が減りやすくなりますが、"
        "その分の処理時間がかかります。既定でオンです。"
    ),
    # ---- ボタン -------------------------------------------------------
    "generate_button": (
        "現在の設定で 3D メッシュの生成を開始します。生成の直前に Ollama の常駐"
        "モデルを解放してから始めます（VRAM の取り合いを避けるため）。正面画像が"
        "無いとここを押した時点でエラーになります。"
    ),
    "reset_button": (
        "「基本」「前処理」「詳細設定」「書き出し設定」の全項目を既定値に戻します"
        "（`px3d/framing.py` の DEFAULT_SETTINGS。画像枠の中身は変わりません）。"
    ),
    # ---- アコーディオン -------------------------------------------------
    "sampler_accordion": (
        "疎構造・形状 SLat・テクスチャ SLat の 3 段それぞれについて、サンプリング"
        "手数と CFG 関連の 3 つの値（guidance strength / guidance rescale / "
        "rescale t）と、共通の max_num_tokens を調整できます。通常は既定値のまま"
        "で構いません。生成結果の質や壊れ方を細かく調整したいときに開いてください。"
    ),
    "export_accordion": (
        "生成した密なメッシュを GLB ファイルへ書き出すときの、面数の上限・"
        "テクスチャ解像度・リメッシュの有無を調整できます。ファイルサイズや"
        "後段のツールでの扱いやすさを優先したいときに開いてください。"
    ),
    # ---- 設定の保存・読み込み -------------------------------------------
    "preset_accordion": (
        "現在の設定一式を名前を付けて保存し、あとから呼び出せる機能です。保存先は "
        "tools/pixal3d/presets/ 配下の JSON ファイル（px3d/presets.py）。画像枠の"
        "中身は保存・読み込みの対象に含まれません。"
    ),
    "preset_name_input": (
        "保存する設定に付ける名前です。使えるのは日本語（ひらがな・カタカナ・漢字・"
        "長音「ー」）、英数字、空白、_、-、(、) のみで、64 文字以内にしてください"
        "（/ や .. など、保存先の外を指しかねない文字は使えません）。"
    ),
    "save_preset_button": (
        "いま画面にある「基本」「前処理」「詳細設定」「書き出し設定」の全項目を、"
        "左の名前でファイルに保存します（同じ名前で保存し直すと上書きします）。"
    ),
    "preset_dropdown": (
        "保存済みの設定の一覧です（五十音・アルファベット順）。ここで選んだ名前に"
        "「読み込み」「削除」ボタンが働きます。"
    ),
    "load_preset_button": (
        "一覧で選んだ設定をファイルから読み込み、画面の各項目に反映します。設定"
        "項目が保存時から増減していても、無いキーは既定値のまま、知らないキーは"
        "無視します。値が範囲外だった項目は既定値に戻し、その旨を下に表示します。"
    ),
    "delete_preset_button": (
        "一覧で選んだ設定のファイルを削除します（元に戻せません）。画像枠や"
        "現在の画面の値には影響しません。"
    ),
    "preset_status_output": (
        "設定の保存・読み込み・削除の結果を表示します（例:「保存しました: 〇〇」"
        "「〇〇は範囲外だったので既定値にしました」）。"
    ),
}


# ---------------------------------------------------------------------------
# 専門用語集（data-term の値 → ダイアログの見出しと本文）
# ---------------------------------------------------------------------------

GLOSSARY: dict[str, dict] = {
    "VRAM": {
        "title": "VRAM（GPU のメモリ）",
        "body": (
            "GPU（NVIDIA A30）が持つ専用メモリ。搭載量は 24576 MiB。\n\n"
            "Pixal3D はモデルの重みと、生成中の中間データ（潜在表現・メッシュ・"
            "テクスチャ）をここに載せて計算します。実測では、4 枚・解像度 1024・"
            "低 VRAM モードで VRAM ピークが約 16.8〜17.3 GiB でした。低 VRAM モード"
            "を切ると 1024 でも 23 GiB を超え、CUDA out of memory になることを"
            "実機で確認しています。\n\n"
            "同じ A30 を Qwen（Ollama）と共有しているため、生成の直前に Ollama の"
            "常駐モデルを解放しています（px3d/ui.py の "
            "_unload_ollama_before_generate）。"
        ),
    },
    "低VRAMモード": {
        "title": "低 VRAM モード",
        "body": (
            "使わない段のモデルを CPU 側（RAM）に退避し、必要な段だけをその都度 "
            "GPU に載せる設定（Pixal3D の low_vram=True）。VRAM の使用量を RAM と"
            "引き換えに減らします。\n\n"
            "既定は有効（VRAM 優先の安全側）。切り替えは 3 通りあり、優先順位は"
            "「起動時のコマンドライン引数（--low-vram / --no-low-vram）」→"
            "「環境変数 PIXAL3D_LOW_VRAM」→「既定値（有効）」です"
            "（README『低 VRAM モード（PIXAL3D_LOW_VRAM）』参照）。\n\n"
            "有効なときは画面の解像度の既定値が 1024 になります（無効なら 1536）。"
            "実測: 4 枚・解像度 1024・有効で VRAM ピーク約 16.8〜17.3 GiB、所要"
            "約 150〜200 秒。無効にすると 1024 でも VRAM が 23 GiB を超え CUDA "
            "out of memory になりました。"
        ),
    },
    "シード": {
        "title": "シード（乱数のシード）",
        "body": (
            "生成に使う乱数生成器の初期値。px3d/ui.py の _generate が生成直前に "
            "torch.manual_seed(int(seed)) を呼びます。\n\n"
            "同じ入力画像・同じ設定・同じシードなら同じ結果が再現できます。値を"
            "変えると、同じ入力からでも別の形状・テクスチャの候補が出ます。"
            "「毎回ランダム」をオンにすると、生成のたびに 0〜2147483647 の乱数を"
            "選び、実際に使った値をシード欄へ書き戻します（あとから同じ結果を"
            "再現したいときのため）。"
        ),
    },
    "解像度": {
        "title": "解像度（1024_cascade / 1536_cascade）",
        "body": (
            "生成に使うパイプラインの種類を選ぶ設定。多視点パイプライン"
            "（vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py の run）は "
            "'1024_cascade' と '1536_cascade' の 2 種類しか受け付けません"
            "（単画像用の '512' / '1024' はここでは使えず ValueError になります）。\n\n"
            "1536 の方が高精細ですが、VRAM 使用量と所要時間が増えます。低 VRAM"
            "モードでは既定が 1024 になります。"
        ),
    },
    "背景除去": {
        "title": "背景除去（BiRefNet）",
        "body": (
            "写真から物体だけを切り出す（アルファ付きにする）処理。Pixal3D の "
            "pipeline_mv.json は既定で briaai/RMBG-2.0（BiRefNet 系）を指しますが、"
            "この重みは HF のゲート付きリポジトリで、ログインと同意が無いと "
            "401 GatedRepoError になりダウンロードできません（実機で確認済み）。\n\n"
            "そのため px3d/rembg_override.py が、パイプライン読み込み前に非ゲート・"
            "MIT ライセンスの ZhengPeng7/BiRefNet へ差し替えています"
            "（README『背景除去モデルの差し替え』参照）。\n\n"
            "画面の「自動」はアルファ（透過）が無い画像だけ背景除去を行い、"
            "「常に行う」は既にアルファ付きの画像にも毎回背景除去モデルを通します。"
        ),
    },
    "物体の大きさ": {
        "title": "物体の大きさ（fill）と生成空間 ±0.5",
        "body": (
            "前処理で物体をキャンバスに収める大きさの割合（px3d/framing.py の "
            "compute_uniform_layout。0.60〜0.95、既定 0.85）。\n\n"
            "上流の作例画像（vendor/Pixal3D/assets/mv_images/example/*.png）は"
            "正方形 1024×1024 で、物体が縦 83〜89% を占める構図になっており、"
            "既定 0.85 はこれに合わせています。\n\n"
            "生成に使うカメラは水平 FOV 20 度・距離 3.1192049980163574 の固定"
            "orbit で、生成空間は原点面で ±0.5 しかないのに対し、カメラ画面の端は"
            "原点面で ±0.55 相当（画面の外周約 9% は生成空間の外）。実測でも生成"
            "GLB の上端が 0.501 と生成空間の境界に張り付いていたことを確認して"
            "います。fill を 0.91 より大きくすると、物体の外接矩形が画面の外周"
            "9% の帯にかかり始め、頭頂や足が生成空間の外に出て切れます。"
        ),
    },
    "疎構造": {
        "title": "疎構造（sparse structure）",
        "body": (
            "3D 生成の 1 段目。TRELLIS.2 系パイプラインが最初に作る、荒い占有"
            "情報（どの位置に物体があるか）の潜在表現です。この段のサンプリング"
            "結果を土台に、次の形状 SLat・テクスチャ SLat が作られます"
            "（px3d/framing.py の build_sampler_params が "
            "sparse_structure_sampler_params として steps / guidance_strength / "
            "guidance_rescale / rescale_t を run_mv に渡します）。"
        ),
    },
    "形状SLat": {
        "title": "形状 SLat（shape structured latent）",
        "body": (
            "3D 生成の 2 段目。疎構造を土台に、メッシュの形（ジオメトリ）を決める"
            "潜在表現（SLat）を作ります。run_mv にはこの段用の手数・guidance "
            "strength・guidance rescale・rescale t を "
            "shape_slat_sampler_params として渡します（既定 12 / 7.5 / 0.5 / 3.0）。"
        ),
    },
    "テクスチャSLat": {
        "title": "テクスチャ SLat（texture structured latent）",
        "body": (
            "3D 生成の 3 段目。形状が決まったあと、色・質感（PBR テクスチャの元に"
            "なる潜在表現）を決める段です。run_mv にはこの段用の手数・guidance "
            "strength・guidance rescale・rescale t を tex_slat_sampler_params と"
            "して渡します（既定 12 / 1.0 / 0.0 / 3.0）。他の 2 段より guidance "
            "strength が低いのが上流の既定です。"
        ),
    },
    "手数": {
        "title": "サンプリングの手数（steps）",
        "body": (
            "疎構造・形状 SLat・テクスチャ SLat の各段で行う拡散サンプリングの"
            "反復回数（1〜50、既定 12）。vendor/Pixal3D の "
            "FlowEulerSampler.sample が steps 回の Euler 積分を行う実装で、"
            "手数を増やすほど 1 回の生成にかかる時間が伸びます。既定の 12 は"
            "上流 CLI（inference_mv.py）の既定値をそのまま踏襲しています。"
        ),
    },
    "guidance strength": {
        "title": "guidance strength（CFG の強さ）",
        "body": (
            "classifier-free guidance（CFG）の強さを決める重み（1.0〜10.0）。\n\n"
            "vendor/Pixal3D/pixal3d/pipelines/samplers/classifier_free_guidance_mixin.py "
            "の実装では、条件あり予測 pred_pos と条件なし予測 pred_neg を\n\n"
            "pred = guidance_strength * pred_pos + (1 - guidance_strength) * pred_neg\n\n"
            "で混ぜます。guidance_strength=1 なら条件あり予測のみ（CFG 補間なし）、"
            "0 なら条件なし予測のみになります。値を上げるほど入力画像への忠実さが"
            "増しますが、上げすぎると guidance rescale で補正が必要なほど信号が"
            "飽和することがあります。3 段の既定値は疎構造 7.5・形状 7.5・"
            "テクスチャ 1.0 です。"
        ),
    },
    "guidance rescale": {
        "title": "guidance rescale",
        "body": (
            "guidance strength を上げたときに起きる信号の過飽和を抑える補正の"
            "強さ（0.0〜1.0）。\n\n"
            "vendor/Pixal3D/pixal3d/pipelines/samplers/classifier_free_guidance_mixin.py "
            "の実装では、条件あり予測だけから求めた x_0 の標準偏差に合わせて、"
            "CFG 適用後の x_0 を再スケールします\n\n"
            "x_0 = guidance_rescale * x_0_rescaled + (1 - guidance_rescale) * x_0_cfg\n\n"
            "0 なら補正なし、1 に近いほど強く補正します。3 段の既定値は疎構造 0.7・"
            "形状 0.5・テクスチャ 0.0（テクスチャ段は既定で guidance_strength=1 の"
            "ため、この値自体が効きません）。"
        ),
    },
    "rescale t": {
        "title": "rescale t",
        "body": (
            "サンプリングの時刻スケジュールを歪める係数（1.0〜6.0）。\n\n"
            "vendor/Pixal3D/pixal3d/pipelines/samplers/flow_euler.py の "
            "FlowEulerSampler.sample では、均等割りの時刻列 t_seq に対して\n\n"
            "t_seq = rescale_t * t_seq / (1 + (rescale_t - 1) * t_seq)\n\n"
            "という変換を掛けます。rescale_t=1.0 なら変換なし（均等割り）で、"
            "大きくするほどノイズが多い序盤（t が 1 に近い側）に手数が厚く"
            "配分されます。3 段の既定値は疎構造 5.0・形状 3.0・テクスチャ 3.0。"
        ),
    },
    "max_num_tokens": {
        "title": "max_num_tokens",
        "body": (
            "パイプラインに渡す最大トークン数（16384〜65536、既定 49152）。"
            "run_mv の max_num_tokens 引数にそのまま渡します。値を大きくすると"
            "複雑な形状・細部を扱える余地が増えますが、その分 VRAM 使用量と"
            "所要時間も増えます。"
        ),
    },
    "decimation": {
        "title": "decimation（面数の削減）",
        "body": (
            "GLB 書き出し時に、生成した密なメッシュを目標頂点数まで間引く処理。"
            "o_voxel.postprocess.to_glb の decimation_target 引数（原文: "
            "'target number of vertices for mesh simplification'）で指定します"
            "（100000〜1000000、既定 1000000）。値を小さくするほどファイルが"
            "軽くなりますが、細部の形状が失われます。"
        ),
    },
    "テクスチャ解像度": {
        "title": "テクスチャ解像度（texture_size）",
        "body": (
            "GLB へ焼き込むテクスチャ画像の一辺のピクセル数（1024 / 2048 / 4096、"
            "既定 4096）。o_voxel.postprocess.to_glb の texture_size 引数（原文: "
            "'size of the texture for baking'）です。大きいほど質感は精細になり"
            "ますが、ファイルサイズと焼き込みの処理時間が増えます。"
        ),
    },
    "リメッシュ": {
        "title": "リメッシュ（remesh）",
        "body": (
            "GLB 書き出しの前に、メッシュの三角形分割を作り直す処理"
            "（o_voxel.postprocess.to_glb の remesh 引数、原文: "
            "'whether to perform remeshing'）。px3d/ui.py は remesh_band=1、"
            "remesh_project=0 で呼んでいます。三角形の分布が整い、次の UV 展開・"
            "テクスチャ焼き込みが安定しやすくなりますが、その分の処理時間が"
            "かかります。既定でオンです。"
        ),
    },
    "PBRテクスチャ": {
        "title": "PBR テクスチャ",
        "body": (
            "物理ベースレンダリング（Physically Based Rendering）向けのテクスチャ"
            "一式。o_voxel.postprocess.to_glb には attr_layout（属性ごとのスライス）"
            "と _PIPELINE.pbr_attr_layout を渡しており、色だけでなく金属度・"
            "粗さなどの複数チャンネルを 1 枚のテクスチャ空間に焼き込んで GLB へ"
            "書き出します。glTF/GLB の標準的な PBR マテリアル表現に対応する"
            "テクスチャセットです。"
        ),
    },
    "GLB": {
        "title": "GLB（glTF Binary）",
        "body": (
            "3D モデル（形状・PBR テクスチャ・マテリアル）を 1 ファイルにまとめた"
            "バイナリ形式。px3d/ui.py の _generate は生成結果を "
            "config.OUTPUTS_DIR 配下（tools/pixal3d/outputs/）へ "
            "<タイムスタンプ>.glb として書き出し、画面の 3D プレビューとダウン"
            "ロード欄の両方に渡します（glb.export(..., extension_webp=True) で"
            "テクスチャは WebP 圧縮）。"
        ),
    },
    "frame 0": {
        "title": "正面基準ビュー（frame 0）",
        "body": (
            "4 視点のうち先頭（正面）を指す、Pixal3D 側の呼び方。"
            "vendor/Pixal3D/inference_mv.py の check_main_view は frame 0 を"
            "「正準の正面姿勢（カメラが (0, -d, 0) にあり原点を見る）」だと仮定し、"
            "残りの視点をすべて frame 0 基準で配置します。\n\n"
            "そのため画面でも正面（0°）の画像だけが必須で、無い・ズレていると"
            "生成結果の向きが学習時の座標系とズレます。4 方位のカメラ姿勢（4x4 "
            "行列）は上流同梱の transforms.json と同じ値を px3d/config.py に"
            "持たせています（仰角 0、水平 FOV 20 度、距離 3.1192049980163574 の"
            "固定 orbit）。"
        ),
    },
    "プリセット": {
        "title": "プリセット（保存済みの設定）",
        "body": (
            "画面の「基本」「前処理」「詳細設定」「書き出し設定」の値をまとめて 1 つの"
            "名前で保存したもの。実体は tools/pixal3d/presets/<名前>.json（px3d/presets.py "
            "の save_preset / load_preset）。画像枠の中身は含みません。\n\n"
            "設定項目が将来増減しても、保存時に無かったキーは既定値のまま、ファイルに"
            "あって画面に無いキーは無視して読み込みます。値の型・範囲が既定値の想定から"
            "外れている項目（壊れた手編集ファイルなど）は既定値に戻し、画面にその旨を"
            "表示します。"
        ),
    },
}


def missing_tooltips(elem_ids: list[str]) -> list[str]:
    """`elem_ids` のうち `TOOLTIPS` に説明が無いものを、渡された順で返す。"""

    return [elem_id for elem_id in elem_ids if elem_id not in TOOLTIPS]


def missing_glossary_terms(terms: list[str]) -> list[str]:
    """`terms` のうち `GLOSSARY` に項目が無いものを、渡された順で返す。"""

    return [term for term in terms if term not in GLOSSARY]


def glossary_json() -> str:
    """`GLOSSARY` を JSON 文字列化する（ダイアログを開く JS 側から読む用）。

    本文はプレーンテキストのままで良い（HTML エスケープしない）。ダイアログ側は
    innerHTML ではなく textContent で挿入するため、エスケープは不要。
    """

    return json.dumps(GLOSSARY, ensure_ascii=False)
