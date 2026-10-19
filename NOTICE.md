# NOTICE — 第三者のソフトウェア・モデル・商標

**English summary.** This repository's own code and documents are under the MIT License (`LICENSE`).
The one exception is `tools/comfyui/patches/`, whose files are derivatives of upstream code and keep the upstream
licenses (see `tools/comfyui/patches/LICENSE-NOTICE.md`). Upstream software and model weights are **not**
redistributed here; setup scripts fetch them from their original sources at pinned commits, under their own licenses.
Patches against Tencent Hunyuan3D-2 are intentionally **not** published, because that license only covers
distribution outside the EU, UK and South Korea. Product and company names are trademarks of their owners;
this project is not affiliated with or endorsed by them.

## 1. このリポジトリ自身

| 範囲 | ライセンス |
|---|---|
| 自作のコード・スクリプト・文書・評価の問題と記録（`tools/`・`Documents/`・`docs/`・`knowledge/` ほか） | MIT（`LICENSE`） |
| `tools/comfyui/patches/*.patch` | 変更する上流のファイルのライセンス（Apache-2.0 / GPL-3.0-or-later / MIT）。`tools/comfyui/patches/LICENSE-NOTICE.md` |

## 2. 同梱しないソフトウェア（setup が固定コミットで取得する）

確認の根拠は、取得した上流の `LICENSE` / `NOTICE` の実物（`tools/*/vendor/` 配下）と各 README の記述。
**表にないものや、ここに書いた版と異なる版を使うときは、取得元の `LICENSE` を自分で確かめること。**

