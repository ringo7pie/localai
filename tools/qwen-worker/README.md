# qwen-worker

ローカルの Qwen3.8-27B を、Claude Code と Codex の**両方**から使える
コード調査・実装ワーカーとして公開する MCP（stdio）サーバー。

親（Claude / Codex）が要件整理・設計・タスク分割・レビュー・統合判断を持ち、
Qwen が調査・実装・テストコード作成を担当する。

**推論はローカルで動くが、Qwen が返した要約と差分は親経由でクラウドへ送られる。
「すべてのコードがローカルだけに留まる」わけではない。**

## 置き場

| 用途 | パス |
|---|---|
| 実装 | `~/.local/share/qwen-worker/` |
| 設定 | `~/.config/qwen-worker/config.toml` |
| タスク成果物 | `~/.local/state/qwen-worker/tasks/<task_id>/` |
| 検証記録 | `~/.local/state/qwen-worker/verification.json` |
| 未適用の root 変更 | `~/.local/state/qwen-worker/pending-root-changes/` |
| バックアップ | `~/.local/state/qwen-worker/backup/<日時>/` |

## ツール

### `qwen_research`（読み取り専用）
`project_root`, `task`, `allowed_read_paths`, `constraints`, `acceptance_criteria`, `context_profile`

Qwen 自身が `search_text` / `list_files` / `read_file` を繰り返し呼び、
根拠となるファイルと行番号を付けて返す。ファイルは書き換えない。

### `qwen_implement`（隔離された作業コピー内）
`project_root`, `task`, `allowed_write_paths`（必須）, `allowed_read_paths`, `constraints`, `acceptance_criteria`, `context_profile`

元の作業ツリーには**一切書き込まない**。`tasks/<id>/baseline/` に原本スナップショットを、
`tasks/<id>/work/` に作業コピーを作り、Qwen は work/ だけを編集する。
差分は `git diff --no-index baseline work` で生成し、`a/` `b/` に直してあるので
プロジェクトルートで `git apply -p1` がそのまま通る。

git worktree は使わない。worktree は元リポジトリの `.git` 配下にメタデータを書くため。

### `qwen_status`
接続先・モデル・有効なプロファイル・検証状況・ロックの保持者・許可ルートを返す。推論しない。

## 返る形（親の文脈を圧迫しない）

`task_id` / `status`（completed, needs_review, failed, blocked, busy）/ 短い要約 /
根拠（ファイル・行番号）/ 変更ファイル一覧 / `diff_path` / `metrics_path` / `transcript_path` /
実行済み・未実施の検証 / 未解決事項 / 次に必要な判断。

**長い思考出力と全ログは `transcript.json` に落とし、親へはパスだけ返す。**

## プロファイル

| 名前 | num_ctx | num_predict | think | 状態 |
|---|---|---|---|---|
| `standard` | 65536 | 8192 | 有効 | 既定 |
| `extract` | 65536 | 4096 | 無効 | 単純な抜き出し・短い要約用 |
| `large` | 131072 | 16384 | 有効 | **使用不可**（実測で CPU オフロード） |

### 入力予算（重要）

Ollama は 1 リクエストのプロンプトを **`num_ctx / 2` トークンで打ち切り、入力の先頭を
黙って捨てる**（実測: 32768→16386、65536→32770。`done_reason` は `stop` で警告も出ない）。

そのため `num_ctx=65536` での実質の入力上限は約 **32768 トークン**。
ワーカーは推定トークン数が予算（既定 24000。推定は実測比で約 1.3 倍に出る）を超えると
`blocked` を返して止まる。**黙って切り捨てることはしない。**
超えたら渡す範囲を絞るか、親でタスクを分割する。

## 排他制御

同時推論はプロセスをまたいで **1 件**。`flock(~/.local/state/qwen-worker/inference.lock)` で
Claude Code と Codex の合計を 1 に保つ。取れなければ既定 30 秒待ち、それでも駄目なら `busy`。
同一内容の依頼は 1 時間のフィンガープリントで重複実行を防ぐ。

## 制限（初期構成で意図的にやらないこと）

- Qwen に任意シェル実行権限を渡さない。ビルド・テストは親の権限管理下で行う
- 差分の自動適用・commit・push・merge をしない
- `.env` / 秘密鍵 / 認証設定は読み込み・複製の対象外（`config.toml` の `denied_globs`）
- `project_root` は `allowed_roots` 配下に限る。モデルの申告だけを根拠にしない
- パストラバーサルとシンボリックリンク経由の範囲外アクセスは realpath で防ぐ

## 使い方

### Claude Code
```
qwen_research を使って、project_root=/home/mt/Proj/xxx、
task="…"、allowed_read_paths=["src"]、acceptance_criteria=["…"] で調査して。
```

### Codex
同じツール名で呼べる。`~/.codex/config.toml` の `[mcp_servers.qwen-worker]` に登録済み。

### 単体で動かす（クライアントを介さない）
```bash
cd ~/.local/share/qwen-worker
./.venv/bin/python mcp_call.py qwen_status '{}' 60
./.venv/bin/python mcp_call.py qwen_research '@/path/to/args.json' 1800
```

## 起動・停止・設定変更

