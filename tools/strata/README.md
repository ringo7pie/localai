# strata

推論エンジン [Strata](https://github.com/Niko1221/Strata)（MoE の CPU-GPU 分担推論、MIT）で、
[RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored IQ3_S（Strata 用 pack 付き）](https://huggingface.co/jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata)
をこのリポジトリの A30 サーバーで動かすための一式。OpenAI 互換 API を `0.0.0.0:8082` で出す。

同じ engine で、コード向け版の [Qwen3.8-Flash-Next Coder IQ1_M](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF)
も動かせる（ポート 8083、unit `strata-coder`。下の「コード向け版（Coder）」）。
abliteration をしていない公式の [Qwen3.8-Flash-Next IQ3_XXS](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF)
も足した（ポート 8084、unit `strata-official`。下の「公式版（非 abliterated）IQ3_XXS」）。3 つは同時には載せない。

上流の `./setup.sh` → `setup.py` は対話式で、足りないものを `sudo apt` / `pip` で入れ、Linux では engine を
その場でコンパイルする（Linux 用のビルド済み engine は無い。v0.1.40.1 のリリース資産は Windows 用の 3 つだけ）。
ここでは同じ手順を非対話・sudo なしで行う。`tools/comfyui` と構成・語り口を揃えている。

## ポート

- **8082**: Strata の汎用版（このツール。`--host 0.0.0.0`。API は `/v1`、Web の簡易チャットは `/`）
- **8083**: Strata のコード向け版（Coder。`run-strata serve --model coder`、unit `strata-coder`）
- **8084**: Strata の公式版（非 abliterated の IQ3_XXS。`run-strata serve --model official`、unit `strata-official`）
- 8080 / 8081 / 8000 / 8188: 入口ページ / Open WebUI / （使用中）/ ComfyUI。上流の既定 8095 は使わない

サーバー IP は `<server-ip>`（例: 192.168.1.10）。API は `http://<server-ip>:8082/v1`、モデル名は **`strata-flash-next:IQ3_S`**。
Coder は `http://<server-ip>:8083/v1`、モデル名は **`strata-flash-coder:IQ1_M`**。
公式版は `http://<server-ip>:8084/v1`、モデル名は **`strata-official:IQ3_XXS`**。

## 固定している版

| 対象 | 版・コミット |
|---|---|
| Niko1221/Strata | `v0.1.40.1` = `82f46a8c8f475f001ad76d92f58f4a4f8ffb0253`（engine の版は CMakeLists.txt の `0.1.40`） |
| ggml-org/llama.cpp（ggml を静的に組み込む、gguf-py） | `3cf03257f219afbe7334045ff7c6a06ac68c627d`（上流 setup.py の `LLAMA_CPP_COMMIT`） |
| モデル（HF） | `jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata` の `17876139539724fc6f0b0fbfdcf7b1daa494d045`（2026-10-01） |
| Coder（HF） | `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF` の `5348543e0147355ac9cbcb031184a3546350988e`（2026-09-29、Apache-2.0） |
| 公式版（HF） | `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF` の `ed59f92082b1e93c0e96d60a8b11aab089b52f09`（2026-09-29、Apache-2.0。上流 setup.py:66 と同じ） |
| MTP の材料（HF） | `Qwen/Qwen3.8-Flash-Next` の `de4b8e4d43b917e7706784d8bb445c9af86a3540`（上流 `tools/mtp_fetch.py` の固定） |
| Python | uv 管理の 3.12.14。依存は上流の `requirements.txt`（版固定）そのまま |
| CUDA（engine のビルド） | `/usr/local/cuda-13.2`、`CMAKE_CUDA_ARCHITECTURES=80`、g++ 13.3 |

モデルの 11 ファイルは大きさと sha256 を `stra/config.py` の `MODEL_FILES` に持つ（LFS の 2 つは HF の oid、
残りは取得後に計算し、HF の git blob sha1 と一致することを確かめた値）。Coder の 3 ファイルは `CODER_FILES`
（GGUF の 2 つは HF の LFS oid、README は同じく git blob sha1 で照合した値）。公式版の 3 ファイルは
`OFFICIAL_FILES`（同じ決め方。shard 2 は Coder の shard 2 と大きさ・sha256 が同じ）。

モデルごとの値（置き場・ポート・unit・env ファイル・サーバー設定・engine のログ・profile・RAM の目安など）は
`stra/config.py` の `ModelSpec`（`RVN`・`CODER`・`OFFICIAL`、`MODELS` で `--model` の名前から引く）にまとめてある。

## 導入

サーバー上で 1 回実行する（冪等。モデル 約 89 GB と MTP の材料 約 5 GB をダウンロードする。空きディスク 約 100 GB）。
sudo は要らない。

```bash
tools/strata/setup-server.sh
```

オプション:

- `--skip-models`: モデルと MTP の draft 層の取得を省略する（あとで `run-strata fetch-models` と `scripts/build-mtp.sh`）
- `--build-only`: venv・上流取得・依存・engine のビルドまでで止める
- `--rebuild`: engine を作り直す（`build/` は残すので、変わったところだけコンパイルされる）
- `--model coder`: コード向け版を足す（既定は `--model rvn`）。下の「コード向け版（Coder）」
- `--model official`: 公式版（非 abliterated）を足す。下の「公式版（非 abliterated）IQ3_XXS」

工程（括弧は上流 setup.py の対応する処理）:

1. CUDA 13.2 の nvcc と g++ の確認。g++ が無ければ `sudo apt-get install -y build-essential` を案内して止まる
   （上流は自分で `sudo apt-get install` する。setup.py:2552-2565）
2. uv と venv（`tools/strata/.venv`、uv 管理の Python 3.12）（上流はシステムの `python3 -m venv`、無ければ sudo apt）
3. Strata を `vendor/Strata` に、llama.cpp を `vendor/Strata/third_party/llama.cpp` に固定コミットで取得
   （上流は llama.cpp を GitHub の zip で取る。置き場は同じなので上流の `tools/_paths.py` が gguf-py を見つける）
4. 依存（上流の `requirements.txt`）と自前パッケージ stra。ready-made engine 用の `nvidia-cublas` などの wheel は入れない
5. engine のビルド（`cmake -G Ninja ... -DSTRATA_ENABLE_CUDA=ON -DSTRATA_BUILD_TESTS=OFF -DCMAKE_CUDA_ARCHITECTURES=80
   -DSTRATA_GGML_DIR=third_party/llama.cpp`、`--target strata -j 10`、失敗したら 1 回だけやり直す）。
   できたものを `vendor/Strata/engine/strata` に置き、`engine/BUILD.json` を書く（setup.py:2575-2702 と同じ）
6. モデル（`run-strata fetch-models`、HF の resolve URL、`curl -C -` で途中から再開）と MTP の draft 層
   （`scripts/build-mtp.sh`。setup.py:4744-4760 と同じ `mtp_fetch.py` → `mtp_pack.py --experts q2_0` → `mtp_rt.py`）
7. `~/.config/systemd/user/strata.service` と `~/.config/strata/strata.env` を置き、daemon-reload（enable はしない）
8. doctor

2026-10-07 の実測: engine のビルド 約 5 分（sm_80 の SASS 58 個）、モデルの取得 14.5 分（約 100 MB/s）、
sha256 の確認（`fetch-models --verify`）1 分 20 秒、MTP の材料の取得と変換 約 7 分。apt のパッケージは要らなかった。

## 起動と停止

```bash
systemctl --user start strata      # API が応答するまで戻らない（ExecStartPost の wait-ready。最大 880 秒）
systemctl --user stop strata
tools/strata/run-strata serve      # フォアグラウンド（engine の引数を足すなら -- の後ろ）
tools/strata/run-strata serve --no-mtp --max-context 65536   # 比較用
```

- **起動前に Ollama のモデルを降ろす**（`~/.claude/scripts/vram-policy.sh release 22000` など）。engine は起動時の
  空き VRAM でエキスパートのキャッシュの大きさを決める（`--expert-cache auto`）。ComfyUI・Hunyuan3D・Pixal3D も
  RAM と VRAM を取り合うので止めておく。
- `serve` は毎回 `run/strata-server.json`（上流サーバーの `--config`、docs/ORCA.md:53-76 の形）を書き直し、
  `vendor/Strata` に移って `python -m serve.server --engine strata --config ... --host 0.0.0.0 --port 8082` を exec する。
  engine のログは `logs/strata-engine.log`、サーバーの出力は journal（`journalctl --user -u strata`）。
- `~/.config/strata/strata.env`: `STRATA_MAX_CONTEXT`（既定 131072）、`STRATA_REASONING_BUDGET_TOKENS`
  （思考の予算。既定は汎用版 32768、公式版 65536、Coder は 0。0 で無効）、`STRATA_EXTRA_ARGS`（engine に足す引数）、
  `STRATA_API_KEY`（付けると `/v1/*` に鍵が要る。空の値にすると上流サーバーが起動しない）。
- 待機中は CPU をほぼ使わない（engine は回り続けない）。止めると 5 秒で RAM と VRAM を返す。
- `strata.service`・`strata-coder.service`・`strata-official.service` は互いに `Conflicts=` を持つ。1 つを
  `systemctl --user start` すると、systemd がほかを止めてから起動する（同時には載らない）。`run-strata serve` を手で
  起動したときは効かない。

## 最終の起動引数

```text
strata --serve --pack models/RVN-Qwen3.8-Flash-Next-IQ3_S/pack
  --native  models/RVN-Qwen3.8-Flash-Next-IQ3_S/RVN-Qwen3.8-Flash-Next-IQ3_S-merged.gguf
  --ple-gguf models/RVN-Qwen3.8-Flash-Next-IQ3_S/RVN-Qwen3.8-Flash-Next-IQ3_S-merged.gguf
  --expert-profile vendor/Strata/data/expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt
  --max-context 131072 --kv int8 --resident-experts
```

モデルカード（README.md:56-62）の例との違いと理由:

- **`--resident-experts` を足した**（low-RAM モードの resident 版）。エキスパートは 53.3 GiB（pack の
  `native_experts.txt` の total、48 層 × 512）で、全部を RAM に置く通常のモードは「エキスパート + 約 10 GB」を要する
  （setup.py の `LOW_RAM_HEADROOM_GB`）。RAM 62.5 GiB では足りない。resident 版は GPU のキャッシュが持たない分
  （実測 40.56 GiB）だけを RAM に写してページロックし、応答中はファイルを読まない（ログの `0 blob reads from the file`）。
- **`--kv-resident 32768` は外した**。low-RAM モードでは KV は VRAM に置く（上流 setup.py も同じ判断）。
- **`--max-context` は 262144 ではなく 131072**。65536 から始め、131072 で生成が 5〜7% 遅くなるだけ（KV が VRAM を
  約 0.9 GiB 多く使い、キャッシュが 8369→7962 枠に減る）と確かめて広げた。約 7.8 万トークンの入力が通ることも確かめた。
  262144 は未計測。
- **`--mtp` と `--spec-min-p 0.5` を足した**（カードでは任意）。MTP の draft 層は RVN の pack に無いので、
  元の Qwen チェックポイントから作る（`scripts/build-mtp.sh`）。VRAM を 約 1.2 GiB（層 950 MiB + head 213 MiB）使い
  キャッシュが 7433 枠に減るが、thinking ありの 4K 入力で 42.2→71.9 tok/s になった（下の表）。RVN は元のモデルの
  abliteration なので元の MTP 層がそのまま当たる（カードの作者も MTP ありで 71% の採用率と書いている）。
  draft の語彙は上流の既定と同じ CJK 込み（`data/draft_vocab.bin`、106,299 トークン）。
- `--expert-profile` はカードのとおり上流同梱の汎用 profile。pack は 0.1.30 で作られたものだが 0.1.40 でそのまま
  読めた（`iq_pack.py` での作り直しは不要だった。0.1.40 の `iq_pack.py --compat-bf16` も同じ変換規則）。

## CUDA 13.2 でビルドした理由

- 上流の本線は CUDA 13 系（配布の engine は CUDA 13.0 でビルド、`MIN_DRIVER = 580`）。CUDA 13 は sm_75 以上に対応し、
  A30（sm_80）はその範囲。ドライバ 595 は CUDA 13.2 に対応する。
- 上流の setup.py で CUDA 12 を使うと、Pascal / Volta 向けの実験扱いの engine（`-DSTRATA_EXPERIMENTAL_SM60=ON`、
  setup.py:2624-2628）になる。sm_80 で使う理由が無い。
- Hunyuan3D と同じ `/usr/local/cuda-13.2` を使う（12.6 は Pixal3D / ComfyUI 用）。engine は
  `/usr/local/cuda-13.2/lib64` の libcudart / libcublas.so.13 にリンクし、サーバー設定の `lib_dirs` でも同じ場所を渡す。

## memlock の扱い

**今の構成では sudo の作業は要らない。** 2026-10-07 の実測:

- この機体の memlock の上限は、端末・`systemd --user`（PID 1582）・PID 1 のいずれも soft / hard とも 8384606208 バイト
  （7.8 GiB）。`user@1000.service` の `LimitMEMLOCK` の表示は 8M で、実際の値と合わない。どこで 7.8 GiB
  （RAM の約 1/8）になるかは確かめていない（systemd-user の PAM に pam_limits が入っている）。
- それでも engine は RAM 複製 40.56 GiB を **全量ページロックできた**（ログ `pinned 40.56 GiB ...; page-locked and
  mapped`）。固定は `cudaHostRegister`（src/core/pinned.cu:354-455）で、NVIDIA のドライバ経由の固定は memlock の
  上限に縛られなかった。mlock の失敗（`mlock failed (raise ulimit -l)`）はログに一度も出ていない。
- mlock を使うのは、`cudaHostRegister` が失敗したときの予備経路（失敗しても警告して続ける。src/platform/memory.cpp:119-127）と、
  `--ple-io ram`（n-gram 表 約 29 GB を RAM に置く。この機体では RAM が足りないので使わない）だけ。
- ユニットの `LimitMEMLOCK=infinity` は、user ユニットでは `systemd --user` 自身の上限（7.8 GiB）までに黙って
  切り詰められる（ユニットは普通に起動し、engine の `/proc/<pid>/limits` は 7.8 GiB のまま）。

予備経路が要る場面（ドライバの更新などで `cudaHostRegister` が失敗するようになった、など）で上限を上げる手順（任意。利用者が sudo で行う）:

```bash
sudo mkdir -p /etc/systemd/system/user@1000.service.d
printf '[Service]\nLimitMEMLOCK=infinity\n' | sudo tee /etc/systemd/system/user@1000.service.d/memlock.conf
# systemd-user の PAM（pam_limits）が上書きする場合に備えて、limits.d にも書く
printf '%s - memlock unlimited\n' "$USER" | sudo tee /etc/security/limits.d/90-strata-memlock.conf
sudo systemctl daemon-reload
# 反映: この利用者は Linger=yes なので、ログインし直しでは user@1000 は再起動されない。
# 機体の再起動か、sudo systemctl restart user@1000.service（デスクトップのセッションも終わる）が要る。
grep 'Max locked memory' /proc/$(systemctl show user@1000.service -p MainPID --value)/limits   # unlimited になる
```

（この手順で 7.8 GiB が unlimited になるかは、sudo を使えないため確かめていない。）

## メモリ上限（MemoryHigh / MemoryMax）

`MemoryHigh=50G` / `MemoryMax=58G`。MemoryHigh は 2026-10-07 に 54/58・46/50・50/54 で起動して決めた。MemoryMax は 2026-10-09 に
利用者の指示で 54G から 58G に上げた（KV キャッシュを fp16 にする計測で RAM 複製が増えるため。公式版も同じ値）。

- cgroup の中身（稼働中）: shmem 41.5 GiB（ページロックした RAM 複製 40.56 GiB を含む）+ anon 1.5 GiB + kernel 0.3 GiB
  が落とせない分で、約 43.5 GiB。残りは GGUF を読んだときの page cache で、上限まで溜まるが捨てられる。
- MemoryHigh=54G: 起動 57 秒だが cgroup が 54 GiB に張り付く。46G: 起動が 80 秒に延びる（page cache を捨てながら読むため）。
  どちらも 65536・MTP なしで比べた。50G で page cache を約 6.5 GiB に抑え、機体に 12 GiB 以上を残す（最終構成の起動 81 秒）。
- MemoryMax=58G は物理的な残り（62.5 GiB − デスクトップ・Docker など約 5 GiB）とほぼ同じ。ふだんの歯止めは MemoryHigh=50G（
  `knowledge/10-silver/resources/service-memory-limits.md` の考え方）。engine は memory.max を読んで RAM 複製の量を
  決め、空きから 4 GiB を残す（src/core/expert_source.cpp:239-325）。上限をこれより下げたり、ほかのものが RAM を
  使っていたりすると、複製しきれない分をファイルから読む（止まらないが遅くなる）。
- cgroup の swap 約 1.16 GiB は毎回出る。中身は engine の heap など（smaps で 0.8 GiB、起動時の作業領域とみられる）で、
  エキスパートの複製ではない。

## 点検（doctor）

```bash
tools/strata/run-strata doctor
```

1 行 1 項目で `OK` / `NG` を出す: nvcc 13.2、venv、Strata と llama.cpp のコミット、engine のビルド物（BUILD.json の
コミット・CUDA・sm_80）、エキスパート profile、モデル 11 ファイル（大きさ。取得の途中なら `.part` の大きさ）、RAM の空き
（止まっているときに 46 GiB 以上）、ポート 8082。表示のみ（常に OK）: MTP の draft 層、memlock の上限（端末・
`systemd --user`・稼働中なら engine）、VRAM、Ollama に載っているモデル（`/api/ps`）、`/health`、systemd の状態、
同時に載せないほかのユニット（`strata-coder`・`strata-official`）の状態、`/v1/models` が返すモデル名。判定は `stra/checks.py` の純粋関数。

`run-strata doctor --model coder` は Coder を点検する（profile は `expert-profile-coder.bin`、モデル 3 ファイル、
手元で作る pack のそろい具合とエキスパートの合計、RAM の空きは 30 GiB 以上、ポート 8083、unit `strata-coder`）。
`run-strata doctor --model official` は公式版を点検する（profile は汎用版と同じ `expert-profile.bin`、モデル 3 ファイル、
手元で作る pack、RAM の空きは仮置きの 46 GiB 以上、ポート 8084、unit `strata-official`）。

## API

- `GET /v1/models` → `{"id": "strata-flash-next:IQ3_S", "meta": {"n_ctx": 131072}, ...}`
  （名前はサーバー設定の `model_name`。Open WebUI の一覧は約 28 文字で切れるので短くした。23 文字）。
  Coder（8083）は `{"id": "strata-flash-coder:IQ1_M", "meta": {"n_ctx": 131072}, ...}`。公式版（8084）は
  `strata-official:IQ3_XXS`（設定どおりの名前。実機の応答はまだ見ていない）
- `POST /v1/chat/completions`（ストリーミング・tools 対応）。thinking は `"reasoning_effort": "none" | "low" | "medium" | "high"`
  か `"chat_template_kwargs": {"enable_thinking": false}`。思考は `reasoning_content` で返る。指定しないと high。
- ストリーミングの最後のチャンクに `usage` と `timings`（llama.cpp と同じ名前。`prompt_per_second`・
  `predicted_per_second`・`draft_n`・`draft_n_accepted`）が付く。
- Open WebUI からは「OpenAI API」の接続として `http://127.0.0.1:8082/v1`（同じ機体）、鍵は任意の文字列
  （`STRATA_API_KEY` を付けたらその値）。Open WebUI での表示は確かめていない。

## 実機試験の結果（2026-10-07）

`scripts/bench_api.py`（ストリーミング、`temperature 0.7`、`max_tokens 256`、毎回プロンプトの先頭を変えて会話の
キャッシュを効かせない）と `scripts/monitor.py`（1 秒ごと）で測った。生成と prefill は engine の時計（`timings`）、
3 回の中央値。thinking ありは `reasoning_effort: low`。

| 条件 | 65536・MTP なし | 131072・MTP なし | **131072・MTP あり（最終）** |
|---|---:|---:|---:|
| 短い質問（38 トークン）thinking なし: 生成 tok/s | 35.1 | 32.8 | 33.4 |
| 短い質問 thinking あり: 生成 tok/s | 45.8 | 42.7 | 48.8 |
| 4K 入力（3,996 トークン）thinking なし: 生成 tok/s | 42.0 | 39.3 | 40.1 |
| 4K 入力 thinking あり: 生成 tok/s | 45.9 | 42.2 | **71.9** |
| 4K 入力の prefill tok/s / 最初の文字まで | 1,044〜1,051 / 3.9 秒 | 1,016 / 4.0 秒 | 995〜1,010 / 4.0〜4.1 秒 |
| 起動（`systemctl --user start` が戻るまで） | 57 秒（上限 54/58） | 75 秒 | 81 秒 |
| GPU のキャッシュ / RAM の複製 | 8369 枠 / 38.53 GiB | 7962 枠 / 39.42 GiB | 7433 枠 / 40.56 GiB |

- 1 回目は毎回遅い（例: 最終構成の 4K・thinking あり 57.4 → 72.7 → 71.9）。キャッシュの入れ替え（adaptive tier）が
  効くまでの分とみられる。短い答えは draft が当たりにくく、MTP の効きが小さい。
- 長い入力: 77,641 トークン（131072・MTP なし）で prefill 1,534 tok/s（50.6 秒）、生成 36.7 tok/s、答えは正しかった。
- 最終構成の資源: cgroup の `memory.peak` 50.0 GiB（= MemoryHigh）、swap の山 1.16 GiB、VRAM の山 23,908 / 24,576 MiB
  （読み込み後の空き 382 MiB）。デコード中のキャッシュ命中率 93%（65536・MTP なし）、ファイルからの読み出し 0。
- 機体全体の swap: 起動のたびに約 +1.2 GiB（ほぼ strata 自身の分）。1 回目（モデル取得直後で page cache が満杯、
  上限 54/58）だけ +4.1 GiB で、ほかのプロセスの分が約 3 GiB 出た。GNOME Shell の cgroup は合計 0.6 GB が swap にあり
  （主に 1 回目。MTP ありの 4 回目の起動でも +0.18 GiB、最終構成の起動では 0）。止めると strata の分は返る。
- デスクトップの重さ（GNOME Shell の cgroup の PSI）: 起動中（91 秒）の待ち時間 memory 0.02 秒・io 0.05 秒・cpu 0.00 秒、
  生成中は 0.01 秒以下。機体全体の `/proc/pressure/memory` は起動中 some 30.6 秒（avg10 の山 59%）だが、ほぼ strata 自身が
  MemoryHigh で絞られた分（cgroup の memory.pressure の合計と同程度）。生成中の `/proc/pressure/cpu` some は約 20%
  （avg10 の山 65%）で、engine が 20 スレッド中 12 本（pool 11 + host）を使うため。デスクトップ側の cpu 待ちは 0.01 秒。

### 汎用版で thinking が終わらないとき（2026-10-07）

- **起きたこと。** 8082 の画面から 467 トークンの要求が 2 回、どちらも thinking のまま上限（130,597 トークン、
  2299 秒と 2498 秒）まで続き、答えは 0 トークンだった（engine のログ `strata serve: prompt 467 tokens`。本文は
  Strata が保存しないので、どの問題かは分からない）。
- **原因の切り分け（同じ 3D の問題を、画面の既定 temperature 0.6 / top_p 0.95 / top_k 20 で流して再現した）。**
  - effort high で 8,000 トークン、effort low でも 24,000 トークンで、答えに届かない。
  - 思考は文が循環するループではない（文の重複は 622 文中 18 文だけ）。同じ式の書き直しと再検算が続く。
    Strata の判定値（直近 2,000 語の 12 語の並びの反復の割合）は 8,000 トークンで 0.228、effort low の 24,000 トークンで 0.293、
    effort high の 50,000 トークンの終わりでは 0.042。
  - 50,000 トークンの再現では、思考の前半（8 等分の 1〜2 番目）にだけ小問 (1)〜(4) の番号が出て、後半は出ない。終わり近くは
    「カプセルは狭義凸か・端点は何か」の議論だった（脇道を歩き続けている疑い。途中の本文は読んでいないので、確定ではない）。
- **`"reasoning_loop_recovery": "recover"` を汎用版にも入れた**（`stra/config.py` の `RVN.server_options`。
  `run/strata-server.json` に出る）。ただし**この症状は直らない**。上の 50,000 トークンの再現（回復を入れたあと）で回復は
  0 回で、答えは 0 文字のままだった。回復が見るのは「同じ並びが 3 回以上出る」反復だけで、脇道を歩き続ける型には効かない。
  Coder の `reasoning_loop_recovery` が効いたのは、同じ 1 文を繰り返す型のループだった。
  下の予算 16,384 の 1 本では回復が 1 回発動した（判定値 0.308、`/metrics` の `reasoning_recoveries`）が、それでも考えは
  まとまらず、答えが出たのは予算で thinking が閉じたため。発動は 1 要求に 1 回までで、出るかどうかも本ごとに違う。
- **`reasoning_budget_tokens` は答えを出させるが、正答にはならない（要求ごとに 16,384 を付けて 1 回、設定 JSON は未変更）。**
  同じ 3D の問題で、thinking が 16,384 トークンで閉じて本文が始まり、412 秒（出始め 312 秒）で `stop` まで終わった
  （付けない場合は 50,000 トークン・922 秒でも本文 0）。ただし中身は、(1) の t の範囲だけが正解（1−r ≤ t ≤ r）で、
  (2) は「0<r≤1/2」「r=1/2」（正解は 1/2<r≤√2/2。問題の前提とも矛盾）、(3) は正しい式を書いたあと「?」で打ち消して結論なし、
  (4) は結論なし、断面の図示も不明確で、「問題文が曖昧」とまとめて終わった。`thinking` を打ち切っても、考えが
  足りないまま答えるので 16,384 では正答は増えなかった。
  **この 1 本は条件どおりではない**: 途中で回復が発動し（上）、そこから先は temperature 1.0 以上・presence_penalty 1.5 以上・
  effort low に切り替わっていた（`serve/server.py:3026-3033`）。予算 32,768 の 1 本は発動 0 回で、条件どおり。
- **予算 32,768 では (1)〜(3) が正解になった（要求ごと、1 回、設定 JSON は未変更）。** 同じ問題で、本文の出始め 619 秒・
  全体 661 秒で `stop`。(1) 1−r ≤ t ≤ r、(2) 1/2 < r ≤ 1/√2、(3) πr²+(4/3)πr³ が正解。(1) の断面も「y=t 上で
  半径 √(r²−t²) と √(r²−(1−t)²) の 2 つのスタジアム形（カプセル形）が交わる」と言葉で正しく述べた（図そのものは描かない）。
  (4) は誤り（3πr²+(11/3)πr³。正解は 3πr²+(2π−8/3)r³。r=0.6 で式 5.881、正解・モンテカルロ 4.1747±0.0021）。
  包除原理の組み立ては合っていて、V1∩V2 の体積を「球の 1/8（πr³/6）」としたところが誤り（正しくは (π+4/3)r³）。
  1 回の試行なので、安定して正解になるかは分からない。
  算数・数学の順位づけに使う場合は、上限を付けると「考え切れなかった」ものが誤答として出るので、
  「上限までに答えが出ない」を結果として記録するほうが公平。
- **汎用版の既定を 32768 にした（2026-10-07）。** `stra/config.py` の `RVN.default_reasoning_budget_tokens` →
  `run/strata-server.json` の `reasoning_budget_tokens`。env ファイルの `STRATA_REASONING_BUDGET_TOKENS` で変える
  （0 で無効。コンテキスト長より小さい値だけ受け付ける）。Strata 画面の Settings からの変更は次の起動で消える。
  Coder は 0 のまま。
- **順位づけの計測への申し送り。** 要求に `reasoning_budget_tokens: 0` と共通の `max_tokens` を送り、「上限までに答えなし」を
  結果として記録する（予算で切ると、考え切れなかったものが誤答に化ける）。Ollama 側の同等は `num_predict`。
- **サンプリングを変えても収束しない（2026-10-07、`scripts/bench_api.py --prompt-file`）。** 3D の問題（md 版、459 トークン）を
  effort high・予算なし（要求で 0）・`max_tokens` 65536 で各 1 回。Ollama の `qwen3.8-flash-next:IQ4_XS`（非 abliterated）が
  48,204 トークンで全問正解したときの設定（GGUF の推奨 temperature 1.0 / top_p 0.95 / top_k 20）にも合わせた。

  | 名前 | temperature | presence_penalty | 結果 | 回復 | 思考の終わり |
  |---|---|---|---|---|---|
  | B | 1.0 | なし | 65,536 で `length`、本文なし（1,307 秒、50.2 tok/s） | 0 回（判定値 0.168） | 2 球の共通部分を数値で点検していた |
  | C | 1.0 | 1.0 | 65,536 で `length`、本文なし（1,432 秒、45.8 tok/s） | 0 回（0.086） | 「問題が不完全では」と座標の前提を疑っていた |
  | D | 0.6 | 1.0 | 65,536 で `length`、本文なし（1,373 秒、45.2 tok/s） | 35,840 で 1 回（0.255）。以後は temp 1.0 以上・pp 1.5 以上・effort low | 「V1 は円柱か」と問題の解釈をやり直していた |
  | A | 0.6 | なし | 65,536 で `length`、本文なし（あとで公式版と比べるために流した） | 13,312 で 1 回（0.276） | 「座標が会話に見えないのでは」「昔の入試問題を思い出そう」と問題そのものを疑っていた |

  （top_p / top_k はどれも 0.95 / 20。）4 本とも、答えを書く前に問題の解釈や周辺の確認へ戻り続ける。presence_penalty は堂々巡りを止めず、
  話をずらす方向に効いた。**採用できる設定が無いので、`RVN.server_options` に `sampling` は入れない。**
- **ループ（同じ文の循環）ではない（4 本の思考の全文を、上流の判定 `serve/server.py:157-174` と同じ数え方で調べた）。**
  上流の値は「直近 2,000 語のうち、直近 30,000 語の中で 3 回以上出た 12 語の並びに入る語の割合」（語は小文字にした `\w+` か
  記号 1 字）。4 本とも、15 文字以上の文の 100% が互いに異なる（最多でも同じ文 3〜5 回）。値が 0.25 を超えたのは A の
  14,000 語目付近（山 0.302）と D の 34,500 語目付近（0.265）だけで、そこで繰り返されていたのは文ではなく同じ式の書き直し
  （A は `(x−1)^2+(y−1)^2` が 10 回、D は `(1, 0.5, 0.5)` が 17 回）。式は記号ごとに 1 語と数えるので、同じ距離の式を
  書き直すだけで値が上がる。回復のあとは値が下がり（A の最後 0.084）、代わりに問題の前提を疑う脇道に入った。
  「Wait / Hmm / 再確認」の語は 170〜202 回で、収束した公式版の 2 本（59〜71 回）の約 3 倍。なお公式版の 2 本目も一時 0.247
  まで上がったが収束したので、この値の高さだけでは「堂々巡り」と決められない。
- **数学など長く考える問題は公式版（8084、下の「公式版（非 abliterated）IQ3_XXS」）を使う。** 同じ条件で、公式版は 3D の問題を
  2 回とも・6 問テストを 1 回、65,536 トークン以内に全問正解した。汎用版は 5 本とも答えに届かなかった。汎用版の予算 32768 は、
  答えが返らない症状を止める安全弁として残す（正答は本ごとに揺れる）。
- **設定の予算 32768 で答えが返ることを確かめた（2026-10-07、再起動のあと）。** 要求に予算を付けず、画面の既定
  （temperature 0.6 / 0.95 / 20、effort high）で同じ問題を 1 回: 32,768 で thinking が閉じ（journal に
  `thinking budget reached (32768 tokens)`）、合計 33,492 トークン・641 秒で `stop`。(1) は t の範囲と 2 つのスタジアム形の断面が
  正解、(3) 正解、(2) は r ≤ √3/2（誤り）、(4) は πr²+(4/3)πr³（誤り）。前の 32,768 の 1 本（(1)〜(3) 正解）と合わせて、
  答えは必ず返るが正答は本ごとに揺れる。`STRATA_REASONING_BUDGET_TOKENS=0` で起動すると鍵が JSON から消え、起動ログが
  「思考の予算: なし」になることも確かめた。

### AVX2 / CPU のカーネル

- CPU は i7-12700（AVX2・FMA・AVX-VNNI あり、AVX-512 なし）。engine は `setup-server.sh` が機体でビルドしたもの
  （`engine/BUILD.json`: source local、v0.1.40）。
- engine のログに、起動のたびに `this CPU has no AVX-512: the expert kernels run on AVX-2 (multi-token for the i-quant gate/up rows)`
  と出る。CPU 側のエキスパートの計算は AVX2 のカーネルで動いている。選ぶ設定は無く、engine が実行時に選ぶ。
- AVX-VNNI の形は、上流の説明では対応 CPU（Alder Lake 以降）で既定で有効（`STRATA_NO_AVXVNNI=1` で止める）。この機体のログには
  出ないので、使われているかは確かめていない。engine の環境に `STRATA_*` は設定していない。
- 任意の `STRATA_IQ3S_MT1=1`（AVX-512 なしの Alder Lake 以降で、IQ3_S の 1 トークンにも複数トークン用のカーネルを使う）は
  上流が速いと書くが、1 トークンの丸めが変わるので既定はオフ。この機体では未計測で、入れていない。

## コード向け版（Coder）

[ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF)
（固定リビジョン `5348543e0147355ac9cbcb031184a3546350988e`、Apache-2.0）を、汎用版と同じ engine・venv・MTP の
draft 層で動かす。各層 512 エキスパートのうち、コード・ツール使用・画像のデータで選んだ 256 を残したもの
（上流 setup.py の `FAMILIES["coder"]`・`MODELS["IQ1_M"]`、docs/MODELS.md の Coder）。

| 項目 | 値 |
|---|---|
| ポート / unit / モデル名 | 8083 / `strata-coder` / **`strata-flash-coder:IQ1_M`**（24 文字） |
| 置き場 | `models/Qwen3.8-Flash-Next-Coder-IQ1_M/`（`IQ1_M/` に 2 分割の GGUF、`pack/` は手元で作る） |
| GGUF | shard 1 = 29,608,446,496 バイト（27.57 GiB）、shard 2 = 28,800,138,432 バイト（26.82 GiB）。sha256 は HF の LFS oid |
| 中身（gguf_reader で確認） | `general.architecture = qwen4exp`（汎用版と同じ）、`expert_count = 256`、48 層。shard 1 は 1,223 テンソルで、PLE の n-gram 表 `per_layer_token_embd.weight` は shard 2 にある（`--ple-gguf` に shard 2 を渡す） |
| エキスパート | 256 個/層 × 48 層、合計 25,146,163,200 バイト（23.42 GiB。pack の `native_experts.txt`）。全層 shard 1 にあり、分割の境目をまたぐ層は無い |
| profile | `vendor/Strata/data/expert-profile-coder.bin`（上流同梱。12,288 組） |
| env ファイル | `~/.config/strata/strata-coder.env`（汎用版の `strata.env` とは別。書ける鍵は同じ） |
| サーバー設定 / engine のログ | `run/strata-server-coder.json` / `logs/strata-coder-engine.log` |

画像用の mmproj（0.85 GiB）は取らない（画像入力は使わない）。

### 導入

```bash
tools/strata/setup-server.sh --model coder
```

engine・venv・vendor・MTP の draft 層は汎用版と共有し、できていれば作り直さない（[1/8]〜[5/8] は確かめるだけ）。
[6/8] で次を行う:

1. `run-strata fetch-models --model coder`: 3 ファイル（README.md と GGUF 2 つ）を `resolve/<固定コミット>/` から
   `curl -C -` で取り、sha256 を確かめる
2. `run-strata build-pack --model coder`: `per_layer_token_embd.weight` が shard 2 にあることを `tools/gguf_reader.py`
   で確かめてから、`tools/iq_pack.py --gguf <shard 1> --out pack`（上流 setup.py:4732-4737 と同じ）。iq_pack.py は隣の
   shard 2 も読み、`index.txt`・`dense.bin`（1.37 GiB）・`native_experts.txt`（最後に書く完成の印）・`tokenizer/`
   （中から `strata_tokenizer.py` を呼ぶ）を書く。エキスパートは GGUF から直に読むので `experts.bin` は作らない。
   `tools/pack_index.py` は上流でも AVX-512 用の Q2_0 の pack にだけ使うもので、ここでは要らない
3. `scripts/build-mtp.sh`: 汎用版と同じ draft 層を確かめるだけ（`mtp_fetch.py verify`）

[7/8] で `~/.config/systemd/user/strata-coder.service` と `strata-coder.env` を置き、daemon-reload（enable はしない）。
[8/8] は `run-strata doctor --model coder`。

2026-10-07 の実測: 取得 17 分 24 秒（58.4 GB、平均 約 56 MB/s）、sha256 の確認 52 秒、pack の作成 2 秒
（変換したテンソルは 0。`conversions.json` の `tensors` が空）。MTP の 31 テンソルは控え（`verified.json`）を外して
sha256 を計算し直し、固定リビジョンの値と一致した。

### 起動と停止、汎用版との切り替え

```bash
systemctl --user start strata-coder   # API が応答するまで戻らない。汎用版が動いていれば先に止める
systemctl --user stop strata-coder
systemctl --user start strata         # 汎用版に戻す（Coder が動いていれば先に止める）
tools/strata/run-strata serve --model coder   # フォアグラウンド（engine の引数を足すなら -- の後ろ）
tools/strata/run-strata doctor --model coder
```

- 2 つのユニットは `Conflicts=` で互いを止める。`Conflicts=` だけでは止める順番が決まらないので、`strata-coder.service`
  に `After=strata.service` を書いた（片側だけ。順序の関係があると systemd は停止の job を起動の job より先に行う）。
  実機で両向きとも、もう一方の `Stopped` の直後に `Starting` が来ることを journal で確かめた（汎用版 → Coder:
  停止 4.7 秒のあと起動、Coder → 汎用版: 停止 0.7 秒のあと起動）。手で起動した `run-strata serve` は対象外。
  公式版（`strata-official`）を足したあとの 3 つの関係は、下の「公式版（非 abliterated）IQ3_XXS」。
- 起動前に Ollama のモデルを降ろすこと（汎用版と同じ）。

### 最終の起動引数

```text
strata --serve --pack models/Qwen3.8-Flash-Next-Coder-IQ1_M/pack
  --native   models/Qwen3.8-Flash-Next-Coder-IQ1_M/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
  --ple-gguf models/Qwen3.8-Flash-Next-Coder-IQ1_M/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf
  --expert-profile vendor/Strata/data/expert-profile-coder.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt --max-context 131072 --kv int8
```

サーバー設定（`run/strata-server-coder.json`）には `"reasoning_loop_recovery": "recover"` を足す（下の「既知の制約」）。
上流 setup.py がこの機体で書く設定との違いと、決めた理由（2026-10-07 の実測）:

- **`--resident-experts` は付けない。** エキスパート 23.42 GiB は RAM に全部載るので、全部を RAM に写してページロックする
  通常のモードにした（上流もこの RAM なら通常のモード）。resident 版は RAM が 16.7 GiB で済むが、greedy・同じプロンプトで
  そろえて比べて遅い（4K 入力・thinking あり 90.1 → 80.3 tok/s、thinking なし 71.3 → 67.3、短い質問 70.7 → 62.8）。
- **`--kv-resident 32768` は付けない**（上流 setup.py は RAM に余裕があれば 65536 以上で足す）。付けると 4K 入力・
  thinking ありが 103.3 → 95.6 tok/s。通常のモードでもキャッシュの命中率が 96.5〜99% と元から高く、KV を RAM に出して
  枠を増やす利点が小さい。
- **`--max-context` は 131072。** 262144 も動き、RAM は増えない（KV は VRAM）が、キャッシュ枠が 8,138 → 7,136 に減り、
  greedy でそろえて 9〜21% 遅い（4K・thinking あり 90.1 → 77.2 tok/s）。要るときは env ファイルの
  `STRATA_MAX_CONTEXT=262144`。
- GPU は 12,288 エキスパートのうち 8,138 枠（66%、15.49 GiB）を持つ。読み込み後の VRAM の空きは 458 MiB。

### メモリ上限（MemoryHigh / MemoryMax）

`MemoryHigh=36G` / `MemoryMax=40G`。

- cgroup の中身（稼働中）: anon 25.2 GiB（ページロックしたエキスパート 23.42 GiB を含む。約 7.8 万トークンの入力で
  25.65）+ shmem 0.5 + kernel 0.15 が落とせない分で、約 26.2 GiB。残りは GGUF を読んだときの page cache で、
  上限まで溜まるが捨てられる。cgroup の swap は 0。
- 40G/44G・32G/36G のどちらでも cgroup は MemoryHigh に張り付く（page cache の分）が、冷えた状態からの起動（14 秒）・
  4K と 7.8 万トークンの prefill・生成は変わらず、PSI の待ちもほぼ 0（memory 0.14〜0.17 秒）だった。
  間を取り、page cache と長い入力の増分に約 10 GiB を残す 36G にした。MemoryMax=40G は機体に 22 GiB 以上を残す。
- 冷えた状態は、モデルのファイルの page cache を `posix_fadvise(POSIX_FADV_DONTNEED)`（root 不要）で捨てて作った。

### 実測（2026-10-07）

汎用版の表と同じ `scripts/bench_api.py`（ストリーミング、temperature 0.7、max_tokens 256、thinking ありは effort low、
3 回の中央値）と `scripts/monitor.py`。生成と prefill は engine の時計（`timings`）。どちらも最終の構成で、もう一方は
止めて測った。汎用版の列もこの日に測り直した値。

| 条件 | **Coder（最終）** | 汎用版（最終） |
|---|---:|---:|
| 短い質問（38 トークン）thinking なし: 生成 tok/s | **62.3** | 33.9 |
| 短い質問 thinking あり: 生成 tok/s | **73.8** | 49.4 |
| 4K 入力（3,996 トークン）thinking なし: 生成 tok/s | **63.3** | 35.8 |
| 4K 入力 thinking あり: 生成 tok/s | **97.2** | 60.0 |
| 4K 入力の prefill tok/s / 最初の文字まで | 1,664 / 2.5 秒 | 972〜990 / 4.1〜4.2 秒 |
| 起動（`systemctl --user start` が戻るまで。モデルの page cache を捨てた冷えた状態） | 14.1 秒 | 78.4 秒 |
| cgroup の `memory.peak`（= MemoryHigh。page cache が上限まで溜まる） | 36.00 GiB | 50.00 GiB |
| 落とせない分（anon + shmem + kernel） | 約 26.2 GiB | 約 43.5 GiB |
| cgroup の swap の山 / 機体の swap の増分 | 0 / 0 | 1.17 GiB / +0.12 GiB |
| VRAM の山 | 23,852 / 24,576 MiB | 23,924 / 24,576 MiB |
| GPU のエキスパートのキャッシュ | 8,138 / 12,288 枠（66%） | 7,433 / 24,576 枠（30%） |
| 機体の PSI（計測の間の合計）memory / io | 0.15 / 2.0 秒（772 秒中） | 25.5 / 7.7 秒（1,461 秒中） |
| デスクトップの待ち memory / io / cpu | 0.00 / 0.02 / 0.11 秒 | 0.00 / 0.01 / 0.39 秒 |
| コード課題・greedy（回復なし） | 3 回中 2 回ループ（16,384 で打ち切り） | 3 回とも同じ型のループ（16,384 で打ち切り） |
| コード課題・temperature 1.0 / top_p 0.95 / top_k 20（回復なし） | 2 回とも答え（3,846・13,965 トークン） | 2 回とも 16,384 で打ち切り（ループではなく考え続けた） |
| コード課題・回復あり（最終の Coder） | 反復を検出した 7 回すべて答えまで | （汎用版は設定を変えていない） |
| 日本語の短い質問 | 実用にならない（下の「既知の制約」） | 自然で、答えも正しい |

コード課題は「Python で LRU キャッシュを実装し、テストも書いてください。」を thinking あり（effort high = テンプレートの
xhigh）・max_tokens 16384 で流した（`bench_api.py --prompt code`）。回復は `"reasoning_loop_recovery": "recover"`。
汎用版の数値は README の上の表（同じ日の別の回）とほぼ同じで、4K・thinking ありだけ 71.9 → 60.0 と低かった。

- 生成の速さは draft（MTP）の当たり方で回ごとに ±10% ほど揺れる（temperature 0.7 で文が毎回変わるため）。
  条件どうしの比較は greedy・同じプロンプト番号でそろえて行った（上の「最終の起動引数」）。
- 7.8 万トークンの入力（77,641 トークン）: prefill 1,975 tok/s（39.7 秒）、生成 55.8 tok/s。答え（最も多い節と冊数）は正しい。
- 起動中・生成中のデスクトップ（GNOME Shell の cgroup）の待ちは memory 0.00 秒・io 0.02 秒・cpu 0.11 秒（772 秒の計測中）。
  機体全体の `/proc/pressure/memory` some 0.15 秒、`/proc/pressure/io` some 2.0 秒（avg10 の山 13%）。機体の swap は増えなかった。

### 既知の制約

- **reasoning のループ（上流 issue #1015）が起きる。** 「Python で LRU キャッシュを実装し、テストも書いてください。」を
  thinking あり（effort high = テンプレートの xhigh）・max_tokens 16384 で流すと、上流の既定（サンプリングを送らない =
  greedy）では 3 回中 2 回が `Need maybe include ...` のような 1 文を繰り返し、16384 トークンの上限まで本文が出なかった
  （`finish_reason: length`、反復の割合 1.0 と 0.957）。英語の課題でも、temperature 1.0 でも同じ型の反復が出る。
  - 対策として、上流サーバーの #728 の回復（`"reasoning_loop_recovery": "recover"`。既定は無効）を Coder のサーバー設定に
    入れた。reasoning の直近 2,000 語の 25% 以上が 3 回以上出た 12 語の並びになると、effort を low に差し替えて続きから
    考え直させる（1 要求に 1 回まで。temperature を 1.0 以上・presence_penalty を 1.5 以上に上げて続ける）。
    入れたあとは、反復を検出した 7 回（日本語 greedy 2、英語 greedy 3、英語 temperature 1.0 が 2）がすべて考え直して
    答えまで届いた（`stop`、6,342〜16,325 トークン。答えまで 2〜4 分）。
  - 要求が送らないときのサンプリングの既定（設定の `"sampling"`）を GGUF の推奨（temperature 1.0 / top_p 0.95 / top_k 20、
    `general.sampling.*`）にする案も試したが、入れない。日本語の課題で 3 回中 2 回、reasoning の中で課題文を引用し直す
    ところで「実」の 1 トークンが続き、上流の #606 の検出（同じトークン 256 回）で 300〜700 トークンのうちに `length` で
    打ち切られた（greedy では 5 回とも起きなかった）。
  - それでも長い reasoning の末に max_tokens に届くことはある（英語の 1 回は 16,325 トークンで止まった）。急ぐなら
    `reasoning_effort` を `low` / `medium` にする。
  - 同じ課題の greedy で、**汎用版（RVN）も 3 回とも同じ型のループ**になった（反復の割合 1.0、1 文が 385〜1,146 回）。
    Coder だけの問題ではない。汎用版の設定は今回は変えていない（回復を入れるなら `stra/config.py` の `RVN` の
    `server_options` に同じ鍵を足す）。
- **日本語はほぼ実用にならない**（上流の注意 #438「CJK が弱い」のとおり）。日本語の短い質問 3 問（ことわざの意味・
  リストとタプルの違い・部屋干しのコツ）に、thinking なし・ありとも、答えに中国語と英語が混じり（「室内晾晒」「核心区别」）、
  6 回中 3 回は「をををを…」「hangのhangの…」「情け = pity, は = is, …」のような繰り返しに陥った。ことわざの意味は誤っていた。
  コードの課題では、コード自体は書ける（`OrderedDict` で `get`/`put` と unittest）が、説明文の日本語が崩れる
  （「key 存在の value の return の。」）。日本語の会話や文章は汎用版を使うこと。
- 画像入力は使わない（mmproj を取っていない）。
- Open WebUI の接続先には足していない（汎用版の 8082 だけ）。

## 公式版（非 abliterated）IQ3_XXS

[ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF)
（固定リビジョン `ed59f92082b1e93c0e96d60a8b11aab089b52f09`、2026-09-29、Apache-2.0）の IQ3_XXS を、汎用版と同じ engine・
venv・MTP の draft 層で動かす。abliteration をしていない元の Qwen3.8-Flash-Next の GSQ-RCO 量子化で、各層 512 エキスパートの
まま（上流 setup.py の `FAMILIES["qwen"]`・`MODELS["IQ3_XXS"]`）。同じリポジトリの Q2_0 / IQ2_XS / IQ3_S と mmproj は取らない。

**足した理由（2026-10-07）。** 汎用版（RVN、abliterated）は、3D の問題を予算なしで流すと、サンプリングを変えても
65,536 トークン以内に一度も答えを出さなかった（上の「汎用版で thinking が終わらないとき」）。公式版は同じ条件で 2 回とも
収束して全問正解した（下の「実測」）。常駐の値（下の「仮置きの値」）は RVN と同じ値のまま動かして測った。

| 項目 | 値 |
|---|---|
| ポート / unit / モデル名 | 8084 / `strata-official` / **`strata-official:IQ3_XXS`**（23 文字） |
| 置き場 | `models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/`（HF と同じ並びで `IQ3_XXS/` に 2 分割の GGUF、`pack/` は手元で作る） |
| GGUF | shard 1 = 47,039,860,096 バイト（43.81 GiB）、shard 2 = 28,800,138,432 バイト（26.82 GiB）。sha256 は HF の LFS oid |
| shard 2 | PLE の n-gram 表。**Coder の shard 2 と同じファイル**（大きさ・sha256 が一致。同じリポジトリの他の量子化の shard 2 とも同じ）。`--ple-gguf` に渡す（上流 docs/AMD_HIP.md の IQ3_XXS の起動例と同じ） |
| エキスパート | 512 個/層 × 48 層、合計 42,912,972,800 バイト（39.97 GiB。pack の `native_experts.txt` の total）。作る前に、HF の `tensor-allocation/...-IQ3_XXS-00001-of-00002.rco-allocation.txt` にある各層の型（gate/up は IQ2_XXS〜IQ3_S、down は IQ4_NL か Q2_0）と、RVN の `native_experts.txt` から求めた 1 行列の要素数 1,638,400 から見込んだ値と一致した。上流の `arena_gb` 42.9 と GB（10^9）で合う |
| profile | `vendor/Strata/data/expert-profile.bin`（汎用版と同じ。上流の `FAMILIES["qwen"]` は既定の profile を使う） |
| env ファイル | `~/.config/strata/strata-official.env`（ほかの 2 つとは別。書ける鍵は同じ） |
| サーバー設定 / engine のログ | `run/strata-server-official.json` / `logs/strata-official-engine.log` |
| サーバー設定に足す鍵 | `"reasoning_loop_recovery": "recover"`（汎用版と同じ）と `"reasoning_budget_tokens": 65536`（**汎用版の 32768 より大きい**。3D の問題の 2 回はどちらも thinking が 32,768 を超えてから収束した（下の「実測」）ので、32768 では収束の前に打ち切る。65536 は約 18 分）。sampling の既定は入れない（2026-10-07 の実験で temperature 1.0・presence_penalty 1.0 のどれも汎用版を収束させなかった。公式版は既定のままで収束した） |

### 導入

```bash
# shard 2 は Coder の shard 2 と同じファイルなので、Coder を入れてあればハードリンクで置ける（同じファイルシステム内。
# 取り直さずに済む）。fetch-models は大きさが合えば取らない。中身は fetch-models --model official --verify で確かめる
mkdir -p tools/strata/models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/IQ3_XXS
ln tools/strata/models/Qwen3.8-Flash-Next-Coder-IQ1_M/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf \
   tools/strata/models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf
tools/strata/setup-server.sh --model official
```

[1/8]〜[5/8] は共有のものを確かめるだけ。[6/8] で次を行う:

1. `run-strata fetch-models --model official`: README.md と shard 1 を `resolve/<固定コミット>/` から取り、sha256 を確かめる
   （shard 2 はハードリンクがあれば取らない）
2. `run-strata build-pack --model official`: Coder と同じ手順（`per_layer_token_embd.weight` が shard 2 にあることを
   `tools/gguf_reader.py` で確かめてから `tools/iq_pack.py --gguf <shard 1> --out pack`）
3. `scripts/build-mtp.sh`: 共有の draft 層を確かめるだけ

[7/8] で `~/.config/systemd/user/strata-official.service` と `strata-official.env` を置き、daemon-reload（enable はしない）。
[8/8] は `run-strata doctor --model official`。

2026-10-07 の実測: shard 1 の取得 14 分 11 秒（47.0 GB、平均 約 55 MB/s）、sha256 の確認 34 秒、pack の作成 3 秒
（`index.txt` 1079 テンソル、arena 1.43 GiB）。shard 2 はハードリンクで取得 0。

### 起動と停止、ほかのモデルとの切り替え

```bash
systemctl --user start strata-official   # API が応答するまで戻らない。汎用版・Coder が動いていれば先に止める
systemctl --user stop strata-official
tools/strata/run-strata serve --model official   # フォアグラウンド（engine の引数を足すなら -- の後ろ）
tools/strata/run-strata doctor --model official
```

- 3 つのユニットは `Conflicts=` で互いを止める。止める順番を決める `After=` は、どの 2 つの間にも片側だけに書いた
  （`strata-coder` に `After=strata.service`、`strata-official` に `After=strata.service strata-coder.service`。
  strata → strata-coder → strata-official の一方向で、輪にならない）。2026-10-07 に journal で確かめた: 汎用版 → 公式版で
  `Stopped strata.service` の後に `Starting strata-official.service`（停止 6 秒）、公式版 → 汎用版で
  `Stopped strata-official.service` の後に `Starting strata.service`（停止 3 秒）。
- 既に置いてある `~/.config/systemd/user/strata.service`・`strata-coder.service` は、雛形の `Conflicts=` に
  `strata-official.service` を足しても変わらない（setup-server.sh は既にあるユニットを上書きせず、違いを知らせるだけ）。
  2026-10-07 は、違いが `Conflicts=` とコメントだけだったので雛形で置き換えて daemon-reload した。
- 起動前に Ollama のモデルを降ろすこと（汎用版と同じ）。

### 起動引数（仮）

```text
strata --serve --pack models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/pack
  --native   models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
  --ple-gguf models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf
  --expert-profile vendor/Strata/data/expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt --max-context 131072 --kv int8 --resident-experts
```

### 仮置きの値（RVN と同じ値のまま動かした）

| 値（`stra/config.py` の `OFFICIAL` と雛形） | 仮置き | 根拠 / 直し方 |
|---|---|---|
| `expert_bytes` | 42,912,972,800（確定） | pack の `native_experts.txt` の total と一致した（試験が照合する） |
| `resident_experts` | True（RVN と同じ） | 上流 setup.py はこの RAM なら `--resident-experts` の無い通常のモードを選ぶ（setup.py:2725 の `low_ram_needed`: 62.5 GiB は 42.9 + 10 より大きい）。Coder の実測では通常のモードのほうが速かった。**通常のモードとはまだ比べていない**（この値のままで汎用版より速い。下の「実測」） |
| `kv_resident` | なし（RVN と同じ） | 上流はこの RAM・131072 では KV ストリーミングを選ばない（setup.py:2776 の `kv_streaming_wanted`: 62.5 < 60 + 1.8 + 1） |
| `default_max_context` | 131072（RVN と同じ） | 生成の速さと VRAM の空き（キャッシュの枠）を見て決める |
| `min_available_ram_gib` | 46（RVN と同じ） | RVN と同じ決め方（RAM に写す量 + engine が残す 4 GiB + 作業領域 約 1.5 GiB） |
| `recommended_memlock_bytes` | 48 GiB（RVN と同じ） | doctor の表示のみ |
| `MemoryHigh` / `MemoryMax` | 50G / 58G（RVN と同じ。MemoryMax は 2026-10-09 に 54G から変更） | 稼働中の cgroup: `memory.peak` 50.00 GiB（= MemoryHigh。汎用版と同じ）、生成中の current 42.4 GiB。落とせない分は shmem 28.62 GiB（GPU 用に page-locked した 27.71 GiB）+ anon 1.57 GiB ≈ 30.2 GiB で、残りは GGUF を写したページキャッシュ（読み直せる）。この値のままで起動 44 秒・生成も速い |

### 実測

2026-10-07。速さは「実機試験の結果」と同じ測り方（`scripts/bench_api.py`、temperature 0.7、`max_tokens` 256、3 回の
中央値、thinking ありは effort low、131072・MTP あり）。汎用版の列は同じ表の最終構成の値。

| 条件 | 公式版 IQ3_XXS | 汎用版 RVN IQ3_S |
|---|---:|---:|
| 短い質問（38 トークン）thinking なし: 生成 tok/s | 42.8 | 33.4 |
| 短い質問 thinking あり: 生成 tok/s | 58.0 | 48.8 |
| 4K 入力（3,996 トークン）thinking なし: 生成 tok/s | 54.5 | 40.1 |
| 4K 入力 thinking あり: 生成 tok/s | **89.0** | 71.9 |
| 4K 入力の prefill tok/s / 最初の文字まで | 1,242〜1,260 / 3.2〜3.3 秒 | 995〜1,010 / 4.0〜4.1 秒 |
| 起動（`systemctl --user start` が戻るまで） | 50 秒（engine の準備 44 秒） | 81 秒 |
| cgroup の `memory.peak` / 落とせない分 | 50.00 GiB（= MemoryHigh）/ 約 30.2 GiB | 50.0 GiB（= MemoryHigh） |
| VRAM（生成中）/ GPU のエキスパートのキャッシュ | 23,899 MiB / 9,638 枠・15.62 GiB | 山 23,908 MiB / 7,433 枠 |
| 日本語の短い質問 3 本（effort high、temp 0.6） | 3 本とも答えあり、同じ文の繰り返しなし（52.7〜62.4 tok/s） | — |

エキスパートが RVN の IQ3_S より小さい型（gate/up に IQ2_XXS〜IQ3_S が混ざる）なので、GPU のキャッシュに多く入り、
CPU 側の読み出しも少ない。

**数学の問題（effort high、予算なし = 要求で 0、`max_tokens` 65536、top_p 0.95 / top_k 20、各 1 回）。** 正解は
3D の問題が (1) 1−r ≤ t ≤ r（断面は 2 つのスタジアム形）、(2) 1/2 < r ≤ √2/2、(3) πr²+(4/3)πr³、(4) 3πr²+(2π−8/3)r³。
6 問テスト（`TestData/数学難問-TEST.md`）は n=1、3 項漸化式 aₙ₊₂=3aₙ₊₁−aₙ（1,1,2,5,13,…）の隣どうし、f(x)=±x、
最大値 1/108（((3±√3)/6, 0) の並べ替え）、(π/8)log 2、16−8√2。

| 問題 | temperature | 公式版 | 汎用版 RVN |
|---|---|---|---|
| 3D | 1.0 | 53,975 トークン・904 秒で `stop`、**4 問とも正解**（(1) の退化の説明に小さな誤り） | 65,536 で `length`、本文なし（上の B） |
| 3D | 0.6 | 49,161 トークン・774 秒で `stop`、**4 問とも正解** | 65,536 で `length`、本文なし（上の A。13,312 で回復が 1 回発動） |
| 6 問テスト | 1.0 | 38,873 トークン・638 秒で `stop`、**6 問とも正解** | 65,536 で `length`、本文なし（1,310 秒、回復 0 回）。思考は問 1 から順に進み、8 等分の後ろ 3 つはほぼ問 6 で、上限のときは問 6 の断面を確かめていた |

3D の 2 回は、どちらも thinking が 32,768 トークンを超えてから収束した（本文の文字数から、thinking は 1 回目 約 4〜5 万、
2 回目 約 3.6〜4.2 万トークン。usage に thinking の数は無い）。そのため公式版の思考の予算の既定は 65536 にした。

### 既知の制約

- abliterated ではない（拒否の方向を取り除いていない）。汎用版の RVN と違い、元の Qwen と同じ応じ方になるはず（未確認）。
- 画像入力は使わない（mmproj を取っていない）。
- Open WebUI の接続先（`http://127.0.0.1:8084/v1`）と入口ページのカードには 2026-10-07 に足した（下の「Open WebUI（8081）からつなぐ」、
  `tools/portal`）。停止中は Open WebUI の一覧に出ないか、選んでもエラーになる（汎用版と同じ）。

## 試験

```bash
uvx --with pytest pytest tools/strata/tests -q
```

GPU もネットワークも使わない（doctor の判定関数、engine の引数とサーバー設定の組み立て、setup-server.sh と config.py の
直値の一致、ユニットの値、記録・計測スクリプトの集計）。`.venv` には pytest を入れない。
モデル別の設定（rvn / coder / official の値が重ならないこと、`--model` の解釈とポートの既定、Coder と公式版の engine の
引数とサーバー設定、汎用版の引数が変わっていないこと、手元で作る pack の判定、3 つのユニットの `Conflicts=` が互いを指し
`After=` が一方向であること、反復の指標）も確かめる（49 件）。

## ライセンス

Strata は MIT、llama.cpp（ggml）は MIT。モデルはカードの表示で Apache-2.0（元の Qwen3.8-Flash-Next に従う）。
Coder と公式版は HF の表示で Apache-2.0。
MTP の draft 層は元の Qwen/Qwen3.8-Flash-Next のテンソルから作るので、その配布元の条件に従う。
汎用版（RVN）は abliterated（拒否の方向を取り除いたもの）で、有害な依頼にも応じる（公式版は abliterated ではない）。LAN に開いているので、
必要なら `STRATA_API_KEY` を付けること。

## Open WebUI（8081）からつなぐ

2026-10-07 に、Open WebUI の接続先へ Strata（`http://127.0.0.1:8082/v1`、API キー無し）を足した。
チャットは Open WebUI のモデル一覧から `strata-flash-next:IQ3_S` を選ぶ。**Strata が停止中は一覧に出ないか、
選んでもエラーになる**（入口ページの Strata カードから起動する。起動に約 80〜115 秒かかる）。

- **接続先は DB が優先される。** Open WebUI は接続先を `~/.local/share/open-webui/data/webui.db` の
  `config` テーブル（`openai.enable` / `openai.api_base_urls` / `openai.api_keys` / `openai.api_configs`）に
  保存し、起動後は環境変数よりこちらを読む。`~/.config/open-webui/open-webui.env` の
  `ENABLE_OPENAI_API` / `OPENAI_API_BASE_URLS` は初期値でしかなく、env だけ直しても反映されない。
- 書き換えたときは Open WebUI を止めてから行い、元は `webui.db.bak-before-strata-20261007`
  （同じディレクトリ）と `open-webui.env.bak-before-strata` に残してある。戻すときは Open WebUI を止めて
  この 2 つを元の名前へ戻す。
- 画面からは「管理者パネル → 設定 → 接続」で同じ設定を見られる。
- 起動の API は `systemctl --user start --no-block` で呼ばれる（入口ページ。Strata の unit は API の
  応答まで `systemctl start` が戻らないため。`tools/portal/README.md` を参照）。
- 接続先は今 3 つ（DB と env の両方）: `http://127.0.0.1:8082/v1`（汎用版）、`:8083/v1`（Coder、
  `webui.db.bak-before-strata-coder-20261007` が足す前）、`:8084/v1`（公式版 `strata-official:IQ3_XXS`、2026-10-07 に
  同じ手順で足した。足す前は `webui.db.bak-before-strata-official-20261007` と
  `open-webui.env.bak-before-strata-official-20261007`）。API キーはどれも空。同時に動くのは 1 つだけなので、
  一覧に出るのは動いているものだけ。
