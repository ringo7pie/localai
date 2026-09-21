# 他の PC から qwen-worker を使う

ローカル Qwen のワーカーは **サーバ機（`this-host` / `<server-ip>`）の上だけ**で動く。
他の PC は SSH でそこに繋ぎ、標準入出力で MCP をやり取りするだけ。
他の PC に Python も Ollama も入れる必要はない。

```
 あなたの PC                              <server-ip>
 ┌────────────────────┐                 ┌──────────────────────────┐
 │ Claude Code / Codex│  ssh -T (鍵)    │ run-qwen-worker (stdio)  │
 │   mcp: qwen-worker ┼────────────────►│   └ Qwen3.8-27B (Ollama) │
 │ エクスプローラ     │  SMB \\…\mt     │ /home/mt/Proj/...        │
 └────────────────────┘                 └──────────────────────────┘
```

## 1. セットアップ

サーバの共有 `\\<server-ip>\mt\.local\share\qwen-worker\remote\` からスクリプトを取る。

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File setup-remote.ps1
```

事前に「設定 → アプリ → オプション機能」で **OpenSSH クライアント**を入れておく。

### macOS / Linux

```bash
bash setup-remote.sh [ホストIP] [--skip-server]
```

ホストIP は省略時 `<server-ip>`。

どちらも **1 回実行で、鍵・ssh config・MCP 登録・サーバー側の鍵受け入れ・疎通確認まで終わる**。
順にやること:

1. 専用鍵 `~/.ssh/qwen-worker` を作る（既にあれば再利用）
2. `~/.ssh/config` に `Host qwen-worker` を足す（既にあれば触らない）
3. `claude` / `codex` があれば MCP 登録し、タイムアウトを合わせる
4. **サーバーへ登録** — 公開鍵を標準入力でサーバーの `add-remote-key.sh` に渡す（ssh がパスワードを対話で 1 回聞く）
5. **疎通確認** — `ssh -n -T qwen-worker` を実行し、通れば「接続 OK」、通らなければ「接続 NG」と原因の見方（パスフレーズ / authorized_keys）を表示する。`claude` があれば `claude mcp get qwen-worker` も表示する

## 2. サーバ側で鍵を受け入れる（スクリプトが自動で行う）

スクリプトが自動で行う。ssh 経由で公開鍵を標準入力で
`add-remote-key.sh <PC名> -` に渡すだけなので、サーバーに手動で何かを打つ必要はない。
その際、**サーバーのログインパスワードを 1 回聞かれる**（ssh が対話で聞く。
スクリプトはパスワードを受け取らない・保存しない・引数にもしない）。

再実行しても鍵が重複しない（`add-remote-key.sh` が重複を弾き、その出力をそのまま見せる）。

手で行うときは `-SkipServer`（Windows）/ `--skip-server`（macOS・Linux）で
手順 4・5 をスキップし、公開鍵と手で打つコマンドの表示だけで終わる:

```powershell
# Windows
Get-Content $HOME\.ssh\qwen-worker.pub | ssh mt@<server-ip> 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh <あなたのPC名> -'
```

```bash
# macOS / Linux
ssh mt@<server-ip> 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh <あなたのPC名> -' < ~/.ssh/qwen-worker.pub
```

この鍵は **`run-qwen-worker` を起動することしかできない**。
`authorized_keys` に `command="..."`, `no-pty`, `no-port-forwarding` が付くため、
シェルに入ることも、ポート転送することもできない。

取り消すとき:

```bash
bash ~/.local/share/qwen-worker/remote/remove-remote-key.sh --list    # 一覧
bash ~/.local/share/qwen-worker/remote/remove-remote-key.sh <PC名>    # 取り消し
```

## 3. 疎通確認

```bash
ssh -n -T qwen-worker     # エラーなく即終了すれば接続 OK（bash / PowerShell / cmd 共通。PowerShell では "< NUL" は使えない）
claude mcp get qwen-worker         # Connected
```

Claude Code で `qwen_status` を呼び、`host.lan_address` が `<server-ip>` なら通っている。

