# localai

[English summary](README.md)

NVIDIA A30（VRAM 24 GB）1 枚で、ローカルの LLM・3D 生成・画像ワークフローを動かし、その上でクラウドの
Claude Code / Codex から作業を回すための、**運用ツール・連携層・評価ハーネス**の一式。
コード・文書・計測の記録をすべてこのリポジトリに置いている。

| 見る場所 | 内容 |
|---|---|
| [docs/portfolio.md](docs/portfolio.md) | 解いた問題・設計の判断・計測した数値・学び（ポートフォリオ向けの 1 枚） |
| [docs/architecture.md](docs/architecture.md) | 全体の構成・GPU の排他・連携層の流れ・評価ハーネス（図つき） |
| [docs/getting-started.md](docs/getting-started.md) | 導入から起動まで、段階ごとの手順 |
| [docs/hardware-requirements.md](docs/hardware-requirements.md) | 動作を確かめた構成と、ツールごとの必要な資源 |
| [NOTICE.md](NOTICE.md) | 第三者のソフトウェア・モデル・商標と、利用上の制約 |
| `https://ringo7pie.github.io/localai/` | 評価レポート（GitHub Pages） |

![入口ページ](docs/images/portal.png)

## 何ができるか

- **GPU 1 枚を取り合う複数のサービスを、1 画面で起動・停止する。** 入口ページ（portal）が GPU の排他を取り、
  Strata の起動前に Ollama のモデルを降ろす。画面を通さない操作は systemd の `Conflicts=` が守る。
- **VRAM に収まらない MoE のモデルを、24 GB のカードで動かす。** Strata（MoE の CPU-GPU 分担推論）を固定コミットから
  ビルドし、OpenAI 互換 API で 5 種（汎用・Coder・公式 IQ3_XXS・公式 IQ3_S・Swift 1.5）出す。
- **複数枚の画像から 3D メッシュを作る。** Hunyuan3D-2mv（4 枚入力）と Pixal3D（1〜4 枚）、ComfyUI の防水メッシュのワークフロー。
- **クラウドの Claude Code / Codex から、機械的な実装の反復だけをローカルの Qwen へ回す。** MCP サーバー
  （qwen-worker・local-ai-bridge）。要求の整理・設計・レビューはクラウドに残す。
- **モデルを測って比べる。** 同じ問題・同じ採点（隠しテスト）で比べ、HTML のレポートにする。2026-10-08 は 9 つの AI を 16 問で、
  2026-10-18 は難問 9 問を Claude 8 構成とローカル 9 モデルで比べた。
- **同じ環境を再現する。** 上流は固定コミット、導入は非対話・冪等・sudo なし。

## 構成

| パス | 内容 | GPU |
|---|---|---|
| `localai` | 入口のスクリプト。`doctor` / `install` / `start` / `stop` / `status` / `test` | 不要 |
| `tools/portal/` | ポート 8080 の入口ページ。起動・停止、GPU の排他、メモリ上限。依存なし | 不要 |
| `tools/strata/` | MoE の CPU-GPU 分担推論（OpenAI 互換 API）。汎用版 8082・Coder 版 8083・公式版 8084・公式版 IQ3_S 8085・Swift 1.5 8086 | 要 |
| `tools/pixal3d/` | 複数画像から 3D メッシュ（Pixal3D、7861） | 要 |
| `tools/hunyuan3d/` | 4 枚の画像から 3D メッシュ（Hunyuan3D-2mv、7860）。**使用許諾の確認が要る**（下記） | 要 |
| `tools/comfyui/` | ComfyUI と防水メッシュのワークフロー（8188）。WTiVo のネイティブ部分（CGAL・CUDA 12.6）を自前でビルドする | 要 |
| `tools/qwen-worker/` | ローカル Qwen を Claude Code / Codex から直接使う MCP ワーカー | 不要（Ollama を呼ぶ） |
| `tools/local-ai-bridge/` | OpenCode 経由でローカル Qwen へ実装を委譲する連携層（台帳・worktree 分離・検証・予算） | 不要（Ollama を呼ぶ） |
| `tools/model-eval/` | モデルの比較評価。問題・採点器・記録・レポートの生成 | 不要（サーバーを呼ぶ） |
| `tools/qwen-model-bench/` | Ollama の 1 モデルが、この機体で実用になるかを測る | 要 |
| `tools/status/`・`tools/gpu-watch-gui/` | いま Qwen が何を処理しているか／GPU を見る小さな常駐ウィンドウ（GTK4） | 不要 |
| `scripts/` | 導入スクリプトの共通部品（`lib/`）と試験（`tests/`）、Pages の組み立て | 不要 |
| `Documents/` | 評価レポート・調査書・ガイド（1 ファイル完結の HTML） | — |
| `knowledge/` | 運用の事実・制約・決定の記録（測った値を残す） | — |
| `TestData/` | 試験問題（数学難問）。3D の入力画像は含めない（`TestData/README.md`） | — |

