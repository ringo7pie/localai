"""Hunyuan3D の Gradio 画面に足す説明文（マウスオーバーの詳細説明・専門用語の用語集）。

torch も gradio も import しない。純粋なデータと、それを扱う純粋関数だけを置く。
説明の根拠は次のいずれかに限る。それ以外は書かない（推測しない）。
- vendor/Hunyuan3D-2/gradio_app.py の実装（値の既定・範囲・分岐）
- tools/hunyuan3d/README.md
- knowledge/10-silver/areas/hunyuan3d.md（実測値）

実行: このモジュール単体は import するだけで完結する（副作用なし）。

このデータを画面へ注入するのは、上流への当て物 0003（help-tooltips-and-glossary）。当て物は
Tencent Hunyuan 3D 2.0 Community License の地域制限のため公開版に含まない。当て物が無い環境では
どこからも import されず、試験（tests/test_units.py）だけが参照する。tools/hunyuan3d/README.md の
「ライセンスの地域制限」「上流への当て物」を参照。
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# マウスオーバーで出す詳細説明。
# キーは gradio_app.py 側の label='...' / gr.Button(value='...') の文字列そのもの。
# ---------------------------------------------------------------------------

TOOLTIPS: dict[str, str] = {
    "Image": (
        "3D 化したい 1 枚の画像を読み込みます。このサーバーは 4 枚入力（MultiView Prompt）の"
        "構成で動いているため、このタブは通常表示されません。"
    ),
    "Text Prompt": (
        "文章から画像を生成してから 3D 化する入力欄です（Text to 3D）。"
        "起動時に --enable_t23d を付けていないと、生成時に「Text to 3D is disable」のエラーになります。"
        "このサーバーは MV モードで動いているため、このタブは通常表示されません。"
    ),
    "Front": (
        "対象物を正面から撮った画像を入れます。4 枚（Front/Back/Left/Right）のうち最低 1 枚あれば"
        "生成できますが、枚数が少ないほど背面・側面の形状精度は落ちます。同一光源・同一距離で撮り、"
        "背景は黒か単色にすると精度が安定します。"
    ),
    "Back": (
        "対象物を背面から撮った画像を入れます。省略すると背面の形状は前後の推定に頼ることになり、"
        "精度が落ちます。Front と同じ光源・距離で撮ってください。"
    ),
    "Left": (
        "対象物を左側から撮った画像を入れます。省略しても生成はできますが、側面の形状精度が落ちます。"
        "Front と同じ光源・距離で撮ってください。"
    ),
    "Right": (
        "対象物を右側から撮った画像を入れます。省略しても生成はできますが、側面の形状精度が落ちます。"
        "Front と同じ光源・距離で撮ってください。"
    ),
    "File": (
        "生成したメッシュの内部的な保存先です。画面には出ませんが、Gen Shape / Gen Textured Shape の"
        "実行結果を Transform（書き出し直し）へ渡すために使われます。"
    ),
    "Generation Mode": (
        "Turbo / Fast / Standard の 3 段階で Inference Steps（拡散の手数）をまとめて切り替えます。"
        "選ぶと Turbo=5、Fast=10、Standard=30 に Inference Steps が上書きされます。"
        "turbo 系のモデルを使っているときだけ表示されます。"
    ),
    "Decoding Mode": (
        "Low / Standard / High の 3 段階で Octree Resolution（メッシュを取り出す解像度）を"
        "まとめて切り替えます。選ぶと Low=196、Standard=256、High=384 に Octree Resolution が"
        "上書きされます。turbo 系のモデルを使っているときだけ表示されます。"
    ),
    "Remove Background": (
        "入力画像の背景を自動で取り除いてから 3D 化します。既定で On です。背景が単色でない画像や、"
        "透過情報を持たない RGB 画像では、このチェックが Off でも自動的に背景除去が適用されます。"
    ),
    "Randomize seed": (
        "生成のたびに Seed をランダムな値へ置き換えます。既定で On です。同じ入力から毎回同じ結果を"
        "再現したいときは Off にして Seed を固定してください。"
    ),
    "Seed": (
        "拡散モデルの乱数の種です。同じ Seed・同じ入力・同じ設定であれば同じ結果を再現できます。"
        "Randomize seed が On のときは、この値は生成のたびに上書きされ使われません。"
    ),
    "Inference Steps": (
        "形状生成の拡散モデルが繰り返す反復計算の回数です。既定値はモデルにより 5〜30。増やすほど"
        "時間はかかりますが形状が安定しやすく、減らすほど速い代わりに粗くなることがあります。"
    ),
    "Octree Resolution": (
        "生成した形状をメッシュとして取り出す際の解像度です。既定 256、範囲は 16〜512。値を"
        "大きくするほど細部を表現できますが、計算時間とメモリの消費が増えます。"
    ),
    "Guidance Scale": (
        "入力画像の条件をどれだけ強く形状に反映させるかの強さ（CFG）です。既定値は 5.0。上げると"
        "条件への忠実さが増しますが、上げすぎると形状が破綻することがあります。"
    ),
    "Number of Chunks": (
        "形状を復元する計算を分割する塊の数です。既定 8000、範囲は 1000〜5000000。実測では値を"
        "大きくするほど一度に処理する量が増えて VRAM を多く使う（必ずしも生成が速くなるわけではない）。"
        "VRAM 不足のエラーが出たときは、上げるのではなく下げて試す。"
    ),
    "File Type": (
        "Transform で書き出すメッシュのファイル形式です。GLB（既定）・OBJ・PLY・STL から選べます。"
        "GLB はテクスチャや法線を含めやすい形式です。"
    ),
    "Simplify Mesh": (
        "Transform を実行するときにメッシュの面数を Target Face Number まで減らします。既定は Off。"
        "ファイルサイズや読み込み負荷を下げたいときに On にします。"
    ),
    "Include Texture": (
        "Transform で書き出す対象を、白メッシュではなくテクスチャ付きメッシュにする内部フラグです。"
        "Gen Textured Shape を実行すると自動で On になり、通常は手で触る項目ではありません。"
    ),
    "Target Face Number": (
        "Simplify Mesh を On にしたときの目標面数です。既定 10000、範囲は 100〜1000000。小さくする"
        "ほど軽量になりますが、形状のディテールは失われます。"
    ),
    "Download": (
        "Transform を実行した後に有効になり、書き出したメッシュファイルをダウンロードします。"
        "Transform を実行する前は押せません。"
    ),
    "Output": (
        "生成・書き出したメッシュのプレビューです（3D ビューア）。Generated Mesh タブは生成直後、"
        "Exporting Mesh タブは Transform 後のプレビューを表示します。"
    ),
    "Mesh Stats": (
        "直近の生成に使ったパラメータ（Seed・Inference Steps・Guidance Scale など）と、各工程に"
        "かかった時間、頂点数・面数を JSON で表示します。"
    ),
    "Gen Shape": (
        "画像から白メッシュ（テクスチャなしの形状）だけを生成します。テクスチャ生成を含まない分"
        "速く、形状だけを確認したいときに使います。押すと生成の直前に Ollama（Qwen）が VRAM から"
        "自動で降ろされます。"
    ),
    "Gen Textured Shape": (
        "画像から形状生成に続けてテクスチャ生成まで行います。Gen Shape より時間がかかります"
        "（実測: 形状生成 21.7 秒、テクスチャ生成 136.2 秒、入力 3 枚のとき）。押すと生成の直前に"
        "Ollama（Qwen）が VRAM から自動で降ろされます。"
    ),
    "Transform": (
        "生成済みのメッシュを、File Type・Simplify Mesh・Target Face Number の設定で書き出し直します。"
        "実行後に Download ボタンが有効になります。"
    ),
    # --- localai: 設定（パラメータ）の保存・読み込み（手元の当て物 0005-save-load-presets。公開版には含まない） ---
    "設定の保存・読み込み": (
        "画面の設定（Inference Steps・Guidance Scale・Seed・Octree Resolution・Remove Background・"
        "Number of Chunks・File Type・Simplify Mesh・Include Texture・Target Face Number・"
        "Randomize seed の 11 項目）に名前を付けて保存し、あとから呼び出します。"
        "保存先はサーバー内の tools/hunyuan3d/presets/ です。既定で閉じています。"
    ),
    "設定名": (
        "保存する設定に付ける名前です。使えるのは日本語（ひらがな・カタカナ・漢字・長音）・英数字・"
        "半角空白・_ - ( ) のみ、64 文字以内。「/」「\\」「..」や先頭の「.」はファイルパスとして"
        "扱われるため使えません。"
    ),
    "保存済みの設定": (
        "これまでに保存した設定名の一覧です。読み込み・削除の対象をここで選びます。"
        "保存・削除すると自動的に更新されます。"
    ),
    "保存": (
        "設定名の欄に入力した名前で、現在の画面の設定を保存します。同じ名前が既にあれば上書きします。"
    ),
    "読み込み": (
        "保存済みの設定のドロップダウンで選んだ設定を画面へ反映します。保存後に項目が増減していても、"
        "無い項目は既定値のまま、知らない項目は無視されます。範囲外の値は既定値に戻り、その旨を表示します。"
    ),
    "削除": (
        "保存済みの設定のドロップダウンで選んだ設定ファイルを削除します。元に戻せません。"
    ),
}


# ---------------------------------------------------------------------------
# 専門用語をクリックしたときに出す用語集。
# キーは画面に並べる用語ボタンの表示文字列（data-term としてもそのまま使う）。
# ---------------------------------------------------------------------------

GLOSSARY: dict[str, dict[str, str]] = {
    "VRAM": {
        "title": "VRAM（GPU メモリ）",
        "body": (
            "GPU が演算に使うメモリです。この機体の GPU（NVIDIA A30）は 24576 MiB。"
            "Hunyuan3D は待機時に 5,365 MiB、生成中は 11,487 MiB 前後を使います（実測）。"
            "Qwen（qwen3.8:27b）は単独で 22,201 MiB を使うため、生成中は同時に載りません。"
        ),
    },
    "低 VRAM モード": {
        "title": "低 VRAM モード（--low_vram_mode）",
        "body": (
            "推論に使わないパイプラインをそのつど CPU 側（RAM）へ退避して GPU メモリを節約する"
            "上流のオプションです。VRAM は節約できますが、この機体（RAM 31GiB）では過去に RAM を"
            "食い潰してデスクトップごとハングした事故があったため、既定は On（VRAM 優先の安全側）"
            "のまま運用しています。切り替えは入口ページ（8080 番）や環境変数 HY3D_LOW_VRAM から"
            "行います。"
        ),
    },
    "FlashVDM": {
        "title": "FlashVDM（--enable_flashvdm）",
        "body": (
            "形状パイプラインの VAE を高速版（turbo）に差し替える起動オプションです。有効にすると"
            "メッシュを取り出す方式（mc_algo）が使われますが、デバイスが CPU / MPS のときは常に"
            "mc（Marching Cubes）が使われます。"
        ),
    },
    "シード": {
        "title": "シード（Seed）",
        "body": (
            "拡散モデルの乱数の種です。同じ Seed・同じ入力・同じ設定であれば同じ結果を再現できます。"
            "Randomize seed を On にすると、生成のたびにランダムな値へ置き換わります。"
        ),
    },
    "Inference Steps": {
        "title": "Inference Steps（拡散の手数）",
        "body": (
            "形状生成の拡散モデルが繰り返す反復計算の回数です。増やすほど時間はかかりますが形状が"
            "安定しやすく、減らすほど速い代わりに粗くなることがあります。このサーバーの既定値は"
            "モデルの種類により 5〜30 です。"
        ),
    },
    "Guidance Scale (CFG)": {
        "title": "Guidance Scale（CFG）",
        "body": (
            "入力画像などの条件をどれだけ強く形状に反映させるかを決める強さです。値を上げると"
            "条件への忠実さが増しますが、上げすぎると形状が破綻することがあります。既定値は 5.0 です。"
        ),
    },
    "Octree Resolution": {
        "title": "Octree Resolution",
        "body": (
            "生成した形状をメッシュとして取り出す際の解像度です。値が大きいほど細部を表現できますが、"
            "計算時間とメモリの消費が増えます。既定 256、範囲は 16〜512 です。"
        ),
    },
    "Number of Chunks": {
        "title": "Number of Chunks",
        "body": (
            "形状を復元する計算を分割する塊の数です。既定 8000。実測では大きくするほど一度に処理する"
            "量が増えて VRAM を多く使う（必ずしも生成が速くなるわけではない）。VRAM 不足のエラーが"
            "出たときは、上げるのではなく下げて試す。"
        ),
    },
    "Marching Cubes (mc)": {
        "title": "Marching Cubes（mc）",
        "body": (
            "ボクセル状の密度データからポリゴンメッシュの表面を取り出すアルゴリズムです。"
            "--mc_algo で指定でき既定は mc。デバイスが CPU / MPS のときは常にこの方式が使われます。"
        ),
    },
    "Remove Background": {
        "title": "Remove Background（背景除去）",
        "body": (
            "入力画像から背景を自動で取り除く処理です（rembg / u2net を使用）。背景が単色でない画像や、"
            "透過情報を持たない RGB 画像では、チェックを Off にしていても自動的に適用されます。"
        ),
    },
    "Face Reduction / Target Face Number": {
        "title": "Face Reduction（面数の削減）と Target Face Number",
        "body": (
            "生成したメッシュの三角形の面数を減らす処理です。Simplify Mesh を On にすると、"
            "Target Face Number（既定 10000）まで面数を減らしてから書き出します。ファイルサイズや"
            "表示負荷を下げたいときに使います。"
        ),
    },
    "Simplify Mesh": {
        "title": "Simplify Mesh",
        "body": (
            "Transform を実行するときにメッシュの面数を Target Face Number まで減らすかどうかの"
            "チェックです。既定は Off。On にすると Face Reduction（面数の削減）が実行されます。"
        ),
    },
    "テクスチャ生成 (delight / paint)": {
        "title": "テクスチャ生成（delight / paint）",
        "body": (
            "形状に色を塗る処理です。delight（照明の影響を取り除く）と paint（複数視点の画像を"
            "合成してテクスチャを貼る）の 2 段階からなります。実測では形状生成 21.7 秒に対し"
            "テクスチャ生成は 136.2 秒と、より時間がかかります（入力 3 枚のとき）。"
        ),
    },
    "GLB / OBJ / PLY / STL": {
        "title": "GLB / OBJ / PLY / STL（書き出し形式）",
        "body": (
            "Transform で書き出せるメッシュのファイル形式です。GLB は法線やテクスチャを含めやすく"
            "既定値です。OBJ・PLY・STL は形状のみで、対応するアプリに合わせて選びます。"
        ),
    },
    "4 ビュー入力 (Front/Back/Left/Right)": {
        "title": "4 ビュー入力（Front / Back / Left / Right）",
        "body": (
            "このサーバーは tencent/Hunyuan3D-2mv を使っており、正面・背面・左・右の最大 4 枚から"
            "3D 形状を復元します。4 枚すべてを用意する必要はありませんが、枚数が少ないほど背面・"
            "側面の形状精度は落ちます。同一光源・同一距離で撮り、背景は黒か単色にすることが"
            "推奨されています。"
        ),
    },
    "Qwen との VRAM の取り合い": {
        "title": "Qwen との VRAM の取り合い",
        "body": (
            "この機体の GPU（VRAM 24576 MiB）は Hunyuan3D と Qwen（Ollama）で共有していますが、"
            "生成中は同時に載りません。Qwen を載せたまま生成すると VRAM 不足で CUDA out of memory"
            "になるため、Gen Shape / Gen Textured Shape を押すたびに Ollama のモデルを自動で"
            "降ろしています。Qwen は次のチャットで自動的に再ロードされます（約 60 秒）。"
        ),
    },
}


def missing_tooltips(labels: list[str]) -> list[str]:
    """渡したラベルのうち TOOLTIPS に説明が無いものを返す（説明の付け忘れ検出用）。"""

    return [label for label in labels if label not in TOOLTIPS]


def glossary_json() -> str:
    """GLOSSARY を JSON 文字列にする（画面へ埋め込む用）。ASCII エスケープはしない。"""

    return json.dumps(GLOSSARY, ensure_ascii=False)


def tooltips_json() -> str:
    """TOOLTIPS を JSON 文字列にする（画面へ埋め込む用）。ASCII エスケープはしない。"""

    return json.dumps(TOOLTIPS, ensure_ascii=False)
