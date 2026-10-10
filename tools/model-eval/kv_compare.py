#!/usr/bin/env python3
"""互換の入口。cond_compare.py を KV キャッシュの型の比べの既定（--kind kv、results/2026-10-09-kv）で呼ぶ。

  kv_compare.py summarize [--root results/2026-10-09-kv]
  kv_compare.py report [--root ...] [--out Documents/Strata_KVキャッシュ比較_2026-10-09.html]

中身は cond_compare.py にある（条件名を任意にした一般化版）。サブコマンドの一覧は cond_compare.py --help。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import cond_compare  # noqa: E402
from cond_compare import *  # noqa: E402,F401,F403  # 古い参照（kv_compare.judge_scores など）をそのまま使えるようにする


def main(argv: list[str] | None = None) -> int:
    return cond_compare.main(argv, default_kind=cond_compare.KIND_KV)


if __name__ == "__main__":
    sys.exit(main())
