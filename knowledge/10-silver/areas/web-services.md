# web-services

このサーバーでブラウザから使うサービスの構成。手順は `tools/portal/README.md` を Read する。

## ポート配置

| ポート | サービス | systemd user ユニット | PC 起動時 |
|---|---|---|---|
| 8080 | 入口ページ（`tools/portal`） | `portal` | **起動する** |
| 8081 | Open WebUI | `open-webui` | 起動しない |
| 7860 | Hunyuan3D | `hunyuan3d` | 起動しない |
| 7861 | Pixal3D | `pixal3d` | 起動しない |
| 8188 | ComfyUI | （未導入） | — |
| 11434 | Ollama API | `ollama`（system） | 起動する |

- 8080 は元々 Open WebUI が使っていた。入口ページを置くために 2026-09-22 に Open WebUI を 8081 へ移した。
  元の設定は `~/.config/systemd/user/open-webui.service.bak` にあり、`tools/portal/setup-server.sh --revert` で戻せる。
- 8188 は ComfyUI 用に空けてあるだけで、ComfyUI は導入していない。入口ページには「未導入」と出る。
- Ollama だけは 127.0.0.1 で待受し、LAN に公開していない。入口ページ・Open WebUI・Hunyuan3D は 0.0.0.0 で待受する。

## 自動起動の方針（2026-09-22 決定）

- **PC 起動時に立ち上がるのは入口ページだけ。** Open WebUI・Hunyuan3D・Pixal3D は `disable` してある。
- 理由は RAM の枯渇でデスクトップがハングしたこと。数値と経緯は
  `knowledge/10-silver/areas/hunyuan3d.md` を Read する。
- 入口ページと Open WebUI は VRAM を使わない。VRAM を使うのは Hunyuan3D・Pixal3D と、Ollama がモデルを
  載せたときだけ。量は `hunyuan3d.md`・`pixal3d.md`・`env.md` を Read する。
- systemd の user ユニットで動く。`loginctl` の `Linger=yes` を設定済みなので、デスクトップにログインしなくても
  入口ページは立ち上がる。

## 入口ページからの起動・停止

- 入口ページのカードにある「起動」「停止」ボタンが `systemctl --user start|stop` を呼ぶ。
- Hunyuan3D は押してから使えるまで約 50 秒〜2 分かかる。その間は「起動中…」と表示される。
- 操作の API は `POST /api/service/<key>/<start|stop>`。**`X-Portal-Request: 1` ヘッダが必須**で、
  無いと 403 を返す。ヘッダの無い単純な POST は他サイトの JavaScript からでも送れるため、
  独自ヘッダでブラウザの preflight を強制して、外部サイトからの操作を防いでいる。
- 認証は無い。LAN 内からは誰でも操作できる。操作できるのは `open-webui`・`hunyuan3d`・`pixal3d` の
  3 つで、入口ページ自身は対象外なので自分を止められない。

## GPU の排他と低 VRAM の切り替え（2026-09-22 追加）

- **Hunyuan3D と Pixal3D は同時に動かせない。** VRAM も RAM も食い合う。入口ページは片方を起動する前に
  もう片方を止め、応答に停止したサービス名を載せる。停止に失敗したら起動しない。画面は押す前に確認を出す。
- 低 VRAM モードの On/Off は入口ページのスイッチで切り替える。API は
  `POST /api/option/<key>/low-vram/<on|off>`。`X-Portal-Request: 1` は起動・停止と同じく必須。
- 値は各サービスの環境変数ファイルに書く。`~/.config/hunyuan3d/hunyuan3d.env` の `HY3D_LOW_VRAM` と
  `~/.config/pixal3d/pixal3d.env` の `PIXAL3D_LOW_VRAM`。どちらも既定は `1`（有効）。
- **稼働中は変更できない**（409 を返す）。systemd の `EnvironmentFile` は起動時にしか読まれないため、
  稼働中に変えても効かず、画面と実態がずれる。
