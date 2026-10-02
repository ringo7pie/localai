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
| `tools/portal/` | ポート 8080 のサービス入口ページ。Open WebUI / Hunyuan3D / ComfyUI を選ぶ |
| `tools/gpu-watch-gui/` | gpu-watch.sh の値を見る小さな常駐ウィンドウ（GTK4）。ログイン時に自動起動できる |

新しく作るリポジトリ・試験データは必ずこの中（例 `tools/*/fixtures/`）に置く。`~/Proj` 直下には作らない。
`~/.local/share/qwen-worker` は `tools/qwen-worker` へのシンボリックリンク。MCP 登録と authorized_keys の強制コマンドがそのパスを指す。

## ビルドとテスト

```bash
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

# portal は依存ゼロ。venv を作らない。試験だけ uv の一時環境で走らせる。
uvx --with pytest pytest tools/portal/tests/test_units.py -q

# gpu-watch-gui も依存ゼロ（システムの python3 + python3-gi の GTK4）。venv を作らない。
uvx --with pytest pytest tools/gpu-watch-gui/tests/test_units.py -q
tools/gpu-watch-gui/run-gpu-watch-gui
# ログイン時の自動起動を入れる/外す
tools/gpu-watch-gui/install-autostart.sh
tools/gpu-watch-gui/install-autostart.sh --uninstall
```

## 常時ロードされる知識

@knowledge/10-silver/areas/env.md
@knowledge/10-silver/work/index.md
