# portal

サーバー（<server-ip>）の 8080 番を「サービスの入口ページ」にする。Open WebUI・Hunyuan3D・Pixal3D・
ComfyUI へのリンクと、GPU（VRAM）の使用状況を 1 画面にまとめる。標準ライブラリだけで動く Python サーバー
（`portal.py`）と、1 ファイル完結の `index.html` で構成する。

## ポート配置

| ポート | サービス | 状態 |
|---|---|---|
| 8080 | 入口ページ（このツール） | 新規 |
| 8081 | Open WebUI | 8080 から移動する |
| 7860 | Hunyuan3D（4 枚の画像 → 3D メッシュ） | 別途導入 |
| 7861 | Pixal3D（1〜4 枚の画像 → 3D メッシュ、別方式） | 別途導入 |
| 8188 | ComfyUI | 未導入。枠だけ「未導入」と表示 |
| 11434 | Ollama API | 触らない |

## 入口ページで何が分かるか

- 上部の GPU 帯: VRAM の使用量 / 総量（数値とバー）、Ollama に読み込まれているモデル名。
  A30 は Qwen と Hunyuan3D を同時には載せられないため、モデルが読み込まれているときは
  「Hunyuan3D や ComfyUI を起動する前に Qwen を降ろす必要がある」旨を表示する。
- Open WebUI / Hunyuan3D / Pixal3D / ComfyUI の 4 枚のカード: 名前・説明・ポート・状態バッジ
  （稼働中 / 起動中… / 停止中 / 未導入）。稼働中のものだけリンクが押せる。
- Open WebUI・Hunyuan3D・Pixal3D のカードには「起動」「停止」ボタンがあり、入口ページから
  systemd --user のユニットを起動・停止できる（下記「起動・停止」を参照）。
- Hunyuan3D・Pixal3D のカードには「低 VRAM モード」のスイッチもある（下記「低 VRAM モードの
  切り替え」を参照）。
- `/api/status` を 5 秒ごとに取得して自動更新する。取得に失敗したときは前の値を残さず
  「状態を取得できません」と表示する（古い状態を正しいと誤解しないため）。
- リンクはページを開いたホスト名（`location.hostname`）から組み立てる。サーバー上でも、
  別の PC のブラウザからでも同じページがそのまま使える。

## 起動・停止（Open WebUI / Hunyuan3D / Pixal3D）

**PC 起動時に自動起動するのは入口ページ（`portal`）だけ。** Open WebUI（`open-webui`）・
Hunyuan3D（`hunyuan3d`）・Pixal3D（`pixal3d`）は自動起動しない。A30 は VRAM 24576 MiB・
RAM 31 GiB しかなく、常時起動しておくと待機中でも VRAM・RAM を占有し、PC がハングしたため。
使うときだけ入口ページから起動する。

- Hunyuan3D・Pixal3D は起動に数十秒〜数分かかる（モデルの読み込み）。ボタンを押した直後は
  「起動中…」のまま。ポートが実際に開くまで待つ必要がある。
- Hunyuan3D は起動すると VRAM を**約 5.4GB** 使用する。Qwen（Open WebUI のチャット）と
  同時に使うと応答が遅くなる。

`POST /api/service/<key>/<start|stop>` の仕様:

| 項目 | 内容 |
|---|---|
| 必須ヘッダ | `X-Portal-Request: 1`（無ければ 403。理由は下記） |
| 対象 `key` | `open-webui`、`hunyuan3d`、`pixal3d` のみ（`comfyui` は未導入のため 409、それ以外の key は 404） |
| `action` | `start` か `stop` のみ（それ以外は 400） |
| GET でこのパスを叩いた場合 | 405（誤操作防止。起動・停止は POST のみ） |
| 未導入のサービスを操作しようとした場合 | 409 |
| 成功・失敗にかかわらず | 500 を返さず、常に `{"ok": bool, "message": str, "state": str}` を JSON で返す |
| `start` のタイムアウト | 30 秒（`Type=simple` なのですぐ返る） |
| `stop` のタイムアウト | 90 秒（Hunyuan3D・Pixal3D は終了に時間がかかることがある） |

