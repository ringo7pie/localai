# 導入から起動まで

段階ごとに、**どこまでやれば何ができるか**を区切って書く。必要な資源は
[hardware-requirements.md](hardware-requirements.md)、仕組みは [architecture.md](architecture.md)。

| ここまで | できること | GPU | 目安 |
|---|---|---|---|
| 0 | 評価レポートを読む・試験を走らせる | 不要 | 数分 |
| 1〜2 | 入口ページ（portal）を見る・Ollama の Qwen と話す | Ollama のみ要 | 約 20 分（17 GB の取得） |
| 3 | MoE の大きなモデル（Strata）を OpenAI 互換 API で使う | 要 | 約 100 GB の取得 |
| 4 | 画像から 3D メッシュ・ComfyUI | 要 | 30 GB 前後ずつ |
| 5 | Claude Code / Codex からローカル Qwen を使う | Ollama が要る | 数分 |

## 0. 取得と点検

```bash
git clone https://github.com/ringo7pie/localai.git
cd localai
./localai doctor
```

`doctor` は 項目ごとに `OK` / `WARN` / `NG` と理由・対処を出す。`NG` があると終了コード 1。

| よくある表示 | 意味と対処 |
|---|---|
| `uv` が NG | 導入手順は https://docs.astral.sh/uv/ 。ツールの venv は uv が作る |
| GPU なしの WARN | 入口ページの閲覧・レポートの閲覧・試験だけ使える。推論はできない |
| VRAM が 24 GiB 未満の WARN | 動作確認は 24 GB のカードのみ。小さいモデル以外は載らない可能性が高い |
| CUDA 12.6 / 13.2 が無い | ツールごとに要る版が違う（Pixal3D・ComfyUI は 12.6、Strata・Hunyuan3D は 13.2）。使うものだけ入れればよい |

試験（GPU 不要）:

```bash
./localai test
./localai test --list          # 走らせる試験の名前の一覧
./localai test --only portal   # 1 つだけ
```

## 1. Ollama と Qwen

```bash
./localai install ollama
```

公式の導入手順と `ollama pull qwen3.8:27b` を表示する（実行はしない。`curl | sh` を勝手に走らせない）。
表示された手順を自分で実行する。17 GB のモデルの初回ロードに約 60 秒かかる。コンテキスト長は
65,536 が上限（超えると KV キャッシュが CPU に溢れる）。値の根拠は `knowledge/10-silver/areas/env.md`。

## 2. 入口ページ

```bash
./localai install portal        # 8080 を使う。使用中なら --port 18080 など
./localai start portal
```

ブラウザで `http://<server-ip>:8080/`（同じ機体なら `http://127.0.0.1:8080/`）を開く。
GPU の使用量・Ollama のモデル・各サービスの状態と「起動」「停止」ボタンが出る。

- Open WebUI は**別途導入**する（このリポジトリには含めない。公式の手順に従う）。入口ページから起動・停止するには、
  user unit `open-webui.service` として **8081** で動かす。8080 を使っている既存の Open WebUI を 8081 へ移したいときだけ
  `./localai install portal --move-open-webui`（元の設定はバックアップされ、`--revert --move-open-webui` で戻せる）。
- 入口ページ以外のサービスは自動起動しない（`enable` しない）。

## 3. Strata（MoE の CPU-GPU 分担推論）

```bash
./localai install strata --model rvn        # rvn | coder | official
./localai start strata                       # 80〜115 秒かかる
```

- モデルと MTP の材料で約 100 GB を取得する。RAM が足りないと `doctor`（`run-strata doctor`）が NG を出す。
  ほかの Strata を止めておく。
- API は OpenAI 互換。`http://<server-ip>:8082/v1`、モデル名は `strata-flash-next:IQ3_S`
  （Coder は 8083 `strata-flash-coder:IQ1_M`、公式は 8084 `strata-official:IQ3_XXS`、公式の IQ3_S は 8085 `strata-official:IQ3_S`、
  Swift 1.5 は 8086 `strata-swift:IQ3_XXS`）。
