#!/usr/bin/env python3
"""Strata の OpenAI 互換 API（/v1/chat/completions、ストリーミング）の速さを測る（標準ライブラリのみ）。

  bench_api.py --prompt short --thinking off --runs 3
  bench_api.py --prompt 4k --thinking on --runs 3 --max-tokens 256
  bench_api.py --base-url http://127.0.0.1:8083/v1 --model strata-flash-coder:IQ1_M \
      --prompt code --thinking on --effort high --max-tokens 16384 --temperature none --save-dir logs/x
  bench_api.py --prompt-file TestData/数学難問-三次元空間-TEST.md --thinking on --effort high \
      --reasoning-budget 8192 --presence-penalty 1.0 --max-tokens 65536 --timeout 2400 --runs 1 --label budget8k

1 回ごとに次を 1 行の JSON で出し、最後に中央値の表を出す:
- ttft_s: 送ってから最初の文字（reasoning_content か content）が届くまでの秒（壁時計）
- prompt_tokens / completion_tokens / reasoning_tokens（usage）
- prefill_tok_s: サーバーの timings.prompt_per_second（engine の時計）
- decode_tok_s: サーバーの timings.predicted_per_second（engine の時計）
- wall_decode_tok_s: (completion_tokens - 1) / (最後の差分 - 最初の差分)（壁時計の検算）
- draft_n / draft_n_accepted: 投機デコードの提案と採用（engine が出したときだけ）

会話のキャッシュ（--prompt-cache）が同じ前置きを使い回すと prefill が速く見えるので、
毎回プロンプトの先頭に違う番号を入れる。

--prompt code（コード生成の課題）と ja（日本語の短い質問）は、速さよりも答えの質と「reasoning が同じ文を
繰り返して止まらない」（上流 issue #1015）かを見るためのもの。次も出す:
- reasoning_repeat_coverage: 上流サーバーの #728 の検出（serve/server.py の reasoning_repeat_coverage）と同じ指標。
  直近 2,000 語のうち、3 回以上出た 12 語の並びに含まれる語の割合。上流はこれが 0.25 以上でループとみなす。
- reasoning_max_repeats / content_max_repeats: 同じ文（15 文字以上）が出た最多の回数と、その文。
--save-dir を付けると、reasoning と本文の全文を 1 回ごとにファイルへ書く。
--temperature none はサンプリングを送らない（サーバーの既定 = greedy。Open WebUI などが何も送らないときと同じ）。

「問題ファイルを 1 問として送り、思考の予算とペナルティを変えて収束するか」を測る使い方:
- --prompt-file: ファイルの全文（UTF-8）を user メッセージとして送る（--prompt より優先）。先頭に「（問題 番号）」の行を
  足して会話のキャッシュを避ける（問題文は変えない）。
- --reasoning-budget N: 要求に reasoning_budget_tokens を入れる（#123）。0 も送る（要求の値が設定 JSON の値より優先し、
  0 は「予算なし」なので、サーバー設定に予算が入っていても無効にできる）。付けなければ鍵を入れない。
- --presence-penalty / --repetition-penalty: 付けたときだけ要求に入れる。
- 結果の行に次が増える: finish_reason、has_answer（本文が出たか）、thinking_tokens と thinking_tokens_source、
  reasoning_budget_tokens / presence_penalty / repetition_penalty（送った値。送らなければ null）、prompt_file。
  thinking_tokens は usage.completion_tokens_details.reasoning_tokens（あれば）。無いときは推定: reasoning が 1 文字も
  届かなければ 0、本文が出ていなければ completion_tokens で代用（全部 thinking とみなす）、本文もあれば null にして
  reasoning_chars（文字数）で見る。どれかは thinking_tokens_source に書く。
  上流の Chat Completions のストリームは今のところ reasoning_tokens を usage に入れない（vendor/Strata/serve/server.py の
  openai_chunks）ので、たいてい推定になる。
- 65,536 トークンの生成は約 52 tok/s で約 21 分。--timeout 2400 を目安にする（既定の 900 秒では足りない）。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

SHORT_QUESTION = "富士山の高さは何メートルですか。理由を一文添えて答えてください。"

# コード生成の課題（Coder の本来の用途。thinking ありで reasoning のループが起きないかを見る）
CODE_TASK = "Python で LRU キャッシュを実装し、テストも書いてください。"
# 同じ課題の英語版（日本語の課題文がループの引き金かを切り分ける）
CODE_TASK_EN = "Implement an LRU cache in Python and write tests for it."

# 日本語の短い質問（Coder は CJK が弱いと上流が注意している。docs/MODELS.md の Coder、#438）。回ごとに順に使う。
JA_QUESTIONS = (
    "「情けは人のためならず」の本来の意味を、よくある誤解と合わせて 3 行で説明してください。",
    "Python のリストとタプルの違いを、使い分けの目安と合わせて日本語で簡潔に説明してください。",
    "梅雨の時期に洗濯物を部屋干しするときのコツを 3 つ、箇条書きで教えてください。",
)

# 上流サーバーの #728 の検出と同じ値（serve/server.py の LOOP_HISTORY_WORDS など）
LOOP_HISTORY_WORDS = 30000
LOOP_WIDTH = 12
LOOP_WINDOW = 2000


def repeat_coverage(text: str) -> float:
    """直近 2,000 語のうち、3 回以上出た 12 語の並びに含まれる語の割合（serve/server.py の
    reasoning_repeat_coverage と同じ計算）。語が 2,000 に満たなければ 0。"""

    words = re.findall(r"\w+|[^\w\s]", text.lower())[-LOOP_HISTORY_WORDS:]
    if len(words) < LOOP_WINDOW:
        return 0.0
    grams = [tuple(words[index:index + LOOP_WIDTH]) for index in range(len(words) - LOOP_WIDTH + 1)]
    counts = collections.Counter(grams)
    start = max(0, len(words) - LOOP_WINDOW)
    covered: set[int] = set()
    for index in range(start, len(grams)):
        if counts[grams[index]] >= 3:
            covered.update(range(index, index + LOOP_WIDTH))
    return len(covered) / (len(words) - start)


def max_sentence_repeats(text: str, min_chars: int = 15) -> tuple[int, str]:
    """同じ文（改行・句点・ピリオドで区切り、min_chars 文字以上）が出た最多の回数と、その文。"""

    sentences = [part.strip() for part in re.split(r"[\n。！？]|(?<=[.!?])\s", text)]
    counts = collections.Counter(sentence for sentence in sentences if len(sentence) >= min_chars)
    if not counts:
        return 0, ""
    sentence, count = counts.most_common(1)[0]
    return count, sentence

# 4K トークン用の素材。中身が繰り返しだけにならないよう、番号ごとに数字を変える。
PARAGRAPH = (
    "第{index}節。ある町の図書館では、{year}年に蔵書が{books}冊に増え、利用者は一日平均{visitors}人だった。"
    "館長は閲覧室の照明を{lamps}台入れ替え、開館時間を{hours}時間に延ばした。翌年の予算は{budget}万円で、"
    "そのうち{share}割が新しい本の購入に充てられた。地域の学校との連携で、毎月{events}回の読み聞かせ会が開かれた。"
)


def build_long_prompt(target_chars: int, nonce: int) -> str:
    parts = []
    index = 0
    while sum(len(part) for part in parts) < target_chars:
        index += 1
        parts.append(
            PARAGRAPH.format(
                index=index, year=1990 + index % 30, books=10000 + index * 137, visitors=50 + index * 7 % 300,
                lamps=10 + index % 40, hours=8 + index % 5, budget=300 + index * 11 % 900, share=1 + index % 9,
                events=1 + index % 6,
            )
        )
    body = "\n".join(parts)
    return (
        f"資料番号 {nonce}。次の資料を読んで、蔵書が最も多かった節の番号と冊数、全体の傾向を 3 行で答えてください。\n\n"
        + body
    )


def stream_chat(base_url: str, payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"},
        method="POST",
    )
    started = time.monotonic()
    first_delta = None
    last_delta = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict[str, Any] = {}
    timings: dict[str, Any] = {}
    finish = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("usage"):
                usage = chunk["usage"]
            if chunk.get("timings"):
                timings = chunk["timings"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                text = (delta.get("content") or "") + (delta.get("reasoning_content") or "")
                if text:
                    now = time.monotonic()
                    first_delta = first_delta if first_delta is not None else now
                    last_delta = now
                if delta.get("content"):
                    content_parts.append(delta["content"])
                if delta.get("reasoning_content"):
                    reasoning_parts.append(delta["reasoning_content"])
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
    ended = time.monotonic()
    completion = int(usage.get("completion_tokens") or 0)
    wall_decode = None
    if first_delta is not None and last_delta is not None and last_delta > first_delta and completion > 1:
        wall_decode = (completion - 1) / (last_delta - first_delta)
    details = usage.get("completion_tokens_details") or {}
    reasoning_text = "".join(reasoning_parts)
    content_text = "".join(content_parts)
    # thinking のトークン数: usage にあればそれ。無いときは、reasoning が届かなければ 0、本文が出ていなければ全部が thinking とみなして
    # completion_tokens で代用（推定）。本文があれば按分できないので null にして reasoning_chars を見てもらう。
    if isinstance(details.get("reasoning_tokens"), int):
        thinking_tokens: int | None = details["reasoning_tokens"]
        thinking_source = "usage.completion_tokens_details.reasoning_tokens"
    elif not reasoning_text:
        thinking_tokens = 0
        thinking_source = "estimate: usage に無い。reasoning_content が 1 文字も届かなかったので 0"
    elif not content_text and completion:
        thinking_tokens = completion
        thinking_source = "estimate: usage に無い。本文が無いので completion_tokens を thinking とみなした"
    else:
        thinking_tokens = None
        thinking_source = "none: usage に無い。reasoning_chars（文字数）で見る"
    reasoning_repeats, reasoning_sentence = max_sentence_repeats(reasoning_text)
    content_repeats, content_sentence = max_sentence_repeats(content_text)
    return {
        "ttft_s": round(first_delta - started, 2) if first_delta is not None else None,
        "total_s": round(ended - started, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion,
        "reasoning_tokens": details.get("reasoning_tokens"),
        "prefill_tok_s": timings.get("prompt_per_second"),
        "decode_tok_s": timings.get("predicted_per_second"),
        "wall_decode_tok_s": round(wall_decode, 1) if wall_decode else None,
        "cache_n": timings.get("cache_n"),
        "draft_n": timings.get("draft_n"),
        "draft_n_accepted": timings.get("draft_n_accepted"),
        "finish": finish,
        "finish_reason": finish,
        "has_answer": bool(content_text.strip()),
        "thinking_tokens": thinking_tokens,
        "thinking_tokens_source": thinking_source,
        "content_head": content_text[:120],
        "reasoning_chars": len(reasoning_text),
        "content_chars": len(content_text),
        "reasoning_repeat_coverage": round(repeat_coverage(reasoning_text), 3),
        "reasoning_max_repeats": reasoning_repeats,
        "reasoning_top_sentence": reasoning_sentence[:80],
        "content_max_repeats": content_repeats,
        "content_top_sentence": content_sentence[:80],
        "_reasoning_text": reasoning_text,
        "_content_text": content_text,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8082/v1")
    parser.add_argument("--model", default="strata-flash-next:IQ3_S")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--prompt", choices=["short", "4k", "code", "code-en", "ja"], default="short")
    parser.add_argument("--prompt-file", default=None,
                        help="このファイルの全文（UTF-8）を user メッセージとして送る（--prompt より優先）。"
                             "先頭に「（問題 番号）」の行を足す")
    parser.add_argument("--long-chars", type=int, default=5600, help="4k の素材の文字数（日本語は約 1.4 文字で 1 トークン）")
    parser.add_argument("--thinking", choices=["on", "off"], default="off")
    parser.add_argument("--effort", default="low", help="--thinking on のときの reasoning_effort")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", default="0.7",
                        help="数値か none（none は送らない = サーバーの既定の greedy）")
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--reasoning-budget", type=int, default=None,
                        help="reasoning_budget_tokens を要求に入れる。0 も送る（予算なし。サーバー設定の予算を無効にできる）。"
                             "付けなければ送らない")
    parser.add_argument("--presence-penalty", type=float, default=None, help="付けたときだけ presence_penalty を送る")
    parser.add_argument("--repetition-penalty", type=float, default=None,
                        help="付けたときだけ repetition_penalty を送る（1 = なし）")
    parser.add_argument("--save-dir", default=None, help="reasoning と本文の全文を 1 回ごとに書くディレクトリ")
    parser.add_argument("--label", default="", help="結果の行に付ける名前（比較表を作るとき用）")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="秒。65,536 トークンの生成は約 52 tok/s で約 21 分かかるので、そのときは --timeout 2400 を目安に")
    parser.add_argument("--nonce-base", type=int, default=int(time.time()) % 100000)
    parser.add_argument("--out", default=None, help="結果を JSON Lines で追記するファイル")
    args = parser.parse_args(argv)

    prompt_file_text = None
    prompt_name = args.prompt
    if args.prompt_file:
        prompt_file_text = Path(args.prompt_file).read_text(encoding="utf-8")
        prompt_name = Path(args.prompt_file).stem

    results = []
    for run_index in range(args.runs):
        nonce = args.nonce_base + run_index
        if prompt_file_text is not None:
            # 問題文はそのまま。会話のキャッシュを避ける番号は、他のプロンプトと同じく先頭に別の行として置く。
            text = f"（問題 {nonce}）\n\n{prompt_file_text}"
        elif args.prompt == "short":
            text = f"（質問 {nonce}）{SHORT_QUESTION}"
        elif args.prompt == "code":
            text = f"（課題 {nonce}）{CODE_TASK}"
        elif args.prompt == "code-en":
            text = f"(Task {nonce}) {CODE_TASK_EN}"
        elif args.prompt == "ja":
            text = f"（質問 {nonce}）{JA_QUESTIONS[run_index % len(JA_QUESTIONS)]}"
        else:
            text = build_long_prompt(args.long_chars, nonce)
        payload: dict[str, Any] = {
            "model": args.model,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": args.max_tokens,
            "stream": True,
            "reasoning_effort": args.effort if args.thinking == "on" else "none",
        }
        if args.temperature.lower() != "none":
            payload["temperature"] = float(args.temperature)
        if args.top_p is not None:
            payload["top_p"] = args.top_p
        if args.top_k is not None:
            payload["top_k"] = args.top_k
        # 0 も「予算なし」として明示的に送る（None のときだけ鍵を入れない）
        if args.reasoning_budget is not None:
            payload["reasoning_budget_tokens"] = args.reasoning_budget
        if args.presence_penalty is not None:
            payload["presence_penalty"] = args.presence_penalty
        if args.repetition_penalty is not None:
            payload["repetition_penalty"] = args.repetition_penalty
        result = stream_chat(args.base_url, payload, args.api_key, args.timeout)
        reasoning_text = result.pop("_reasoning_text")
        content_text = result.pop("_content_text")
        result.update({"run": run_index + 1, "prompt": prompt_name, "prompt_file": args.prompt_file,
                       "thinking": args.thinking, "label": args.label, "model": args.model,
                       "temperature": payload.get("temperature"),
                       "reasoning_budget_tokens": payload.get("reasoning_budget_tokens"),
                       "presence_penalty": payload.get("presence_penalty"),
                       "repetition_penalty": payload.get("repetition_penalty")})
        if args.save_dir:
            save_dir = Path(args.save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{args.label or prompt_name}-{args.thinking}-{run_index + 1}"
            (save_dir / f"{stem}.prompt.txt").write_text(text, encoding="utf-8")
            (save_dir / f"{stem}.reasoning.txt").write_text(reasoning_text, encoding="utf-8")
            (save_dir / f"{stem}.content.txt").write_text(content_text, encoding="utf-8")
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.out:
            with open(args.out, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    def median(key: str) -> float | None:
        values = [row[key] for row in results if isinstance(row.get(key), (int, float))]
        return round(statistics.median(values), 1) if values else None

    print(
        f"中央値: prompt={prompt_name} thinking={args.thinking} prompt_tokens={median('prompt_tokens')} "
        f"ttft_s={median('ttft_s')} prefill_tok_s={median('prefill_tok_s')} decode_tok_s={median('decode_tok_s')} "
        f"wall_decode_tok_s={median('wall_decode_tok_s')} completion_tokens={median('completion_tokens')} "
        f"has_answer={sum(1 for row in results if row['has_answer'])}/{len(results)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
