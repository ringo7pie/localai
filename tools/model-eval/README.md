# model-eval

11 の AI（Claude 2 種・Ollama 4 種・Strata 5 種。Strata の公式 IQ3_S と Swift 1.5 は 2026-10-16 に `targets.py` へ足したもので、
計測はまだ。Ollama の `gemma4:31b-ctx32k` は 2026-10-18 に消したので、2026-10-08 の評価の記録にだけ残る）を、
頭の良さ（3D 数学）・コーディング 6 問・追加の 3 試験で比べる道具。
結果は `summarize.py` → `build_report.py` で `Documents/AIモデル評価_2026-10-08.html` にまとめる。
2026-10-18 には、Sonnet と Opus で差が付くように作った難しいコーディング 6 問と数学 3 問で測り直した
（下の「2026-10-18 の評価」。`build_report_hard.py` → `Documents/AIモデル評価_2026-10-18.html`）。
標準ライブラリだけで書いてあり、`/usr/bin/python3`（3.12）で動く。venv は作らない。

計画は `~/.claude/plans/graceful-questing-panda.md`（方針 1〜7）。

## 構成

| パス | 内容 |
|---|---|
| `run_eval.py` | 入口。`run`（ローカルの 1 モデルを流して採点。`--max-tokens`・`--reasoning-budget`・`--prompt-lang`・`--retry-eos`・`--deadline`・`--progress`）・`grade-claude`・`claude-prompt`・`import-claude`・`regrade`・`unload`・`pending`・`show-prompt`・`list` |
| `targets.py` | 11 の AI の定義（API のモデル名・ポート・unit・表示名・系統） |
| `evallib/clients.py` | Ollama `/api/chat`（NDJSON）と Strata `/v1/chat/completions`（SSE）のストリームを同じ形の結果に揃える |
| `evallib/sandbox.py` | コーディングの採点（コードの取り出し・静的な走査・隠しテストの実行） |
| `evallib/scoring.py` | ランキングの式（能力・速度点・総合） |
| `evallib/common.py` | パス・問の一覧・上限・問題文の組み立て・記録の読み書き（`HARD_ORDER` は 2026-10-18 の 9 問の流す順） |
| `evallib/progress.py` | 進捗の状態ファイル（`progress.json`）の読み書きと、経過・残り時間の計算 |
| `progress.py` | 進捗の表示（いま何を試験中か・工程と全行程の経過と残り）と、工程の境・Claude の各回の書き込み |
| `suites/coding/` | `PREAMBLE.md`（共通の指示）、`c1`〜`c6/` の `prompt.md`・`tests.py`（隠しテスト）・`reference.py`（参照解）、`harness.py`。英語版 `PREAMBLE.en.md`・`c4/prompt.en.md`・`c5/prompt.en.md` と、日本語版との対応表 `TRANSLATION_NOTES.md` |
| `suites/extra/` | `inst1`〜`3`・`needle1`〜`3`・`json1`〜`3/` の `prompt.md`・`answer.json`、採点器 `grade_extra.py`、`make_needle.py` |
| `suites/coding_v3/` | 2026-10-18 の難しいコーディング 6 問。`PREAMBLE.md`（v2 と同文）、`h1`〜`h6/` の `prompt.md`・`tests.py`・`reference.py`・`oracle.py`（h3・h5 は乱数の入力を作る `gen_*.py` も） |
| `suites/math/` | 2026-10-18 の数学 3 問。`POSTAMBLE.md`（答えの書き方）、`m1`〜`m3/` の `prompt.md`・`answer.json`・`reference.py`、採点器 `grade_math.py`、検算 `verify_numeric.py`（numpy） |
| `summarize.py` | `results/<日付>/` を集めて `summary.json` を作る |
| `build_report.py` | `summary.json`（と `findings.json`）から HTML を作る |
| `build_report_hard.py` | 2026-10-18 の評価の HTML（Sonnet と Opus の差・時間の実績の節つき）。表と図は `build_report.py` の部品を使う |
| `build_problem_guide_hard.py` | 2026-10-18 の 9 問の解説書（`Documents/AIモデル評価_出題内容_2026-10-18.html`）を作る。本文は `suites/problem_guide_hard.json`、結果のマスは `summary.json` |
| `build_problem_guide.py` | 出した 16 問の解説書（`Documents/AIモデル評価_出題内容_2026-10-08.html`）を作る。本文は `suites/problem_guide.json`、結果のマスは `summary.json` |
| `run_local.sh` | ローカルのモデルを決めた順に全部流す（再開できる。最後に `results/<日付>/DONE`）。`ORDER`・`SUITE`・`BUDGET_MIN`・`DEADLINE`・`--dry-run` |
| `run_kv_compare.sh` | Strata 3 種で KV キャッシュの型（int8 / fp16）を変えて C4・C5 を流す（下の「KV キャッシュの比べ」）。最後に `results/2026-10-09-kv/DONE` |
| `run_fix_compare.sh` | Strata 3 種のコーディング性能の調査。C4・C5 を思考の上限なし・生成 65,536 で流し（実験 A）、問題文を英語にしても流す（実験 B）（下の「コーディング性能の調査」）。最後に `results/2026-10-09-fix/DONE` |
| `cond_compare.py` | 条件を変えて流した C4・C5 の集計（`summarize`）・HTML（`report`）と、`run_fix_compare.sh`・`run_kv_compare.sh` が使う小道具（`server-info`・`journal-counts`・`pending`・`copy-baseline`・`check-kv`・`copy-int8-rep1`）。条件名は任意 |
| `kv_compare.py` | `cond_compare.py` を KV の比べの既定（`--kind kv`、`results/2026-10-09-kv`）で呼ぶ薄い互換の入口 |
| `results/2026-10-08/` | 記録（追跡する）。`math3d_local.json`・`local/`・`claude/`・`summary.json`・`DONE` |
| `work/` | 採点の作業場所・スモーク・ログ（追跡しない） |
| `tests/` | 単体試験 |

