# portal

サーバー（<server-ip>）の 8080 番を「サービスの入口ページ」にする。Open WebUI・Hunyuan3D・ComfyUI への
リンクと、GPU（VRAM）の使用状況を 1 画面にまとめる。標準ライブラリだけで動く Python サーバー
（`portal.py`）と、1 ファイル完結の `index.html` で構成する。

## ポート配置

| ポート | サービス | 状態 |
|---|---|---|
| 8080 | 入口ページ（このツール） | 新規 |
| 8081 | Open WebUI | 8080 から移動する |
| 7860 | Hunyuan3D（4 枚の画像 → 3D メッシュ） | 別途導入 |
| 8188 | ComfyUI | 未導入。枠だけ「未導入」と表示 |
| 11434 | Ollama API | 触らない |

## 入口ページで何が分かるか

- 上部の GPU 帯: VRAM の使用量 / 総量（数値とバー）、Ollama に読み込まれているモデル名。
  A30 は Qwen と Hunyuan3D を同時には載せられないため、モデルが読み込まれているときは
  「Hunyuan3D や ComfyUI を起動する前に Qwen を降ろす必要がある」旨を表示する。
- Open WebUI / Hunyuan3D / ComfyUI の 3 枚のカード: 名前・説明・ポート・状態バッジ
  （稼働中 / 起動中… / 停止中 / 未導入）。稼働中のものだけリンクが押せる。
- Open WebUI と Hunyuan3D のカードには「起動」「停止」ボタンがあり、入口ページから
  systemd --user のユニットを起動・停止できる（下記「起動・停止」を参照）。
- `/api/status` を 5 秒ごとに取得して自動更新する。取得に失敗したときは前の値を残さず
  「状態を取得できません」と表示する（古い状態を正しいと誤解しないため）。
- リンクはページを開いたホスト名（`location.hostname`）から組み立てる。サーバー上でも、
  別の PC のブラウザからでも同じページがそのまま使える。

## 起動・停止（Open WebUI / Hunyuan3D）

**PC 起動時に自動起動するのは入口ページ（`portal`）だけ。** Open WebUI（`open-webui`）と
Hunyuan3D（`hunyuan3d`）は自動起動しない。A30 は VRAM 24576 MiB・RAM 31 GiB しかなく、
3 サービスを常時起動しておくと待機中でも Hunyuan3D が VRAM 5,352 MiB・RAM 15.9 GiB、
Open WebUI が RAM 775 MiB を占有し、PC がハングしたため。使うときだけ入口ページから起動する。

- Hunyuan3D は起動に **1〜2 分**かかる（モデルの読み込み）。ボタンを押した直後は
  「起動中…」のまま。ポートが実際に開くまで待つ必要がある。
- Hunyuan3D は起動すると VRAM を**約 5.4GB** 使用する。Qwen（Open WebUI のチャット）と
  同時に使うと応答が遅くなる。

`POST /api/service/<key>/<start|stop>` の仕様:

| 項目 | 内容 |
|---|---|
| 必須ヘッダ | `X-Portal-Request: 1`（無ければ 403。理由は下記） |
| 対象 `key` | `open-webui`、`hunyuan3d` のみ（`comfyui` は未導入のため 409、それ以外の key は 404） |
| `action` | `start` か `stop` のみ（それ以外は 400） |
| GET でこのパスを叩いた場合 | 405（誤操作防止。起動・停止は POST のみ） |
| 未導入のサービスを操作しようとした場合 | 409 |
| 成功・失敗にかかわらず | 500 を返さず、常に `{"ok": bool, "message": str, "state": str}` を JSON で返す |
| `start` のタイムアウト | 30 秒（`Type=simple` なのですぐ返る） |
| `stop` のタイムアウト | 90 秒（Hunyuan3D は終了に時間がかかることがある） |

**認証は無い。LAN 内から誰でも起動・停止を呼べる。** LAN の外には公開していない前提での割り切り。
そのうえで、次の 2 つで被害の範囲を絞っている。

1. 操作できるユニットは `open-webui` と `hunyuan3d` の 2 つに固定。利用者が渡した文字列を
   そのまま `systemctl` へ渡すことはない（`key` で `SERVICES` を引き、こちら側が持つユニット名だけを使う）。
   入口ページ自身（`portal`）は一覧に無いので、自分を止められない。
