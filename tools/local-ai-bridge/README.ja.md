# local-ai-bridge

クラウドの Claude Code / Codex を使ったまま、**実装の探索・編集・テストの反復だけ**を
LAN 内のローカル Qwen へ移すための連携層。

クラウドを Qwen に置き換えるものではない。要求整理・設計・タスク分解・合格条件・
重要なレビューと判断はクラウドに残る。

## 1. 役割の分担

| 呼び方 | 何をするか | この環境での実体 |
|---|---|---|
| **クラウド** | 要求整理、設計、タスク分解、合格条件、レビューと判断 | Claude Code 2.1.278 / Codex（ChatGPT デスクトップ版同梱） |
| **作業 PC** | ソース検索、部分読み取り、編集、ビルド、テスト | この PC。OpenCode 1.19.2 + この連携層 |
| **A30 サーバー** | 推論の実行 | この PC（同一ホスト）。Ollama 0.40.5 + `qwen3.8:27b` |

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

A30 サーバー上では、導入スクリプトを **1 回**走らせるだけでよい。再実行しても既にあるものは触らない（冪等）。

```bash
# いつ: 最初の 1 回だけ（再実行しても安全）
~/Proj/localai/tools/local-ai-bridge/scripts/setup-server.sh --workspace ~/Proj/localai
```

`setup-server.sh` がやること（`[1/7]`〜`[7/7]`）:

1. uv と python3 の確認（uv が無ければ導入方法を表示して終了）
2. OpenCode 1.19.2 を `~/.opencode/bin` へ（公式単体バイナリ。シェル設定は書き換えない）
3. 連携層の仮想環境 `.venv`（`requirements.lock.txt` と `-e .`）
4. `~/.config/local-ai-bridge/bridge.toml` を `config/bridge.toml.example` から作り、`[registration] allowed_roots` を書く（既にあれば触らない）
5. Claude Code / Codex への MCP 登録（`register-claude.sh` / `register-codex.sh`）
6. スキル `/qwen` `/qwen-read`（`install-skills.sh`）と委譲ルールの短い版（`add-delegation-rules.sh --short`）
7. `--workspace` で渡したリポジトリの登録と `doctor`

主な引数: `--allowed-root DIR`（複数可、既定 `$HOME/Proj`）、`--workspace PATH`（複数可）、`--mcp-scope local|user`（既定 `local`）、`--no-rules`、`--no-skills`。
検証プロファイルはスクリプトでは付けない。`doctor` が通ったあとで `local-ai-task workspace add ... --verify NAME --cmd "..."`（§3）で足す。

`doctor` がすべて OK になってから使うこと。とくに次の 2 行を確認する。

- `見えるモデル: ollama/qwen3.8:27b` — ローカル以外のモデルが見えていないこと
- `実効設定: enabled_providers=['ollama'] …` — 設定ファイルを置いただけでなく、
  OpenCode が実際にその値で解決していること

他の PC に置くときは `docs/setup-workpc.md`（`scripts/setup-workpc.sh` / `setup-workpc.ps1`）。
sudo が要る作業（ufw、linger、Ollama の drop-in）は `scripts/server-approvals.sh` が差分・影響・戻し方を表示し、人が項目ごとに承認して実行する。

<details>
<summary>手で行う場合（スクリプトと同じ手順）</summary>

```bash
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.19.2 --no-modify-path
cd ~/Proj/localai/tools/local-ai-bridge
~/.local/bin/uv venv --python 3.12 .venv
~/.local/bin/uv pip install --python .venv/bin/python -r requirements.lock.txt
~/.local/bin/uv pip install --python .venv/bin/python -e .
mkdir -p ~/.config/local-ai-bridge
cp config/bridge.toml.example ~/.config/local-ai-bridge/bridge.toml
chmod 600 ~/.config/local-ai-bridge/bridge.toml
$EDITOR ~/.config/local-ai-bridge/bridge.toml   # [registration] allowed_roots と作業場所
./run-local-ai-task doctor
./scripts/register-claude.sh local
./scripts/register-codex.sh
./scripts/install-skills.sh
./scripts/add-delegation-rules.sh --short ~/.claude/CLAUDE.md
```

</details>

## 3. 使い方

### CLI

```bash
# 委譲から適用・再検証まで 1 回で済ませる（推奨。親はこれだけ呼べばよい）
# Bash ツールから呼ぶときは --max-wait 540（Bash の 600 秒上限の内側に収める）
./run-local-ai-task run \
  --workspace selftest \
  --request-id fix-total-length-002 \
  --goal "total_length が区間の重なりを二重に数えている。1回だけ数えるよう直す" \
  --scope "src/interval.py" \
  --acceptance "tests/test_interval.py の 4 件すべてが通る" \
  --verify unittest --mode deep --max-wait 540
# 終了コード: 0 合格して適用済み / 1 不合格 / 2 設定エラー / 3 重複 / 4 時間切れ

# 個別の段階を自分で踏みたいとき（測定・調査用。通常は run を使う）
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
./run-local-ai-task wait    task_xxxxxxxx          # 完了まで待って結果を返す
./run-local-ai-task result  task_xxxxxxxx
./run-local-ai-task result  task_xxxxxxxx --diff
./run-local-ai-task artifact task_xxxxxxxx --name verify-1.log --start 1 --lines 60
./run-local-ai-task cancel  task_xxxxxxxx
./run-local-ai-task resume  task_xxxxxxxx
```

### MCP（クラウドから）

