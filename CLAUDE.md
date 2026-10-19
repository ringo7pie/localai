# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# localai

NVIDIA A30 1 枚でローカル LLM を動かし、その上に作業を任せるための環境。推論サーバ・モデル・ハードの制約は knowledge/10-silver/areas/env.md にある。

## 構成

| パス | 内容 |
|---|---|
| `knowledge/` | ナレッジベース本体 |
| `tools/qwen-worker/` | ローカル Qwen を Claude Code / Codex から直接使う MCP ワーカー |
| `tools/local-ai-bridge/` | OpenCode 経由でローカル Qwen へ実装を委譲する連携層。スキル `/qwen` `/qwen-read` の実体も（README.ja.md） |
| `tools/status/` | いま Qwen が何を処理しているかを見る（サーバー用 sh と、他の PC 用 sh / ps1） |
| `tools/hunyuan3d/` | 正面・背面・左・右の 4 枚の画像から 3D メッシュを作る Hunyuan3D-2mv（ポート 7860） |
| `tools/pixal3d/` | 同じく複数画像から 3D メッシュを作る Pixal3D（TencentARC、ポート 7861）。Hunyuan3D とは排他 |
| `tools/comfyui/` | ComfyUI と PixelArtistry の防水メッシュ用ワークフロー（ポート 8188）。WTiVo のネイティブ部分（CGAL・CUDA 12.6）を自前でビルドする |
| `tools/strata/` | MoE の CPU-GPU 分担推論エンジン Strata（OpenAI 互換 API）。汎用版 RVN IQ3_S（8082、unit `strata`）・Coder IQ1_M（8083、`strata-coder`）・公式 IQ3_XXS（8084、`strata-official`）・公式 IQ3_S（8085、`strata-official-iq3s`）・Swift 1.5 IQ3_XXS（8086、`strata-swift`）。モデルごとの値は `stra/config.py` の `ModelSpec` |
| `tools/portal/` | ポート 8080 のサービス入口ページ。Open WebUI / Strata 5 種 / Hunyuan3D / Pixal3D / ComfyUI を起動・停止する |
| `tools/qwen-model-bench/` | Ollama の 1 モデルをこの機体で実用になるか測る（`bench-model.sh <モデル名>`、結果は `results/`） |
| `tools/gpu-watch-gui/` | gpu-watch.sh の値を見る小さな常駐ウィンドウ（GTK4）。ログイン時に自動起動できる |
| `scripts/` | 導入スクリプトの共通部品（`lib/render-unit.sh` `lib/server-host.sh`）、試験（`tests/`）、Pages の組み立て（`build-site.sh`） |
| `docs/` | 公開用の文書（アーキテクチャ・導入・資源・紹介ページ）と、Pages の元（`site/`）・画像（`images/`） |
| `TestData/` | モデルに解かせる試験問題（数学難問）。3D 生成の入力画像は出所が不明なため追跡しない（`TestData/README.md`） |
| `Documents/` | 利用者向けにまとめた文書（モデル比較など） |

ルートの `./localai` が導入・起動・点検の入口（`doctor` / `install` / `start|stop|status` / `test`）。
新しく作るリポジトリ・試験データは必ずこの中（例 `tools/*/fixtures/`）に置く。`~/Proj` 直下には作らない。
`~/.local/share/qwen-worker` は `tools/qwen-worker` へのシンボリックリンク。MCP 登録と authorized_keys の強制コマンドがそのパスを指す。

## 全体の仕組み（複数のツールにまたがる約束）

- **GPU は 1 枚を取り合う。** Ollama（Qwen 27B で VRAM 22 GiB）・Strata・Hunyuan3D・Pixal3D・ComfyUI は同時に載らない。
  排他は 2 か所で実装している: 入口ページの `portal.py` の `GPU_EXCLUSIVE_KEYS`（起動前にほかを止める）と
  `OLLAMA_UNLOAD_BEFORE_START_KEYS`（起動前に Ollama のモデルを降ろす）、Strata 5 種どうしは systemd の `Conflicts=`
  （`After=` は一方向だけに書く。両側に書くと順序が輪になる）。サービスを足すときは両方と `index.html` の同じキーを揃える。
- **サービスは systemd の user unit で、enable しない。** 各ツールの `systemd/*.service.example` が雛形で、`setup-server.sh` が
  `@REPO_ROOT@` をこの clone の絶対パスに置換して `~/.config/systemd/user/` に置く（`scripts/lib/render-unit.sh`。既にあれば上書きしないので、
  雛形を変えたら置換して手で写す）。env ファイルは `~/.config/<tool>/`。
