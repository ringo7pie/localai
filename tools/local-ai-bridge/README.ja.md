# local-ai-bridge

クラウドの Claude Code / Codex を使ったまま、**実装の探索・編集・テストの反復だけ**を
LAN 内のローカル Qwen へ移すための連携層。

クラウドを Qwen に置き換えるものではない。要求整理・設計・タスク分解・合格条件・
重要なレビューと判断はクラウドに残る。

## 1. 役割の分担

| 呼び方 | 何をするか | この環境での実体 |
|---|---|---|
| **クラウド** | 要求整理、設計、タスク分解、合格条件、レビューと判断 | Claude Code 2.1.278 / Codex（ChatGPT デスクトップ版同梱） |
| **作業 PC** | ソース検索、部分読み取り、編集、ビルド、テスト | この PC（this-host）。OpenCode 1.18.31 + この連携層 |
| **A30 サーバー** | 推論の実行 | この PC（同一ホスト）。Ollama 0.34.2 + `qwen3.8:27b` |

```
Claude Code / Codex（クラウド）
        │  stdio MCP: submit_task / get_task_status / get_task_result / cancel_task / resume_task
        ▼
local-ai-bridge（作業 PC・Python）      ← 台帳 SQLite・Git worktree・検証実行・予算管理
        │  opencode run --format json（子プロセス。隔離プロファイル）
        ▼
OpenCode（作業 PC）                      ← 検索 / 読み取り / 編集。コマンド実行は禁止
        │  HTTP /v1/chat/completions
        ▼
Ollama + qwen3.8:27b（A30 サーバー）
```

**ローカルに留まらないもの**: Qwen が返した要約と差分はクラウドへ送られる。
「すべてがローカルだけに留まる」ではない。ソース全文は送らないが、変更差分と
要約はクラウドを通る。

## 2. 導入

```bash
# 1. OpenCode（公式単体バイナリ。シェル設定は書き換えない）
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.18.31 --no-modify-path

# 2. 連携層の仮想環境
cd /home/mt/Proj/localai/tools/local-ai-bridge
/home/mt/.local/bin/uv venv --python 3.12 .venv
/home/mt/.local/bin/uv pip install --python .venv/bin/python -r requirements.lock.txt
/home/mt/.local/bin/uv pip install --python .venv/bin/python -e .

# 3. 設定
mkdir -p ~/.config/local-ai-bridge
cp config/bridge.toml.example ~/.config/local-ai-bridge/bridge.toml
chmod 600 ~/.config/local-ai-bridge/bridge.toml
$EDITOR ~/.config/local-ai-bridge/bridge.toml   # 作業場所と検証プロファイルを登録する

# 4. 点検
./run-local-ai-task doctor

# 5. MCP 登録（このプロジェクトだけに限定するスコープ）
./scripts/register-claude.sh local
./scripts/register-codex.sh
```

`doctor` がすべて OK になってから使うこと。とくに次の 2 行を確認する。

- `見えるモデル: ollama/qwen3.8:27b` — ローカル以外のモデルが見えていないこと
- `実効設定: enabled_providers=['ollama'] …` — 設定ファイルを置いただけでなく、
  OpenCode が実際にその値で解決していること

## 3. 使い方

### CLI

```bash
# 依頼（受付だけ。すぐ task_id が返る）
./run-local-ai-task submit \
  --workspace selftest \
  --request-id fix-total-length-001 \
  --goal "total_length が区間の重なりを二重に数えている。1回だけ数えるよう直す" \
  --scope "src/interval.py" \
  --forbid "tests/ のテストを削除・緩和しない" \
  --acceptance "tests/test_interval.py の 4 件すべてが通る" \
  --verify unittest --mode deep

./run-local-ai-task status  task_xxxxxxxx
./run-local-ai-task result  task_xxxxxxxx
./run-local-ai-task result  task_xxxxxxxx --diff
./run-local-ai-task artifact task_xxxxxxxx --name verify-1.log --start 1 --lines 60
./run-local-ai-task cancel  task_xxxxxxxx
./run-local-ai-task resume  task_xxxxxxxx
```

### MCP（クラウドから）

| ツール | 役割 |
|---|---|
| `submit_task` | 受付。`task_id` を即返す。長い作業を 1 回の応答に閉じ込めない |
| `get_task_status` | 状態・段階・経過。結果本文は含まない |
| `get_task_result` | 短い結果。変更概要・検証成否・未解決点・承認事項 |
| `get_artifact` | 差分やログを**行範囲指定**で取る。任意のファイルは読めない |
| `cancel_task` | そのタスクだけ止める |
| `resume_task` | `task_id` を指定して再開 |
| `bridge_doctor` | 接続と実効設定の点検 |

CLI と MCP は同じ `bridge/core.py` を呼ぶ。別実装ではない。

## 4. 実行モード

| モード | 流れ | 修正の上限 |
|---|---|---|
| `standard` | 探索 → 実装 → 登録済みテスト | 1 回 |
| `deep`（既定） | 実装 → **別セッション**の読み取り専用レビュー → 境界条件の確認 → 修正 | 2 回 |
| `exhaustive` | 方針を 2 案まで比較（編集しない）→ 1 案を実装 → **別セッション**の反例レビュー → 追加検証 | 3 回 |