## 使い方

```bash
cd ~/Proj/localai/tools/model-eval
./run_eval.py list
./run_eval.py show-prompt --suite coding --item c1 --for-claude    # Claude に渡す全文
./run_eval.py run --target gemma4:e4b --suite coding --limit 1 --results-dir work/smoke   # スモーク
./run_eval.py unload --target gemma4:e4b
./run_local.sh                     # 本番（P2）。数時間かかるので run_in_background で動かす
./run_local.sh --retry-errors      # status が error の問だけ流し直す（記録済みの問は飛ばす）
ONLY=strata-official:IQ3_XXS ./run_local.sh    # 1 モデルだけ
./run_eval.py grade-claude         # Claude の答えを採点して書き戻す
./summarize.py && ./build_report.py
```

### KV キャッシュの比べ（Strata 3 種・int8 と fp16・C4 と C5）

```bash
./run_kv_compare.sh --dry-run          # 流す順番と命令を表示するだけ（systemctl も run_eval も実行しない）
./run_kv_compare.sh                    # 本番。3 時間を超えるので run_in_background で動かし、results/2026-10-09-kv/DONE か終了の通知で待つ
ONLY_TARGETS=strata-official:IQ3_XXS ONLY_KV=fp16 ./run_kv_compare.sh      # 1 モデル・1 つの型だけ
./cond_compare.py summarize --kind kv  # results/2026-10-09-kv/summary.json（./kv_compare.py summarize でも同じ）
./cond_compare.py report --kind kv     # Documents/Strata_KVキャッシュ比較_2026-10-09.html（findings.json があれば所見も載せる）
```

KV の型は `systemctl --user set-environment STRATA_EXTRA_ARGS="--kv fp16"` で切り替える（終了時に必ず外す）。起動のたびに engine のログの
最後の起動行の `--kv` を確かめ、違えばその条件を `kv_mismatch` として飛ばす。記録は
`results/2026-10-09-kv/<int8|fp16>/rep<1〜3>/local/<slug>/coding/<問>-run1.json`（int8 の rep1 は既存の記録の写し）、
条件ごとの起動の記録は `<int8|fp16>/server-<slug>.json`。点の判定は最小・最大だけを比べる（式は HTML の節 6）。

### コーディング性能の調査（Strata 3 種・思考の上限と問題文の言語・C4 と C5）

Strata の評価は思考の上限（`reasoning_budget_tokens` 24,576）を付けて流しており、Ollama には同じ上限が無かった。上限を外したときと、
問題文を英語にしたとき、思考の強さを low にしたとき（`ARM_SPEC="low-ja=1,2,3"`）に点が変わるかを調べる。
結果（2026-10-09）: どの条件も基準（思考最大・上限 24,576）を上回らなかった。まとめは `Documents/Strata_コーディング性能の調査_2026-10-09.html`。

```bash
./run_fix_compare.sh --dry-run          # 基準の写し元 18 本と、流す順番・命令を表示するだけ（systemctl も run_eval も実行せず、置き場も作らない）
./run_fix_compare.sh                    # 本番。5〜6 時間（最悪 7.5 時間）かかるので run_in_background で動かし、results/2026-10-09-fix/DONE か終了の通知で待つ
ONLY_TARGETS=strata-official:IQ3_XXS ONLY_ARMS=nobudget-en ./run_fix_compare.sh   # 1 モデル・1 つの条件だけ
./cond_compare.py summarize   # results/2026-10-09-fix/summary.json（既定の条件 5 つ。--conditions a,b,c と --labels 表示名,表示名,... で変える。先頭が基準）
./cond_compare.py report      # Documents/Strata_コーディング性能の調査_2026-10-09.html（results/2026-10-09-fix/findings.json があれば載せる）
```

