# status — いま Qwen が何を処理しているかを見る

| ファイル | どこで打つ | いつ |
|---|---|---|
| `qwen-status.sh [--watch 秒] [--lines N]` | A30 サーバー | 点検したいとき（委譲が長い・返事が無いとき） |
| `qwen-status-remote.sh --server user@host [--watch 秒]` | 他の PC（macOS / Linux / WSL2） | 同上。ssh でサーバー側のスクリプトを呼ぶ。接続先は必須（環境変数 `LOCALAI_SERVER_HOST` でも指定できる） |
| `qwen-status-remote.ps1 -Server user@host [-Watch 秒]` | 他の PC（Windows PowerShell） | 同上 |

表示するもの: GPU 使用率と VRAM ／ Ollama に載っているモデルと降りる予定時刻 ／ local-ai-bridge の実行中・待ち行列のタスク
（段階 implement / verify / review、ツール呼び出し回数、直近の操作、最後のイベントからの経過秒）／ qwen-worker の推論ロックと実行中タスク ／ Open WebUI。
読み取りだけで何も変更しない。

他の PC からはサーバーのログインパスワードを ssh が聞く。qwen-worker 用の鍵は強制コマンド付きなので、この用途には使えない。
毎回聞かれるのが嫌なら自分の通常の鍵を `ssh-copy-id <user>@<server-ip>`（例: alice@192.168.1.10）で登録する（その鍵はシェルが取れる普通の鍵なので、
qwen-worker 用の鍵とは分けて管理する）。