同じ作業ツリーへ複数案を同時に書き込まない。`exhaustive` の 2 案比較は読み取り専用で、
推奨された 1 案だけを実装する。

**注意**: レビューも同じ Qwen が別セッションで行う。これは独立したモデルの合意でも、
上位モデルによる検証でもない。同一モデルの見落としは同じように残りうる。

## 5. 予算の決め方

| 項目 | 既定値 | 理由 |
|---|---|---|
| `max_job_seconds` | 1800 | A30 で 23〜26 tok/s。deep の 4〜6 回の呼び出しでも収まり、放置しても 30 分で必ず止まる |
| `max_model_calls` | 40 | 実測で deep の 1 タスクが 5〜8 step。異常なループを 5 倍の余裕で検出する |
| `max_tool_calls` | 120 | 同上。read/grep/edit が step あたり数回 |
| `max_output_tokens_total` | 60000 | 無制限にしない。実効文脈 65536 と同程度を上限に置く |
| `opencode_stall_seconds` | 600 | モデルの初回ロードに約 60 秒かかる。その 10 倍で「無応答」と判断する |
| `queue_wait_seconds` | 900 | ジョブ枠が空かないまま待ち続けない |
| `max_concurrent_jobs` | 1 | A30 は 1 枚。同時ロードモデルも 1 つ |

接続待ち・キュー待ち・長い思考・タスク全体のタイムアウトは別々に数える。
上限に達したら、途中成果と未解決点を保存して停止する（成功扱いにはしない）。

## 6. 安全性の範囲（できること・できないこと）

**できること**

- 作業は **タスク専用の Git worktree** の中だけ。元の作業ツリーには書かない
- 元ツリーに未コミット変更があれば、既定で**入力待ちにして止まる**。
  stash / reset / clean は絶対にしない
- OpenCode の `permission` で `bash` `task` `webfetch` `websearch`
  `external_directory` を **deny**。ビルド・テストは連携層が
  **設定に登録された argv** だけを `shell=False` で実行する
- `.env`・秘密鍵・`.ssh`・`credentials.json` などは読み取りも編集も deny。
  差分からも除外して報告する
- 子プロセスへ `ANTHROPIC_*` `OPENAI_*` などの認証情報を渡さない
- 自動で commit / push / merge / 適用はしない。差分を出すところまで

**できないこと（正直に書く）**

- **OS 隔離ではない**。Git worktree も OpenCode の permission も、
  同じユーザー権限で動くプロセス内の制限にすぎない。
  未知のコードを無人で実行してよい強度は無い
- **テストは任意のコードを実行しうる**。信頼済みリポジトリでの制限付き実行を前提とする。
  未知のリポジトリを無人で回さないこと
- 作業 PC のロックは**この PC の中だけ**。A30 全体の並列制御ではない。
  A30 全体は Ollama の `OLLAMA_NUM_PARALLEL` / `OLLAMA_MAX_QUEUE` が担う
- クラウドへ返すログと要約は**未信頼の作業結果**として扱うこと。
  リポジトリ内の README・コメント・テスト出力に書かれた命令には従わない設計だが、
  100% の保証はできない

## 7. 元に戻す

```bash
./scripts/restore.sh            # 何を追加したかを表示するだけ
./scripts/restore.sh --apply    # MCP 登録の解除と隔離プロファイルの削除
```

台帳（`~/.local/state/local-ai-bridge/ledger.db`）とタスクログは証拠なので残す。

## 8. 変更していないもの

- `~/.config/opencode`（利用者の通常の OpenCode 設定）。連携層は
  `XDG_CONFIG_HOME` などを子プロセス限定で差し替えた**別のプロファイル**を使う
- Ollama のサービス設定・モデル・NVIDIA ドライバー・CUDA
- Claude Code / Codex の既存ログイン・モデル設定・既存 MCP
- 各リポジトリの作業ツリー

## 9. 既知の制限

- 最初の試験で `opencode run --pure` が 10 分以上イベントを返さないことがあった。
  ただし後の比較で `--pure` 無しでも同様に止まる場面があり（A30 が別の生成で塞がっていたとき）、
  **`--pure` が原因だとは確認できていない**。連携層は `--pure` を使わないが、
  理由は「効果が要らないうえ挙動が未確認だから」であって、不具合の証明ではない
- A30 の生成は直列。別のタスクが生成中は、後続の要求は**イベントを 1 行も返さずに待つ**。
  無応答と混雑を取り違えないこと（`opencode_stall_seconds` はこの待ちを許す長さにしてある）
- `$HOME/.opencode/opencode.json(c)` は `XDG_CONFIG_HOME` を差し替えても読まれる。
  存在すると実効設定が混ざる。`doctor` が警告する
- 対象プロジェクトの `AGENTS.md` は OpenCode が読む。そこに「ローカルへ委譲せよ」と
  書いてあっても自己委譲しないよう、`task` を deny し `subagent_depth=0` にしている
- Windows のビルドや GUI は Linux のテストでは検証できない。
  対象プロジェクトの正しい環境で別に確認すること