- 条件（腕）: `budget24k-ja`（基準。思考の上限 24,576・生成 32,768・日本語。既存の記録の写しで流さない）、`nobudget-ja`（A。上限なし・生成
  65,536・日本語）、`nobudget-en`（B。A と同じ条件で英語の問題文）。順番は Coder（A 3 回 → B 3 回）→ 公式（A 3 回 → B 2 回）→ RVN（A 3 回）。
  追加の条件は `ARM_SPEC`（`low-ja`＝思考の強さ low・生成 32,768、`low-65k-ja`＝low・生成 65,536 など）で流す。`cond_compare.py` の既定の条件は
  `budget24k-ja,nobudget-ja,nobudget-en,low-ja,low-65k-ja`（任意の数。先頭が基準で、ほかを全部基準と比べる）。
  モデルごとに unit を 1 回起動し、そのモデルの全部の条件を流してから止める。KV の型は切り替えない（int8 のまま。`set-environment` は使わない。
  `STRATA_EXTRA_ARGS` が残っていれば止める）。
- 基準の写し元: rep1 は `results/2026-10-08/`、rep2・rep3 は `results/2026-10-09-kv/int8/rep<N>/`。写し元は `budget24k-ja/source.json` に書く。
- 記録: `results/2026-10-09-fix/<条件>/rep<1〜3>/local/<slug>/coding/<c4|c5>-run1.json`。条件 × モデルごとの起動の記録（枠・命中率・VRAM・RAM・起動秒）は
  `<条件>/server-<slug>.json`、モデルの unit の journal から数えた「repeated reasoning detected」「thinking budget reached」
  「the reply reached max tokens」の行数は `journal-counts-<slug>.json`（起動から停止まで・条件ごと）。
- 集計と判定（HTML の節 7 にも式を出す）: 条件 × モデル × 問ごとに、点の一覧・平均・最小・最大・全部合格の回数・答えが出た回数（本文が空でなく
  採点できた回。途中で切れた答えも数える）・終わり方の内訳（`self_finished`・`budget_cut`・`answer_truncated`・`no_answer_at_limit`・`repeat_stop`・
  `eos_in_thinking`・`error`・`missing`。1 回ごとに 1 つに分類する `classify_end`）を出す。基準との比べは、平均の差（条件 − 基準）と、
  条件の最小 > 基準の最大 →「上がった」、最大 < 最小 →「下がった」、それ以外 →「差は判定できない」、記録が無ければ「比べられない」（KV の比べと同じ規則）。
  C4・C5 をまとめた行（6 回）も出す。`results/2026-10-09-fix/excluded.json`（`{"key": "理由"}`）のモデルは集計・表・図から外し、節 7 に理由を出す。
  記録が 1 本も無い条件 × モデルは「流していない」扱い（足りない記録に数えない）で、一部だけあるときは足りない回を警告する。
- `report` の節 0・1・2・5・6・7 は `findings.json`（`summary`・`settings`・`evidence`・`recommendations`・`facts`・`opinions`・`caveats`）から出す
  （無い項目は節に「（未記入）」と出す）。節 1 の表（項目・Strata・Ollama・判定）は `--settings-table` に渡す JSON
  （`item`・`strata`・`ollama`・`verdict` の配列）でもよい。
- **Strata の思考の上限（`reasoning_budget_tokens`）は、点を下げるのではなく支えている（2026-10-09 の実測）。** 上限を外す
  （`--reasoning-budget 0 --max-tokens 65536`）と、公式は C4・C5 の 6 回とも答えが出ず、Coder も 6 回中 3 回しか答えが出なかった。
  コーディングの計測では上限 24,576 を付けたままにし、「Strata の点は上限に助けられた値で、Ollama には同じ上限が無い」と文書に書く。
  `tools/strata/README.md` の申し送り（順位づけでは上限を付けない）は 3D 数学の計測から出たもので、コーディングには当てはまらなかった。

### 思考中の停止トークン（`eos_in_thinking`）

思考の途中で停止トークンが出て、本文が空のまま終わることがある（finish が stop・本文が空・思考あり。Ollama も Strata も同じ）。
`clients.py` はこれを status `eos_in_thinking` として記録する（error ではない）。`run_eval.py run` は既定（`--retry-eos`）で、この要求を
**1 回だけ**流し直す。1 回目の記録は `<問>-run1.attempt1.json` に残し、2 回目を `<問>-run1.json` に書く（`attempts: 2`・`first_attempt_status`）。
2 回目も思考中の停止なら、そのまま 0 点・答えなしで記録する。累計時間には両方を足す。`--no-retry-eos` で流し直しを止める。
`eos_in_thinking` は 0 点・答えなしとして数え、`--retry-errors` の対象にならない（記録済みとして飛ばす）。

### 出題内容の解説書（16 問・色分け）