**認証は無い。LAN 内から誰でも起動・停止を呼べる。** LAN の外には公開していない前提での割り切り。
そのうえで、次の 2 つで被害の範囲を絞っている。

1. 操作できるユニットは `open-webui`・`hunyuan3d`・`pixal3d` の 3 つに固定。利用者が渡した文字列を
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

## GPU の排他（Hunyuan3D ⇔ Pixal3D）

Hunyuan3D と Pixal3D はどちらも GPU（VRAM）を使う 3D メッシュ生成器で、A30 1 枚では同時に
載せられない。そのため、**片方を起動すると、もう片方が動いていれば（稼働中・起動中）自動で
先に止めてから起動する。**

- 純粋関数 `services_to_stop_before_start(key, states)`（`portal.py`）が、`GPU_EXCLUSIVE_KEYS =
  ("hunyuan3d", "pixal3d")` のうち起動対象以外で running / starting のものの key 一覧を返す。
- `POST /api/service/<key>/start` はこのリストのユニットを先に `systemctl --user stop` してから
  対象ユニットを起動する。**停止に失敗した場合は起動を中止する**（両方立ち上がって RAM が
  枯れるのを防ぐため）。
- 成功時の応答には `"stopped": ["hunyuan3d"]` のように、実際に止めた key の一覧が入る。
- 画面側は、起動ボタンを押したときに止めるものがある場合だけ「Hunyuan3D を停止して Pixal3D を
  起動します。よろしいですか？」のように確認ダイアログを出す。キャンセルすれば何も起きない
  （実際に止めるかどうかの最終判断はサーバー側で行う。確認ダイアログはあくまで事前の案内）。

## 低 VRAM モードの切り替え（Hunyuan3D / Pixal3D）

Hunyuan3D・Pixal3D のカードには「低 VRAM モード」のスイッチがある。値は各サービスの
systemd ユニットが `EnvironmentFile` として読む env ファイルに書き込む
（Hunyuan3D は `~/.config/hunyuan3d/hunyuan3d.env` の `HY3D_LOW_VRAM`、Pixal3D は
`~/.config/pixal3d/pixal3d.env` の `PIXAL3D_LOW_VRAM`。値は `1`/`0`。ファイルや変数が
無ければ既定値 on として扱う）。

`POST /api/option/<key>/low-vram/<on|off>` の仕様:

| 項目 | 内容 |
|---|---|
| 必須ヘッダ | `X-Portal-Request: 1`（起動・停止と同じ。無ければ 403） |
| 対象 `key` | `hunyuan3d`、`pixal3d` のみ。それ以外の key は 404 |
| `low-vram` 以外の設定名・`on`/`off` 以外の値 | 400 |
| その設定を持たないサービス（`open-webui`、`comfyui`） | 400 |
| **稼働中・起動中（running / starting）のサービス** | **409**。`{"ok": false, "message": "変更するには先に停止してください。"}` |
| GET でこのパスを叩いた場合 | 405 |
| 成功時 | `{"ok": true, "message": str, "value": bool}` |

**停止中のときしか変更できない。** systemd の `EnvironmentFile` はユニットの起動時にしか
読まれないため、稼働中に書き換えても動いているプロセスには反映されず、利用者が「変えたのに
変わらない」と誤解する。そのため稼働中・起動中は 409 を返し、書き込み自体を行わない。

env ファイルの読み書きは `portal.py` の純粋関数 `parse_env_file` / `render_env_file` が担う。
`render_env_file` は既存の行・コメントを保ったまま対象の変数だけを差し替え、無ければ末尾に
追記する。実際の書き込みは `write_option_value` が行い、同じディレクトリの一時ファイルへ
書いてから `os.replace` で置き換える（書き込み途中でプロセスが落ちても壊れた状態で残らない
ようにするため）。

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