**`Enter passphrase for key` と聞かれる場合**: 鍵にパスフレーズが付いている。サーバーのログイン
パスワードではないので何を入れても通らない。MCP は対話できないため、パスフレーズ無しに直す:

```powershell
ssh-keygen -p -f $HOME\.ssh\qwen-worker   # 旧パスフレーズを入れ、新しいものは Enter を 2 回（空）
```

旧パスフレーズが分からなければ `qwen-worker` と `qwen-worker.pub` を削除して setup-remote.ps1 を再実行し、
サーバー側で `remove-remote-key.sh <PC名>` で古い鍵を消してから新しい公開鍵を受け入れ直す。
原因は PowerShell 7.3 以降で `-N '""'` が文字列 `""` をパスフレーズにしてしまう挙動。修正済みの
setup-remote.ps1 は `--%` で渡すので新規作成では起きない。

## 4. パスの扱い（重要）

`project_root` と `allowed_read_paths` / `allowed_write_paths` は
**サーバ側の絶対パス**で渡す。あなたの PC 上のパスや SMB パスは受け付けない。

| あなたの PC で開くとき | ワーカーに渡すとき |
|---|---|
| `\\<server-ip>\mt\Proj\localai` | `/home/mt/Proj/localai` |
| `/Volumes/mt/Proj/localai` (mac) | `/home/mt/Proj/localai` |
| `Z:\Proj\localai` (割り当て済みドライブ) | `/home/mt/Proj/localai` |

許可ルートは `/home/mt/Proj` 配下のみ。外を指すと `blocked` が返る。

成果物（差分・全対話・計測値）はサーバの
`/home/mt/.local/state/qwen-worker/tasks/<task_id>/` に出る。
SMB では `\\<server-ip>\mt\.local\state\qwen-worker\tasks\<task_id>\`。
ただし **400 行以下の差分は結果の `diff_text` に本文が入る**ので、
たいていはファイルを開かずにレビューできる。

## 5. 委譲ルール（あなたの CLAUDE.md / AGENTS.md に貼る）

```markdown
## ローカル Qwen への委譲（qwen-worker MCP。管理対象: この節のみ）
- 通常のコード調査・局所的な実装は `qwen_research` / `qwen_implement` へ委譲する
- 1 タスクに目的・範囲・制約・完了条件を明示する。親の会話全体は渡さない
- パスはサーバ側の絶対パス（`/home/mt/Proj/...`）で渡す。SMB パスは使わない
- 同じ調査・実装を親が最初から重複実行しない。Qwen の根拠と差分を親が確認する
- 差分の適用とビルド・テストは親が既存の承認・権限制御に従って行う。ワーカーは適用しない
- Qwen が書いたテストだけで判断しない。既存テストと完了条件も確認する
- 大規模な設計判断、権限・認証の変更、繰り返し失敗する作業は親が判断する
- 親が実装を引き取ったときは理由を記録する
- 失敗を文脈長不足と決めつけない。情報不足・ツール接続の不具合・モデルの判断ミスも切り分ける
```

## 6. 知っておくこと

- **推論はサーバの GPU 1 枚を全員で共有する。** Ollama は生成を 1 本ずつ直列に処理する
  （実測: 同時に投げた 2 本のうち、片方が 18.5 秒、もう片方は待たされて 36.9 秒）。
  エラーにはならず、順番待ちになるだけ。
- **同時に走るワーカーのジョブは全 PC 合計で 1 件。** サーバ上の `flock` で制御している。
  空くまで既定 30 秒待ち、それでも駄目なら `busy` が返る。
- **入力の上限は約 32,768 トークン。** 超えると `blocked` が返る（黙って切り捨てない）。
  範囲を絞るか、タスクを分割する。
- 推論はローカルだが、**返った要約と差分はあなたの親エージェント経由でクラウドへ送られる。**
  「すべてがローカルに留まる」わけではない。

## 7. ブラウザチャット

同じサーバで Open WebUI が動いている。

```
http://<server-ip>:8080
```

初回はアカウント登録。同じ Qwen3.8-27B を使うので、上の「順番待ち」は
ワーカーとブラウザの間でも起きる。
