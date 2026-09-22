# web-services

このサーバーでブラウザから使うサービスの構成。手順は `tools/portal/README.md` を Read する。

## ポート配置

| ポート | サービス | systemd user ユニット | PC 起動時 |
|---|---|---|---|
| 8080 | 入口ページ（`tools/portal`） | `portal` | **起動する** |
| 8081 | Open WebUI | `open-webui` | 起動しない |
| 7860 | Hunyuan3D | `hunyuan3d` | 起動しない |
| 8188 | ComfyUI | （未導入） | — |
| 11434 | Ollama API | `ollama`（system） | 起動する |

- 8080 は元々 Open WebUI が使っていた。入口ページを置くために 2026-09-22 に Open WebUI を 8081 へ移した。
  元の設定は `~/.config/systemd/user/open-webui.service.bak` にあり、`tools/portal/setup-server.sh --revert` で戻せる。
- 8188 は ComfyUI 用に空けてあるだけで、ComfyUI は導入していない。入口ページには「未導入」と出る。
- Ollama だけは 127.0.0.1 で待受し、LAN に公開していない。入口ページ・Open WebUI・Hunyuan3D は 0.0.0.0 で待受する。

## 自動起動の方針（2026-09-22 決定）

- **PC 起動時に立ち上がるのは入口ページだけ。** Open WebUI と Hunyuan3D は `disable` してある。
- 理由は RAM の枯渇でデスクトップがハングしたこと。数値と経緯は
  `knowledge/10-silver/areas/hunyuan3d.md` を Read する。
- 入口ページと Open WebUI は VRAM を使わない。VRAM を使うのは Hunyuan3D と、Ollama がモデルを
  載せたときだけ。量は `knowledge/10-silver/areas/hunyuan3d.md` と `env.md` を Read する。
- systemd の user ユニットで動く。`loginctl` の `Linger=yes` を設定済みなので、デスクトップにログインしなくても
  入口ページは立ち上がる。

## 入口ページからの起動・停止

- 入口ページのカードにある「起動」「停止」ボタンが `systemctl --user start|stop` を呼ぶ。
- Hunyuan3D は押してから使えるまで約 50 秒〜2 分かかる。その間は「起動中…」と表示される。
- 操作の API は `POST /api/service/<key>/<start|stop>`。**`X-Portal-Request: 1` ヘッダが必須**で、
  無いと 403 を返す。ヘッダの無い単純な POST は他サイトの JavaScript からでも送れるため、
  独自ヘッダでブラウザの preflight を強制して、外部サイトからの操作を防いでいる。
- 認証は無い。LAN 内からは誰でも操作できる。操作できるのは `open-webui` と `hunyuan3d` の 2 つだけで、
  入口ページ自身は対象外なので自分を止められない。
