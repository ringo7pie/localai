---
name: qwen
description: 実装・局所修正・テスト追加を local-ai-bridge 経由でローカル Qwen へ委譲し、判定・適用・再検証まで 1 回で終わらせる
argument-hint: <依頼文（目的・範囲・禁止事項・合格条件があれば含める）>
allowed-tools: mcp__local-ai-bridge__run_task, mcp__local-ai-bridge__wait_for_task, Bash, Read
---

# ローカル Qwen への実装委譲

依頼: $ARGUMENTS

## 0. 判断材料（1 行・実行は止めない）

委譲が得なのは会話が長く、単独なら 4 ターン以上かかる仕事。1〜2 ターンで済む修正は自分で直すほうが安い。

## 1. workspace の確認

Bash で実行する。

```bash
/home/mt/Proj/localai/tools/local-ai-bridge/run-local-ai-task workspace which "$PWD"
```

終了コードが 1 なら、このディレクトリは未登録。次のメッセージを出して**ここで終わる**（勝手に登録しない）。

> このディレクトリは未登録。`local-ai-task workspace add <リポジトリのパス>` で登録してから。

終了コード 0 なら、出力の workspace_id を次の手順で使う。

## 2. 依頼の組み立て

`$ARGUMENTS` から goal を作る。本文中に明示があれば scope / forbidden / acceptance をそこから拾う。
無ければ次を既定にする。

- scope: 空（Qwen 側の探索に任せる）
- forbidden: `["テストを削除・緩和しない"]`
- acceptance: `["登録済みの検証コマンドが通る"]`

mode は `$ARGUMENTS` に「小さい」「1 行」「軽微」のいずれかがあれば `standard`、それ以外は `deep`。
request_id は `qwen-<YYYYmmdd-HHMMSS>`（今の時刻から作る）。

## 3. 実行（1 回だけ）

MCP ツール `run_task` が使えるなら、それを **1 回**呼ぶ（`max_wait_sec` は 1200）。
workspace・goal・scope・forbidden・acceptance・mode・request_id を渡す。

MCP に `run_task` が見当たらない（古い会話など）ときだけ、Bash で代わりに実行する。

```bash
/home/mt/Proj/localai/tools/local-ai-bridge/run-local-ai-task run \
  --workspace <workspace_id> --request-id <request_id> \
  --goal "<goal>" --scope "<scope>" --forbid "<forbidden>" --acceptance "<acceptance>" \
  --mode <mode> --max-wait 540
```

（Bash ツールの 600 秒上限の内側に収めるため `--max-wait 540`、timeout は 590000ms を指定する。）
終了コードが「時間切れ」（4）で `timed_out` のときだけ、返った `task_id` で
`run-local-ai-task wait <task_id> --max-wait 540` を **1 回だけ**追加で呼ぶ。

`submit` / `status` / `wait` を個別に何度も叩かない。ターンが積み上がり、
長い会話では単独で直すより高くつく。

## 4. 報告（600 字以内・箇条書き）

次を含める。

- `judged_ok` / `applied` / `state`
- 変更ファイル一覧
- 検証コマンドと終了コード
- 未解決点
- `task_id`

不合格のときは `reasons` と `apply_hint` を出す。**自動で再投入しない。**
commit / push はしない。生ログ・差分本文はここに貼らない
（必要なら `get_artifact` / `run-local-ai-task artifact` で行範囲を指定して別途取る）。