## ポート

| ポート | サービス | 備考 |
|---|---|---|
| 8080 | 入口ページ（portal） | 自動起動するのはこれだけ |
| 8081 | Open WebUI | 別途導入（このリポジトリには含めない） |
| 8082 / 8083 / 8084 / 8085 / 8086 | Strata 汎用版 / Coder 版 / 公式版 / 公式版 IQ3_S / Swift 1.5 | 5 つは同時には載せない |
| 7860 / 7861 | Hunyuan3D / Pixal3D | 排他 |
| 8188 | ComfyUI | 排他 |
| 11434 | Ollama API | 127.0.0.1 のみ |

## 導入

動作を確かめた構成: Ubuntu 24.04・NVIDIA A30 24 GB・ドライバ 595・CUDA 13.2 と 12.6・RAM 64 GB。
ほかの構成は未検証（[docs/hardware-requirements.md](docs/hardware-requirements.md)）。
前提: `git`・`uv`・`python3`（3.12 以上）・`systemctl --user`。GPU のツールは NVIDIA ドライバと CUDA Toolkit。

```bash
git clone https://github.com/ringo7pie/localai.git
cd localai
./localai doctor              # 前提の点検（OK / WARN / NG と対処を出す）
./localai install ollama      # 公式の導入手順と `ollama pull qwen3.8:27b` を表示する（実行はしない）
./localai install portal      # 入口ページ（8080）
./localai start portal
```

使うものだけを足す。いずれも非対話・冪等・sudo なし（`install` は `tools/<名前>/setup-server.sh` を呼ぶだけで、
引数はそのまま渡る）。

```bash
./localai install strata --model rvn       # 約 100 GB。rvn | coder | official | official-iq3s | swift
./localai install pixal3d                  # 約 30 GB・CUDA 12.6
./localai install comfyui                  # 約 16 GB・CUDA 12.6
./localai install hunyuan3d --accept-tencent-license   # 約 23 GB・使用許諾の確認が要る
./localai install qwen-worker              # Claude Code / Codex への MCP 登録も行う
```

起動と停止は入口ページか、`./localai start|stop|restart|status <サービス>`。入口ページが動いていればその API を使い、
GPU の排他と Ollama のアンロードは入口ページが行う。

GPU が無い機体でも、入口ページの閲覧・評価レポートの閲覧・試験は試せる:

```bash
./localai test                                            # GPU 不要の試験を、ツールごとに OK / FAIL / SKIP で出す
python3 tools/portal/portal.py --host 127.0.0.1 --port 18080   # 入口ページだけ（依存なし）
```

## 評価（2026-10-18）