| ツール | 役割 |
|---|---|
| `run_task` | **推奨**。1 回の呼び出しで 委譲→完了待ち→6 フラグ判定→作業ツリーへ適用→再検証→短い要約 まで行う。commit はしない。上限秒を過ぎたら `timed_out=true` で `task_id` を返す |
| `submit_task` | 受付。`task_id` を即返す。長い作業を 1 回の応答に閉じ込めない |
| `get_task_status` | 状態・段階・経過。結果本文は含まない |
| `wait_for_task` | 完了まで待って `get_task_result` と同じ形で返す。上限秒を過ぎたら `timed_out=true` で状態だけ返す |
| `get_task_result` | 短い結果。変更概要・検証成否・未解決点・承認事項 |
| `get_artifact` | 差分やログを**行範囲指定**で取る。任意のファイルは読めない |
| `cancel_task` | そのタスクだけ止める |
| `resume_task` | `task_id` を指定して再開 |
| `bridge_doctor` | 接続と実効設定の点検 |

CLI と MCP は同じ `bridge/core.py` を呼ぶ。別実装ではない。

### Claude Code からは: `/qwen` `/qwen-read`

実装の委譲は `/qwen <依頼文>`、大きなソースの調査は `/qwen-read <調べること>`。
実体は `skills/qwen/`・`skills/qwen-read/`。次で `~/.claude/skills/` へ登録する。

```bash
./scripts/install-skills.sh              # シンボリックリンクを張る
./scripts/install-skills.sh --uninstall  # リンクだけ外す
```

委譲するかどうかの判断基準は §10 と同じ（文脈が大きく単独 4 ターン以上のときだけ得）。

### workspace の登録（`local-ai-task workspace`）

`--workspace` に渡す workspace_id は、`allowed_roots` 配下の Git リポジトリだけ登録できる。

```bash
./run-local-ai-task workspace add /path/to/repo --id myrepo \
  --verify unittest --cmd "python3 -m pytest -q"
./run-local-ai-task workspace list
./run-local-ai-task workspace which /path/to/repo/subdir   # 無ければ終了コード 1
./run-local-ai-task workspace remove myrepo
```

### 親からの推奨の使い方: one-shot を 1 回呼ぶ

クラウド側からは `run_task`（MCP）を **1 回**呼ぶ。MCP が見えない会話では Bash から
`run-local-ai-task run ... --max-wait 540` を **1 回**呼ぶ。どちらも 委譲・待ち・
6 フラグ判定・適用・再検証までを 1 回の呼び出しに閉じ込め、親へは短い要約だけが返る。
`submit` / `status` / `wait` / `get_artifact` を親が個別に叩かない。分けて叩くと親のターンが
積み上がり、文脈の長い会話ではその往復だけで単独で直すより高くつく。

委譲するのは「**親の文脈が大きい（会話が長い）**」かつ「**クラウド単独でやると 4 ターン以上**」の
仕事だけ。新しい短い会話や極小の修正は親が直すほうが安い（§10）。

`.claude/agents/local-delegate.md` の委譲係サブエージェントは、`run` を 1 回呼ぶ薄い包みとして
残してある。親が Bash を持たない場合などに使う。

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
- 連携層自身は commit / push / merge / 適用をしない。差分を出すところまで
- 差分の適用は、検証合格かつ範囲内（`verification.passed`・`changes.out_of_scope` が空・
  `test_integrity.suspicious` が偽・`changes.applies_to_original` が真）のときに限り、
  `local-delegate` が作業ツリーへ `git apply` してよい。**commit / push はしない**

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

## 10. 費用の実測と最終結論（2026-09-21・round 1〜5）

- one-shot 版・新規小文脈（round 3, F1/F2/F3/F5）の実測は 委譲/単独 0.81〜1.15。文脈が
  大きい会話向けの「0.25〜0.50」は、単独が 4〜5 ターンかかるという前提の**計算値**だった
- **round 4（実測）**: 親の文脈 約 92 万トークン/ターンの会話で、新規課題 F6（3 ファイル・
  6 テスト）を A（自力 2 ターン $0.7076）と B（`run --mode deep` 1 回 2 ターン $0.6200）で
  解き、**B/A = 0.88**。前提が崩れ、50% 以下は出なかった
- **全ラウンドを通じて B/A は 0.81〜1.15、0.88 の範囲。50% 以下は一度も観測されていない。**
- **トークン費用の削減を目的とした委譲には実測上メリットが無い**（−12%〜+15%）。何度も
  往復する難タスクなら委譲が有利になりうるが、Qwen 失敗時の引き取り費用
  （round 2 F4 で $0.94）で相殺されうる
- 費用以外の理由（ソース全文をクラウドへ送らない、別実装での照合、A30 が空いていれば
  並行実行）は使う理由として残る。速度はクラウドのサブエージェントより遅い（6 分前後）
- **round 5（実測・実運用の実装）**: 同規模の導入スクリプト 2 本を、A = Sonnet 5 xHigh サブ（親 2 ターン + サブ 11 ターン、$0.73、8.5 分）と
  B = Qwen 委譲（親 17 ターン $2.07、Qwen $0、36 分）で作り、**B/A = 2.85**。Qwen の推論が無料でも、親が
  待ち・確認で刻むターン（`run` の時間切れ → `wait` → 監視 → 結果読み → 適用）が費用の本体。委譲→待ち→結果を
  常駐ループ 1 本にまとめると親は 3 ターン程度に減る（後半 3 件で確認。費用は再計測していない）。
  Qwen の出力には親の補修が各 1 か所要った（実行ビット無し、`wsl` 抜け、既存行の置換漏れ）
- 詳細は `bench/results.json` の `round3`/`round4`/`round5`、
  `knowledge/30-gold/verification-report.md` §1.12〜1.13
