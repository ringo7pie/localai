# 利用量の比較方法

「クラウドのトークン消費が減ったか」を確かめるための手順。
**削減率は事前に保証しない。** 測ってから言う。

## 1. 何が別々に測れるか

| 量 | どこで取れるか | 取れるか |
|---|---|---|
| クラウドの実トークン数 | Claude Code のセッション記録 + `bench/measure_cloud_tokens.py` | **取れる**（2026-09-21 訂正。下記 1.1） |
| クラウドへ返した文字数・バイト数 | `get_task_result` の `usage.returned_bytes` | 取れる |
| ローカル推論量 | `usage.local_inference`（モデル呼出数・ツール呼出数・入出力トークン） | 取れる |
| 処理時間・待機時間 | `status` の `elapsed_sec`、`queue_wait_sec` | 取れる |
| 修正回数 | `attempt_count` | 取れる |

`get_task_result` の `usage.cloud_tokens` は今も `null` のままにしてある。
連携層はクラウド側のターンを見ていないので、そこに書くと嘘になる。
クラウドの消費は連携層の外（セッション記録）から測る。**推定で埋めない。**

### 1.1 クラウドの実トークン数の測り方（訂正）

**旧記述「クラウドの実トークン数は取得できない。`/cost` を人が実行するしかない」は誤りだった。**
Claude Code は 1 ターンごとの `usage` をセッション記録に書いている。ここから実測できる。

- 親の記録: `~/.claude/projects/<プロジェクト>/<session-id>.jsonl`
- サブエージェントの記録: `~/.claude/projects/<プロジェクト>/<session-id>/subagents/agent-<id>.jsonl`
  （サブエージェントの消費は親の jsonl に入らない。別ファイルになる）

手順:

```bash
# 1. 測定区間の開始時刻を印として出す
python3 bench/measure_cloud_tokens.py mark

# 2. 測りたい作業を実行する

# 3. 区間を指定して合算する
# --session は省略できる（環境変数 CLAUDE_CODE_SESSION_ID を使う。旧 CLAUDE_SESSION_ID も後方互換で読む）
python3 bench/measure_cloud_tokens.py sum \
  --session <session-id> --since <開始 ISO> --until <終了 ISO>

# --since の代わりに直近 N 分を窓にできる
python3 bench/measure_cloud_tokens.py sum --last-minutes 30

# 親のターンだけを見たいとき
python3 bench/measure_cloud_tokens.py sum --session <id> --since <ISO> --parent-only
# 機械可読
python3 bench/measure_cloud_tokens.py sum --session <id> --since <ISO> --json

# サブエージェント 1 体だけの費用を出す（A/B の 1 群がサブエージェントのとき）
python3 bench/measure_cloud_tokens.py sum --session <id> --subagent agent-<id>
# そのセッションにあるサブエージェントの一覧
python3 bench/measure_cloud_tokens.py sum --session <id> --list-subagents
```

サブエージェント単体の記録は `--subagent <agent-id>` で指定する。
どの `agent-id` があるかは `--list-subagents` で一覧できる。

料金は `bench/rates.json`（既定 Claude Opus 5: 入力 $5/MTok・出力 $25/MTok・
キャッシュ読み 0.1×・キャッシュ書き 5 分 TTL 1.25×・1 時間 TTL 2.0×）。

注意（いずれも実測で踏んだ落とし穴。ツール側は対応済み）:

- **重複排除**。1 つの assistant メッセージは内容ブロックごとに複数行へ分かれて書かれ、
  各行が同じ `message.id` と同じ `message.usage` を持つ。素直に全行を足すと 2〜3 倍に水増しされる。
  `message.id`（無ければ `requestId`）で落とす。
- **サブエージェントの合算**。請求は本人に乗るので、既定では `subagents/*.jsonl` も足す。
  委譲係サブエージェントを使う運用では、これを足さないと B 側を過小評価する。
- **記録ファイルは必ず指定する**。更新時刻が一番新しい jsonl を選ぶ自動判定は、
  並行して動く別セッションの記録を掴むので廃止した。