前回より難しい問題で測り直した。コーディング 6 問（隠しテスト・サンドボックスで採点）と数学 3 問で、Sonnet と Opus に
差が出るように作った。レポート: [AIモデル評価](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_2026-10-18.html)・[出題内容の解説](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_%E5%87%BA%E9%A1%8C%E5%86%85%E5%AE%B9_2026-10-18.html)・
[この機体のローカル AI の一覧](https://ringo7pie.github.io/localai/reports/%E3%83%AD%E3%83%BC%E3%82%AB%E3%83%ABAI%E4%B8%80%E8%A6%A7_2026-10-18.html)。

能力は 9 問の点数の平均、時間は 1 回あたりの中央値。Claude は各問 3 回をサブエージェント経由で測った（時間は API の待ちを含む）。
ローカルは各問 1 回で、この機体での生成時間（モデルのロードは含まない）。

| モデル | 能力 | 時間（中央値） |
|---|---|---|
| Sonnet 5.5 xHigh | 98.6% | 98 秒 |
| Sonnet 5.5 Low | 98.4% | 29 秒 |
| Opus 5.5 xHigh | 99.9% | 123 秒 |
| Opus 5.5 Low | 98.8% | 31 秒 |
| Strata 公式 IQ3_XXS | 77.8% | 363 秒 |
| Strata Coder IQ1_M | 68.2% | 393 秒 |
| Strata 公式 IQ3_S | 66.5% | 451 秒 |
| Strata Swift 1.5 IQ3_XXS | 55.2% | 364 秒 |
| gemma4:31b-it-qat | 54.5% | 443 秒 |
| qwen3.8:27b | 27.8% | 534 秒 |
| gemma4:e4b | 18.0% | 115 秒 |
| qwen3.8-flash-next IQ4_XS（Ollama） | 11.1% | 1,404 秒 |
| Strata 汎用 RVN IQ3_S | 4.0% | 480 秒 |

両モデルの High・Medium もレポートにある（どれも 98〜100%）。

**事実**
- Claude 8 構成（Sonnet・Opus × effort 4 段階）はすべて 98〜100%。Sonnet と Opus は、High だけ Opus が上
  （Opus の全回が Sonnet の全回より高い）で、xHigh・Medium・Low は点の範囲が重なり、差は判定できない。
- 決まって違ったのは、問 H3 の 1 ケースだけ。Sonnet は 12 回すべて、Opus は 12 回中 1 回落とした。
- effort を xHigh から Low に下げると、時間は 3〜4 分の 1 になり、能力は同じ 98〜100% の幅のまま。
- ローカルで H3（型推論）と H5（最小 DFA）を満点にしたモデルは無い。
- 最良のローカル（公式 IQ3_XXS）の能力は Sonnet xHigh の約 8 割で、1 問の時間は約 3.7 倍。
- qwen3.8:27b の失点の多くは、思考の途中で止まり本文が空のまま終わった回（eos_in_thinking）。

**注意**: ローカルは各問 1 回なので、小さな差は誤差の範囲。問題は Claude でもつまずくように選んでいる。ふだんの作業での差は
これより小さいかもしれない（測っていない）。

## 評価（2026-10-08）

9 つの AI を、3D 数学・コーディング 6 問（隠しテスト）・追加の 3 試験（指示追従・長文検索・JSON）で比べた。
読み方・条件・注意はレポートにある: [AIモデル評価](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_2026-10-08.html)・
[出題内容の解説](https://ringo7pie.github.io/localai/reports/AI%E3%83%A2%E3%83%87%E3%83%AB%E8%A9%95%E4%BE%A1_%E5%87%BA%E9%A1%8C%E5%86%85%E5%AE%B9_2026-10-08.html)・
[Strata のコーディング性能の調査](https://ringo7pie.github.io/localai/reports/Strata_%E3%82%B3%E3%83%BC%E3%83%87%E3%82%A3%E3%83%B3%E3%82%B0%E6%80%A7%E8%83%BD%E3%81%AE%E8%AA%BF%E6%9F%BB_2026-10-09.html)。

![コーディングの結果（問 × モデル）](docs/images/eval-coding-heatmap.png)

- Claude 2 種はコーディングで全問合格し、能力では差がつかなかった（天井効果）。
- Strata のコーディングの点は、設定の誤りではなく、強く量子化したモデルが難しい問題で思考を自分で終えられないことに
  よる、と見ている（意見）。評価が付けていた思考の上限は、点を下げる原因ではなく支えていた。

## 試験

GPU を使わない試験は `./localai test` でまとめて走る。個別に走らせるときは [CLAUDE.md](CLAUDE.md) の
「ビルドとテスト」。GitHub Actions（`.github/workflows/ci.yml`）も同じものを走らせる。

## セキュリティ

- 入口ページとモデルのサーバーは LAN に開く構成で、**認証が無い**。LAN の誰でも起動・停止できる。
  ファイアウォール（`ufw` など）で守るか、`127.0.0.1` で待ち受けさせる。
- Strata の汎用版は abliterated（拒否の方向を取り除いたモデル）で、有害な依頼にも応じる。公開するなら
  `STRATA_API_KEY` を付ける。
- qwen-worker・local-ai-bridge は、Qwen が返した要約と差分が親を通ってクラウドへ送られる。
  「すべてがローカルだけに留まる」構成ではない。

## ライセンスと第三者

このリポジトリのコード・文書は MIT（[LICENSE](LICENSE)）。上流のソフトウェアとモデルの重みは**再配布しない**
（setup が各配布元から固定コミットで取得する）。一覧と条件は [NOTICE.md](NOTICE.md)。

- **Hunyuan3D-2** は Tencent Hunyuan 3D 2.0 Community License で、EU・UK・韓国は対象外。GitHub では配布の地域を絞れないため、
  Hunyuan3D-2 へのパッチは公開していない。`tools/hunyuan3d/setup-server.sh` は `--accept-tencent-license` で
  条件を確認するまで何も取得しない。
- **Pixal3D** は出力を収益化しない前提で運用する（NVIDIA の Source Code License・Meta の DINOv3 が混ざる）。
- 各社の名称・商標は権利者のもの。このリポジトリは提携も承認も受けていない。

## Claude Code で作業するとき

[CLAUDE.md](CLAUDE.md) に、構成・ビルドとテスト・運用の約束がある。`knowledge/10-silver/` は測った事実の記録で、
`knowledge/20-bronze/` は原本層（追跡しない）。
