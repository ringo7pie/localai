"""4 視点の画像を同じ縮尺・正方形・余白付きに揃えるための純粋関数群。

torch も PIL も numpy も import しない（config.py / options.py と同じ設計方針。
`uvx --with pytest` の一時環境で torch なしで試験が走ることを前提にしている）。

## 頭が平らになる・足が壊れる問題との関係

`vendor/Pixal3D/inference_mv.py` の `to_cond_tensor`（:177）は `image.resize((size, size))`
するだけで、縦長画像を正方形に引き伸ばす（縦横比を保たない）。加えて `make_rembg`（:144）は
「transforms.json が枠取りを表すので切り抜きも縮小もしない」設計のため、画面いっぱいに人物を
写した縦長写真をそのまま渡すと、上下が生成空間の外にはみ出して頭頂・足が切り落とされる
（実測: カメラは水平 FOV 20 度・距離 3.1192 で、生成空間は原点面で ±0.5 に対しカメラ画面の
端は ±0.55 相当。つまり画面の外周約 9% は生成空間の外）。

この対策として、ここでは 4 視点それぞれの物体の外接矩形（bbox）から「物体の高さ」が
全視点で揃うような縮尺を求め、正方形キャンバスの中央に余白付きで配置する
（`compute_uniform_layout`）。実際に画素を読んで bbox を求めたり、PIL でキャンバスに
貼り付けたりする処理は numpy / PIL が要るため `px3d/ui.py` 側に置く。
"""

from __future__ import annotations


def compute_uniform_layout(
    bboxes: dict[str, tuple[int, int, int, int]],
    canvas_size: int,
    fill: float,
) -> dict[str, dict]:
    """4 視点の物体の外接矩形から、全視点で縮尺を揃えた配置を求める。

    引数:
        bboxes: 視点名 → 物体の外接矩形 `(left, top, right, bottom)`
            （元画像のピクセル座標。right / bottom は含まない終端）。
        canvas_size: 貼り付け先の正方形キャンバスの一辺（ピクセル）。
        fill: 一番大きい辺がキャンバスに占める割合（0.5 以上 1.0 未満）。

    返り値: 視点名 → `{"scale": float, "resized_size": (w, h), "paste_offset": (x, y)}`。

        - scale: 元画像に掛ける縮尺（フル画像のリサイズは呼び出し側がこの値を使う。
          bbox のピクセル座標だけからは元画像全体のサイズが分からないため、
          このモジュールは元画像のサイズを引数に取らない設計にしてある）。
        - resized_size: 物体の外接矩形を scale で拡縮したときの大きさ（丸めた整数）。
        - paste_offset: 元画像全体を scale で拡縮したものをキャンバスへ貼るときの
          左上座標。拡縮後の外接矩形の中心がキャンバス中心に来るように決める。

    仰角 0 の周回カメラでは物体の高さがどの方位でも変わらない前提で、各視点の
    「物体の高さ = H ピクセル」に正規化する（H はキャンバス上で最大の辺が
    `fill * canvas_size` にちょうど収まる値）:

        H = fill * canvas_size / max(1.0, max_i(幅_i / 高さ_i))

    視点ごとの縮尺は `scale_i = H / 高さ_i`。撮影解像度やズームが視点ごとに違っても、
    正規化後の物体の高さは全視点で揃う。

    fill が 0.5 未満・1.0 以上、canvas_size が正でない、外接矩形の幅か高さが 0 以下、
    bboxes が空のときは ValueError。
    """

    if not (0.5 <= fill < 1.0):
        raise ValueError(f"fill は 0.5 以上 1.0 未満で指定してください: {fill}")
    if canvas_size <= 0:
        raise ValueError(f"canvas_size は正の値で指定してください: {canvas_size}")
    if not bboxes:
        raise ValueError("bboxes が空です（少なくとも 1 視点の外接矩形が必要です）")

    widths: dict[str, float] = {}
    heights: dict[str, float] = {}
    for view, bbox in bboxes.items():
        left, top, right, bottom = bbox
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            raise ValueError(
                f"{view} の外接矩形の幅または高さが 0 以下です: {bbox}"
            )
        widths[view] = width
        heights[view] = height

    max_ratio = max(1.0, max(widths[view] / heights[view] for view in bboxes))
    object_height = fill * canvas_size / max_ratio

    layout: dict[str, dict] = {}
    for view, bbox in bboxes.items():
        left, top, right, bottom = bbox
        scale = object_height / heights[view]
        resized_size = (round(widths[view] * scale), round(heights[view] * scale))

        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        paste_x = canvas_size / 2.0 - center_x * scale
        paste_y = canvas_size / 2.0 - center_y * scale

        layout[view] = {
            "scale": scale,
            "resized_size": resized_size,
            "paste_offset": (round(paste_x), round(paste_y)),
        }
    return layout


