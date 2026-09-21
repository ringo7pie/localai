---
name: qwen-read
description: 大きなソースの調査を読み取り専用でローカル Qwen（qwen-worker）へ委譲し、根拠（ファイル:行）付きの要約だけを受け取る
argument-hint: <調べること>
allowed-tools: mcp__qwen-worker__qwen_research, mcp__qwen-worker__qwen_status, Bash
---

# ローカル Qwen への調査委譲（読み取り専用）

調べること: $ARGUMENTS

## 1. project_root を決める

Bash で実行する。

```bash
git -C "$PWD" rev-parse --show-toplevel
```

失敗する（git 管理外の）ときは `$PWD` を project_root として使う。

## 2. 許可ルートの確認

`qwen-worker` の許可ルート（`allowed_roots`）は `/home/mt/.config/qwen-worker/config.toml` で決まっており、
現在の設定値は次の 1 つだけ。

- `/home/mt/Proj`

project_root がこの配下に無いなら、`qwen_research` は呼ばずに `qwen_status` を呼んで
接続先・許可ルートの案内をそのまま出し、**ここで終わる**。

## 3. 調査の実行（1 回だけ）

```
qwen_research(project_root=<1 で決めた root>, task="$ARGUMENTS", context_profile="standard")
```

目的・範囲を `$ARGUMENTS` の記述だけに絞る。親の会話全体を渡さない。

## 4. 報告

`qwen_research` が返した根拠（ファイル:行）付きの要約を、そのまま返す。
要約を書き直して薄めない。

この結果を受けた親は、同じファイルを丸ごと Read しない。必要な箇所だけ行範囲を限定して読む。
