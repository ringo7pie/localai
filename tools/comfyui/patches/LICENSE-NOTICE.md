# patches のライセンス

このディレクトリの `*.patch` は、上流のファイルの行（文脈行と削除行）を含む**派生物**です。
リポジトリのルートの `LICENSE`（MIT）ではなく、**各パッチが変更する上流のファイルのライセンス**に従います。
どのパッチがどのライセンスかは次のとおりです（対象ファイルの `SPDX-License-Identifier` を、
固定したコミットの実物で確かめた結果）。

| パッチ | 変更する上流 | 対象ファイル | ライセンス | 本文 |
|---|---|---|---|---|
| `wtivo-node-allow-linux.patch` | [Mstafa-awad/WTiVo-WatertightVoxel-ComfyuiNode](https://github.com/Mstafa-awad/WTiVo-WatertightVoxel-ComfyuiNode) `fb9e9ea6` | `wtivo.py` | Apache-2.0 | `LICENSES/Apache-2.0.txt` |
| `wtivo-src-core-vertices-lifetime.patch` | [Mstafa-awad/WTiVo-WatertightVoxel](https://github.com/Mstafa-awad/WTiVo-WatertightVoxel) `7a0ac7cb` | `native/core/wtivo_core.cpp` | Apache-2.0 | `LICENSES/Apache-2.0.txt` |
| `wtivo-src-linux-build.patch` | 同上 | `CMakeLists.txt`、`scripts/build_gpupr.py` | GPL-3.0-or-later | `LICENSES/GPL-3.0-or-later.txt` |
| `cumesh-eigen-include.patch` | [visualbruno/CuMesh](https://github.com/visualbruno/CuMesh) `d10e54c3`（元は Jianfeng Xiang の CuMesh） | `setup.py` | MIT（Copyright (c) 2025 Jianfeng XIANG） | `LICENSES/MIT-CuMesh.txt` |

## 守っていること

- **変更の表示**: 各パッチの冒頭（最初の `diff` 行の前）に、変更したこと・対象・上流の版・ライセンスを書いている。
  `git apply` は先頭の説明文を読み飛ばすので、そのまま当たる。
- **ライセンス本文**: 上流の配布物にある本文をそのまま `LICENSES/` に置いている（Apache-2.0 の §4(a)、GPL-3.0 の §5・§6、MIT の許諾文の同梱）。
- **上流の著作権表示**: 対象ファイルの冒頭にある著作権表示は、パッチが上流を変更しない限り（このパッチは冒頭を変えない）
  そのまま残る。パッチを当てた結果は上流のライセンスのまま。
- **ルートの MIT との関係**: このディレクトリのパッチは、リポジトリの他の部分（自作のスクリプトや文書）とは別の著作物として、
  集積して置いてあるだけである。他の部分は MIT。パッチだけを取り出して再配布するときは、上の表のライセンスに従うこと。

## 範囲外

- 上流のソースそのもの（ComfyUI・WTiVo・CuMesh・ComfyUI のカスタムノード・PixelArtistry のワークフロー）は
  このリポジトリに**含めない**。`setup-server.sh` が固定したコミットで取得する。それぞれの
  ライセンスは取得先に従う（ルートの `NOTICE.md` に一覧）。
