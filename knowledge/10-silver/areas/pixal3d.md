# pixal3d

画像 1〜4 枚から 3D メッシュを作る Pixal3D（TencentARC、ポート 7861）の運用上の事実。
導入と使い方の手順は `tools/pixal3d/README.md` を Read する。
上流の事情（固定コミット、拡張 6 本のビルド、CUDA 12.6 や torch の選定理由、UI を自前で書いた理由、
背景除去モデルの差し替え）は `knowledge/10-silver/resources/pixal3d-upstream.md` を Read する。

## 使い方の前提

- 入力は正面（0°）・右 90°・背面（180°）・左 270° の 4 枠。1 枚でも生成できるが、
  **正面は必須**。上流が frame 0 を正面基準ビューとして扱うため、欠けると結果が別の向きで出る。
- Hunyuan3D-2mv と同じ 4 枚から別方式で作れる。使い分けは下のライセンスの節で決まる。

## VRAM と RAM（2026-09-22 実測。4 枚入力、解像度 1024、低 VRAM モード）

| 項目 | 値 |
|---|---|
| VRAM ピーク | 17,337 MiB |
| RAM ピーク | 30.4 GiB |
| swap ピーク | 16.3 GiB |
| 所要時間 | 194〜216 秒 |
| 出力 | GLB 33MB、頂点 641,803 / 面 968,048、PBR テクスチャ付き |

- **低 VRAM モードは実質切れない。** Off にすると解像度 1536 で 23.12 GiB、1024 でも 23.32 GiB まで
  VRAM が伸びて CUDA out of memory になる。A30 24 GiB では On が必須。入口ページのスイッチで
  Off にはできるが、生成が失敗する。
- swap 8 GiB のままでは常駐サービスとして RAM 残り 200MiB まで落ちて生成が停滞した。swap を増やして
  解決した。現在の swap 構成は `env.md` を Read する。
- ユニットに `MemoryHigh=24G` / `MemoryMax=28G` を入れてある。超えたときに落ちるのはサービスだけで、
  デスクトップは巻き込まない。
- Hunyuan3D とは同時に動かせない。入口ページが片方を自動で止める。詳細は `web-services.md` を Read する。
- 重み約 24.5GB は `tools/pixal3d/models/` 配下に置く。`HF_HOME` と `TORCH_HOME` もそこへ向ける。
  既定のままだと Open WebUI と共有している `~/.cache` に混ざる。

## ライセンス

コードと重みは MIT 表示。しかし推論時に避けられない形で **nvdiffrast / nvdiffrec**
（NVIDIA Source Code License、**非商用限定**）と **DINOv3**（Meta 独自ライセンス）が混ざる。
HF のモデルカードに `extra_gated_eu_disallowed: true` が残り、地域制限の有無は上流 Issue #33 で
質問されたまま回答が無い。

**Pixal3D の出力を収益化する用途には使えない前提で運用する。収益化するなら Hunyuan3D 側を使う**
（`hunyuan3d.md` を Read する）。
