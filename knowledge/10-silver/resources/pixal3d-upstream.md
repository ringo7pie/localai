# pixal3d-upstream

Pixal3D（TencentARC、SIGGRAPH 2026、arXiv:2605.10922）の上流の事情と、この機体に載せるときに
何をどう選んだか。導入をやり直すときと、上流を更新するときに Read する。
毎回の運用で効く事実は `knowledge/10-silver/areas/pixal3d.md` にある。

## 固定しているコミット

| 対象 | コミット |
|---|---|
| TencentARC/Pixal3D | `f7cf38429b0bd264f1995f0f8743a88b1c728b94` |
| microsoft/TRELLIS.2 | `75fbf0183001ed9876c8dbb35de6b68552ee08bd` |
| JeffreyXiang/FlexGEMM | `6dd94a859c26ee8246888502eada3dd8ad85532e` |
| JeffreyXiang/CuMesh | `12289e1062f0603f2f0d0771b02e1395d247f26f` |
| JeffreyXiang/nvdiffrec（renderutils ブランチ） | `b296927cc7fd01c2ac1087c8065c4d7248f72da4` |
| NVlabs/nvdiffrast（tag v0.4.0） | `253ac4fcea7de5f396371124af597e6cc957bfae` |
| natten | 0.21.0（PyPI の sdist をソースビルド） |

Pixal3D と TRELLIS.2 はタグが切られていない。拡張側も上流の `setup.sh` はコミットを固定しないため、
ビルドが通った版をこちらで固定している。

## 環境の選び方

- **Pixal3D 単体では環境が完結しない。** README の Step 1 が TRELLIS.2 の導入で、CUDA 拡張 6 本
  （o-voxel / FlexGEMM / CuMesh / nvdiffrec / nvdiffrast / natten）は TRELLIS.2 の `setup.sh` 経由で入る。
  2026-09-22 に A30（sm80）でビルド成功。合計およそ 17 分、うち natten が 11 分。
- **CUDA は 12.6。** TRELLIS.2 が動作確認しているのは 12.4 だが Ubuntu 24.04 のリポジトリに無く、
  torch 2.6.0 に cu126 ホイールがあるため 12.6 にした。Python は uv 管理の 3.10、torch 2.6.0+cu126。
- **flash_attn は入れない。** 上流 README が `ATTN_BACKEND=sdpa` で動くと明記している。Ampere では
  これで足り、ビルドが 1 本減る。スパース畳み込みの backend は既定の flex_gemm。
- **MoGe は入れない。** 単視点の `inference.py` だけが使い、上流が固定する `trimesh==4.10.1` と
  依存が衝突する（MoGe は `trimesh>=4.11` を要求する）。
- **o-voxel は `--no-deps` でビルドする。** pyproject が cumesh と flex_gemm を git+URL の実行時依存に
  持ち、そのままだと uv がコミット未固定の clone を勝手にビルドしてしまう。
- **natten は wheel を使わずソースビルドする。** `whl.natten.org` の 0.21.0 は torch 2.7.0 用しか無く、
  上流の `requirements-hfdemo.txt` にある wheel は「H 系 GPU 用」と明記されていて sm80 のカーネルを
  含む保証が無い。

## UI を自前で書いた理由

上流同梱の `app.py` は単一画像専用で、マルチビューは `inference_mv.py` にしか無い。さらに
`app.launch(share=True)` が固定で、起動のたびに Gradio の公開トンネルを外部に張る。LAN 内サービスには
使えないため、`tools/pixal3d/px3d/ui.py` に 4 枠の画面を自前で書いた。

マルチビューの入力は `transforms.json`（camera-to-world の 4x4 と `camera_angle_x`）が要る。
上流同梱の既定値（方位 0/90/180/270 度、仰角 0、FOV 20 度、距離 3.1192）を流用してよいと README にある。
**frame 0 は正面でなければならない**（`check_main_view` が正面基準ビューを前提にしている）。

## 重みと背景除去モデル

- 重み約 24.5GB は HF の標準キャッシュ方式で `tools/pixal3d/models/hf` に置く。`from_pretrained` には
  リポジトリ ID をそのまま渡す。ローカルディレクトリ方式にすると 23GB の二重保存になる。
- 画像条件付けの DINOv3 は公式（`facebook/...`）がゲート付きで、上流の `inference_mv.py` 自身が
  `camenduru/dinov3-vitl16-pretrain-lvd1689m` というミラーを使っている。
- **背景除去モデルは差し替えてある。** `pipeline_mv.json` が指す `briaai/RMBG-2.0` はゲート付きで
  401 になり落とせない。上流クラスの既定値である `ZhengPeng7/BiRefNet`（ゲート無し、MIT、425MB）を使う。
  `from_pretrained` の中で組み立てられるため戻り値を後から差し替えられず、
  `px3d/rembg_override.py` が呼び出し前にモジュール属性を差し替える。上流への当て物は作っていない。
- BiRefNet は `trust_remote_code=True` で HF 上のコードを実行する。そのコードが einops を要求するため
  `requirements.lock.txt` に足してある。上流の `requirements.txt` には無い。
- NAF（高解像度段の特徴アップサンプラ）は `torch.hub` で valeoai/NAF を取りに行くため、`TORCH_HOME` も
  `tools/pixal3d/models/torch` へ向ける。