サーバーは stdio。親が必要なときに起動し、セッション終了で落ちる。常駐しない。

```bash
# 設定変更
$EDITOR ~/.config/qwen-worker/config.toml    # 次回起動から有効

# 依存の確認
~/.local/share/qwen-worker/.venv/bin/python -c "import mcp; print('ok')"

# 境界テスト
~/.local/share/qwen-worker/.venv/bin/python ~/.local/share/qwen-worker/tests/test_sandbox.py
```

## 元に戻す

```bash
claude mcp remove qwen-worker -s user
codex mcp remove qwen-worker                  # /usr/lib/chatgpt/resources/codex
# ~/.claude/settings.json の "env" を消す（バックアップ: state/backup/<日時>/）
# ~/.claude/CLAUDE.md と ~/.codex/AGENTS.md の「ローカル Qwen への委譲」節を消す
rm -rf ~/.local/share/qwen-worker ~/.config/qwen-worker ~/.local/state/qwen-worker
```

---

## 他の PC から使う（SSH 経由）

他の PC の Claude Code / Codex は、SSH でこのホストに繋いで stdio のまま MCP をやり取りする。
他 PC 側に Python も Ollama も要らない。コードもこのホスト側にあるものを触る。

```bash
# 他の PC 側（配布物は remote/ にある。SMB \\<server-ip>\mt から取る）
bash setup-remote.sh                                   # macOS / Linux
powershell -ExecutionPolicy Bypass -File setup-remote.ps1   # Windows

# このホスト側で鍵を受け入れる
bash ~/.local/share/qwen-worker/remote/add-remote-key.sh <PC名> <公開鍵ファイル>
bash ~/.local/share/qwen-worker/remote/remove-remote-key.sh --list   # 一覧
bash ~/.local/share/qwen-worker/remote/remove-remote-key.sh <PC名>   # 取り消し
```

鍵には強制コマンドが付く。`run-qwen-worker` を起動する以外に使えない。

```
command="/home/mt/.local/share/qwen-worker/run-qwen-worker",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... qwen-worker@<PC名>
```

他 PC の MCP 登録は `-- ssh -T qwen-worker` の 1 行だけ。

```bash
claude mcp add -s user qwen-worker -- ssh -T qwen-worker
codex  mcp add          qwen-worker -- ssh -T qwen-worker
```

### リモート向けの挙動

- `qwen_status` が `host` を返す（ホスト名・LAN アドレス・SMB 共有・タスク置き場の SMB パス）
- 差分が `inline_diff_max_lines`（既定 400）行以下なら、結果の **`diff_text` に本文が入る**。
  超えたら `diff_text_omitted` になり `diff_path` を読む
- `project_root` と `allowed_*_paths` は**このホスト上の絶対パス**。SMB パスは `allowed_roots` の検証で弾かれる
- `flock` はこのホスト上にあるので、**全リモートからの依頼を合計 1 件に直列化**する

詳細と他 PC 向けの手順は `remote/README-remote.md`。

---

## ブラウザチャット（Open WebUI）

同じホストで Open WebUI 0.11.3 が `systemd --user` のサービスとして動く。

| 項目 | 値 |
|---|---|
| URL | `http://<server-ip>:8080` |
| 設定 | `~/.config/open-webui/open-webui.env` |
| ユニット | `~/.config/systemd/user/open-webui.service` |
| データ | `~/.local/share/open-webui/data` |
| 版の記録 | `~/.local/share/open-webui/requirements.lock.txt` |

```bash
systemctl --user status open-webui
systemctl --user restart open-webui
journalctl --user -u open-webui -n 50
```

Ollama は `127.0.0.1:11434` のまま。**LAN に公開していない。**
外から見えるのは SSH（22）、Samba（445）、Open WebUI（8080）だけ。

### 意図的に切ってある設定

`ENABLE_TITLE_GENERATION` / `ENABLE_TAGS_GENERATION` / `ENABLE_FOLLOW_UP_GENERATION` /
`ENABLE_AUTOCOMPLETE_GENERATION` を全て `false` にしてある。
これらは同じモデルで裏側の追加推論を走らせる。Ollama は生成を 1 本ずつ直列に処理するため、
有効だと 1 発言ごとに順番待ちが増える。

`ENABLE_SIGNUP=true` のままなので、**最初の 1 人を登録したら `false` にして再起動すること**。

```bash
sed -i 's/^ENABLE_SIGNUP=true/ENABLE_SIGNUP=false/' ~/.config/open-webui/open-webui.env
systemctl --user restart open-webui
```

### GPU の共有について

Ollama は生成を 1 本ずつ直列に処理する（実測: 同時に投げた 2 本が 18.5 秒 / 36.9 秒）。
ワーカーとブラウザチャットは互いに順番待ちになる。エラーにはならない。

ワーカーはツール実行とモデル生成を交互に行うため、ローカルのファイル操作中は
Ollama が空く。ブラウザからの短い質問はその隙間に入ることが多い
（実測: ワーカーのジョブ実行中に送って 2 秒で応答）。

`num_ctx` は Ollama 側の `OLLAMA_CONTEXT_LENGTH=65536` が既定。
**Open WebUI 側で上げないこと。** 65536 を超えると KV キャッシュが CPU に溢れる（実測済み）。