- **ツールごとの共通の型。** `setup-server.sh`（非対話・sudo を使わない導入。上流の対話式インストーラを置き換える）、
  `run-<tool>`（`serve` / `doctor` などの入口）、`vendor/`（上流をコミット固定で取り込む。直接は直さず `patches/` で当てる。**Hunyuan3D のパッチは Tencent のライセンスの地域制限のため追跡・公開しない**。手元の `tools/hunyuan3d/patches/` は `.gitignore`）、
  `models/` と `.venv` は追跡しない。Python と CUDA はツールごとに違う（下の「ビルドとテスト」）。
- **Open WebUI（8081、このリポジトリ外）** は Ollama と Strata 5 種（8082〜8086 の `/v1`）につなぐ。接続先は
  `~/.local/share/open-webui/data/webui.db` の `config` テーブルが優先され、env は初期値でしかない（`tools/strata/README.md`）。
- **Strata の設定は起動のたびに作り直される。** `run-strata serve` が `run/strata-server*.json` を `stra/config.py` と env から
  生成するので、画面の Settings で変えた値は次の起動で消える。思考の予算（`STRATA_REASONING_BUDGET_TOKENS`）や
  コンテキスト長（`STRATA_MAX_CONTEXT`。既定はモデルの上限 262144）なども env で変える。

## ビルドとテスト

```bash
# GPU を使わない試験をまとめて（ツールごとに OK / FAIL / SKIP）。CI も同じ。
./localai test
uvx --with pytest pytest scripts/tests -q        # localai・setup-server.sh・共通部品の試験（偽の PATH で呼ぶ。実機には触れない）

# 仮想環境は追跡していない。無ければ各ディレクトリで作る:
#   uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.lock.txt -e .
tools/qwen-worker/.venv/bin/python tools/qwen-worker/tests/test_sandbox.py
tools/local-ai-bridge/.venv/bin/python -m pytest tools/local-ai-bridge/tests/test_units.py -q
tools/local-ai-bridge/run-local-ai-task doctor

# hunyuan3d は uv 管理の Python 3.11 を使う（上流の実績ある依存に cp312 wheel が無いため）。
#   tools/hunyuan3d/setup-server.sh
tools/hunyuan3d/.venv/bin/python -m pytest tools/hunyuan3d/tests/test_units.py -q
tools/hunyuan3d/run-hunyuan3d doctor
# 実機試験（GPU と重みを実際に使う。数分かかる。先に systemctl --user stop hunyuan3d）
tools/hunyuan3d/.venv/bin/python tools/hunyuan3d/tests/test_generate_real.py

# pixal3d は uv 管理の Python 3.10 と CUDA 12.6 を使う（Hunyuan3D の 3.11 / CUDA 13.2 とは別系統）。
#   tools/pixal3d/setup-server.sh
# 試験は torch を import しないので uv の一時環境で走る。
uvx --with pytest pytest tools/pixal3d/tests/test_units.py -q
tools/pixal3d/run-pixal3d doctor

# comfyui は Python 3.12 と CUDA 12.6（WTiVo のビルド）。
#   tools/comfyui/setup-server.sh
uvx --with pytest pytest tools/comfyui/tests/test_units.py tools/comfyui/tests/test_run_workflow.py -q
uvx --with pytest --with numpy --with scipy --with trimesh pytest tools/comfyui/tests/test_measure_mesh.py -q
tools/comfyui/run-comfyui doctor                  # 自己試験込み（GPU を使う）。--skip-selftest で省く

# strata は Python 3.12 と CUDA 13.2（engine を sm_80 でビルド）。.venv に pytest は入れない。
#   tools/strata/setup-server.sh --model rvn|coder|official
uvx --with pytest pytest tools/strata/tests -q
uvx --with pytest pytest tools/strata/tests/test_units.py -q -k official   # 1 つに絞る例
tools/strata/run-strata doctor --model rvn       # RAM の判定は、ほかの Strata が止まっていないと NG になる
# API の速さ・答えの計測（--prompt-file で問題ファイルを 1 問として送る。--save-dir に全文を残す）
tools/strata/.venv/bin/python tools/strata/scripts/bench_api.py --help

# portal は依存ゼロ。venv を作らない。試験だけ uv の一時環境で走らせる。
uvx --with pytest pytest tools/portal/tests/test_units.py -q

# gpu-watch-gui も依存ゼロ（システムの python3 + python3-gi の GTK4）。venv を作らない。
uvx --with pytest pytest tools/gpu-watch-gui/tests/test_units.py -q
tools/gpu-watch-gui/run-gpu-watch-gui
# ログイン時の自動起動を入れる/外す
tools/gpu-watch-gui/install-autostart.sh
tools/gpu-watch-gui/install-autostart.sh --uninstall
```

## 長い計測の待ち方

推論の計測は 1 本で 20 分を超えることがある。終わりは `run_in_background` の終了通知か、成果物のファイルができたこと
（`until [ -f ... ]`）で待つ。`until ! pgrep -f "<文字列>"` は待機している bash 自身に一致して終わらない。

## 常時ロードされる知識

@knowledge/10-silver/areas/env.md
@knowledge/10-silver/work/index.md
