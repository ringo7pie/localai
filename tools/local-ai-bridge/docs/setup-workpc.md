# 追加の作業 PC を足す手順

この文書は「A30 サーバー（this-host / <server-ip>）はそのまま、別の PC を作業 PC にする」
場合の手順。**この手順はまだ実機で検証していない**（別 PC が無いため）。
未検証であることを承知のうえで使うこと。

## 0. 構成

作業 PC ごとに OpenCode と連携層を置く。推論だけを A30 へ送る。
A30 側のワークスペース全体を複製する必要はない。

```
作業 PC (Windows 11 / WSL2 / Linux / macOS)
  Claude Code または Codex
        │ stdio MCP
  local-ai-bridge（その PC の Python）
        │ 子プロセス
  OpenCode（その PC のファイルを編集）
        │ HTTP 127.0.0.1:11434（SSH トンネルの入口）
  ─────── SSH ───────▶ A30 サーバー 127.0.0.1:11434 の Ollama
```

**Ollama を LAN へ公開しない。** `OLLAMA_HOST=0.0.0.0` にはしない。
SSH トンネルなら、ファイアウォールの変更も新しい待受ポートも要らない。

## 1. 1 スクリプトで導入する（推奨）

作業 PC で導入スクリプトを **1 回**走らせる。途中で A30 サーバーのログインパスワードを ssh が 1〜2 回聞く（鍵の登録と本体の複製）。サーバー側で何かする必要はない。

```bash
# macOS / Linux / WSL2。いつ: 最初の 1 回だけ（再実行しても安全）
scp mt@<server-ip>:Proj/localai/tools/local-ai-bridge/scripts/setup-workpc.sh .
bash setup-workpc.sh --server-ip <server-ip>
```

```powershell
# Windows 11。WSL2 が要る（bridge 本体は fcntl を使うため Windows ネイティブでは動かない）
# いつ: 最初の 1 回だけ。この Windows→WSL2 の経路は未検証
scp mt@<server-ip>:Proj/localai/tools/local-ai-bridge/scripts/setup-workpc.sh .
scp mt@<server-ip>:Proj/localai/tools/local-ai-bridge/scripts/setup-workpc.ps1 .
powershell -ExecutionPolicy Bypass -File .\setup-workpc.ps1 -ServerIp <server-ip>
```

`setup-workpc.sh` がやること（`[1/7]`〜`[7/7]`）: トンネル専用鍵 `~/.ssh/a30-tunnel` → サーバーの `authorized_keys` に制限付きの 1 行を追記（§2 の行と同じ）→ `~/.ssh/config` に `Host a30-ollama` → トンネル起動ヘルパ `~/.local/bin/a30-tunnel`（`start|stop|status`）→ uv と OpenCode → 本体を `rsync` で複製し `.venv` と `bridge.toml` を作る → MCP 登録・スキル・委譲ルール → `doctor`。
主な引数: `--server-ip`、`--server-user`、`--install-dir`（既定 `~/local-ai-bridge`）、`--allowed-root`（複数可）、`--skip-server`（サーバーへの鍵登録を表示だけにする）、`--no-rules`。

**使うたび**にやることは 1 つだけ: `a30-tunnel start`（トンネルを張る）。切るのは `a30-tunnel stop`、確認は `a30-tunnel status`。

以下 §2〜§5 は、スクリプトがやっていることの説明と、手で進めたい人向けの手順。

## 2. A30 サーバー側（承認が必要な作業はしない）

作業 PC の公開鍵を A30 側の `~/.ssh/authorized_keys` へ追加する。
トンネル専用にするなら、転送先を 1 つに限定した行にする。

```
# ~/.ssh/authorized_keys の 1 行（A30 サーバー側）
restrict,port-forwarding,permitopen="127.0.0.1:11434",command="echo tunnel-only" ssh-ed25519 AAAA... workpc-01
```

- `restrict` で pty・エージェント転送・X11 転送などをまとめて落とす
- `permitopen` で 11434 以外への転送を禁じる
- `command=` でシェルを取らせない

この編集は鍵の受け渡しを伴うため、**利用者本人が行う**。連携層は代行しない。

## 3. 作業 PC 側: トンネルを張る

### Linux / macOS / WSL2

```bash
ssh -N -L 127.0.0.1:11434:127.0.0.1:11434 mt@<server-ip>
```

常駐させるなら `autossh` か systemd --user のユニットにする。

### Windows 11（ネイティブ、PowerShell）

Windows 同梱の OpenSSH クライアントで同じことができる。

```powershell
ssh -N -L 127.0.0.1:11434:127.0.0.1:11434 mt@<server-ip>
```

確認:

```powershell
curl.exe http://127.0.0.1:11434/api/version
```

### WSL2 の注意

WSL2 から Windows 側のポートは `127.0.0.1` では見えないことがある。
**トンネルは WSL2 の中で張る**のが確実。WSL2 内で上の `ssh -N -L` を実行する。

## 4. 作業 PC 側: OpenCode と連携層

```bash
# OpenCode（版を固定する）
curl -fsSL https://opencode.ai/install | bash -s -- --version 1.18.31 --no-modify-path

# 連携層
git clone <このリポジトリ> && cd <repo>/tools/local-ai-bridge
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.lock.txt
uv pip install --python .venv/bin/python -e .

mkdir -p ~/.config/local-ai-bridge
cp config/bridge.toml.example ~/.config/local-ai-bridge/bridge.toml
```

`bridge.toml` で直すところ:

| キー | 値 |
|---|---|
| `[ollama] base_url` | `http://127.0.0.1:11434`（トンネルの入口。そのままでよい） |
| `[opencode] binary` | その PC 上の opencode のパス |
| `[opencode] config_source` | clone 先の `opencode-profile/opencode.json` |
| `[state] root` | **ローカルディスク上**にする。ネットワークドライブ不可 |
| `[workspace.*]` | その PC 上のリポジトリを登録する |

### Windows ネイティブで使う場合の制約（未検証）

- 連携層は `fcntl.flock` と `/proc` を使う。**Windows ネイティブでは動かない。**
  Windows では **WSL2 の中**で連携層を動かすこと。
- 検証プロファイルの `command` は WSL2 側から見えるコマンドになる。
  Windows のビルド（MSVC、UE など）を WSL2 から起動する必要がある場合は、
  そのための argv を登録すること。Linux のテストだけで Windows のビルドや GUI を
  成功扱いにしないこと。

### MCP 登録（手で進める場合）

```bash
<install-dir>/scripts/register-claude.sh user
<install-dir>/scripts/register-codex.sh   # codex があれば
<install-dir>/scripts/install-skills.sh
```

## 5. 点検

```bash
./run-local-ai-task doctor
```

`ollama 接続` が OK になれば、トンネル越しに A30 へ届いている。

## 6. 同時実行について

A30 は 1 枚。作業 PC が増えても推論は直列化される。
**作業 PC 側の `max_concurrent_jobs` は、その PC の中だけの制限。**
A30 全体の制御は A30 側の `OLLAMA_NUM_PARALLEL` と `OLLAMA_MAX_QUEUE` が担う。
作業 PC のロックだけで A30 全体の並列制御ができているとは言えない。
