"""RMBG-2.0（ゲート付き）を避け、非ゲートの BiRefNet 既定モデルを強制する。

実機で判明した事実:
    pipeline_mv.json の rembg_model は
        {"name": "BiRefNet", "args": {"model_name": "briaai/RMBG-2.0"}}
    を指しているが、briaai/RMBG-2.0 は HF のゲート付きリポジトリで、ログインと利用規約への
    同意が無いと 401 GatedRepoError になりダウンロードできない（実際に失敗を確認済み）。

    一方 vendor/Pixal3D/pixal3d/pipelines/rembg/BiRefNet.py の BiRefNet クラスの既定値は
    ZhengPeng7/BiRefNet（= config.REMBG_MODEL）で、こちらはゲート無し・MIT ライセンス・425MB。

    Pixal3DImageTo3DPipeline.from_pretrained（vendor/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py:123）
    は次の行を from_pretrained の内部で直接実行し、戻り値をパイプラインの rembg_model 属性に
    入れてしまう。

        pipeline.rembg_model = getattr(rembg, args['rembg_model']['name'])(**args['rembg_model']['args'])

    そのため、from_pretrained が返した後で rembg_model を差し替えることはできない
    （差し替える前に GatedRepoError で例外になる）。

なぜこの方式（モジュール属性の実行時差し替え）を選んだか:
    - vendor/ は書き換え禁止（別エージェントが同時に作業中）で、上流コードへの当て物（patch）も
      今回は作らない方針にした。
    - `getattr(rembg, 'BiRefNet')` は「呼び出された瞬間に」pixal3d.pipelines.rembg モジュールの
      BiRefNet 属性を引く。つまり from_pretrained を呼ぶ前に、そのモジュール属性そのものを
      差し替えておけば、上流のソースを 1 行も変えずに済む。
    - pipeline_mv.json 側が渡す args.rembg_model.args.model_name（briaai/RMBG-2.0）は
      サブクラスの __init__ で握りつぶし、常に config.REMBG_MODEL を使う。
"""

from __future__ import annotations


def force_rembg_model(model_name: str) -> None:
    """pixal3d.pipelines.rembg.BiRefNet を、常に model_name でモデルを作るクラスに差し替える。

    inference_mv.init_pipeline() / run_inference()（内部で Pipeline.from_pretrained を呼ぶ）より
    前に、必ず 1 度呼ぶこと。vendor/Pixal3D が PYTHONPATH 上にあるプロセス（px3d.ui、
    px3d.cli generate のサブプロセス）でのみ使う関数なので、import はここでだけ行う。
    """

    from pixal3d.pipelines import rembg as rembg_module

    original_birefnet = rembg_module.BiRefNet

    class _ForcedBiRefNet(original_birefnet):
        def __init__(self, *args, **kwargs):
            # pipeline_mv.json が渡す model_name（ゲート付きで落とせない）を上書きする。
            kwargs["model_name"] = model_name
            super().__init__(*args, **kwargs)

    rembg_module.BiRefNet = _ForcedBiRefNet
