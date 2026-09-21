# 運用手順（Ubuntu・A30 サーバー兼 作業 PC）

## 起動と停止

連携層は常駐サービスではない。タスクを受け付けたときだけ実行管理プロセスが起動し、
終わると消える。止めたいときは対象タスクを `cancel` する。

```bash
BRIDGE=/home/mt/Proj/localai/tools/local-ai-bridge

# 状態を見る
$BRIDGE/run-local-ai-task list --limit 10
$BRIDGE/run-local-ai-task list --state running

# 委譲から適用・再検証まで 1 回で済ませる（推奨。status / wait を個別に叩かない）
# Bash ツールから呼ぶときは --max-wait 540（Bash の 600 秒上限の内側に収める）
$BRIDGE/run-local-ai-task run \
  --workspace selftest --request-id <一意な id> \
  --goal "<目的>" --scope "<変更可能範囲>" --acceptance "<合格条件>" \
  --verify unittest --mode deep --max-wait 540
# 終了コード: 0 合格して適用済み / 1 不合格 / 2 設定エラー / 3 重複 / 4 時間切れ
# 時間切れ（4）のときだけ、返った task_id で wait を 1 回足す

# 完了まで待って結果を受け取る（status を何度も叩かない）
$BRIDGE/run-local-ai-task wait task_xxxxxxxx
$BRIDGE/run-local-ai-task wait task_xxxxxxxx --max-wait 600 --no-diff

# 実行中のタスクを止める（そのタスクだけ。Ollama には触らない）
$BRIDGE/run-local-ai-task cancel task_xxxxxxxx
```

## workspace の登録

```bash
$BRIDGE/run-local-ai-task workspace add /path/to/repo --id myrepo \
  --verify unittest --cmd "python3 -m pytest -q"
$BRIDGE/run-local-ai-task workspace list
$BRIDGE/run-local-ai-task workspace which "$PWD"    # 含む workspace_id。無ければ終了コード 1
$BRIDGE/run-local-ai-task workspace remove myrepo
```

登録できるのは `~/.config/local-ai-bridge/bridge.toml` の `[registration] allowed_roots`
配下の Git リポジトリだけ。`submit` / `run` の `--workspace` はここで登録した id を指す。

## Claude Code のスキル（`/qwen` `/qwen-read`）

```bash
$BRIDGE/scripts/install-skills.sh              # ~/.claude/skills/{qwen,qwen-read} へリンク
$BRIDGE/scripts/install-skills.sh --uninstall  # リンクだけ外す
```

実体は `$BRIDGE/skills/qwen/`・`$BRIDGE/skills/qwen-read/`。実装の委譲は `/qwen`、
調査だけなら `/qwen-read` を使う（README.ja.md §3）。

## 診断

```bash
$BRIDGE/run-local-ai-task doctor
```

見るところ:

| 行 | 期待 | 違うときに疑うこと |
|---|---|---|
| `ollama 接続` | `version=0.34.2` | `systemctl status ollama`。別 PC ならトンネルが切れている |
| `モデル` | `digest=22130167c4c2` | `ollama list` でタグが変わっていないか |
| `opencode` | `version=1.18.31` | 自動更新で版が変わっていないか（`autoupdate: false` にしてある） |
| `実効設定` | `enabled_providers=['ollama']` | `$HOME/.opencode/opencode.json` が出来ていないか |
| `見えるモデル` | `ollama/qwen3.8:27b` だけ | クラウドのプロバイダーが混ざっていないか |
| `workspace ...` | `git=True 未コミット=0` | 未コミットがあると既定では受付が止まる |

## ログと証拠の置き場

```
~/.local/state/local-ai-bridge/
├── ledger.db                      台帳（SQLite）
├── locks/job-0.lock               ジョブ枠
├── opencode-profile/              隔離した OpenCode 設定・データ・キャッシュ
├── worktrees/<task_id>/           タスク専用の作業ツリー
└── tasks/<task_id>/
    ├── runner.log                 実行管理プロセスの標準出力
    ├── events-<段階>-<n>.jsonl    OpenCode の生 JSON イベント
    ├── stderr-<段階>-<n>.log      OpenCode の標準エラー
    ├── verify-<n>.log             検証コマンドの出力（1 番は基準コミット）
    ├── changes.diff               差分
    ├── child.pid                  実行中の OpenCode の PID
    └── result.json                結果の索引
```

生の思考・イベントはここに置き、クラウドへは毎回返さない。

## 差分を当てる（承認後）

連携層は元のリポジトリへ書き込まない。適用は人が行う。

```bash
TASK=task_xxxxxxxx
DIFF=~/.local/state/local-ai-bridge/tasks/$TASK/changes.diff
REPO=/home/mt/Proj/localai/tools/local-ai-bridge/fixtures/selftest

git -C "$REPO" apply --check -p1 "$DIFF"    # 先に当たるか確かめる
git -C "$REPO" apply -p1 "$DIFF"            # 当てる
git -C "$REPO" diff                          # 自分の目で見る
```

commit / push は連携層はしない。

## 後片付け

作業ツリーは自動では消さない（途中成果が証拠になるため）。溜まったら外す。

```bash
# 一覧
git -C /home/mt/Proj/localai/tools/local-ai-bridge/fixtures/selftest worktree list

# 個別に外す
git -C /home/mt/Proj/localai/tools/local-ai-bridge/fixtures/selftest worktree remove --force \
    ~/.local/state/local-ai-bridge/worktrees/task_xxxxxxxx
git -C /home/mt/Proj/localai/tools/local-ai-bridge/fixtures/selftest worktree prune
```

## よくある詰まり

**`awaiting_input` で止まる / submit がエラーになる**
元のツリーに未コミット変更がある。勝手に stash しない設計。
`--on-dirty use_head` か `--on-dirty include_uncommitted` を明示する。

**`aborted` になる**
予算か無応答の上限。`result` の `open_questions` に理由が入る。
途中成果は作業ツリーとログに残っている。`resume` で続けられる。

**`state_inconsistent: true` が出る**
台帳では実行中だが実行管理プロセスが生きていない（電源断など）。
`resume` で引き継ぐか、`result` で途中成果を確認する。

**初回だけ異常に遅い**
Ollama が 17 GB のモデルを VRAM へ読み込んでいる。約 60 秒かかる。
`OLLAMA_KEEP_ALIVE` は既定 5 分なので、間が空くとまた発生する。

## 元に戻す

```bash
$BRIDGE/scripts/restore.sh          # 何を追加したかの表示だけ
$BRIDGE/scripts/restore.sh --apply  # MCP 登録の解除と隔離プロファイルの削除
```

委譲ルールを消すには、対象ファイルの
`<!-- local-ai-bridge:begin ... -->` から `<!-- local-ai-bridge:end -->` までを削る。
`.bak` も残っている。
