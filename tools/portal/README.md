# portal

サーバー（`<server-ip>`。例: 192.168.1.10）の 8080 番を「サービスの入口ページ」にする。Open WebUI・Strata（汎用版と、
コード向けの Strata Flash-Next Coder、公式量子化版の Strata 公式版）・Hunyuan3D・Pixal3D・ComfyUI へのリンクと、GPU（VRAM）の使用状況を 1 画面にまとめる。標準ライブラリだけで動く Python サーバー
（`portal.py`）と、1 ファイル完結の `index.html` で構成する。

## ポート配置

| ポート | サービス | 状態 |
|---|---|---|
| 8080 | 入口ページ（このツール） | 新規 |
| 8081 | Open WebUI | 8080 から移動する |
| 8082 | Strata（Qwen3.8 Flash Next 125B の abliterated 版 IQ3_S。OpenAI 互換 API の推論エンジン） | 別途導入。systemd --user のユニット名は `strata`。自動起動しない |
| 8083 | Strata Flash-Next Coder（同じ Strata で動く、コード向けのモデル。Qwen3.8-Flash-Next の 512 エキスパートを半分に削った版） | 別途導入。systemd --user のユニット名は `strata-coder`。自動起動しない。汎用の Strata とは同時に動かせない |
| 8084 | Strata 公式版（Qwen3.8-Flash-Next の ISTA-DASLab 公式量子化 GSQ-RCO の IQ3_XXS。512 エキスパートのまま・abliterated ではない。汎用版と答えを比べる用） | 別途導入。systemd --user のユニット名は `strata-official`。自動起動しない。ほかの Strata とは同時に動かせない |
| 8085 | Strata 公式版 IQ3_S（公式版と同じ公式モデルの軽い量子化 IQ3_S。2026-10-16 に追加） | 別途導入。systemd --user のユニット名は `strata-official-iq3s`。自動起動しない。ほかの Strata とは同時に動かせない |
| 8086 | Strata Swift 1.5（UkisAI が Qwen3.8-Flash-Next を思考が短く終わるように追加学習した派生の IQ3_XXS。2026-10-16 に追加） | 別途導入。systemd --user のユニット名は `strata-swift`。自動起動しない。ほかの Strata とは同時に動かせない |
| 7860 | Hunyuan3D（4 枚の画像 → 3D メッシュ） | 別途導入 |
| 7861 | Pixal3D（1〜4 枚の画像 → 3D メッシュ、別方式） | 別途導入 |
| 8188 | ComfyUI（1 枚の画像 → 水密メッシュ・低ポリのゲーム用アセット。PixelArtistry のワークフロー） | 別途導入。systemd --user のユニット名は `comfyui` |
| 11434 | Ollama API | 触らない |

## 入口ページで何が分かるか

- 上部の GPU 帯: VRAM の使用量 / 総量（数値とバー）、Ollama に読み込まれているモデル名。
  A30 は Qwen と Strata（5 つとも）・Hunyuan3D・Pixal3D・ComfyUI を同時には載せられないため、モデルが読み込まれているときは
  「Strata（汎用版・Coder 版・公式版）は起動時に自動で降ろす。Hunyuan3D・Pixal3D・ComfyUI を起動する前には Qwen を降ろす必要がある」旨を表示する。
- Open WebUI / Strata / Strata Flash-Next Coder / Strata 公式版 / Hunyuan3D / Pixal3D / ComfyUI の 7 枚のカード: 名前・説明・ポート・状態バッジ
  （稼働中 / 起動中… / 停止中 / 未導入）。稼働中のものだけリンクが押せる。
  「未導入」は systemd のユニットがまだ無いときに出る（Strata・Strata Flash-Next Coder・Strata 公式版・ComfyUI のユニットを作る前など）。