# vendor/Pixal3D/inference_mv.py の run_inference() のサンプラー既定値と同じ
# （上流 CLI の既定を素直に踏襲する）。「毎回ランダム」以外の全設定項目の既定値をここに集約し、
# px3d/ui.py 側では数値リテラルとして重複させない。
DEFAULT_SETTINGS = {
    # 基本
    "resolution": 1536,
    "seed": 42,
    "randomize_seed": False,
    # 前処理
    "fill": 0.85,
    "background_removal": "auto",  # "auto"（アルファが無いときだけ）または "always"（常に行う）
    # 詳細: 疎構造（sparse structure）
    "ss_steps": 12,
    "ss_guidance_strength": 7.5,
    "ss_guidance_rescale": 0.7,
    "ss_rescale_t": 5.0,
    # 詳細: 形状（shape slat）
    "shape_steps": 12,
    "shape_guidance_strength": 7.5,
    "shape_guidance_rescale": 0.5,
    "shape_rescale_t": 3.0,
    # 詳細: テクスチャ（tex slat）
    "tex_steps": 12,
    "tex_guidance_strength": 1.0,
    "tex_guidance_rescale": 0.0,
    "tex_rescale_t": 3.0,
    "max_num_tokens": 49152,
    # 書き出し
    "decimation_target": 1000000,
    "texture_size": 4096,
    "remesh": True,
}

# 解像度 → run_mv に渡す pipeline_type。
# 多視点パイプライン（vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py の run）は
# '1024_cascade' と '1536_cascade' しか受け付けず、それ以外は ValueError になる。
# 単画像の TRELLIS.2 にある '512' / '1024' は使えないので、ここにも入れない。
_PIPELINE_TYPE_BY_RESOLUTION = {
    1024: "1024_cascade",
    1536: "1536_cascade",
}


def build_sampler_params(settings: dict) -> dict:
    """画面の設定値の辞書から、`run_mv` に渡す引数一式を組み立てる純粋関数。

    返り値のキーは `sparse_structure_sampler_params` / `shape_slat_sampler_params` /
    `tex_slat_sampler_params`（それぞれ `steps` / `guidance_strength` / `guidance_rescale` /
    `rescale_t`）、`max_num_tokens`、`pipeline_type`。
    """

    resolution = int(settings["resolution"])
    if resolution not in _PIPELINE_TYPE_BY_RESOLUTION:
        raise ValueError(f"未対応の解像度です: {resolution}")

    return {
        "sparse_structure_sampler_params": {
            "steps": settings["ss_steps"],
            "guidance_strength": settings["ss_guidance_strength"],
            "guidance_rescale": settings["ss_guidance_rescale"],
            "rescale_t": settings["ss_rescale_t"],
        },
        "shape_slat_sampler_params": {
            "steps": settings["shape_steps"],
            "guidance_strength": settings["shape_guidance_strength"],
            "guidance_rescale": settings["shape_guidance_rescale"],
            "rescale_t": settings["shape_rescale_t"],
        },
        "tex_slat_sampler_params": {
            "steps": settings["tex_steps"],
            "guidance_strength": settings["tex_guidance_strength"],
            "guidance_rescale": settings["tex_guidance_rescale"],
            "rescale_t": settings["tex_rescale_t"],
        },
        "max_num_tokens": int(settings["max_num_tokens"]),
        "pipeline_type": _PIPELINE_TYPE_BY_RESOLUTION[resolution],
    }