評価レポートを読む人向けに、出した問題を問題ごとに説明した HTML。何を聞いたか・具体例・何が難しいか・何の力を見るか・採点の仕方・用語と、
9 モデルの点（色つきのマス）を並べ、問題文の原文は折りたたんで載せる。問題の種類ごとに 5 色（3D 数学・コーディング・指示に従う力・
資料からの検索・JSON の取り出し）で、種類の名前も文字で出す。1 ファイルで完結し、外部参照は無い。元のレポートの付録からリンクしている。

```bash
./build_problem_guide.py                       # suites/problem_guide.json と results/2026-10-08/summary.json → Documents/AIモデル評価_出題内容_2026-10-08.html
./build_problem_guide.py --out work/guide.html # 出力先を変える（--summary と --guide も変えられる）
```

- 解説の本文は `suites/problem_guide.json`（手で書く）。読み込みのときに原文と照合し、食い違えば HTML を作らず終了コード 1 で止まる:
  具体例の文字列が問題文か採点の答えにあること、隠しテストの件数が `tests.py` の `def case_` の数と合うこと
  （C1 25・C2 26・C3 25・C4 23・C5 24・C6 20）、指示追従の条件と JSON の期待値が `answer.json` と合うこと、3D の正解が
  `Documents/3D問題_実施モデル一覧_2026-10-08.md` の表と合うこと。問題を足す・変えたら、この JSON も直す。
- 種類の色は `CATEGORY_COLORS`。dataviz スキルの検証済みの 8 色から緑・アクア・赤を外した 5 色で、隣り合う並びが通常の視覚・色覚の型の
  どちらでも見分けられる（`validate_palette.js --mode light`、隣接の最悪 CVD ΔE 19.9）。正解・誤り・答えなしの色は元のレポートと同じ。
- `summary.json` の `excluded` のモデルは出さない。記録が無いマスは「記録なし」と出す。

試験（GPU は使わない。サンドボックスの子プロセスは起動する）:

```bash
uvx --with pytest pytest tools/model-eval/tests -q
```

一時ファイルは `work/pytest/` の下に作って消す（/tmp を使わない）。`pytest.ini` でキャッシュも作らない。

## 2026-10-18 の評価（Sonnet と Opus で差が付く難問 + ローカル 9 モデル + 18 時間の工程管理）

前回（2026-10-08）は Claude 2 種がすべての試験で満点になり能力の差が測れなかったので、差が付くように問題を作り直した。
計画は `~/.claude/plans/pasted-content-id-9510-home-mt-proj-loc-purrfect-hopcroft.md`。結果は `results/2026-10-18/`、
文書は `Documents/AIモデル評価_2026-10-18.html`（`build_report_hard.py`）。

| 試験 | 問 | 採点 |
|---|---|---|
| `suites/coding_v3/`（難しいコーディング 6 問） | H1 3D 凸包（整数・同一平面の面をまとめる）・H2 最短で辞書順最小の編集スクリプト（O(ND)）・H3 Hindley–Milner の型推論・H4 分母上限つきの最良有理近似・H5 正規表現の最小 DFA と区別する最短の文字列・H6 ドミノと L トロミノの敷き詰めの数 | 隠しテストの合格率（18〜28 ケース・部分点）。各問に `reference.py`（参照解）と `oracle.py`（別の作りの総当たり）。期待値は参照解で計算し、オラクルと照合した（`tests/test_hard.py`） |
| `suites/math/`（数学 3 問） | M1 正四面体の平行体（体積・表面積）・M2 2 本の線分のまわりの立体の差（体積・重心）・M3 立方体の中の点の確率（3 つの d） | 本文の `答え(a): <値>` の行を `grade_math.py` が読み、相対誤差 1e-5 で比べる。正解は `reference.py` の閉じた式と、`verify_numeric.py`（numpy のモンテカルロ）で検算した値（`answer.json`） |

- 流す順は `common.HARD_ORDER`（H4 → M1 → H1 → H3 → M2 → H6 → M3 → H2 → H5、易しい順）。`run_eval.py run --suite hard`。
- 問題は計測の前に凍結した（`results/2026-10-18/frozen.json` に sha256）。変えたら全モデル流し直しになる。
- 条件は前回と同じ（生成 32,768・Strata の思考予算 24,576・1 要求 40 分・thinking あり）。ローカルは各問 1 回、Claude は各問 3 回。
  Claude は Sonnet・Opus × effort xhigh・high・medium・low の 8 種（`targets.CLAUDE_EFFORT_PAIRS`）。
- 1 モデルの累計時間の上限は、はじめ 70 分。`run_local.sh` の `DEADLINE`（全モデルの締切）から逆算して、後ろのモデルの上限を詰める。
  `run_eval.py run --deadline` は締切を過ぎた問を飛ばし、1 要求の時間上限も締切までに縮める。