- Strata の 5 枚のカード（汎用版 `strata`・Coder 版 `strata-coder`・公式版 `strata-official`・公式版 IQ3_S `strata-official-iq3s`・
  Swift 1.5 `strata-swift`）は、稼働中に 2 つのリンクを出す。1 つ目は
  Strata 自身の画面（そのカードのポート。汎用版は 8082、Coder 版は 8083、公式版は 8084、公式版 IQ3_S は 8085、Swift 1.5 は 8086。上流のサーバーはルートでチャットと
  Monitor の画面を返す）、2 つ目は Open WebUI（8081）。ふだんのチャットは Open WebUI のモデル一覧から
  Strata のモデルを選んで使う。Open WebUI が動いていなければ、2 つ目は押せない案内文になる。
  リンクの定義は 5 枚のカードで共有している（`index.html` の `STRATA_OPEN_LINKS`。1 つ目のリンク先のポートは
  `SERVICES` の `port` から取る）。
- 7 枚のカードすべてに「起動」「停止」ボタンがあり、入口ページから systemd --user のユニットを
  起動・停止できる（下記「起動・停止」を参照）。ユニットがまだ無いサービスはボタンが出ない。
- Hunyuan3D・Pixal3D のカードには「低 VRAM モード」のスイッチもある（下記「低 VRAM モードの
  切り替え」を参照）。
- `/api/status` を 5 秒ごとに取得して自動更新する。取得に失敗したときは前の値を残さず
  「状態を取得できません」と表示する（古い状態を正しいと誤解しないため）。
- リンクはページを開いたホスト名（`location.hostname`）から組み立てる。サーバー上でも、
  別の PC のブラウザからでも同じページがそのまま使える。

## 起動・停止（Open WebUI / Strata / Strata Flash-Next Coder / Strata 公式版 / Hunyuan3D / Pixal3D / ComfyUI）

**PC 起動時に自動起動するのは入口ページ（`portal`）だけ。** Open WebUI（`open-webui`）・
Strata（`strata`）・Strata Flash-Next Coder（`strata-coder`）・Strata 公式版（`strata-official`）・Strata 公式版 IQ3_S（`strata-official-iq3s`）・
Strata Swift 1.5（`strata-swift`）・Hunyuan3D（`hunyuan3d`）・Pixal3D（`pixal3d`）・ComfyUI（`comfyui`）は自動起動しない。A30 の VRAM は 24576 MiB しかなく、
常時起動しておくと待機中でも VRAM・RAM を占有する。RAM が 31 GiB だった頃に、これで PC が
ハングしたため自動起動をやめた（RAM はその後 62.5 GiB に増設したが、VRAM の排他は変わらない）。
使うときだけ入口ページから起動する。

- Hunyuan3D・Pixal3D・Strata（5 つとも）は起動に数十秒〜数分かかる（モデルの読み込み。汎用の Strata は約 83GB）。
  ボタンを押した直後は「起動中…」のまま。ポートが実際に開くまで待つ必要がある。
- Hunyuan3D は起動すると VRAM を**約 5.4GB** 使用する。Qwen（Open WebUI のチャット）と
  同時に使うと応答が遅くなる。

`POST /api/service/<key>/<start|stop>` の仕様:

| 項目 | 内容 |
|---|---|
| 必須ヘッダ | `X-Portal-Request: 1`（無ければ 403。理由は下記） |
| 対象 `key` | `open-webui`、`strata`、`strata-coder`、`strata-official`、`strata-official-iq3s`、`strata-swift`、`hunyuan3d`、`pixal3d`、`comfyui` のみ（それ以外の key は 404） |
| `action` | `start` か `stop` のみ（それ以外は 400） |
| GET でこのパスを叩いた場合 | 405（誤操作防止。起動・停止は POST のみ） |
| ユニットがまだ無い（未導入の）サービスを操作しようとした場合 | 409 |
| 成功・失敗にかかわらず | 500 を返さず、常に `{"ok": bool, "message": str, "state": str}` を JSON で返す。他のサービスを止めたときは `stopped`、Strata（`strata`・`strata-coder`・`strata-official`・`strata-official-iq3s`・`strata-swift`）の起動で Ollama のモデルを降ろす処理をしたときは `unloaded_models` も入る（下記） |
| `start` のタイムアウト | 30 秒（`systemctl start --no-block` で待たずに返る。Strata のように「API が応答するまで戻らない」ユニットでも、起動中の表示のまま成功で返る） |
| `stop` のタイムアウト | 90 秒（Hunyuan3D・Pixal3D は終了に時間がかかることがある） |