- 委譲 1 件の費用を出すときは、区間内の親ターンを丸ごと足さない。
  並行作業や診断のターンが混ざる。委譲に帰属するのは「起動 1 + 受領 1 = 2 ターン」。

## 2. 比較の手順（同じ合格条件で 2 回やる）

同じタスク・同じ合格条件で、次の 2 通りを実行して比べる。

### A. クラウド単独

1. Claude Code の新しい会話を開く
2. `measure_cloud_tokens.py mark` で**開始時刻を記録**
3. 委譲せずに、クラウドだけで実装させる（`local-ai-bridge` を使わない）
4. 合格条件を満たしたら終了時刻を記録し、`sum --session <id> --since ... --until ...` で合算

### B. ローカルへ委譲

1. Claude Code の新しい会話を開く
2. `measure_cloud_tokens.py mark` で開始時刻を記録
3. `submit_task` で委譲。`get_task_status` は**必要最小限**にする
   （細かい進捗確認でクラウドを何度も呼ぶと、その分クラウドを消費する）
4. `get_task_result` で結果を受け取り、差分を確認して適用
5. **失敗した場合のクラウド側の修正も B の消費に含める**
6. 合格条件を満たしたら `sum` で区間を合算する。
   委譲係サブエージェントを使った場合は `subagents/*.jsonl` の分も必ず含める（既定で合算される）

### 記録する表

| 項目 | A（クラウド単独） | B（委譲） |
|---|---|---|
| クラウド入力トークン | | |
| クラウド出力トークン | | |
| キャッシュ読み / 書きトークン | | |
| クラウド費用（USD） | | |
| クラウドのターン数 | | |
| 所要時間（人の待ち時間） | | |
| ローカル推論トークン | 0 | |
| 修正回数 | | |
| 合格条件を満たしたか | | |

## 3. 検証すべき反対仮説

この 2 つを必ず含めること。良い結果だけを集めない。

### 仮説 1: 小さいタスクでは委譲の手間で消費が増える

対象: 1 ファイル 1 行の修正など。

委譲には `submit_task` の引数（目的・範囲・禁止事項・合格条件）を書く手間と、
`get_task_result` を読む手間がかかる。クラウドが自分で直せば 1 往復で済むものが、
委譲すると 3 往復になることがある。

測り方: 上の A/B を「1 行の typo 修正」で実行する。

### 仮説 2: 難しいタスクではローカル失敗後の再実装で消費が増える

対象: 複数ファイルにまたがる設計変更など。

ローカルが失敗すると、クラウドは「失敗した差分を読む」「原因を考える」
「自分で実装し直す」を追加で行う。委譲しなければ発生しなかった消費。

測り方: ローカルが `failed` または `aborted` になったタスクを 3 件集め、
そのあとクラウドが引き取るまでの `/cost` 差分を記録する。

## 4. 測定そのもので消費しない

- 比較のために大量のクラウド処理を無断で走らせない
- A と B は同じタスクを 1 回ずつ。統計を取るなら回数を決めて合意してから
- `get_task_status` のポーリング間隔を短くしない（30 秒以上を目安にする）

## 5. 現時点で測れていないもの

- **連携層の中からクラウドの消費を読むこと**。`usage.cloud_tokens` は `null` のまま。
  測定はセッション記録を読む外部ツール（`bench/measure_cloud_tokens.py`）で行う
- **Codex 側の実トークン数**。セッション記録の形式を確認していない。
  上の手順は Claude Code の記録に対してのみ検証した
- **委譲に帰属する親ターンの厳密な切り出し**。並行作業のターンが区間に混ざるため、
  「起動 1 + 受領 1 = 2 ターン」という帰属の置き方で近似している
- **小さい文脈の会話での実測**。今ある実測は文脈 約 61 万トークン/ターンの会話のもの。
  小文脈での見込みは計算値であって実測ではない

測れるようになったもの（旧版からの訂正）:

- **クラウドの実トークン数と費用**。セッション記録から実測できる（§1.1）
- **A/B の実測値**。結果は `bench/results.json` と
  `knowledge/30-gold/verification-report.md` §1.11 にある。この文書は手順のみ
