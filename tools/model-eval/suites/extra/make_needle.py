#!/usr/bin/env python3
"""needle（長い資料からの検索）の問題文を作る。乱数の種を固定しているので、何度実行しても同じ文になる。

  /usr/bin/python3 suites/extra/make_needle.py          # needle1〜3 の prompt.md と answer.json を書き直す
  /usr/bin/python3 suites/extra/make_needle.py --check  # 書き直さず、今のファイルと一致するかだけ確かめる

資料は架空の町の記録（約 8,000 文字。日本語は 1 トークンが約 1.2〜1.5 文字なので約 6k トークン）。
合言葉の文を、段落の数で 20% / 55% / 85% の位置に 1 つだけ埋める。3 問とも種を変えて資料の中身を変え、
会話のキャッシュ（同じ前置きの使い回し）で後の問ほど prefill が速くなるのを避ける。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent
TARGET_CHARS = 8000

# (問 ID, 合言葉, 埋める位置, 乱数の種)
NEEDLES = (
    ("needle1", "月影ポプラ", 0.20, 101),
    ("needle2", "銀河モノレール", 0.55, 202),
    ("needle3", "琥珀の砂時計", 0.85, 303),
)

DISTRICTS = ("北浜", "南台", "東原", "西沢", "中町", "川端", "山手", "新田")

TEMPLATES = (
    "第{n}節（{year}年の記録）。みずなみ町の{district}地区では、春先の平均気温が{temp}度で、前年より{diff}度高かった。"
    "用水路の点検は{checks}回行われ、そのうち{repairs}か所で補修が必要とされた。",
    "第{n}節。町立図書館の{district}分室は、{year}年に蔵書を{books}冊まで増やした。平日の利用者は一日平均{visitors}人で、"
    "土曜日には読み聞かせ会が{events}回開かれた。",
    "第{n}節。{year}年の秋祭りでは、{district}地区の山車が{floats}台出て、見物客は延べ{guests}人に達した。"
    "運営に加わったボランティアは{volunteers}人で、清掃は翌朝{hour}時に終わった。",
    "第{n}節。町営バスの{route}系統は、{year}年に一日{trips}往復へ増便された。始発は{first}時{minute}分で、"
    "終点の{district}団地までの所要時間はおよそ{duration}分である。",
    "第{n}節。{district}地区の農家{farms}戸は、{year}年に米を合計{rice}俵出荷した。梅雨の長雨で収穫は{delay}日遅れたが、"
    "品質の検査では一等米の割合が{ratio}割を超えた。",
    "第{n}節。{year}年の町議会では、{district}地区の歩道の整備に{budget}万円が計上された。工事は{months}か月かけて行われ、"
    "延長{length}メートルの区間で段差がなくなった。",
)

NEEDLE_SENTENCE = "第{n}節の補足。記録係のあいだで今年使われている合言葉は「{word}」であり、外部の人には伝えないこと。"

QUESTION = (
    "質問: この資料には、記録係のあいだで使われている合言葉が 1 つだけ書かれています。その合言葉を答えてください。"
    "答えは合言葉だけを 1 行で書き、かぎかっこ・説明・前置きは付けないでください。"
)


def _paragraph(rng: random.Random, number: int) -> str:
    template = TEMPLATES[rng.randrange(len(TEMPLATES))]
    values = {
        "n": number, "year": rng.randint(1985, 2024), "district": rng.choice(DISTRICTS),
        "temp": rng.randint(8, 16), "diff": rng.randint(1, 3), "checks": rng.randint(3, 20),
        "repairs": rng.randint(1, 9), "books": rng.randint(8000, 60000), "visitors": rng.randint(30, 400),
        "events": rng.randint(1, 6), "floats": rng.randint(2, 12), "guests": rng.randint(2000, 40000),
        "volunteers": rng.randint(20, 300), "hour": rng.randint(5, 10), "route": rng.randint(1, 15),
        "trips": rng.randint(8, 40), "first": rng.randint(5, 7), "minute": rng.choice((0, 10, 15, 20, 30, 45)),
        "duration": rng.randint(15, 70), "farms": rng.randint(12, 140), "rice": rng.randint(800, 9000),
        "delay": rng.randint(3, 15), "ratio": rng.randint(6, 9), "budget": rng.randint(300, 9000),
        "months": rng.randint(2, 14), "length": rng.randint(150, 2400),
    }
    return template.format(**values)


def build(item_id: str, word: str, depth: float, seed: int) -> tuple[str, dict]:
    rng = random.Random(seed)
    paragraphs: list[str] = []
    while sum(len(paragraph) for paragraph in paragraphs) < TARGET_CHARS:
        paragraphs.append(_paragraph(rng, len(paragraphs) + 1))
    insert_at = round(len(paragraphs) * depth)
    # 合言葉の段落は、直前の節の補足として置く（節の番号は直前の段落に合わせる）
    paragraphs.insert(insert_at, NEEDLE_SENTENCE.format(n=insert_at, word=word))
    document = "\n".join(paragraphs)
    prompt = (
        f"次の資料（資料番号 {seed}）を読んで、最後の質問に答えてください。\n\n"
        f"資料:\n\"\"\"\n{document}\n\"\"\"\n\n{QUESTION}\n"
    )
    answer = {"kind": "needle", "answer": word, "depth": depth, "paragraphs": len(paragraphs),
              "needle_paragraph_index": insert_at, "document_chars": len(document), "seed": seed}
    return prompt, answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="書き直さず、今のファイルと一致するかだけ確かめる")
    args = parser.parse_args(argv)
    mismatches = []
    for item_id, word, depth, seed in NEEDLES:
        prompt, answer = build(item_id, word, depth, seed)
        item_dir = SUITE_DIR / item_id
        answer_text = json.dumps(answer, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if (item_dir / "prompt.md").read_text(encoding="utf-8") != prompt or \
                    (item_dir / "answer.json").read_text(encoding="utf-8") != answer_text:
                mismatches.append(item_id)
            continue
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        (item_dir / "answer.json").write_text(answer_text, encoding="utf-8")
        print(f"{item_id}: {len(prompt)} 文字、段落 {answer['paragraphs']}、合言葉は {answer['needle_paragraph_index']} 番目")
    if mismatches:
        print(f"一致しない: {', '.join(mismatches)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