**認証は無い。LAN 内から誰でも起動・停止を呼べる。** LAN の外には公開していない前提での割り切り。
そのうえで、次の 2 つで被害の範囲を絞っている。

1. 操作できるユニットは `open-webui`・`strata`・`strata-coder`・`strata-official`・`strata-official-iq3s`・`strata-swift`・`hunyuan3d`・`pixal3d`・`comfyui` の 9 つに固定。利用者が渡した文字列を
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

## GPU の排他（Hunyuan3D ⇔ Pixal3D ⇔ ComfyUI ⇔ Strata ⇔ Strata Flash-Next Coder ⇔ Strata 公式版）

Hunyuan3D・Pixal3D はどちらも GPU（VRAM）を使う 3D メッシュ生成器で、ComfyUI も Pixal3D / TRELLIS.2 の
3D 生成で GPU を大きく使う。Strata の汎用版は VRAM を約 20GB 以上、RAM を約 50GB 以上使う推論エンジンで、
Coder 版（`strata-coder`）は VRAM を大きく、RAM を約 32GB 級使う。公式版（`strata-official`）は汎用版と同程度
（2026-10-07 の実測で、cgroup の `memory.peak` 50.00 GiB、VRAM は生成中 23,899 MiB）。公式版 IQ3_S（`strata-official-iq3s`）と
Swift 1.5（`strata-swift`、2026-10-16 に追加）も汎用版・公式版と同じ程度。A30 1 枚・RAM 62.5 GiB では 8 つを
同時に載せられず、**同時に動かせるのは 8 つのうち 1 つだけ**（Strata の 5 つどうしも同時には動かせない）。
**どれかを起動すると、
他のサービスが動いていれば（稼働中・起動中）自動で先に止めてから起動する。**

- 純粋関数 `services_to_stop_before_start(key, states)`（`portal.py`）が、`GPU_EXCLUSIVE_KEYS =
  ("hunyuan3d", "pixal3d", "comfyui", "strata", "strata-coder", "strata-official", "strata-official-iq3s", "strata-swift")` のうち
  起動対象以外で running / starting のものの key 一覧を返す。
  例: ComfyUI を起動するとき Pixal3D が running なら `["pixal3d"]`。Open WebUI はグループ外なので
  常に空リスト。
- `POST /api/service/<key>/start` はこのリストのユニットを先に `systemctl --user stop` してから
  対象ユニットを起動する。**停止に失敗した場合は起動を中止する**（複数が立ち上がって RAM が
  枯れるのを防ぐため）。
- 成功時の応答には `"stopped": ["hunyuan3d"]` のように、実際に止めた key の一覧が入る。
- 画面側は、起動ボタンを押したときに止めるものがある場合だけ「Pixal3D を停止して ComfyUI を
  起動します。よろしいですか？」のように確認ダイアログを出す。キャンセルすれば何も起きない
  （実際に止めるかどうかの最終判断はサーバー側で行う。確認ダイアログはあくまで事前の案内）。
  画面側の `GPU_EXCLUSIVE_KEYS`（`index.html`）は `portal.py` と同じ並びに保つ（試験で一致を確認している）。

### Strata の起動前に Ollama のモデルを降ろす

Strata（汎用版・Coder 版・公式版・公式版 IQ3_S・Swift 1.5 とも）は Qwen（Ollama。`qwen3.8:27b` で実測 22 GiB）と VRAM を同居できない。そのため
`POST /api/service/strata/start`・`POST /api/service/strata-coder/start`・`POST /api/service/strata-official/start`・
`POST /api/service/strata-official-iq3s/start`・`POST /api/service/strata-swift/start` は、同じ GPU を使うサービスを止めたあと、
**Ollama に載っているモデルをすべて VRAM から降ろしてから** Strata を起動する。

- 載っているモデルは `http://127.0.0.1:11434/api/ps` で取り、1 つずつ
  `POST /api/generate {"model": <名前>, "keep_alive": 0}` を送って降ろす（`unload_ollama_models`）。
  純粋関数（`ollama_models_to_unload`・`build_ollama_unload_body`・`describe_ollama_unload`）と、
  HTTP を呼ぶ関数（`request_ollama_unload`）は分けてある。