- 10-19 00:47 に利用者の指示で期限と上限を外した。上限で飛ばされた問（qwen3.8:27b 3 問・qwen3.8-flash-next:IQ4_XS 5 問）の元の記録を
  `results/2026-10-18/skipped-budget70/` に写し、`BUDGET_MIN=100000`（上限なし）・`DEADLINE` なし・`--retry-skipped` で流し直した。
  `summarize.py` はこの置き場から `budget_reruns`（流し直した問と結果）を、`meta.json` の argv から `model_budgets_min`（渡した上限の並び。
  例 `[70, 100000]`）を作り、HTML の 6 節に 70 分の時点の点と流し直した後の点を並べる。
- 採点の改定（問題文は変えず、隠しテストと採点器だけ）は `frozen.json` の `amendments` に理由と sha256 を残した。最後に、ほかの計測の
  止まった機体で全記録を 2 回続けて採点し直し、2 回の点が一致することを確かめた。

```bash
# ローカル 9 モデル（背景で。終わりは results/2026-10-18/DONE）
ORDER="gemma4:e4b,qwen3.8:27b,gemma4:31b-it-qat,strata-official:IQ3_XXS,strata-official:IQ3_S,strata-swift:IQ3_XXS,strata-flash-coder:IQ1_M,strata-flash-next:IQ3_S,qwen3.8-flash-next:IQ4_XS" \
  SUITE=hard RUN_DATE=2026-10-18 BUDGET_MIN=70 DEADLINE=2026-10-19T06:40:41+09:00 ./run_local.sh
./run_local.sh --dry-run            # 順番・上限・命令を出すだけ（同じ環境変数で）
# 時間の上限で飛ばされた問だけを、上限なしで流し直す（10-19 の P1b）
ORDER="qwen3.8:27b,qwen3.8-flash-next:IQ4_XS" SUITE=hard RUN_DATE=2026-10-18 BUDGET_MIN=100000 ./run_local.sh --retry-skipped
# Claude（メインが Agent ツールで起動）。問題文のファイルを書き、受験用の指示文を出す
./run_eval.py claude-prompt --date 2026-10-18 --model opus --suite coding_v3 --item h1 --run 1
# 受験側が保存した答え（claude-raw/）を記録にする。ツールは Read・Write・SubagentHandback の 3 回だけ許す
./run_eval.py import-claude --date 2026-10-18 --model opus --suite coding_v3 --item h1 --run 1 --wall-s 120 --tokens 40000 \
  --tool-uses-raw 3 --tool-names Read,Write,SubagentHandback
./run_eval.py grade-claude --date 2026-10-18
./run_eval.py regrade --date 2026-10-18          # ローカルの記録を今の採点器で採点し直す
./summarize.py --results-dir results/2026-10-18 --suites coding_v3,math --no-math3d
./build_report_hard.py                           # 所見は results/2026-10-18/findings.json（facts・opinions）
./build_problem_guide_hard.py                    # 9 問の解説書（Documents/AIモデル評価_出題内容_2026-10-18.html）
```

9 問の解説書は、2026-10-08 の解説書（`build_problem_guide.py`）と同じ作り。解説の本文は `suites/problem_guide_hard.json`（手で書く）で、
問題ごとに、やること・具体例・何が難しいか・何の力を見るか・採点の仕方（隠しテストの種類と件数）・用語・結果のマス（Claude は 3 回の
平均と回ごとの点）・問題文の原文を載せる。数学は図（M1 は 2 次元で描いた同じ考え方、M2・M3 は断面）と、answer.json の正解の式と値、
H6 は 2 × 3 の 5 通りの敷き詰めの図を付ける。読み込みのときに、具体例の文字列が問題文にあること、隠しテストの件数が `tests.py` の
`def case_` の数と合うこと、数学の小問が `answer.json` と合うことを確かめ、食い違えば HTML を作らず終了コード 1 で止まる。

### 進捗の表示（`progress.py`）

いま何を試験中か・工程ごとの経過と残り・全行程の経過と残りを 1 画面に出す。状態は `results/2026-10-18/progress.json`
（`run_local.sh` と `run_eval.py --progress` がモデルと問の開始・終了を、メインが工程の境と Claude の各回を書く）。読み取りだけ。

```bash
./progress.py show                 # 1 回だけ表示
./progress.py show --watch 30      # 30 秒ごとに表示し直す（Ctrl-C で止める）
./progress.py show --json          # 同じ内容を JSON で
ssh <サーバー> ~/Proj/localai/tools/model-eval/progress.py show --watch 30   # 他の PC から

# 途中で計画を変えたとき（メインが書く）
./progress.py phase add P1b --label "ローカルの流し直し（時間の上限なし）" --planned-min 160 --depends P1 --before P3 --lane local
./progress.py deadline lift --note "ユーザーの指示"   # 全行程の期限を外す（deadline restore で戻す）
```