- 起動のたびに設定が作り直される。画面の Settings で変えた値は残らない。思考の予算などは環境変数
  （`~/.config/strata/*.env`）で変える。詳しくは `tools/strata/README.md`。
- **汎用版は abliterated** で有害な依頼にも応じる。LAN に開くなら `STRATA_API_KEY` を付ける。

## 4. 3D 生成・ComfyUI

```bash
./localai install pixal3d                                  # MIT。出力を収益化しない前提
./localai install hunyuan3d --accept-tencent-license       # 下の注意を読んでから
./localai install comfyui
```

- 同時に載せられるのは 1 つ。入口ページか `./localai start <名前>` で起動すると、動いているほうは自動で止まる。
  ただし Ollama のモデルは、3D 生成・ComfyUI の起動前には自分で降ろす（入口ページの案内に従う）。
- **Hunyuan3D の使用許諾**: EU・UK・韓国は対象外。`--accept-tencent-license` を付けるまで何も取得しない。
  公開版にはパッチを含めないため、画面の説明・設定の保存・失敗パラメータの表示は使えない
  （[tools/hunyuan3d/README.md](../tools/hunyuan3d/README.md)）。
- **入力画像**: このリポジトリには含めない。権利を持つ画像を、正面・背面・左・右の 4 枚で用意する
  （[TestData/README.md](../TestData/README.md)）。
- 低 VRAM モードは重みを CPU 側へ置くため、RAM を強く使う。メモリ上限は入口ページから変えられる。

## 5. Claude Code / Codex からローカル Qwen を使う

```bash
./localai install qwen-worker
```

Claude Code への MCP 登録（`claude mcp add -s user qwen-worker`）までを行う。登録後、Claude Code のセッションで
`qwen_research`（読み取り専用の調査）と `qwen_implement`（隔離した作業コピーでの実装）が使える。

- 許可ルート（`~/.config/qwen-worker/config.toml` の `allowed_roots`）は、既定でこの clone だけ。ほかのプロジェクトを
  渡すときは、その親ディレクトリを足す。
- **ローカルに閉じない**: 返された要約と差分は親を通ってクラウドへ送られる。
- より重い連携層（台帳・worktree 分離・検証・予算）は `tools/local-ai-bridge/README.ja.md`。

## 6. 他の PC から使う

- 入口ページと各 API は LAN に開く。サービスを足したら、ファイアウォールでそのポートを許可する
  （手順と切り分けは `knowledge/10-silver/resources/lan-access.md`）。
- 他の PC から Qwen を使う: `tools/qwen-worker/remote/setup-remote.sh <server-ip>`（SSH トンネル）。
  Windows 用の PowerShell 版もあるが、実機では未検証。
- **認証が無い**。LAN の外へは出さない。

## 7. 困ったとき

| 症状 | 見ること |
|---|---|
| サーバーからは動くが、ほかの PC から見えない | ファイアウォールでポートを許可したか（`lan-access.md`） |
| 起動ボタンを押しても「起動中…」のまま | 冷えた状態では 4〜5 分かかる。ポートが開くまで待つ。`journalctl --user -u <名前>` |
| `Conflicts` で別の Strata が止まる | 仕様。5 種は同時に載せない |
| RAM 不足でサービスが落ちる | `MemoryMax` の歯止めが効いた。ほかの重いサービスを止める。値は入口ページで変える |
| 設定ファイルを変えたのに反映されない | Strata は起動のたびに作り直す。Open WebUI の接続先は DB が優先される |
| 試験が `SKIP` になる | 実機が要る試験（`hunyuan3d-real`・`local-ai-bridge-real`）は手で流す |

## 8. 停止・撤去

```bash
./localai stop strata
./tools/portal/setup-server.sh --revert        # 入口ページを止めて外す
```

各ツールの `.venv`・`vendor/`・`models/` はツールのディレクトリの中にある（追跡しない）。
消すときは、そのディレクトリを削除し、`~/.config/systemd/user/<名前>.service` と
`~/.config/<ツール名>/` を消して `systemctl --user daemon-reload`。