- 起動の応答に `"unloaded_models": ["qwen3.8:27b"]` のように、降ろす要求が受け付けられたモデル名が入る
  （載っているものが無ければ空リスト）。要求が受け付けられたことだけを見ており、VRAM が空いたことまでは確かめない。
- **降ろすのに失敗しても起動は続ける。** `message` に「注意: …」を足す（降ろせなかったモデル名、または
  `/api/ps` に到達できず確認できなかったこと）。VRAM が足りなければ Strata の起動が失敗するおそれがある。
- Strata が停止中（`stopped`）のときだけ降ろす。すでに稼働中・起動中の Strata への start は何も起こらないので、
  無関係な Qwen の応答を途中で切らない。未導入（409）・他のサービスの停止に失敗した（起動中止）ときも降ろさない。
- 対象は Strata の 5 つだけにしている（`OLLAMA_UNLOAD_BEFORE_START_KEYS = ("strata", "strata-coder", "strata-official", "strata-official-iq3s", "strata-swift")`）。Hunyuan3D は、上流への当て物 0001 を
  当てた環境では生成の直前に自分で降ろす（当て物は公開版に含まない。公開版では `serve` の起動時と、手で実行する
  `run-hunyuan3d free-vram` だけ。`knowledge/10-silver/areas/hunyuan3d.md`）。Pixal3D・ComfyUI は、これまでの動作（画面の警告を見て
  利用者が降ろす）を変えないため含めていない。増やすときはこのタプルと、`index.html` の同名の配列に足す
  （試験で一致を確認している）。
- 画面側は、降ろされるモデルがあるとき、起動ボタンの確認ダイアログに「Ollama のモデル（…）を VRAM から降ろして
  Strata を起動します」と出す。
- 降ろしたあとに Open WebUI で Ollama のモデルを選ぶと、Ollama がそのモデルを再び VRAM に載せる。Strata が
  動いている間は、Ollama のモデルを使わないこと。

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
| その設定を持たないサービス（`open-webui`、`strata`、`strata-coder`、`strata-official`、`strata-official-iq3s`、`strata-swift`、`comfyui`。Strata の 5 つ・ComfyUI には低 VRAM のスイッチを付けていない） | 400 |
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

## メモリ上限（MemoryHigh / MemoryMax）の設定

Open WebUI・Strata・Strata Flash-Next Coder・Strata 公式版・Hunyuan3D・Pixal3D・ComfyUI の各カードには「メモリ上限」欄があり、systemd --user ユニットの
`MemoryHigh` / `MemoryMax` を画面から GiB 単位で変更できる（`unit` が `None` のサービスは対象外だが、
今は全サービスが unit を持つ）。ユニットがまだ無い（未導入の）間は欄を出さず、
API も 409 を返す（`set-property` の宛先が無いため）。

- **MemoryHigh を超えると、そのサービスは絞られて遅くなる**（cgroup が回収を強めるため）。
- **MemoryMax を超えると、そのサービスだけが強制終了される。**
- 実測（2026-09-22）: 機体の RAM を 31 GiB だった頃に決めた上限（Pixal3D 24/28G）が小さすぎて、
  Pixal3D が MemoryHigh を超えたまま swap 満杯で絞られ続け、生成が 43 秒 → 18 分 42 秒に遅くなった。
  その後 RAM を 62.5 GiB（`/proc/meminfo` の MemTotal 65504276 kB）に増設したため、上限も見直した。

### 既定値・許容範囲・推奨上限の根拠

機体の RAM 62.5 GiB のうち、デスクトップ・Ollama・システムなど各サービス以外で約 10.5 GiB、
Qwen がチャットで GPU に入りきらないときさらに約 6 GiB を RAM に使う。これを踏まえ:

| 項目 | 値（この機体） | 決め方 |
|---|---|---|
| 既定 MemoryHigh | 44 GiB | `MEMORY_DEFAULT_HIGH_GIB` |
| 既定 MemoryMax | 48 GiB | `MEMORY_DEFAULT_MAX_GIB` |
| 下限 | 4 GiB | `MEMORY_MIN_GIB` |
| 許容上限（画面から設定できる上限） | 58 GiB | RAM 総量 − `MEMORY_RESERVE_GIB`（4 GiB）を切り捨て |
| 推奨上限（超えても拒否はしないが警告する） | 48 GiB | RAM 総量 − `MEMORY_RECOMMENDED_MARGIN_GIB`（14 GiB）を切り捨て |

**許容上限より大きい値は画面からもエラーで拒否する。** これを超えると、上限に届く前に機体全体の
RAM が尽き、`systemd-oomd` がデスクトップ（GNOME Shell）ごと止めるおそれがある
（2026-09-22 に実際に発生）。推奨上限は拒否しない代わりに黄色い注意を出す。

### サービスごとの既定値（Strata・Strata Flash-Next Coder・Strata 公式版）

「既定に戻す」の値は全サービス共通の 44 / 48 GiB だが、`SERVICES` の項目に `memory_default`
（`{"high_gib": ..., "max_gib": ...}`）があればそちらを使う（`build_memory_entry`）。
汎用の Strata は 125B の MoE のエキスパートを RAM に置き（約 50 GiB 以上）、共通の既定値では
MemoryHigh に絞られて遅くなるため、50 / 54 GiB を持たせている（2026-10-07 の実測で cgroup の memory.peak が 50.0 GiB。許容上限は 58 GiB）。
根拠は `tools/strata/README.md`。

Coder 版（`strata-coder`）は RAM を約 36 GiB 使う（2026-10-07 の実測で cgroup の `memory.peak` 36.00 GiB）ので、
36 / 40 GiB を持たせている（32/36 と 40/44 でも起動・prefill・生成に差は無かった。根拠は `tools/strata/README.md`）。
`portal.py` の `SERVICES` の `strata-coder` の `memory_default` で変えられる。
許容上限（RAM 総量 − 4 GiB。この機体で 58 GiB）以下であることは、試験で確かめている。

公式版（`strata-official`）は、汎用の Strata と同じ 50 / 54 GiB を持たせている。2026-10-07 に MemoryHigh 50G / MemoryMax 54G の
まま動かして実測し、値は変えなかった（cgroup の `memory.peak` 50.00 GiB = MemoryHigh で汎用版と同じ、生成中の current 42.4 GiB。
落とせない分は約 30.2 GiB で、残りは GGUF を写したページキャッシュ）。根拠は `tools/strata/README.md` の「公式版」の節。
値を変えるときは `portal.py` の `SERVICES` の `strata-official` の `memory_default` を書き換え、試験の値も合わせる。

公式版 IQ3_S（`strata-official-iq3s`）と Swift 1.5（`strata-swift`、2026-10-16 に追加）も、実測前の仮置きとして同じ 50 / 54 GiB。
実測したら `tools/strata/README.md` の値に合わせて見直す。

### systemctl への反映（恒久設定と `--runtime` の両方に書く理由）

変更は `systemctl --user set-property <unit> MemoryHigh=<N>G MemoryMax=<M>G` を**続けて 2 回**
実行する（`build_set_property_commands`）。

1. 1 回目（`--runtime` 無し）: `~/.config/systemd/user.control/<unit>.service.d/` に書く。
   恒久設定で、PC を再起動しても残る。
2. 2 回目（`--runtime` 付き）: `/run/user/1000/systemd/user.control/` に書く。ランタイム設定で、
   PC を再起動すると消えるが、**恒久設定より優先度が高い**。以前に誰かが `--runtime` で設定した
   値が残っていると、恒久設定だけ書き換えても反映されない（実際に Pixal3D で発生していた:
   恒久設定は 44/48 のままなのに、有効な値は過去に `--runtime` で書かれた 44/52 だった）。
   両方に同じ値を書くことで、どちらが残っていても画面で決めた値が必ず効く。

どちらも**稼働中のユニットへ再起動なしで即座に効く**。停止中のユニットにも実行できる。
`systemctl revert` は使わない（ユニットファイル本体が `~/.config/systemd/user/` にあるため、
消えてしまう危険がある）。

### API

`POST /api/memory/<key>/<high_gib>/<max_gib>` の仕様（`<high_gib>`/`<max_gib>` は GiB の整数）:

| 項目 | 内容 |
|---|---|
| 必須ヘッダ | `X-Portal-Request: 1`（起動・停止と同じ。無ければ 403） |
| 対象 `key` | `open-webui`、`strata`、`strata-coder`、`strata-official`、`strata-official-iq3s`、`strata-swift`、`hunyuan3d`、`pixal3d`、`comfyui` のみ。存在しない key（`portal` を含む）・`unit` が `None` のサービスは 404 |
| ユニットがまだ無い（未導入の）サービス | 409 |
| `high_gib`/`max_gib` が整数でない | 400 |
| `min_gib ≤ high ≤ max ≤ allowed_max_gib` を満たさない | 400（理由を `message` に） |
| GET でこのパスを叩いた場合 | 405 |
| 成功・失敗にかかわらず | 500 を返さず `{"ok": bool, "message": str, "warning": str \| null, "memory": {...}}` を返す。ただし `/proc/meminfo` が読めない場合のみ 500 |
| `warning` | `max_gib` が推奨上限を超えるときだけ文字列。それ以外は `null`（拒否はしない） |
| `memory` | 書き換え後に読み直した `{"high_gib", "max_gib", "current_gib"}`（GiB、float。上限無しは `null`） |

`GET /api/status` にも `ram`（`{"total_gib", "allowed_max_gib", "recommended_max_gib", "min_gib",
"default_high_gib", "default_max_gib", "available"}`）と、各サービスの `memory`
（`{"high_gib", "max_gib", "current_gib"}`。`unit` を持たないサービスは `null`）が入る。

curl から叩くときはヘッダを付ける:

```bash
curl -X POST -H "X-Portal-Request: 1" http://<server-ip>:8080/api/memory/pixal3d/44/48
```

## 導入コマンド

サーバー上で **サービスを動かす一般ユーザーとして**実行する（root では動かない。理由は下記）。

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

## ComfyUI の扱い（実施済み）

ComfyUI は「未導入の枠」から、起動・停止できるサービスになった。ComfyUI 本体（ポート 8188、
systemd --user のユニット名 `comfyui`）の導入はこのツールの外で行う。入口ページ側でしたこと:

1. `portal.py` の `SERVICES` にある `comfyui` エントリを `"unit": "comfyui"` にした。これで
   `/api/status` の `state`/`controllable` がユニットの有無から計算され、起動・停止ボタンと
   メモリ上限欄が出る。低 VRAM のスイッチは付けていない（`options` 無し）。
2. `GPU_EXCLUSIVE_KEYS` に `comfyui` を足し、Hunyuan3D・Pixal3D と同じ GPU の排他グループに入れた
   （ComfyUI は Pixal3D / TRELLIS.2 の 3D 生成で GPU を大きく使うため。上記「GPU の排他」）。
   `index.html` の `GPU_EXCLUSIVE_KEYS` も同じ並びにした。
3. `index.html` の `SERVICE_META.comfyui`・用語集・ツールチップ・Qwen の警告文を、実態
   （1 枚の画像から水密メッシュや低ポリのゲーム用アセットを作る PixelArtistry のワークフロー。
   Pixal3D / TRELLIS.2 + WTiVo + LODTailor）に合わせて直した。
4. `comfyui` のユニットがまだ無い間は、カードは「未導入」のまま（ボタンは出ず、
   `POST /api/service/comfyui/start` は 409）。ユニットを作れば再起動なしで操作できるようになる。

別のサービスを足すときも同じ手順でよい: `SERVICES` に `unit` 付きで足し、GPU を大きく使うなら
`GPU_EXCLUSIVE_KEYS`（`portal.py` と `index.html` の両方）に足し、`SERVICE_META` に説明を書く。
起動前に Ollama のモデルを降ろしたいなら `OLLAMA_UNLOAD_BEFORE_START_KEYS`（同じく両方）にも足す。

## Strata の扱い

汎用の Strata（ポート 8082、systemd --user のユニット名 `strata`）の導入はこのツールの外で行う。
入口ページ側でしたこと:

1. `SERVICES` に `strata`（`"name": "Strata（Qwen3.8 Flash Next）"`）を足した。チャット系なので Open WebUI の次に並べる。
   低 VRAM のスイッチは付けていない（`options` 無し）。メモリ上限の欄は、`memory` を返すユニットがあれば
   他のサービスと同じ仕組みで出る（ユニットが無い間は「未導入」で、欄もボタンも出ない）。
2. `GPU_EXCLUSIVE_KEYS` に足し、ComfyUI・Hunyuan3D・Pixal3D と同時には動かせないようにした。
3. 起動前に Ollama のモデルを降ろす処理を足した（上記「Strata の起動前に Ollama のモデルを降ろす」）。
4. `index.html` に `SERVICE_META.strata`・用語集（Strata・abliterated）・ツールチップ・確認ダイアログの文言を足した。
5. `strata` のユニットがまだ無い間は、カードは「未導入」のまま（ボタンは出ず、
   `POST /api/service/strata/start` は 409）。

注意: メモリ上限の欄の「既定に戻す」は、`memory_default` を持たないサービスでは全サービス共通の既定値
（MemoryHigh 44 / MemoryMax 48 GiB。`MEMORY_DEFAULT_*`）に戻す。Strata は RAM を約 50GB 以上使うので、
これでは足りず、`memory_default` で 50 / 54 GiB を持たせている（上記「サービスごとの既定値」）。

### Strata Flash-Next Coder（`strata-coder`）

同じ Strata（推論エンジン）で動く、コード向けのモデル。Qwen3.8-Flash-Next の 512 エキスパートを半分に削った版で、
SWE-bench Verified 75.6 などの数字は作者の報告。日本語は実用にならず（実測）、画像入力は未対応。
ポート 8083、systemd --user のユニット名 `strata-coder`、自動起動しない。導入はこのツールの外で行う。
入口ページ側でしたこと:

1. `SERVICES` に `strata-coder`（`"name": "Strata Flash-Next Coder"`）を、汎用の `strata` の次に足した。
   低 VRAM のスイッチは付けていない（`options` 無し）。メモリ上限の既定値は 36 / 40 GiB（実測。上記）。
2. `GPU_EXCLUSIVE_KEYS` と `OLLAMA_UNLOAD_BEFORE_START_KEYS` に足した（`portal.py` と `index.html` の両方）。
   `strata` と同じ扱いで、ComfyUI・Hunyuan3D・Pixal3D・汎用の Strata のどれとも同時に動かせず、起動前に
   Ollama のモデルを降ろす。
3. `index.html` に `SERVICE_META["strata-coder"]`・用語集（Strata Flash-Next Coder）・ツールチップ・Qwen の警告文を
   足した。「Strata の画面」リンクは、2 つの Strata カードで共有する `STRATA_OPEN_LINKS` にまとめた。
4. `strata-coder` のユニットがまだ無い間は、カードは「未導入」のまま（ボタンは出ず、
   `POST /api/service/strata-coder/start` は 409）。

### Strata 公式版（`strata-official`）

同じ Strata（推論エンジン）で動く 3 つ目のモデル。Qwen3.8-Flash-Next の ISTA-DASLab 公式量子化（GSQ-RCO）の IQ3_XXS で、
512 エキスパートのまま・abliterated ではない（汎用版 `strata` は abliterated の RVN 版 IQ3_S）。用途は汎用版と同じで、
数学などで汎用版と答えを比べる用。API のモデル名は `strata-official:IQ3_XXS`。
ポート 8084、systemd --user のユニット名 `strata-official`、自動起動しない。導入はこのツールの外で行う。
入口ページ側でしたこと:

1. `SERVICES` に `strata-official`（`"name": "Strata 公式版（IQ3_XXS）"`）を、`strata-coder` の次に足した。
   低 VRAM のスイッチは付けていない（`options` 無し）。メモリ上限の既定値は汎用版と同じ 50 / 54 GiB
   （2026-10-07 の実測で、この値のままでよいと確かめた。上記）。
2. `GPU_EXCLUSIVE_KEYS` と `OLLAMA_UNLOAD_BEFORE_START_KEYS` に足した（`portal.py` と `index.html` の両方）。
   `strata`・`strata-coder` と互いに排他で、起動前に Ollama のモデルを降ろす。入口ページが先に止める処理は
   このタプルだけで決まる。systemd 側の `Conflicts=` は別の作業で入れる。