- 工程の残り = 計画 − 経過（超過なら「超過」）。ローカルの計測（P1 と `--lane local` で足した工程）は、いまのモデルの上限の残り +
  後のモデル数 ×（上限 + 切替 5 分）を締切で頭打ちにした値。1 モデルの上限が 10000 分以上（`BUDGET_MIN=100000` など）なら「上限なし」と
  みなし、いまのモデルの残りの問 × 1 問の見込み（記録済みの累計 ÷ 記録済みの問。無ければ `est_item_min`、既定 15 分）+
  後のモデルの残りの問（`run_local.sh` が書く `items_after`）× `est_item_min` + 後のモデル数 × 切替 5 分にする。
- まだ始まっていない工程の開始の見込みは、前の工程（状態ファイルの `depends`。無ければ P3 は P1・P2）の終了の見込みから出す。
  `phase add --before P3` で足した工程は P3 の `depends` にも入る。
- 全行程は「期限（T0 + 18 時間）まで残り」と「見込みの残り（各工程の終了の見込みの最大）」の両方を出す。`deadline lift` のあとは
  「期限まで残り」の代わりに、外した時刻と理由を出す。
- 2026-10-18 の評価では、10-19 00:47 に期限を外し、時間の上限で飛ばされた問を上限なしで流し直す工程 P1b を足した
  （飛ばされた元の記録は `results/2026-10-18/skipped-budget70/` に残す）。

## 問題文（ローカルと Claude で同じもの）

system メッセージは使わない。user メッセージの全文は次のとおり（`run_eval.py show-prompt` で確かめられる）。

| 試験 | user メッセージの全文 |
|---|---|
| コーディング | `suites/coding/PREAMBLE.md` の全文 + 空行 + `suites/coding/<c1〜c6>/prompt.md` の全文（前後の空白は落とす） |
| 追加 | `suites/extra/<問>/prompt.md` の全文（前置きなし） |
| 3D（Claude だけ） | `TestData/数学難問-三次元空間-TEST.md` の全文 |

Claude に渡すときだけ、最後に空行と「ツールやコードの実行は使わず、答えだけを返してください。」を足す
（`show-prompt --for-claude` と同じ。`evallib/common.py` の `CLAUDE_SUFFIX`）。
`tests.py`・`reference.py`・`answer.json` は答えなので渡さない。

英語版（コーディングの共通の指示と C4・C5 だけ）は `suites/coding/PREAMBLE.en.md`・`c4/prompt.en.md`・`c5/prompt.en.md`
（`run_eval.py show-prompt --prompt-lang en`、`run --prompt-lang en`）。日本語版の忠実な訳で、関数名・引数名・数値・例・禁止事項を変えていない。
隠しテストと採点は日本語版と同じ。対応表は `suites/coding/TRANSLATION_NOTES.md`。

コーディング 6 問（v2、2026-10-08 に作り直し。易しすぎて差がつかなかった v1 は
`results/2026-10-08/archive-coding-v1-easy/suite-coding-v1/` に退避）:

| 問 | 題材 | 狙い | 難しさ |
|---|---|---|---|
| C1 | シェル風の単語分割 `split_words` | 引用・エスケープ・行の継続・コメントの規則を正確に実装する | 中 |
| C2 | cron 式の次回実行時刻 `next_run` | 日と曜日の OR 規則、範囲と刻み、名前、閏日、`None` の判定。1 分ずつ調べる作りは時間切れ | 中 |
| C3 | 時刻表つきの最早到着 `earliest_arrival` | 乗り換え時間と回数の上限。駅ごとの最早到着だけでは誤り、素朴な緩和は時間切れ | 難 |
| C4 | 厳密な JSON パーサ `parse_json`（`json` 禁止） | RFC 8259 の文法、サロゲートペア、数の文法、重複キー、深さ 50,000、1 MB | 難 |
| C5 | 正規表現の部分集合 `regex_search`（`re` 禁止） | 文字クラス・グループ・選択・アサーションの構文解析と、指数時間にならない照合 | かなり難 |
| C6 | 数独 `solve_sudoku`（解の一意性つき） | 17 ヒントの難問と解なし・解複数の盤面を 1 秒程度で判定する探索 | かなり難 |

needle の資料は `make_needle.py` が種を固定して作る（約 8,350 文字。gemma4 のトークナイザで 6,449〜6,516 トークン）。
作り直したら `make_needle.py --check` で一致を確かめる。

## Claude の結果の形式

メインが Agent ツールの結果を、1 問 1 回につき 1 つの JSON で保存する。

```
results/2026-10-08/claude/<sonnet|opus>/<math3d|coding|extra>/<問ID>-run<n>.json
```

問 ID は 3D が `3d`、コーディングが `c1`〜`c6`、追加が `inst1`〜`3`・`needle1`〜`3`・`json1`〜`3`。

```json
{
  "model": "opus",
  "suite": "coding",
  "item": "c3",
  "run": 1,
  "content": "Claude の最終の答え（本文そのまま）",
  "wall_s": 123.4,
  "usage": null,
  "tool_uses": 0,
  "grade": null
}
```

