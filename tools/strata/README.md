# strata

推論エンジン [Strata](https://github.com/Niko1221/Strata)（MoE の CPU-GPU 分担推論、MIT）で、
[RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored IQ3_S（Strata 用 pack 付き）](https://huggingface.co/jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata)
をこのリポジトリの A30 サーバーで動かすための一式。OpenAI 互換 API を `0.0.0.0:8082` で出す。

同じ engine で、コード向け版の [Qwen3.8-Flash-Next Coder IQ1_M](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF)
も動かせる（ポート 8083、unit `strata-coder`。下の「コード向け版（Coder）」）。
abliteration をしていない公式の [Qwen3.8-Flash-Next IQ3_XXS](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF)
も足した（ポート 8084、unit `strata-official`。下の「公式版（非 abliterated）IQ3_XXS」）。
2026-10-16 に、同じ公式モデルの軽い量子化 IQ3_S（ポート 8085、unit `strata-official-iq3s`。下の「公式版 IQ3_S」）と、思考を短く終える
fine-tune の [Swift 1.5](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF) IQ3_XXS（ポート 8086、unit `strata-swift`。
下の「Swift 1.5」）を足した。5 つは同時には載せない。

上流の `./setup.sh` → `setup.py` は対話式で、足りないものを `sudo apt` / `pip` で入れ、Linux では engine を
その場でコンパイルする（Linux 用のビルド済み engine は無い。v0.1.44.1 のリリース資産も Windows 用の 3 つだけ。2026-10-16 確認）。
ここでは同じ手順を非対話・sudo なしで行う。`tools/comfyui` と構成・語り口を揃えている。

## ポート

- **8082**: Strata の汎用版（このツール。`--host 0.0.0.0`。API は `/v1`、Web の簡易チャットは `/`）
- **8083**: Strata のコード向け版（Coder。`run-strata serve --model coder`、unit `strata-coder`）
- **8084**: Strata の公式版（非 abliterated の IQ3_XXS。`run-strata serve --model official`、unit `strata-official`）
- **8085**: Strata の公式版の軽い量子化 IQ3_S（`run-strata serve --model official-iq3s`、unit `strata-official-iq3s`）
- **8086**: Strata の Swift 1.5（思考を短く終える fine-tune の IQ3_XXS。`run-strata serve --model swift`、unit `strata-swift`）
- 8080 / 8081 / 8000 / 8188: 入口ページ / Open WebUI / （使用中）/ ComfyUI。上流の既定 8095 は使わない

サーバー IP は `<server-ip>`（例: 192.168.1.10）。API は `http://<server-ip>:8082/v1`、モデル名は **`strata-flash-next:IQ3_S`**。
Coder は `http://<server-ip>:8083/v1`、モデル名は **`strata-flash-coder:IQ1_M`**。
公式版は `http://<server-ip>:8084/v1`、モデル名は **`strata-official:IQ3_XXS`**。
公式版 IQ3_S は `http://<server-ip>:8085/v1`、モデル名は **`strata-official:IQ3_S`**。
Swift 1.5 は `http://<server-ip>:8086/v1`、モデル名は **`strata-swift:IQ3_XXS`**。

## 固定している版

| 対象 | 版・コミット |
|---|---|
| Niko1221/Strata | `v0.1.44.1` = `296b59d2f73c8f04a805df29c2fa97655adace78`（engine の版は CMakeLists.txt の `0.1.44.1`） |
| ggml-org/llama.cpp（ggml を静的に組み込む、gguf-py） | `3cf03257f219afbe7334045ff7c6a06ac68c627d`（上流 setup.py の `LLAMA_CPP_COMMIT`） |
| モデル（HF） | `jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata` の `17876139539724fc6f0b0fbfdcf7b1daa494d045`（2026-10-01） |
| Coder（HF） | `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF` の `5348543e0147355ac9cbcb031184a3546350988e`（2026-09-29、Apache-2.0） |
| 公式版（HF） | `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF` の `ed59f92082b1e93c0e96d60a8b11aab089b52f09`（2026-09-29、Apache-2.0。上流 setup.py:66 と同じ）。公式版 IQ3_S も同じリポジトリ・同じリビジョンの `IQ3_S/` |
| Swift 1.5（HF） | `ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF` の `99bb8f7f95c7aa7b24a36a7786a4f657b30f5d3d`（2026-10-07。Swift Open License v1.0 + Qwen Community License 1.0。下の「Swift 1.5」） |
| MTP の材料（HF） | `Qwen/Qwen3.8-Flash-Next` の `de4b8e4d43b917e7706784d8bb445c9af86a3540`（上流 `tools/mtp_fetch.py` の固定） |
| Python | uv 管理の 3.12.14。依存は上流の `requirements.txt`（版固定）そのまま |
| CUDA（engine のビルド） | `/usr/local/cuda-13.2`、`CMAKE_CUDA_ARCHITECTURES=80`、g++ 13.3 |

モデルの 11 ファイルは大きさと sha256 を `stra/config.py` の `MODEL_FILES` に持つ（LFS の 2 つは HF の oid、
残りは取得後に計算し、HF の git blob sha1 と一致することを確かめた値）。Coder の 3 ファイルは `CODER_FILES`
（GGUF の 2 つは HF の LFS oid、README は同じく git blob sha1 で照合した値）。公式版の 3 ファイルは
`OFFICIAL_FILES`（同じ決め方。shard 2 は Coder の shard 2 と大きさ・sha256 が同じ）。公式版 IQ3_S の 3 ファイルは `OFFICIAL_IQ3S_FILES`
（shard 1 だけが IQ3_S のもの。README と shard 2 は公式版と同じ）、Swift 1.5 の 6 ファイルは `SWIFT_FILES`（GGUF 2 つは HF の LFS oid、
README・LICENSE・LICENSE-QWEN・NOTICE は取得後に計算して git blob sha1 と照合した値）。

モデルごとの値（置き場・ポート・unit・env ファイル・サーバー設定・engine のログ・profile・RAM の目安など）は
`stra/config.py` の `ModelSpec`（`RVN`・`CODER`・`OFFICIAL`・`OFFICIAL_IQ3S`・`SWIFT`、`MODELS` で `--model` の名前から引く）にまとめてある。

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
- `--model official-iq3s`: 公式版の軽い量子化 IQ3_S を足す。下の「公式版 IQ3_S」
- `--model swift`: Swift 1.5（IQ3_XXS）を足す。下の「Swift 1.5」

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
- `~/.config/strata/strata.env`: `STRATA_MAX_CONTEXT`（既定はモデルの上限 262144。2026-10-18 に 131072 から広げた）、`STRATA_REASONING_BUDGET_TOKENS`
  （思考の予算。既定は汎用版 32768、公式版・公式版 IQ3_S・Swift 65536、Coder は 0。0 で無効）、`STRATA_EXTRA_ARGS`（engine に足す引数）、
  `STRATA_API_KEY`（付けると `/v1/*` に鍵が要る。空の値にすると上流サーバーが起動しない）。
- 待機中は CPU をほぼ使わない（engine は回り続けない）。止めると 5 秒で RAM と VRAM を返す。
- `strata.service`・`strata-coder.service`・`strata-official.service`・`strata-official-iq3s.service`・`strata-swift.service` は互いに
  `Conflicts=` を持つ。1 つを `systemctl --user start` すると、systemd がほかを止めてから起動する（同時には載らない）。
  `run-strata serve` を手で起動したときは効かない。別のモデルを動かした直後に起動するときは、先に page cache を捨てる
  （下の「他のモデルを動かした直後の RVN の起動」。RVN 以外でも同じ）。

## 最終の起動引数

```text
strata --serve --pack models/RVN-Qwen3.8-Flash-Next-IQ3_S/pack
  --native  models/RVN-Qwen3.8-Flash-Next-IQ3_S/RVN-Qwen3.8-Flash-Next-IQ3_S-merged.gguf
  --ple-gguf models/RVN-Qwen3.8-Flash-Next-IQ3_S/RVN-Qwen3.8-Flash-Next-IQ3_S-merged.gguf
  --expert-profile vendor/Strata/data/expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt
  --max-context 262144 --kv int8 --kv-resident 65536 --resident-experts --adapt-async 1
```

モデルカード（README.md:56-62）の例との違いと理由:

- **`--resident-experts` を足した**（low-RAM モードの resident 版）。エキスパートは 53.3 GiB（pack の
  `native_experts.txt` の total、48 層 × 512）で、全部を RAM に置く通常のモードは「エキスパート + 約 10 GB」を要する
  （setup.py の `LOW_RAM_HEADROOM_GB`）。RAM 62.5 GiB では足りない。resident 版は GPU のキャッシュが持たない分
  （実測 40.56 GiB）だけを RAM に写してページロックし、応答中はファイルを読まない（ログの `0 blob reads from the file`）。
- **`--kv-resident 65536`（KV ストリーミング）を 2026-10-18 に足した。** 2026-10-07〜17 は外していた（low-RAM モードでは KV は VRAM に置く、
  という上流 setup.py と同じ判断）。262144 にすると KV が VRAM を約 3.5 GiB 取ってキャッシュの枠が 7,430 → 6,549 に減るので、KV を RAM に置き
  VRAM には直近の 65536 セルだけを残す形にした。枠 7,732、4K 入力・thinking あり 72.9 → 76.0 tok/s、短い質問 53.9 → 60.3、RAM +1.0 GiB
  （下の「速さの設定と文脈長 262144」）。
- **`--max-context` はモデルの上限 262144（2026-10-18）。** 65536 から始め、131072 で生成が 5〜7% 遅くなるだけ（KV が VRAM を
  約 0.9 GiB 多く使い、キャッシュが 8369→7962 枠に減る）と確かめて広げ（2026-10-07）、約 7.8 万トークンの入力が通ることも確かめた。
  262144 は上の KV ストリーミングと `--adapt-async 1` で、131072 のときより速い（64.5 → 76.0 tok/s）。
- **`--adapt-async 1`（キャッシュの入れ替えを生成の合間に裏で進める）を 2026-10-18 に足した。** 131072 で 64.5 → 73.3 tok/s（+14%）。
- **`--mtp` と `--spec-min-p 0.5` を足した**（カードでは任意）。MTP の draft 層は RVN の pack に無いので、
  元の Qwen チェックポイントから作る（`scripts/build-mtp.sh`）。VRAM を 約 1.2 GiB（層 950 MiB + head 213 MiB）使い
  キャッシュが 7433 枠に減るが、thinking ありの 4K 入力で 42.2→71.9 tok/s になった（下の表）。RVN は元のモデルの
  abliteration なので元の MTP 層がそのまま当たる（カードの作者も MTP ありで 71% の採用率と書いている）。
  draft の語彙は上流の既定と同じ CJK 込み（`data/draft_vocab.bin`、106,299 トークン）。
- `--expert-profile` はカードのとおり上流同梱の汎用 profile。pack は 0.1.30 で作られたものだが 0.1.40 でそのまま
  読めた（`iq_pack.py` での作り直しは不要だった。0.1.40 の `iq_pack.py --compat-bf16` も同じ変換規則）。
  0.1.44.1 でも pack は読めた。ただし RVN の GGUF は、メタデータを直さないと起動できない（下の「v0.1.44.1 への更新」）。

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

- `GET /v1/models` → `{"id": "strata-flash-next:IQ3_S", "meta": {"n_ctx": 262144}, ...}`
  （名前はサーバー設定の `model_name`。Open WebUI の一覧は約 28 文字で切れるので短くした。23 文字。`n_ctx` は
  `--max-context`。2026-10-18 からモデルの上限 262144）。
  Coder（8083）は `{"id": "strata-flash-coder:IQ1_M", "meta": {"n_ctx": 262144}, ...}`。公式版（8084）は
  `strata-official:IQ3_XXS`、公式版 IQ3_S（8085）は `strata-official:IQ3_S`、Swift 1.5（8086）は `strata-swift:IQ3_XXS`
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
  （`engine/BUILD.json`: source local、v0.1.44.1）。
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
  公式版（`strata-official`）を足したあとの 3 つの関係は、下の「公式版（非 abliterated）IQ3_XXS」。2026-10-16 に 5 つになってからの
  関係は、下の「5 つのモデルの切り替え」。
- 起動前に Ollama のモデルを降ろすこと（汎用版と同じ）。

### 最終の起動引数

```text
strata --serve --pack models/Qwen3.8-Flash-Next-Coder-IQ1_M/pack
  --native   models/Qwen3.8-Flash-Next-Coder-IQ1_M/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
  --ple-gguf models/Qwen3.8-Flash-Next-Coder-IQ1_M/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf
  --expert-profile vendor/Strata/data/expert-profile-coder.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt --max-context 262144 --kv int8 --adapt-async 1 --kv-grow
```

サーバー設定（`run/strata-server-coder.json`）には `"reasoning_loop_recovery": "recover"` を足す（下の「既知の制約」）。
上流 setup.py がこの機体で書く設定との違いと、決めた理由（2026-10-07 の実測）:

- **`--resident-experts` は付けない。** エキスパート 23.42 GiB は RAM に全部載るので、全部を RAM に写してページロックする
  通常のモードにした（上流もこの RAM なら通常のモード）。resident 版は RAM が 16.7 GiB で済むが、greedy・同じプロンプトで
  そろえて比べて遅い（4K 入力・thinking あり 90.1 → 80.3 tok/s、thinking なし 71.3 → 67.3、短い質問 70.7 → 62.8）。
- **`--kv-resident 32768` は付けない**（上流 setup.py は RAM に余裕があれば 65536 以上で足す）。付けると 4K 入力・
  thinking ありが 103.3 → 95.6 tok/s。通常のモードでもキャッシュの命中率が 96.5〜99% と元から高く、KV を RAM に出して
  枠を増やす利点が小さい。
- **`--max-context` はモデルの上限 262144（2026-10-18）。** 2026-10-07 の実測では 131072 → 262144 でキャッシュ枠が 8,138 → 7,136 に減り
  greedy で 9〜21% 遅かった（4K・thinking あり 90.1 → 77.2 tok/s）ので 131072 にしていた。2026-10-18 に `--kv-grow`（KV は使った分だけ
  VRAM に取り、残りを枠に回す。通常モード限定）を足して 262144 にした: 枠 8,752、4K・thinking あり 81.0 tok/s（131072・kv-grow なしの
  基準 78.2）。`--adapt-async 1` も足した（下の「速さの設定と文脈長 262144」）。
- GPU は 12,288 エキスパートのうち、131072・kv-grow なしで 8,138 枠（66%、15.49 GiB。読み込み後の VRAM の空き 458 MiB）、
  262144・kv-grow ありで 8,752 枠（文脈を使うにつれて KV に返す）。

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

- 3 つのユニット（当時）は `Conflicts=` で互いを止める。止める順番を決める `After=` は、どの 2 つの間にも片側だけに書いた
  （`strata-coder` に `After=strata.service`、`strata-official` に `After=strata.service strata-coder.service`。
  strata → strata-coder → strata-official の一方向で、輪にならない。2026-10-16 に公式版 IQ3_S と Swift 1.5 が鎖の後ろに足された）。
  2026-10-07 に journal で確かめた: 汎用版 → 公式版で
  `Stopped strata.service` の後に `Starting strata-official.service`（停止 6 秒）、公式版 → 汎用版で
  `Stopped strata-official.service` の後に `Starting strata.service`（停止 3 秒）。
- 既に置いてある `~/.config/systemd/user/strata.service`・`strata-coder.service` は、雛形の `Conflicts=` に
  `strata-official.service` を足しても変わらない（setup-server.sh は既にあるユニットを上書きせず、違いを知らせるだけ）。
  2026-10-07 は、違いが `Conflicts=` とコメントだけだったので雛形で置き換えて daemon-reload した。
- 起動前に Ollama のモデルを降ろすこと（汎用版と同じ）。

### 起動引数（2026-10-18 から。通常モード・262144・adapt-async・kv-grow）

```text
strata --serve --pack models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/pack
  --native   models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
  --ple-gguf models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/IQ3_XXS/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00002-of-00002.gguf
  --expert-profile vendor/Strata/data/expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt --max-context 262144 --kv int8 --adapt-async 1 --kv-grow
```

2026-10-07〜16 は `--max-context 131072 --kv int8 --resident-experts`（RVN と同じ resident 版）だった。変えた理由と数値は
「速さの設定と文脈長 262144」。

### 値と決め方（2026-10-07 は RVN と同じ値のまま動かし、10-17〜18 の実測で見直した）

| 値（`stra/config.py` の `OFFICIAL` と雛形） | 仮置き | 根拠 / 直し方 |
|---|---|---|
| `expert_bytes` | 42,912,972,800（確定） | pack の `native_experts.txt` の total と一致した（試験が照合する） |
| `resident_experts` | **False（通常のモード。2026-10-17 に変更）** | 上流 setup.py はこの RAM なら `--resident-experts` の無い通常のモードを選ぶ（setup.py:2725 の `low_ram_needed`: 62.5 GiB は 42.9 + 10 より大きい）。2026-10-17 に greedy でそろえて比べ、通常のモードが 8〜20% 速かった（下の「速さの設定（2026-10-17〜18）」）。2026-10-07〜16 は True（RVN と同じ resident 版）だった |
| `kv_resident` | なし（RVN と同じ） | 上流はこの RAM・131072 では KV ストリーミングを選ばない（setup.py:2776 の `kv_streaming_wanted`: 62.5 < 60 + 1.8 + 1） |
| `default_max_context` | 262144（モデルの上限。2026-10-18 に 131072 から広げた） | 通常のモードは `--kv-grow` で KV の未使用分をキャッシュの枠に回せるので、131072 → 262144 の損が小さい（下の「速さの設定」） |
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

## 公式版 IQ3_S（軽い量子化、2026-10-16 に追加）

公式版（IQ3_XXS）と同じ [ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF)
（同じ固定リビジョン `ed59f920…`）の IQ3_S。上流 `setup.py` の `RECOMMENDED_SIZES`（0.1.44）がこのサイズで、Q8_0 との KL は IQ3_XXS の 0.202 に対して
0.144（上流 `docs/QUANTS.md`）。1 トークンあたりは IQ3_XXS より遅い（同じ i7-12700 の上流コミュニティ計測で IQ3_S 19〜20 / IQ3_XXS 26 tok/s）。

**足した理由。** `Documents/AIモデル評価_2026-10-08.html` で Strata の弱点は「思考が終わらず予算で打ち切られる」ことで、
`Documents/Strata_コーディング性能の調査_2026-10-09.html` は設定では直らないと結論し、量子化だけを変えた比較が無かった。同じモデル・同じ engine で
量子化だけが違うものを並べて、その仮説を確かめる。

| 項目 | 値 |
|---|---|
| ポート / unit / モデル名 | 8085 / `strata-official-iq3s` / **`strata-official:IQ3_S`**（21 文字） |
| `--model` の名前 | `official-iq3s` |
| 置き場 | `models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S/`（HF と同じ並びで `IQ3_S/` に 2 分割の GGUF、`pack/` は手元で作る） |
| GGUF | shard 1 = 54,817,524,224 バイト（51.05 GiB）、sha256 `4c1eb2ce…`。shard 2 は公式版・Coder の shard 2 と同じファイル（ハードリンク） |
| エキスパート | 512 個/層 × 48 層、合計 50,292,326,400 バイト（46.84 GiB。pack の `native_experts.txt` の total。上流コミュニティの実測の experts.bin と同じ値） |
| profile / MTP | `vendor/Strata/data/expert-profile.bin`（汎用・公式版と同じ）/ `models/mtp/rt`（共有） |
| env ファイル / サーバー設定 / engine のログ | `~/.config/strata/strata-official-iq3s.env` / `run/strata-server-official-iq3s.json` / `logs/strata-official-iq3s-engine.log` |
| サーバー設定に足す鍵 | `"reasoning_loop_recovery": "recover"` と `"reasoning_budget_tokens": 65536`（公式版と同じ） |
| 起動の形 | `--resident-experts`（RVN と同じ low-RAM の resident 版。エキスパート 46.84 GiB + 約 10 GB の通常のモードは MemoryHigh 50G に収まらない） |
| `MemoryHigh` / `MemoryMax` | 50G / 58G（汎用版と同じ。2026-10-17 の実測で、落とせない分 約 38.2 GiB に 11.8 GiB の余裕があり、このまま） |

### 導入

```bash
# shard 2 は Coder・公式版と同じファイル。取り直さずにハードリンクで置く（同じファイルシステム内）
mkdir -p tools/strata/models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S/IQ3_S
ln tools/strata/models/Qwen3.8-Flash-Next-Coder-IQ1_M/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf \
   tools/strata/models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf
tools/strata/setup-server.sh --model official-iq3s
```

工程は公式版と同じ（[6/8] で `fetch-models --model official-iq3s`（README と shard 1）→ `build-pack --model official-iq3s` → MTP の確認、
[7/8] で unit と env、[8/8] で doctor）。

2026-10-16 の実測: shard 1 の取得 16 分 49 秒（51.1 GiB、平均 約 54 MB/s。別の作業と並行）、sha256 の確認を含めて `fetch-models` が終わるまで
約 17 分、pack の作成 2 秒（`index.txt` 1079 テンソル、arena 1.43 GiB。変換したテンソルは 0）。shard 2 はハードリンクで取得 0。
doctor は RAM の空き以外すべて OK（そのとき別プロジェクトの学習が RAM 8.4 GiB・VRAM 5.6 GiB を使っていたため、空き 39.0 GiB で NG。設定の問題ではない）。

### 起動引数

```text
strata --serve --pack models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S/pack
  --native   models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf
  --ple-gguf models/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf
  --expert-profile vendor/Strata/data/expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt --max-context 262144 --kv int8 --resident-experts --adapt-async 1
```

2026-10-16〜17 は `--max-context 131072 --kv int8 --resident-experts` だった。2026-10-18 に 262144 と `--adapt-async 1` を足した
（resident 版のまま。「速さの設定と文脈長 262144」）。

### 実測（2026-10-17）

`scripts/bench_api.py`（ストリーミング、temperature 0.7、max_tokens 256、3 回の中央値、thinking ありは effort low、131072・MTP あり）と
`scripts/monitor.py`（1 秒ごと）。ほかの Strata は止めて、別プロジェクトの GPU 利用が無いことを確かめてから、モデルの page cache を捨てて起動した。
公式版（IQ3_XXS）の列は 10-16（engine 0.1.44.1）の測り直しの値（thinking あり・4K は未測定なので 10-07 の値）。

| 条件 | **公式版 IQ3_S** | 公式版 IQ3_XXS |
|---|---:|---:|
| 短い質問（38 トークン）thinking なし: 生成 tok/s | 44.1 | 53.2 |
| 短い質問 thinking あり: 生成 tok/s | 60.4 | 58.0（10-07） |
| 4K 入力（3,996 トークン）thinking なし: 生成 tok/s | 48.0 | 53.3 |
| 4K 入力 thinking あり: 生成 tok/s（draft の採用 142 / 174） | 72.9 | 89.0（10-07） |
| 4K 入力の prefill tok/s / 最初の文字まで | 1,073 / 3.8 秒 | 1,265 / 3.2 秒 |
| 7.8 万トークンの入力（76,813）: prefill tok/s / 最初の文字まで / 生成 tok/s | 1,596 / 48.2 秒 / 57.5 | 未測定 |
| 起動（`systemctl --user start` が戻るまで。page cache を捨てた冷えた状態） | 49 秒（RAM 複製 34 秒） | 50 秒（10-07） |
| GPU のエキスパートのキャッシュ / RAM の複製 | 8,159 枠・約 15.5 GiB / 34.77 GiB（ページロック） | 9,638 枠 / 27.71 GiB |
| デコード中のキャッシュ命中率 | 83〜98%（多くは 93〜96%） | 未測定 |
| cgroup の `memory.peak` / 落とせない分（shmem 35.8 + anon 2.0 + kernel 0.35） | 50.00 GiB（= MemoryHigh）/ 約 38.2 GiB | 50.00 GiB / 約 30.2 GiB |
| VRAM の山 / swap の山（cgroup）| 23,902 MiB / 1.12 GiB | 23,899 MiB / — |
| 機体の PSI（計測の間）memory / io / cpu | 0.15 / 0.16 / 49.2 秒（99 秒中） | — |

- 上流のコミュニティ計測（RTX 3060、IQ3_S 19〜20 / IQ3_XXS 26 tok/s、約 3 割遅い）から見込んだほどは遅くない。この機体では、thinking なしで
  10〜17%、thinking あり・4K で 18% 遅い（公式版 IQ3_XXS の 10-07 の値との比）。短い質問の thinking ありは IQ3_S のほうが速く出ているが、
  生成の速さは draft の採用率で回ごとに ±10% ほど揺れるので差とは言えない。
- 落とせない分は約 38.2 GiB で MemoryHigh=50G に 11.8 GiB の余裕がある。残りは GGUF を読んだときの page cache（読み直せる）。
  機体の RAM の空きの最小は 19.0 GiB、デスクトップ（GNOME Shell の cgroup）の待ちは memory / io とも 0.00 秒。
- CPU の待ち（psi cpu some）が 49% あり、engine の CPU プールが律速に近い（IQ3_XXS と同じ傾向。RAM に置いたエキスパートを CPU で計算する）。

## Swift 1.5（思考を短く終える fine-tune、2026-10-16 に追加）

[ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF)
（固定リビジョン `99bb8f7f95c7aa7b24a36a7786a4f657b30f5d3d`、2026-10-07）の IQ3_XXS。UkisAI が Qwen3.8-Flash-Next を post-training した派生で、
アーキテクチャ（`qwen4exp`、512 エキスパート/層）は同じ。作者の BF16・xhigh の計測では思考トークンが中央値で 63% 減り、精度の差は 1% 未満
（GPQA-Diamond 89.8→89.6、AIME 2026 98.7→96.7、LiveCodeBench v6 88.4→90.4。モデルカード）。上流 Strata 0.1.44 は family `swift` として
正式に対応し、「1 トークンの速さは元と同じ」（4K・IQ2_XS で 78.7 対 78.3 tok/s）と報告する（`docs/DETAILS.md` の "Or: Swift 1.5"）。
量子化は ISTA の GSQ-RCO の allocation profile を再利用した UkisAI 自身の配布。

**足した理由。** 公式版 IQ3_S と同じ（思考が終わらない症状に、今度はモデルの側から当たる）。公式版と同じ IQ3_XXS なので、差は fine-tune の分だけ。

**ライセンス。** UkisAI の追加学習の部分は Swift Open License v1.0（年商 100 万ドル以上の法人による商用利用は別契約の Swift Enterprise License が要る。
非商用・研究用途は可。個人は対象外）、元の Qwen の部分は Qwen Community License 1.0。この機体では個人の非商用・研究用途として使う
（2026-10-16 の利用者の判断）。配布元の `LICENSE`・`LICENSE-QWEN`・`NOTICE` もモデルと一緒に取る。`NOTICE.md` に書いてある。

| 項目 | 値 |
|---|---|
| ポート / unit / モデル名 | 8086 / `strata-swift` / **`strata-swift:IQ3_XXS`**（20 文字） |
| `--model` の名前 | `swift` |
| 置き場 | `models/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/`（HF はサブディレクトリを持たないので、ルート直下に 2 分割の GGUF とライセンス。`pack/` は手元で作る） |
| GGUF | shard 1 = 39,785,790,560 バイト（37.05 GiB）、sha256 `3bddaa66…`。shard 2 = 36,180,282,560 バイト（33.70 GiB）、`b0b15f78…`。**shard 2 は元の Qwen とは別物**（PLE の n-gram 表が shard 1、層 12〜47 のエキスパートが shard 2。手元の pack の `native_experts.txt` の shard 列で確認。上流 `tools/iq_pack.py` の注記は「層 13〜47」） |
| `--native` / `--ple-gguf` | どちらも shard 1（`build-pack` が `per_layer_token_embd.weight` が shard 1 にあることを確かめてから作った） |
| エキスパート | 512 個/層 × 48 層、合計 42,912,972,800 バイト（39.97 GiB。pack の `native_experts.txt` の total。公式版 IQ3_XXS と同じ値） |
| profile / MTP | `vendor/Strata/data/expert-profile.bin`（上流 `FAMILIES["swift"]` は profile を持たず既定を使う）/ `models/mtp/rt`（共有。元の Qwen の MTP 層） |
| env ファイル / サーバー設定 / engine のログ | `~/.config/strata/strata-swift.env` / `run/strata-server-swift.json` / `logs/strata-swift-engine.log` |
| サーバー設定に足す鍵 | `"reasoning_loop_recovery": "recover"` と `"reasoning_budget_tokens": 65536`（公式版と同じ） |
| 起動の形 | 公式版と同じ。2026-10-18 から通常モード（`--resident-experts` なし）・262144・KV int8・MTP あり・`--adapt-async 1 --kv-grow`（2026-10-16〜17 は `--resident-experts`・131072） |
| `MemoryHigh` / `MemoryMax` | 50G / 58G（公式版と同じ。通常モードの落とせない分は約 42.3 GiB（anon 41.80 + shmem 0.49 + kernel）で収まる。resident 版のときは約 30.7 GiB だった） |

画像用の mmproj（`mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf`、0.91 GiB）は取らない（画像入力は使わない）。

### 導入

```bash
tools/strata/setup-server.sh --model swift
```

[6/8] で `fetch-models --model swift`（README・LICENSE・LICENSE-QWEN・NOTICE・shard 1・shard 2 を `resolve/99bb8f7f…/` から取り、sha256 を確かめる）→
`build-pack --model swift`（shard 1 に PLE の表があることを確かめてから `iq_pack.py --gguf <shard 1>`。隣の shard 2 も読む）→ MTP の確認、
[7/8] で unit と env、[8/8] で doctor。

2026-10-16 の実測: 6 ファイルの取得と sha256 の確認 22 分 47 秒（70.7 GiB、平均 約 55 MB/s）、pack の作成 4 秒（`index.txt` 1079 テンソル、
arena 1.43 GiB。96 テンソルを F32 → BF16 に変換、すべて誤差 0: Swift の GGUF は BF16 の値を F32 で持つため）。`native_experts.txt` は v3 の shard 列つきで、
層 0〜11 が shard 1、12〜47 が shard 2。doctor は RAM の空き以外すべて OK（別プロジェクトの学習が動いていたため空き 43.7 GiB で NG。設定の問題ではない）。

### 起動引数

```text
strata --serve --pack models/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/pack
  --native   models/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
  --ple-gguf models/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf
  --expert-profile vendor/Strata/data/expert-profile.bin --expert-cache auto --prefill auto
  --spec 4 --spec-min-p 0.5 --mtp models/mtp/rt --max-context 262144 --kv int8 --adapt-async 1 --kv-grow
```

2026-10-16〜17 は `--max-context 131072 --kv int8 --resident-experts`（公式版の当時の形）だった。2026-10-18 に公式版と同じ通常モード・
262144・`--adapt-async 1 --kv-grow` にした（「速さの設定と文脈長 262144」）。

### 実測（2026-10-17）

公式版 IQ3_S と同じ測り方（`scripts/bench_api.py`、temperature 0.7、max_tokens 256、3 回の中央値、thinking ありは effort low、131072・MTP あり、
page cache を捨てた冷えた状態から起動）。公式版（IQ3_XXS）の列は公式版 IQ3_S の表と同じ値。

| 条件 | **Swift 1.5 IQ3_XXS** | 公式版 IQ3_XXS | 公式版 IQ3_S |
|---|---:|---:|---:|
| 短い質問（38 トークン）thinking なし: 生成 tok/s | 45.1 | 53.2 | 44.1 |
| 短い質問 thinking あり: 生成 tok/s | 67.2 | 58.0（10-07） | 60.4 |
| 4K 入力（3,996 トークン）thinking なし: 生成 tok/s | 53.4 | 53.3 | 48.0 |
| 4K 入力 thinking あり: 生成 tok/s（draft の採用 159 / 196） | 79.7 | 89.0（10-07） | 72.9 |
| 4K 入力の prefill tok/s / 最初の文字まで | 1,248 / 3.2 秒 | 1,265 / 3.2 秒 | 1,073 / 3.8 秒 |
| 7.8 万トークンの入力（76,813）: prefill tok/s / 最初の文字まで / 生成 tok/s | 1,729 / 44.5 秒 / 65.1 | 未測定 | 1,596 / 48.2 秒 / 57.5 |
| 起動（`systemctl --user start` が戻るまで） | 42 秒（RAM 複製 30 秒） | 50 秒（10-07） | 49 秒 |
| GPU のエキスパートのキャッシュ / RAM の複製 | 9,773 枠・15.84 GiB / 27.49 GiB（ページロック） | 9,638 枠 / 27.71 GiB | 8,159 枠 / 34.77 GiB |
| デコード中のキャッシュ命中率 | 73〜98%（多くは 92〜97%） | 未測定 | 83〜98% |
| cgroup の `memory.peak` / 落とせない分（shmem 28.4 + anon 2.0 + kernel 0.31） | 50.00 GiB（= MemoryHigh）/ 約 30.7 GiB | 50.00 GiB / 約 30.2 GiB | 50.00 GiB / 約 38.2 GiB |
| VRAM の山 / swap の山（cgroup） | 23,900 MiB / 1.05 GiB | 23,899 MiB / — | 23,902 MiB / 1.12 GiB |
| 機体の RAM の空きの最小 / PSI memory | 26.5 GiB / 0.00 秒 | — | 19.0 GiB / 0.15 秒 |

- 1 トークンの速さは公式版 IQ3_XXS と同じ範囲（上流の「元と同じ速さ」のとおり）。元の Qwen から作った MTP の draft 層の採用率も、
  4K・thinking ありで 74〜81%（公式版 IQ3_S は 77〜82%）で、fine-tune で下がった様子は無い。
- RAM・VRAM の使い方も公式版 IQ3_XXS とほぼ同じ（同じ割り当ての量子化なので、エキスパートの大きさも同じ）。`MemoryHigh=50G` に約 19 GiB の余裕がある。
- **日本語の短い質問 3 本（effort high、temperature 0.6、`--prompt ja`）は 3 本とも自然で正しい答えだった**（ことわざの意味と誤解・
  リストとタプルの違い・部屋干しのコツ。中国語や英語の混入なし、同じ文の繰り返しなし、61.7 tok/s）。思考は英語で 202〜707 字と短く、
  答えまで 3〜6 秒。全文は `logs/swift-ja-20261017/`。

**3D の問題（2026-10-17、1 回）。** 公式版の 10-07 と同じ条件（`TestData/数学難問-三次元空間-TEST.md`、effort high、予算なし = 要求で 0、
`max_tokens` 65536、temperature 1.0 / top_p 0.95 / top_k 20）。正解は公式版の節と同じ。

| | Swift 1.5 IQ3_XXS | 公式版 IQ3_XXS（10-07、2 回） |
|---|---|---|
| 終わり方 | 42,744 トークン・664 秒で `stop`（思考は推定 約 39,800 トークン） | 53,975 トークン・904 秒 / 49,161 トークン・774 秒で `stop` |
| 正誤 | **4 問とも正解**（(1) 1−r ≤ t ≤ r と 2 つのスタジアム形、(2) 1/2 < r ≤ √2/2 と反例つきの必要性、(3) πr²+(4/3)πr³、(4) 3πr²+(2π−8/3)r³） | 2 回とも 4 問正解 |
| 小さな誤り | (1) の注記「t = 1−r のとき b = r」（正しくは b = 0） | (1) の退化の説明に小さな誤り（1 回目） |
| 思考の中の「Wait / Hmm / 再確認」の語 | 10 回（思考 約 9.7 万字） | 59〜71 回（上の「汎用版で thinking が終わらないとき」の記録。数え方は同じ） |
| 生成 | 64.9 tok/s（draft の採用 22,749 / 34,289） | 59.8 / 63.7 tok/s |

- **この 1 本は条件どおりではない。** 5,120 トークンで #728 の回復が 1 回発動し（journal の `repeated reasoning detected at 5120 tokens
  (coverage=0.269)`）、そこから先は effort low・temperature 1.0 以上・presence_penalty 1.5 以上に切り替わっていた（`serve/server.py:3026-3033`）。
- 思考の長さは公式版の 2 回より 13〜21% 短く、時間は 14〜27% 短かった。作者の BF16・xhigh の計測（中央値で 63% 減）ほどは縮んでいない。
  1 回だけなので、回ごとの揺れと区別できない。全文は `logs/swift-3d-20261017/`。

### 既知の制約

- MTP の draft 層は元の Qwen3.8-Flash-Next の `mtp.*` から作ったもの（上流も共有する）。2026-10-17 の実測で採用率は公式版と同じ範囲だった。
- abliterated ではない。

## 5 つのモデルの切り替え

`Conflicts=` は 5 つのユニットが互いに持ち、止める順番を決める `After=` は一方向の鎖
strata → strata-coder → strata-official → strata-official-iq3s → strata-swift で、自分より前のものだけを書く（輪にならない）。
どれを `systemctl --user start` しても、ほかが RAM を返してから読み込む。既に置いてあるユニット（`~/.config/systemd/user/*.service`）は
`setup-server.sh` が上書きしないので、雛形の `Conflicts=` を変えたときは手で置き直して `daemon-reload` する（2026-10-16 に 3 つを置き直した）。

## 速さの設定と文脈長 262144（2026-10-17〜18）

利用者の指示「A30 に収まるように、文脈長と KV キャッシュを最大に」で、5 つとも `--max-context` をモデルの上限 **262144** にした
（GGUF の `context_length`。KV は int8 で VRAM、約 13.7 KB/トークン、262144 で約 3.5 GiB）。あわせて、上流 0.1.40〜0.1.44 の速さの
設定をこの機体で測って採った。測り方は `logs/phase2-20261017/run-arms.sh`・`logs/ctx262k-20261018/run-arms.sh`（追跡しない）:
unit を止める → page cache を捨てる → env（`STRATA_EXTRA_ARGS`・`STRATA_MAX_CONTEXT`）→ 起動 → 暖機 1 本 → `scripts/bench_api.py` を
**greedy（`--temperature none`）・同じ問題番号**で、短い質問 / 4K 入力 thinking なし（各 256 トークン）/ 4K 入力 thinking あり（effort low、
512 トークン）を 3 回ずつ流して中央値。採る基準: 4K 入力・thinking ありで 3% 以上速く、短い質問が大きく遅くならない。
差が 3% 未満なら RAM の少ない方。同じ条件の測り直しで 1〜2% 揺れる（Coder はもっと大きい）。

| モデル | モード | 131072 の基準 | 131072 + `--adapt-async 1` | 262144 の腕（採ったものは太字） | 落とせない RAM | 枠 |
|---|---|---:|---:|---|---:|---:|
| 公式 IQ3_XXS | 常駐（10-07〜16） | 89.8 / 63.1 / 56.9 | 98.0 / 69.4 / 63.3 | — | 30.0 GiB | 9,773 |
| 公式 IQ3_XXS | **通常（10-17〜）** | 98.0 / 70.1 / 69.1 | 104.3 / 75.2 / 76.0 | **adapt-async + kv-grow: 102.9 / 79.3 / 76.8** | 42.3 GiB | 10,452 |
| Coder | 通常 | 78.2 / 67.2 / 81.6 | 84.2 / 65.7 / 74.3 | kv-grow: 80.4 / 65.1 / 69.6。**adapt-async + kv-grow: 81.0 / 63.3 / 78.7** | 25.8 GiB | 8,752 |
| Swift 1.5 | 常駐（10-16〜17） | 87.4 / 60.7 / 55.2 | 97.7 / 68.3 / 66.1 | adapt-async: 94.9 / 64.5 / 64.5（枠 8,601）。+ kv-resident 65536: 97.9 / 69.2 / 63.2（枠 10,178、RAM 33.0 GiB） | 30.5 GiB | 8,601 |
| Swift 1.5 | **通常（10-18〜）** | — | — | **adapt-async + kv-grow: 105.9 / 75.6 / 73.2** | 42.3 GiB | 10,452 |
| 公式 IQ3_S | 常駐 | 74.9 / 56.2 / 53.0 | 83.8 / 64.8 / 63.3 | **adapt-async: 83.1 / 61.1 / 61.7**（枠 7,146）。+ kv-resident 65536: 84.8 / 61.1 / 60.0（枠 8,503、RAM 40.5 GiB） | 39.5 GiB | 7,146 |
| 汎用版 RVN | 常駐 | 64.5 / 51.4 / 49.8 | 73.3 / 60.3 / 55.4 | adapt-async: 72.9 / 59.8 / 53.9（枠 6,549）。**+ kv-resident 65536: 76.0 / 62.1 / 60.3**（枠 7,732） | 46.2 GiB | 7,732 |

値は 4K 入力 thinking あり / 4K 入力 thinking なし / 短い質問 の tok/s。「落とせない RAM」は cgroup の shmem + anon（採った形）。
`memory.peak` はどれも 50.00 GiB = MemoryHigh（page cache が上限まで溜まる）。

- **`--adapt-async 1`**（GPU のキャッシュの入れ替えを生成の合間に裏で進める。上流 0.1.44 の実測 +7〜11%）は 5 つとも +6〜14% で採った。
- **通常モード**（エキスパートを全部 RAM に写してページロック）は、収まる 3 つ（Coder・公式 IQ3_XXS・Swift）で resident 版より 8〜20% 速い。
  公式 IQ3_S（46.84 GiB）と RVN（53.3 GiB）は MemoryHigh 50G に収まらないので resident 版のまま。
- **`--kv-grow`**（KV は使った分だけ VRAM に取り、残りをエキスパートの枠に回す。通常モード限定）で、262144 にしても枠が 131072・kv-grow なしより
  多い（公式 9,728 → 10,452、Coder 8,135 → 8,752）。速さは 131072 と同じ範囲（公式 104.3 → 102.9）。131072 で kv-grow だけ足しても速さは変わらない
  （公式 98.0 → 97.8、枠 10,593）。
- **`--kv-resident 65536`**（KV ストリーミング。KV を RAM に置き、VRAM には直近 65536 セル）は resident 版で 262144 の枠の減りを戻す。RVN では
  4%（短い質問 12%）速く RAM +1.0 GiB で採った。公式 IQ3_S では 2% で RAM +2.3 GiB なので採らない。engine のログ: `KV streaming: 65536 of
  262144 cells per QSA layer in VRAM, the K/V in 3.09 GiB of pinned RAM`。
- **採らなかったもの**: `STRATA_IQ3S_MT1=1`（IQ3_S 型のエキスパートの複数トークン用カーネル。公式 IQ3_XXS で 89.8 → 90.7、短い質問 −6.5%）。
  上流の自動調整 `tools/calibrate.py`（`--pcie-frac`・`--spec-min-p`・`--pool-workers`）は未実施。
- 262144 にすると、KV が VRAM にあっても RAM の落とせない分が約 1.9 GiB 増えた（RVN 43.2 → 45.1 GiB。上流 DETAILS.md の「low-RAM モードでは
  文脈長は RAM に数えない」とは合わない。プロンプト用のバッファと見られるが未確認）。
- 起動時間: 公式 39 秒・Coder 20 秒・Swift 33 秒・公式 IQ3_S 67 秒・RVN 94 秒（kv-resident で 88 → 94 秒）。

### KV の型 k8v4 の比較（2026-10-18、採らなかった）

`--kv k8v4`（K を int8、V を Hadamard 回転つきの 4 ビットで持つ。上流 0.1.25 の PR #120。int8 より 23% 小さい）を、採用した設定（`--kv int8`）と
比べた。測り方は上の表と同じ（greedy・3 回の中央値）に、約 19 万トークンの入力 1 本（`bench_api.py --long-chars 270000`、答えは資料の中の最大の節と
冊数で照合）と、公式版だけ上流の `vendor/Strata/tools/needle_bench.py`（128K の文章の 10 / 50 / 90% の位置に隠した合言葉を、思考なし・greedy で答えさせる）を足した。
`STRATA_EXTRA_ARGS="--kv k8v4"` で切り替え（engine は後ろの `--kv` を使う）。記録は `logs/k8v4-20261018/`（追跡しない）。

| モデル（KV の置き方） | 型 | KV の大きさ | 枠 | 4K 思考あり / 4K 思考なし / 短い質問 | 4K の prefill | 19 万トークン: prefill / 生成 / 答え |
|---|---|---:|---:|---|---:|---|
| 公式 IQ3_XXS（kv-grow） | int8 | 3.35 GiB | 10,452 | 107.4 / 77.0 / 77.4 | 1,406 | 1,746 / 69.4 / 正 |
| | k8v4 | 2.65 GiB | 10,480 | 103.8 / 70.4 / 75.0 | 1,395 | 1,608 / 68.1 / 正 |
| Swift 1.5（kv-grow） | int8 | 3.35 GiB | 10,452 | 103.7 / 75.3 / 77.1 | 1,424 | — |
| | k8v4 | 2.65 GiB | 10,480 | 103.2 / 75.8 / 81.9 | 1,378 | — |
| Coder（kv-grow） | int8 | 3.35 GiB | 8,753 | 83.1 / 64.3 / 81.4 | 1,677 | — |
| | k8v4 | 2.65 GiB | 8,775 | 103.3 / 73.1 / 73.6 | 1,584 | — |
| 公式 IQ3_S（全部 VRAM） | int8 | 3.35 GiB | 7,146 | 81.4 / 59.8 / 61.3 | 1,028 | 1,510 / 57.2 / 正 |
| | k8v4 | 2.65 GiB | 7,519 | 84.0 / 60.8 / 61.1 | 1,015 | 1,428 / 60.3 / 正 |
| RVN（KV を RAM に） | int8 | 3.09 GiB（RAM） | 7,732 | 74.7 / 61.1 / 60.6 | 1,000 | 1,388 / 51.6 / 正 |
| | k8v4 | 2.39 GiB（RAM） | 7,813 | 72.9 / 60.7 / 54.8 | 964 | 1,343 / 47.8 / 正 |

needle（公式 IQ3_XXS、128K = 125,045 トークン）: int8・k8v4 とも 3 か所すべて正解。1 本の時間は int8 63〜72 秒、k8v4 68〜78 秒。

- **使った分だけ取る 3 つ（kv-grow）では効かない。** 起動時の KV は 0.25 → 0.21 GiB しか違わず、枠は 28 しか増えない。19 万トークンでも生成は同じ
  （69.4 → 68.1）で、プロンプトを読む速さは 8% 落ちた（1,746 → 1,608 tok/s）。Coder の 4K 思考ありの差（83.1 → 103.3）は、同じ条件で 78〜101 と
  揺れる範囲（10-17〜18 の記録）で、k8v4 の効果とは言えない。
- **KV を全部 VRAM に置く公式 IQ3_S では少し効く。** 枠が 373 増え、4K 思考あり +3%、19 万トークンの生成 +5%。ただしプロンプトを読む速さは −5%。
  差は測り直しの揺れ（1〜2%）より少し大きいだけで、V を 4 ビットにする精度の代わりに取るほどではないと判断した。
- **KV を RAM に置く RVN では遅くなる**（4K 思考あり −2%、短い質問 −10%、19 万トークンの生成 −7%）。RAM は 0.7 GiB 減る。
- 答え（19 万トークンの照合・needle）はどれも int8 と同じく正しかった。上流の精度の記録（「4 ビットより長い文書で良い」）以上のことは測っていない。
- 計測の途中で、公式 IQ3_S の 19 万トークンの計測の直後に起動した RVN（int8）が、エキスパートを RAM に写している最中（24/48 層）に systemd-oomd に
  落とされた（14:24、`Failed with result 'oom-kill'`）。engine は「本当の空き 22.38 GiB、モデルの page cache を捨てて 41.38 GiB」と出し、残りを
  ほかのファイルの cache を空けながら固定していた。GGUF の page cache は捨ててあった。10 分後に同じ設定で測り直すと 88 秒で起動した。原因は切り分けていない。

## v0.1.44.1 への更新（2026-10-16）

v0.1.40.1 → v0.1.44.1（コミット `296b59d2…`）。llama.cpp の固定コミット（`3cf03257…`）は上流の `setup.py` も `third_party/ggml/VERSION.txt`
も同じなので変えていない。`setup-server.sh --build-only --rebuild` で engine を作り直した（CUDA 13.2・sm_80）。
新版は CMake の既定で K-quant の MMQ と Q6_K のエキスパート用カーネルが入り、engine が 49.4 MiB → 64.3 MiB に増えた
（`strata_kq` は別ライブラリで、その形式のモデルを載せたときだけ読まれる。上流の CMakeLists.txt の注記）。

### RVN の GGUF のメタデータを直した

- 新 engine は起動時に GGUF のメタデータから形状を読み、`qwen4exp.attention.compress_ratios` が「full attention の層
  （`(層番号 + 1)` が `full_attention_interval` で割り切れる層）だけ 0 でない」ことを検査する（`include/strata/artifact/gguf_reader.hpp` の
  `read_geometry`、上流のコミット `f812e9a1`）。旧 engine は形状を決め打ちしていたので見ていなかった。
- RVN の GGUF（`RVN-Qwen3.8-Flash-Next-IQ3_S-merged.gguf`）は 48 個すべてが 0 で、`strata generate: qwen4exp.attention.compress_ratios[3] = 0,
  but full_attention_interval = 4 makes layer 3 full attention` で起動に失敗する。Coder・公式版の GGUF（ISTA の配布）は
  インデックス 3, 7, …, 47 だけ 4 で、そのまま動いた。HF の RVN リポジトリは固定リビジョン（`17876139…`）のまま更新が無い（2026-10-16 確認）。
- 利用者の判断で、RVN の GGUF の該当 12 要素（int32、ファイル内オフセット 2345, 2361, …, 2521）を 0 → 4 に書き換えた。
  ファイルの大きさは変わらない。変わったのはこの 12 要素の 48 バイトのうち 12 バイトだけ（スクリプトが書いた前後のメタデータ領域を比べて確かめる）。
  `scripts/patch_gguf_compress_ratios.py <gguf>` は現状の表示だけ、`--apply` で直す、`--revert` で全部 0 に戻す。
  直すのは全部 0 のときだけ、戻すのは期待どおりの配列のときだけで、書く前に生のバイトと読み取った値の一致を確かめる。
- **HF に固定した sha256 とは一致しなくなる。** `run-strata fetch-models --verify` は RVN の GGUF で失敗する（`--verify` なしの
  `setup-server.sh` の再実行は大きさだけ見るので通る）。取り直したときは `--apply` をもう一度実行する。
- 旧 engine（v0.1.40.1）に戻すときは、`--revert` は要らない（旧 engine はこの配列を読まない。旧 engine での確認はしていない）。

### 他のモデルを動かした直後の RVN の起動

2026-10-16、Coder・公式版を動かした直後に RVN を起動すると、エキスパートを RAM に複製している途中（`copied cache complement through
layer 24/48`）で `systemd-oomd killed 3 process(es) in this unit` となり、起動が失敗した。page cache に前のモデルの GGUF が約 23 GiB
残っていた。`posix_fadvise(DONTNEED)` で 3 つのモデルと MTP の GGUF の page cache を捨ててから起動すると、72 秒で起動した。
モデルを切り替えるときは、前のモデルを止めたあとに次を実行する（root 不要）:

```bash
python3 -c 'import os, sys
for path in sys.argv[1:]:
    descriptor = os.open(path, os.O_RDONLY)
    os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
    os.close(descriptor)' tools/strata/models/*/*.gguf tools/strata/models/*/*/*.gguf tools/strata/models/mtp/*.gguf
```

### 確認した結果（2026-10-16、`scripts/bench_api.py`、max_tokens 256、3 回の中央値）

3 つとも doctor が全部 OK で、起動し、答えを返した。速さは 2026-10-07 の記録と同じ範囲（thinking ありは effort low）。

| 条件 | 汎用版 RVN（10-07 の測り直し） | Coder（10-07） | 公式版（10-07） |
|---|---:|---:|---:|
| 短い質問 thinking なし: 生成 tok/s | 42.1（33.9） | 62.4（62.3） | 53.2（42.8） |
| 4K 入力 thinking なし: 生成 tok/s | 48.8（35.8） | 65.2（63.3） | 53.3（54.5） |
| 4K 入力 thinking あり: 生成 tok/s | 56.4（60.0） | 98.2（97.2） | 未測定 |
| 4K 入力の prefill tok/s | 1,001（972〜990） | 1,641（1,664） | 1,265（1,242〜1,260） |

- 汎用版の 4K・thinking ありだけ 6% 遅いが、1 回の測定で、原因（draft の採用率のばらつきなど）は確かめていない。
- 77,641 トークンの長い入力・数学難問は測り直していない。

## 試験

```bash
uvx --with pytest pytest tools/strata/tests -q
```

GPU もネットワークも使わない（doctor の判定関数、engine の引数とサーバー設定の組み立て、setup-server.sh と config.py の
直値の一致、ユニットの値、記録・計測スクリプトの集計）。`.venv` には pytest を入れない。
モデル別の設定（rvn / coder / official / official-iq3s / swift の値が重ならないこと、`--model` の解釈とポートの既定、各モデルの engine の
引数とサーバー設定、汎用版の引数が変わっていないこと、手元で作る pack の判定、5 つのユニットの `Conflicts=` が互いを指し
`After=` が一方向の鎖であること、反復の指標）も確かめる。

## ライセンス

Strata は MIT、llama.cpp（ggml）は MIT。モデルはカードの表示で Apache-2.0（元の Qwen3.8-Flash-Next に従う）。
Coder と公式版（IQ3_XXS・IQ3_S）は HF の表示で Apache-2.0。Swift 1.5 は Swift Open License v1.0（UkisAI の部分）+ Qwen Community License 1.0
（元の部分）で、年商 100 万ドル以上の法人の商用利用は別契約（上の「Swift 1.5」）。
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
- 接続先は今 5 つ（DB と env の両方）: `http://127.0.0.1:8082/v1`（汎用版）、`:8083/v1`（Coder、
  `webui.db.bak-before-strata-coder-20261007` が足す前）、`:8084/v1`（公式版 `strata-official:IQ3_XXS`、2026-10-07 に
  同じ手順で足した。足す前は `webui.db.bak-before-strata-official-20261007` と
  `open-webui.env.bak-before-strata-official-20261007`）、`:8085/v1`（公式版 IQ3_S `strata-official:IQ3_S`）と `:8086/v1`
  （Swift 1.5 `strata-swift:IQ3_XXS`。2 つとも 2026-10-16 に同じ手順で足した。足す前は `webui.db.bak-before-strata-5models-20261016` と
  `open-webui.env.bak-before-strata-5models-20261016`）。API キーはどれも空。同時に動くのは 1 つだけなので、
  一覧に出るのは動いているものだけ。
