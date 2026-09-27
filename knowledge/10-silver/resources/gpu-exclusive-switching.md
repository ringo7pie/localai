# gpu-exclusive-switching

Hunyuan3D と Pixal3D の切り替え（A30 が 1 枚しかないための排他）と、低 VRAM モードの扱い。
ポート配置と自動起動の方針は `knowledge/10-silver/areas/web-services.md` を Read する。

## 排他と低 VRAM モード

- **Hunyuan3D と Pixal3D は同時に動かせない。** VRAM も RAM も食い合う。入口ページは片方を起動する前に
  もう片方を止め、応答に停止したサービス名を載せる。停止に失敗したら起動しない。画面は押す前に確認を出す。
- 低 VRAM モードの On/Off は入口ページのスイッチで切り替える。API は
  `POST /api/option/<key>/low-vram/<on|off>`。`X-Portal-Request: 1` は起動・停止と同じく必須。
- 値は各サービスの環境変数ファイルに書く。`~/.config/hunyuan3d/hunyuan3d.env` の `HY3D_LOW_VRAM` と
  `~/.config/pixal3d/pixal3d.env` の `PIXAL3D_LOW_VRAM`。どちらも既定は `1`（有効）。
- **稼働中は変更できない**（409 を返す）。systemd の `EnvironmentFile` は起動時にしか読まれないため、
  稼働中に変えても効かず、画面と実態がずれる。

## 切り替えには数分かかる（2026-09-27 実測）

- **片方を止めた直後にもう片方を起動すると遅い。** Hunyuan3D を止めた直後の Pixal3D の起動に
  **250 秒**かかった。ディスクキャッシュが温まっている状態の 80 秒に対して約 3 倍。
  約 24GB の重みをディスクから読み直すため。
- 入口ページの「起動中…」は「1〜2 分かかります」と表示するが、冷えた状態では 4〜5 分かかる。
- 起動が終わったかどうかは、ポートが開いたかどうかで判断する。systemd が `active` でも
  モデルの読み込み中はポートが開いていない。