- `model` と `suite` はディレクトリ名、`item` と `run` はファイル名と一致させる（`grade-claude` が確かめる）。
- `wall_s`: Agent の結果の duration（秒）。`usage`: 分かればトークン数（`output_tokens` か `total_tokens`）、無ければ null。
- `tool_uses`: Agent の結果のツール使用回数。1 以上の回は無効（集計から外す）。やり直して別の `run` 番号で保存する。
- `grade`: 3D はメインが `{"q1": true, "q2": false, "q3": true, "q4": null}` を書く（true = 正解、false = 誤り、
  null = 答えなし。正解は `results/2026-10-08/math3d_local.json` の `answer_key`）。コーディングと追加は null で置き、
  `grade-claude` が埋める。
- 任意の `batch_size`: 1 体に複数の問をまとめたとき（追加の試験は 1 種 3 問を 1 体）、その問の数。時間は `wall_s ÷ batch_size`
  を 1 問の時間とする。省略は 1。まとめたときは、答えを問ごとに切り分けて `content` に入れる（区切りの見出しの行は入れない。
  指示追従の採点は行の数と行末を見るため）。

採点:

```bash
./run_eval.py grade-claude                 # 全部（コーディングは隠しテスト、追加は採点器）。3D は grade の記入漏れを知らせる
./run_eval.py grade-claude --model opus
```

終了コード 1 は「要確認あり」（形式の不足・3D の未採点・ツールを使った回）。何度実行してもよい（毎回採点し直す）。

## ローカルの記録の形式

`results/<日付>/local/<slug>/<suite>/<問>-run1.json` に 1 要求 1 つ。主な項目:

| 項目 | 内容 |
|---|---|
| `prompt` / `request` | 送った全文と、messages 以外の要求の中身 |
| `content` / `thinking` | 答えの本文と思考（Ollama の `message.thinking`、Strata の `reasoning_content`） |
| `prompt_tokens` / `completion_tokens` | サーバーの値（出力は思考を含む） |
| `thinking_tokens_est` | 推定。出力トークン × 思考の文字数 ÷ (思考 + 本文の文字数)。どちらの API も思考のトークン数を出さないため |
| `ttft_s` / `t_first_content_s` | 最初の文字（思考か本文）まで、本文の最初の文字までの秒 |
| `wall_s` / `load_s` / `wall_excl_load_s` | 壁時計、Ollama のロード時間、ロードを除いた時間（速度の計算に使う） |
| `server_decode_tok_s` / `wall_decode_tok_s` | サーバーの生成速度と、壁時計での検算 |
| `delta_chunks` | 文字の入った差分の数（ほぼ 1 トークンに 1 つ）。時間切れ・stall でサーバーのトークン数が無いときの目安 |
| `finish` / `status` | 終わり方。status は `ok`・`length`（上限）・`eos_in_thinking`（思考中に停止トークン・本文が空）・`timeout`（1 要求の時間上限）・`stall`（300 秒なにも届かない）・`error`・`skipped_time_budget` |
| `limits` / `prompt_lang` | 実際に送った上限（`max_tokens`・`reasoning_budget_tokens`（Strata だけ。0 は上限なし）・`request_timeout_s`）と、問題文の言語（`ja`・`en`） |
| `attempts` / `first_attempt_status` | 1 要求を流した回数（思考中の停止でやり直したら 2）と、やり直した 1 回目の status（1 回目の記録は `<問>-run1.attempt1.json`） |
| `grade` | 採点。`score`（0〜1）・`all_passed`・`no_answer` と、試験ごとの内訳 |

`meta.json` には起動ごとの情報（Ollama のロード時間、`/api/ps` の GPU 配置率と文脈長、VRAM、Strata の `/v1/models`）を残す。

## 条件（計画の方針 2）

| 試験 | 生成の上限（Ollama `num_predict` = Strata `max_tokens`） | Strata の思考予算 | 1 要求の時間上限 |
|---|---|---|---|
| コーディング 6 問 | 32,768 | 24,576 | 40 分 |
| 追加 3 種 × 3 問 | 8,192 | 6,144 | 20 分 |

- thinking はすべてあり（Ollama `think: true`、Strata `reasoning_effort: "high"`）。
- サンプリング: Ollama は送らない（各 Modelfile の既定）。`num_ctx` も送らない（各 Modelfile の `num_ctx`。2026-10-18 から
  A30 に載る最大を Modelfile に持たせている: `tools/qwen-model-bench/README.md` の「文脈長の上限」。2026-10-08 の評価のときは
  it-qat がサーバーの既定 65536、ctx32k が Modelfile の 32768 だった）。Strata は temperature 1.0 / top_p 0.95 / top_k 20 を送る。
- Ollama は最初に `/api/generate` で読み込んでから流す（ロード時間を問の時間から外す）。keep_alive は 15 分で、
  1 モデル終わるごとに `unload`（keep_alive:0）で降ろす。