3. `index.html` に `SERVICE_META["strata-official"]`・用語集（Strata 公式版。カード名の括弧の前が用語になる）・
   ツールチップ・Qwen の警告文・ポートの説明を足した。「Strata の画面」リンクは `STRATA_OPEN_LINKS` を使う。
4. `strata-official` のユニットがまだ無い間は、カードは「未導入」のまま（ボタンは出ず、
   `POST /api/service/strata-official/start` は 409）。

### Strata 公式版 IQ3_S（`strata-official-iq3s`）と Strata Swift 1.5（`strata-swift`）

2026-10-16 に足した 4 つ目・5 つ目の Strata。公式版 IQ3_S は公式版と同じ公式モデルの軽い量子化（API のモデル名 `strata-official:IQ3_S`、
ポート 8085）、Swift 1.5 は UkisAI が Qwen3.8-Flash-Next を思考が短く終わるように追加学習した派生の IQ3_XXS（`strata-swift:IQ3_XXS`、ポート 8086。
Swift Open License v1.0。この機体では個人の非商用・研究用途）。どちらも自動起動しない。導入はこのツールの外で行う（`tools/strata/README.md`）。
入口ページ側でしたことは公式版と同じ型:

1. `SERVICES` に `strata-official-iq3s`（`"name": "Strata 公式版 IQ3_S（軽い量子化）"`）と `strata-swift`（`"name": "Strata Swift 1.5（IQ3_XXS）"`）を
   `strata-official` の次に順に足した。`options` 無し。メモリ上限の既定値は実測前の仮置きで 50 / 54 GiB。
2. `GPU_EXCLUSIVE_KEYS`・`OLLAMA_UNLOAD_BEFORE_START_KEYS` に足した（`portal.py` と `index.html` の両方）。
3. `index.html` に `SERVICE_META` の 2 件・用語集（カード名の括弧の前が用語になる: 「Strata 公式版 IQ3_S」「Strata Swift 1.5」）・
   ツールチップ・Qwen の警告文・ポートの説明・ほかのカードの「GPU の排他」の文言を足した。
4. ユニットがまだ無い間は、カードは「未導入」のまま。

## 別の PC から開く

サーバーの IP は `<server-ip>`。同じ LAN 上の PC（Windows + Blender など）のブラウザで
`http://<server-ip>:8080/` を開けば、サーバー上で開いたときと同じ入口ページが表示される。
リンクはページの `location.hostname` を使って組み立てているため、IP でアクセスしても
ホスト名でアクセスしても、各サービスへのリンクは自動的に正しいホストを指す。

## マウスオーバーの説明・専門用語のダイアログ

画面上の入力欄・ボタン・スイッチ・状態バッジ・GPU 帯には `title` 属性で詳細説明が付いている
（ブラウザ標準のツールチップ）。説明文は `index.html` 内の `TOOLTIPS`（キーで引く 1 つのオブジェクト）
にまとめている。

VRAM・RAM・swap・Qwen/Ollama・各サービス名（Strata・Strata Flash-Next Coder・abliterated を含む）・低 VRAM モード・GPU の排他・MemoryHigh/MemoryMax・
推奨上限/許容上限・systemd user ユニット・自動起動・ポート・`X-Portal-Request` などの専門用語は、
点線の下線が付いた `<span class="term" data-term="...">` になっており、クリックすると `<dialog>` で
見出しと説明を表示する（閉じるボタン・Esc・背景クリックで閉じる）。用語集は `index.html` 内の
`GLOSSARY` にまとめている。本文は `textContent` で入れており、`GLOSSARY` の値に HTML タグを
混ぜても解釈されない。

いずれの文言も事実に基づく（`knowledge/10-silver/areas/env.md`・`web-services.md`・`hunyuan3d.md`・
`pixal3d.md` の実測値・決定事項）。カードは 5 秒ごとに作り直されるため、専門用語のクリック処理は
個々の要素にではなく `document` へのイベント委譲で行っている。

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
