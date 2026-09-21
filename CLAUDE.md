# localai

NVIDIA A30 1 枚でローカル LLM を動かし、その上に作業を任せるための環境。
推論サーバの選定・モデル・ハードの制約は knowledge/10-silver/areas/env.md にある。

## 構成

| パス | 内容 |
|---|---|
| `knowledge/` | ナレッジベース本体 |
| `tools/qwen-worker/` | ローカル Qwen を Claude Code / Codex から直接使う MCP ワーカー |
| `tools/local-ai-bridge/` | OpenCode 経由でローカル Qwen へ実装を委譲する連携層。スキル `/qwen` `/qwen-read` の実体も（README.ja.md） |

新しく作るリポジトリ・試験データは必ずこの中（例 `tools/*/fixtures/`）に置く。`~/Proj` 直下には作らない。
`~/.local/share/qwen-worker` は `tools/qwen-worker` へのシンボリックリンク。MCP 登録と authorized_keys の強制コマンドがそのパスを指す。

## ビルドとテスト

```bash
# 仮想環境は追跡していない。無ければ各ディレクトリで作る:
#   uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.lock.txt -e .
tools/qwen-worker/.venv/bin/python tools/qwen-worker/tests/test_sandbox.py
tools/local-ai-bridge/.venv/bin/python -m pytest tools/local-ai-bridge/tests/test_units.py -q
tools/local-ai-bridge/run-local-ai-task doctor
```

## 常時ロードされる知識

@knowledge/10-silver/areas/env.md
@knowledge/10-silver/work/index.md