- 上の値は `run_eval.py run` の既定。`--max-tokens` と `--reasoning-budget`（0 = 上限なし。Strata の要求にだけ効く）で上書きでき、
  実際に送った値は記録の `limits` に残る。コーディングでは既定の上限のままが最も点が高かった（上の「コーディング性能の調査」）。
- 上限で本文が出なかった問・時間切れ・stall・思考中の停止（`eos_in_thinking`）は 0 点。1 モデルの累計（ロードを除く壁時計）が 100 分を超えたら、
  残りの問を `skipped_time_budget`（0 点）にする。累計は問を送る前に見るので、最後の 1 問は上限を越えて走りうる。
- 再開: 記録がある問は飛ばす。`--retry-errors` は `error` を、`--retry-skipped` は `skipped_time_budget` を流し直す。
  `--redo` は全部。

## 採点

- コーディング: 答えの最後の ```python ブロック（無ければ最後の ``` ブロック、それも無ければ `def` を含む本文全体）を
  `work/<日付>/<slug>/<問>/solution.py` に書き、隠しテスト（各 20〜26 ケース。易しいものから並べ、性能のケースを最後に置く）
  を動かす。点数は合格したケースの割合（部分点）、`all_passed` は全部合格か。C4 は `json`、C5 は `re` を使うと 0 点
  （各 `tests.py` の `FORBIDDEN_CALLS`。import と呼び出しの両方を静的な走査で見つける）。
- 指示追従（inst）: `answer.json` の 5 つの条件を機械で確かめ、満たした割合が点数。
- needle: 答えの飾り（空白・かぎかっこ・引用符・`**`・末尾の句点）だけを外して、合言葉と完全一致なら 1 点。
- JSON: 本文全体 → ```json ブロック → 最初の `{` から最後の `}` の順に読み、6 項目の一致率が点数。文字列は NFKC で
  比べ、整数・真偽値は型も見る。`format`（JSON モード）は使わない（Strata と条件を揃えるため）。

## サンドボックス（擬似的な遮断）

この機体では AppArmor の制限で `unshare -rn` や `bwrap` が使えない。本物のネット遮断・名前空間の隔離はしていない。
代わりに次の事故防止だけをする（悪意のないモデルの答えが前提）。

- 実行前の静的な走査: socket・subprocess・urllib・http・ctypes・multiprocessing などの import、`os.system`・`os.exec*`・
  `os.fork`・削除系・動的な `__import__` を見つけたら実行せず 0 点。
- 実行中: `python3 -I -S -B`、禁止モジュールの import を `sys.meta_path` で拒む、`open` と os のプロセス・書き込み・削除系の
  関数を差し替える、`print` は捨てる。
- 資源: 壁時計 10 秒・CPU 10 秒・アドレス空間 2 GiB（2026-10-18 に 1 GiB から変更）・書けるファイル 1 MiB。子プロセスは静的な走査と実行時の差し替えで止める。
  2026-10-08 の評価のときは RLIMIT_NPROC 0 でスレッドも作れなかった。2026-10-18 に外した（スレッドで深い再帰を動かす答えが、問題文で禁じていないのに全部落ちたため）。2026-10-08 の記録は採点し直していない
  1 ケース 3 秒（SIGALRM）。作業ディレクトリは `work/` の下で、/tmp は使わない。

## ランキングの式（計画の方針 6。HTML にも出す）

- 能力: 回（問）ごとの点数（0〜1）の平均。答えなし・上限・時間切れ・飛ばしは 0 点。
- 速度点 = (ln T_max − ln T) ÷ (ln T_max − ln T_min)。T は 3D が全問に答えるまでの時間の中央値、コーディングと追加が
  1 問あたりの時間の中央値。Ollama はロード時間を除き、Claude は Agent の duration。
- 総合 = 0.7 × 能力 + 0.3 × 速度点。
- tok/s は参考。Claude の時間は API の待ちを含むので、機体の中で動くローカルの時間とは意味が違う。

3D のローカル 7 種は再計測せず、`Documents/3D問題_実施モデル一覧_2026-10-08.md` の記録を `results/2026-10-08/math3d_local.json`
に写した（`used: false` の回は参考で、能力に入れない）。

## 既知の制約

- Strata 用の読み取りは、上流の `vendor/Strata/serve/server.py` の `openai_chunks` に合わせて書き、偽のサーバーで試験した。
  実機の Strata（8082 / 8084）ではまだ流していない（P2 で初めて使う）。
- この機体にブラウザが無い（firefox は snap 未導入）。SVG の図だけは GdkPixbuf（librsvg、システムの python3-gi）で
  PNG に描いて目で確かめた（2026-10-08。散布図の名前の重なりを直したあと）。ページ全体の組み版（表の幅・ツールチップ）は
  確かめていない。
  構造は試験（`html.parser` で表と SVG の数）で確かめる。