2. `X-Portal-Request: 1` ヘッダを必須にしている。ヘッダの無い単純な POST は他サイトの JavaScript からでも
   送れてしまうため、独自ヘッダでブラウザの事前確認（preflight）を強制する。こちらは preflight に
   応答しないので、**あなたが別のサイトを見ているときに、そのサイトから勝手に起動・停止されることはない**。

curl から叩くときはヘッダを付ける:

```bash
curl -X POST -H "X-Portal-Request: 1" http://<server-ip>:8080/api/service/hunyuan3d/start
curl -X POST -H "X-Portal-Request: 1" http://<server-ip>:8080/api/service/hunyuan3d/stop
```

## 導入コマンド

サーバー上で **mt ユーザーとして**実行する（root では動かない。理由は下記）。

```bash
cd ~/Proj/localai/tools/portal
./setup-server.sh
```

行うこと:

1. 前提を確認する（python3、Open WebUI のユニットの有無）
2. Open WebUI のユニットをバックアップする（`open-webui.service.bak`。既にあれば上書きしない）
3. Open WebUI を 8081 へ移す（`--port 8080` → `--port 8081` に書き換えて再起動）
4. 8080 が空いたことを確認する
5. `~/.config/systemd/user/portal.service` を作り、`systemctl --user enable --now portal` する
6. 8080 / 8081 の待受と `/api/status` の応答を点検する

**Open WebUI が 8081 に移る。ブラウザのブックマークが `http://<server-ip>:8080` を指している場合は
`http://<server-ip>:8081` に変更が必要。** 入口ページ（8080）から Open WebUI のカードをクリックしても開ける。

## 元に戻す

```bash
cd ~/Proj/localai/tools/portal
./setup-server.sh --revert
```

- 入口ページ（`portal.service`）を止める（ユニットファイル自体は残す。完全に消したい場合は
  `~/.config/systemd/user/portal.service` を手動で削除する）
- Open WebUI を 8080 へ戻す。`open-webui.service.bak` があればそれを復元し、無ければ
  `--port 8081` を `--port 8080` に書き換える

導入の途中（8081 への移行）で失敗したときも、`setup-server.sh` はその場でバックアップから
自動的に復元してから失敗終了する。手動で `--revert` を打たなくても Open WebUI は 8080 に残る。

## ComfyUI を後から足すとき

1. ComfyUI にも systemd --user のユニットを用意するなら、`portal.py` の `SERVICES` にある
   `comfyui` エントリの `"unit": None` をユニット名（例 `"comfyui"`）に変える。これだけで
   `/api/status` の `state`/`controllable` が自動的に計算され、入口ページに起動・停止ボタンが出る。
   ユニットを作らない運用のままなら、このエントリは変更不要（`unit: None` のままなら
   `state` は常に `not_installed`、`controllable` は常に `false` になる）。
2. `index.html` の `SERVICE_META.comfyui` にある `stoppedReason` を、実態に合わせて見直す
   （例えば「停止中」相当の文言に変える、説明文を実態に合わせる、など）。
3. GPU を使うワークフローを想定しているなら、GPU 帯の警告文言（Qwen / Hunyuan3D との同時使用不可）に
   ComfyUI も含めるかを検討する。

## 別の PC から開く

サーバーの IP は `<server-ip>`。同じ LAN 上の PC（Windows + Blender など）のブラウザで
`http://<server-ip>:8080/` を開けば、サーバー上で開いたときと同じ入口ページが表示される。
リンクはページの `location.hostname` を使って組み立てているため、IP でアクセスしても
ホスト名でアクセスしても、各サービスへのリンクは自動的に正しいホストを指す。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `portal.py` | `http.server` ベースの本体（標準ライブラリのみ） |
| `index.html` | 入口ページ本体（外部 CDN 不使用、1 ファイル完結） |
| `setup-server.sh` | 導入・移行・点検・`--revert` を行う冪等なスクリプト |
| `systemd/portal.service.example` | `portal.service` の雛形 |
| `tests/test_units.py` | pytest。ネットワーク・GPU・systemd を使わない単体テスト |

## テスト

```bash
# システムに pytest が無ければ、一時的な venv を用意してから実行する
uv venv --python 3.12 /tmp/portaltest
uv pip install --python /tmp/portaltest/bin/python pytest
/tmp/portaltest/bin/python -m pytest tools/portal/tests/test_units.py -q
```
