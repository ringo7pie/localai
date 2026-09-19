# localai

NVIDIA A30 1 枚でローカル LLM を動かし、その上に作業を任せるための環境。
推論サーバの選定・モデル・ハードの制約は knowledge/10-silver/areas/env.md にある。

## 構成

| パス | 内容 |
|---|---|
| `knowledge/` | ナレッジベース本体 |
| `tools/qwen-worker/` | ローカル Qwen を Claude Code / Codex から使う MCP ワーカー |

`~/.local/share/qwen-worker` は `tools/qwen-worker` へのシンボリックリンク。
MCP 登録と authorized_keys の強制コマンドはそのパスを指している。

## ビルドとテスト

```bash
# 仮想環境は追跡していない。無ければ作る
cd tools/qwen-worker && uv venv --python 3.12 .venv \
  && uv pip install --python .venv/bin/python -r requirements.lock.txt \
  && uv pip install --python .venv/bin/python -e .

tools/qwen-worker/.venv/bin/python tools/qwen-worker/tests/test_sandbox.py   # 境界テスト
```

## 常時ロードされる知識

@knowledge/10-silver/areas/env.md
@knowledge/10-silver/work/index.md
