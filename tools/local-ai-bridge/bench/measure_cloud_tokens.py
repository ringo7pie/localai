"""クラウド（Claude Code）側の実トークン消費を、セッション記録から測る。

Claude Code は 1 ターンごとの usage を
~/.claude/projects/<プロジェクト>/<session-id>.jsonl に記録している。
そこから実測値を読む。推定はしない。

使い方:
  python3 measure_cloud_tokens.py mark                      # 今の時刻を印として出す
  python3 measure_cloud_tokens.py sum --since <ISO> [--until <ISO>]
  python3 measure_cloud_tokens.py sum --since <ISO> --json

料金（tools/local-ai-bridge/bench/rates.json。既定は Claude Opus 5）:
  入力 $5.00/MTok / 出力 $25.00/MTok
  キャッシュ読み 0.1x / キャッシュ書き 5分TTL 1.25x・1時間TTL 2.0x
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RATES = {
    "model": "claude-opus-5",
    "input_per_mtok": 5.00,
    "output_per_mtok": 25.00,
    "cache_read_multiplier": 0.1,
    "cache_write_5m_multiplier": 1.25,
    "cache_write_1h_multiplier": 2.0,
    "source": "claude-api skill（2026-06-24 時点のキャッシュ表）。変わったら rates.json を直すこと",
}


def load_rates(path: Path | None) -> dict:
    if path and path.is_file():
        return {**DEFAULT_RATES, **json.loads(path.read_text(encoding="utf-8"))}
    return dict(DEFAULT_RATES)


def find_transcript(explicit: Path | None) -> Path:
    """一番新しく書かれたセッション記録。今動いている会話のものになる。"""
    if explicit:
        return explicit
    root = Path.home() / ".claude" / "projects"
    candidates = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"セッション記録が見つかりません: {root}")
    return candidates[0]


def parse_time(text: str) -> datetime:
    value = text.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def collect(path: Path, since: datetime, until: datetime | None) -> dict:
    totals = {
        "turns": 0,
        "input_tokens": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "models": {},
        "first_ts": None,
        "last_ts": None,
    }
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") or {}
            usage = message.get("usage")
            raw_ts = entry.get("timestamp")
            if not usage or not raw_ts:
                continue
            # 補助スレッド（subagent）の消費も本人の請求に乗るので除外しない。
            stamp = parse_time(raw_ts)
            if stamp < since:
                continue
            if until and stamp > until:
                continue
            totals["turns"] += 1
            totals["input_tokens"] += int(usage.get("input_tokens") or 0)
            totals["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
            totals["output_tokens"] += int(usage.get("output_tokens") or 0)
            details = usage.get("output_tokens_details") or {}
            totals["thinking_tokens"] += int(details.get("thinking_tokens") or 0)
            creation = usage.get("cache_creation") or {}
            write_5m = int(creation.get("ephemeral_5m_input_tokens") or 0)
            write_1h = int(creation.get("ephemeral_1h_input_tokens") or 0)
            if not creation:
                # 内訳が無い版では 5 分 TTL として扱う（過小評価を避けるため安い方に寄せない）
                write_5m = int(usage.get("cache_creation_input_tokens") or 0)
            totals["cache_write_5m"] += write_5m
            totals["cache_write_1h"] += write_1h
            model = message.get("model") or "(不明)"
            totals["models"][model] = totals["models"].get(model, 0) + 1
            iso = stamp.isoformat()
            totals["first_ts"] = totals["first_ts"] or iso
            totals["last_ts"] = iso
    return totals


def price(totals: dict, rates: dict) -> dict:
    per_token_in = rates["input_per_mtok"] / 1_000_000
    per_token_out = rates["output_per_mtok"] / 1_000_000
    parts = {
        "input": totals["input_tokens"] * per_token_in,
        "cache_write_5m": totals["cache_write_5m"] * per_token_in * rates["cache_write_5m_multiplier"],
        "cache_write_1h": totals["cache_write_1h"] * per_token_in * rates["cache_write_1h_multiplier"],
        "cache_read": totals["cache_read"] * per_token_in * rates["cache_read_multiplier"],
        "output": totals["output_tokens"] * per_token_out,
    }
    parts["total"] = sum(parts.values())
    return {key: round(value, 6) for key, value in parts.items()}


def billed_tokens(totals: dict) -> int:
    """素のトークン合計。倍率をかけない「消費量」の指標。"""
    return (
        totals["input_tokens"]
        + totals["cache_write_5m"]
        + totals["cache_write_1h"]
        + totals["cache_read"]
        + totals["output_tokens"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mark", help="今の UTC 時刻を印として出す")
    summary = sub.add_parser("sum", help="期間内の実トークンを合計する")
    summary.add_argument("--since", required=True)
    summary.add_argument("--until", default=None)
    summary.add_argument("--transcript", type=Path, default=None)
    summary.add_argument("--rates", type=Path, default=Path(__file__).parent / "rates.json")
    summary.add_argument("--label", default="")
    summary.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "mark":
        print(datetime.now(timezone.utc).isoformat())
        return 0

    path = find_transcript(args.transcript)
    rates = load_rates(args.rates)
    totals = collect(path, parse_time(args.since), parse_time(args.until) if args.until else None)
    costs = price(totals, rates)
    payload = {
        "label": args.label,
        "transcript": str(path),
        "window": {"since": args.since, "until": args.until, "first_turn": totals["first_ts"], "last_turn": totals["last_ts"]},
        "turns": totals["turns"],
        "tokens": {
            "input": totals["input_tokens"],
            "cache_write_5m": totals["cache_write_5m"],
            "cache_write_1h": totals["cache_write_1h"],
            "cache_read": totals["cache_read"],
            "output": totals["output_tokens"],
            "thinking": totals["thinking_tokens"],
            "billed_total": billed_tokens(totals),
        },
        "usd": costs,
        "models": totals["models"],
        "rates": {key: rates[key] for key in rates if key != "source"},
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    tokens = payload["tokens"]
    print(f"[{args.label or '区間'}] ターン {payload['turns']}  記録 {path.name}")
    print(f"  入力(非キャッシュ) {tokens['input']:>10,}")
    print(f"  キャッシュ書き 1h  {tokens['cache_write_1h']:>10,}   5m {tokens['cache_write_5m']:,}")
    print(f"  キャッシュ読み     {tokens['cache_read']:>10,}")
    print(f"  出力               {tokens['output']:>10,}   (うち思考 {tokens['thinking']:,})")
    print(f"  素の合計           {tokens['billed_total']:>10,} トークン")
    print(f"  費用               ${costs['total']:.4f}"
          f"  (読み ${costs['cache_read']:.4f} / 書き ${costs['cache_write_1h']+costs['cache_write_5m']:.4f}"
          f" / 出力 ${costs['output']:.4f} / 入力 ${costs['input']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