| 名前 | 取得元・固定 | ライセンス | 使われ方・注意 |
|---|---|---|---|
| Strata | [Niko1221/Strata](https://github.com/Niko1221/Strata) `v0.1.44.1` | MIT（Copyright (c) 2026 Niko1221 and the Strata contributors） | `tools/strata`。engine を取得してビルドする |
| llama.cpp（ggml・gguf-py） | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) `3cf03257` | MIT | Strata の engine に静的に組み込まれる（上流の `setup.py` の手順） |
| Ollama | [ollama.com](https://ollama.com) | MIT | 利用者が公式の手順で導入する。同梱しない |
| Open WebUI | [open-webui/open-webui](https://github.com/open-webui/open-webui) | BSD-3-Clause をもとにした独自ライセンス（ブランド表示の保持条項を含む） | 別途導入する。同梱しない。導入時に原文を確認すること |
| Hunyuan3D-2 | [Tencent-Hunyuan/Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) `f8db6309` | **Tencent Hunyuan 3D 2.0 Community License**（下の「地域制限」） | `tools/hunyuan3d`。Tencent の NOTICE 表示を README に載せる |
| Pixal3D | [TencentARC/Pixal3D](https://github.com/TencentARC/Pixal3D) `f7cf3842` | MIT（Copyright (c) 2026 Tencent） | `tools/pixal3d` |
| TRELLIS.2 | [microsoft/TRELLIS.2](https://github.com/microsoft/TRELLIS.2) `75fbf018` | MIT（Copyright (c) Microsoft Corporation） | Pixal3D の環境・ComfyUI のノードが使う |
| CuMesh・FlexGEMM | [JeffreyXiang](https://github.com/JeffreyXiang)（ComfyUI 側は visualbruno の fork） | MIT（Copyright (c) 2025 Jianfeng Xiang） | CUDA 拡張。ソースからビルドする |
| nvdiffrast | [NVlabs/nvdiffrast](https://github.com/NVlabs/nvdiffrast) `v0.4.0` | NVIDIA Source Code License（1-Way Commercial） | **非商用が中心**。大規模な商用利用は NVIDIA との別途の合意が要る |
| nvdiffrec | [JeffreyXiang/nvdiffrec](https://github.com/JeffreyXiang/nvdiffrec)（renderutils ブランチ） | NVIDIA Source Code License for nvdiffrec | 同上 |
| natten | PyPI の sdist `0.21.0` | パッケージの表示に従う | ソースからビルドする |
| ComfyUI | [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) `daeb5e53` | GPL-3.0 | `tools/comfyui`。同梱しない |
| PixelArtistry-Watertight-Meshes | [pixelartistry/PixelArtistry-Watertight-Meshes](https://github.com/pixelartistry/PixelArtistry-Watertight-Meshes) `5b3a0e9d` | MIT（Copyright (c) 2026 PixelArtistry。一部は Comfy Org の MIT） | ワークフローを取得し、`adapt_workflows.py` が変換して使う。同梱しない |
| WTiVo-WatertightVoxel とそのノード | [Mstafa-awad](https://github.com/Mstafa-awad/WTiVo-WatertightVoxel) | リポジトリは GPL-3.0。ファイルごとに Apache-2.0 / GPL-3.0-or-later（SPDX）。系譜（CelloCut・FaithC は Apache-2.0、CGAL は GPL、Eigen は MPL-2.0 ほか）は上流の `NOTICE`・`THIRD_PARTY_NOTICES.md` | CGAL を GPL で使うため、ビルド物は GPL の条件に従う。パッチの扱いは `tools/comfyui/patches/LICENSE-NOTICE.md` |
| ComfyUI のそのほかのノード | `tools/comfyui/setup-server.sh` の一覧（Mstafa-awad 製 8 種・visualbruno/ComfyUI-Trellis2） | 各リポジトリの `LICENSE`（README の確認では GPL-3.0 または MIT） | 同梱しない |
| Python の依存 | 各ツールの `requirements.lock.txt`。PyPI などから取得 | 各パッケージ | 同梱しない |

## 3. モデルの重み（同梱しない）

重みは**一切再配布しない**。利用者が配布元から取得し、配布元の条件に従う。

| モデル | 配布元 | 条件 |
|---|---|---|
| Qwen3.8-27B（Ollama `qwen3.8:27b`）・Qwen3.8-Flash-Next | Qwen・Ollama・[ISTA-DASLab](https://huggingface.co/ISTA-DASLab) | 配布元のカードの表示に従う。Strata の Coder 版・公式版（IQ3_XXS・IQ3_S）は HF の表示で Apache-2.0 |
| Swift 1.5 Qwen3.8-Flash-Next（Strata `strata-swift:IQ3_XXS`） | [ukisai](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF)（UkisAI） | **Swift Open License v1.0**（UkisAI の追加学習の部分。年商 100 万ドル以上の法人の商用利用は別契約「Swift Enterprise License」が要る。非商用・研究用途は可）+ 元の Qwen の部分は Qwen Community License 1.0（配布元の `LICENSE-QWEN`）。このリポジトリでは個人の非商用・研究用途で使う（2026-10-16）。配布元の付録の表示: Copyright 2026 UkisAI. Swift Contribution licensed under the Swift Open License v1.0. Derivative of Qwen3.8-Flash-Next, Copyright (c) 2026 Qwen, Qwen Community License 1.0. |
| Strata 汎用版（RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored IQ3_S） | [jimmy31chen](https://huggingface.co/jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata) | カードの表示に従う。abliterated（拒否の方向を取り除いた版）で、有害な依頼にも応じる。LAN に開くときは `STRATA_API_KEY` を付ける |
| Gemma 4 系（e4b・31b） | Google | Gemma の利用規約と禁止利用ポリシー |
| Hunyuan3D-2mv・Hunyuan3D-2 | [tencent](https://huggingface.co/tencent) | Tencent Hunyuan 3D 2.0 Community License |
| Pixal3D | [TencentARC/Pixal3D](https://huggingface.co/TencentARC/Pixal3D) | MIT |
| DINOv3 | Meta（`camenduru/dinov3-vitl16-pretrain-lvd1689m` は非公式ミラー） | Meta 独自のライセンス。**ミラーを使ってもライセンスは Meta のものに従う。地域制限の有無は上流でも未回答** |
| 背景除去（BiRefNet） | [ZhengPeng7/BiRefNet](https://huggingface.co/ZhengPeng7/BiRefNet) | MIT。RMBG-2.0（CC BY-NC 4.0）は使わない |

## 4. 利用上の制約（大事なもの）

- **Hunyuan3D の地域制限**: EU・UK・韓国は使用許諾の対象外。月間アクティブユーザー 100 万人超は Tencent へ別途申請。
  出力を使って他の AI モデルを改善してはならない。**このリポジトリは、この条件のため Hunyuan3D-2 へのパッチを公開しない**
  （配布は対象地域内に限られ、GitHub では地域を絞れないため）。`tools/hunyuan3d/setup-server.sh` は、
  `--accept-tencent-license` で条件を確認するまで上流の取得とモデルのダウンロードを行わない。
  根拠は上流の `LICENSE` の §3（配布は Territory 内に限る）と §5.b・§5.c（出力で他の AI を改善しない・Territory 外で使わない）。
  Tencent Hunyuan 3D 2.0 is licensed under the Tencent Hunyuan 3D 2.0 Community License Agreement, Copyright © 2025 Tencent. All Rights Reserved. The trademark rights of “Tencent Hunyuan” are owned by Tencent or its affiliate.
- **Pixal3D の出力は収益化しない前提**: nvdiffrast・nvdiffrec（非商用が中心）と DINOv3（Meta 独自）が推論経路に混ざる。
  収益化するなら Hunyuan3D 側（上の地域制限に従う）を検討する。
- **GPL**: ComfyUI（GPL-3.0）と WTiVo（GPL-3.0 / CGAL）は同梱しないが、取得・ビルドした物を第三者へ配布するときは GPL に従う。

## 5. 評価の記録に含まれるモデルの出力

`tools/model-eval/results/` と `Documents/` の評価レポートは、各モデル（Claude・Qwen・Gemma・Strata の 5 種ほか）が
出題に答えた出力を、評価の記録として含む。出力の取り扱いは各提供元の利用規約に従う。
Hunyuan3D・Pixal3D が生成した 3D メッシュは含めない。

## 6. 商標

Claude・Anthropic（Anthropic, PBC）、Qwen（Alibaba Cloud）、Gemma（Google LLC）、Hunyuan・Tencent（Tencent）、
NVIDIA・A30・CUDA（NVIDIA Corporation）、ChatGPT・Codex（OpenAI）、Ollama、Open WebUI、ComfyUI、Strata は、
それぞれの権利者の名称または商標である。このリポジトリは、これらの権利者と提携しておらず、後援・承認も受けていない。
名称は、互換性や出所を説明する目的でだけ使う。

## 7. 法的な助言ではない

この文書は、作者が上流のライセンスを確認した結果の記録であり、法的な助言ではない。
利用・再配布の前に、取得元の `LICENSE` の原文を確かめること。
