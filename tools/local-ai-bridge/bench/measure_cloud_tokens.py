"""クラウド（Claude Code）側の実トークン消費を、セッション記録から測る。

Claude Code は 1 ターンごとの usage を
~/.claude/projects/<プロジェクト>/<session-id>.jsonl に記録している。
そこから実測値を読む。推定はしない。

読むときの注意（実測で分かったこと）:
- 1 つの assistant メッセージは内容ブロックごとに複数行へ分かれて書かれる。
  それぞれ同じ ``message.id`` と同じ ``message.usage`` を持つので、素直に全行を
  足すと 2〜3 倍に水増しされる。``message.id``（無ければ ``requestId``）で
  重複を落とす。
- サブエージェントの消費は親の jsonl に入らない。
  ~/.claude/projects/<プロジェクト>/<session-id>/subagents/agent-<id>.jsonl に
  別ファイルで書かれる（親側の行に ``isSidechain`` は立たない）。
  請求は本人に乗るので、既定ではこれも合算する。
- 記録ファイルは必ず指定する。更新時刻が一番新しい jsonl を選ぶ自動判定は、
  並行して動く別セッションの記録を掴むので廃止した。

- モデルは 1 つとは限らない。同じセッションでも親が Fable 5.1、サブエージェントが
  Opus 5 ということがある。単価はメッセージごとに ``message.model`` で引く
  （実測で見つかった欠陥: 以前は全部を Opus 5 の単価で計算していた）。

使い方:
  python3 measure_cloud_tokens.py mark                      # 今の時刻を印として出す
  python3 measure_cloud_tokens.py sum --session <session-id> --since <ISO> [--until <ISO>]
  python3 measure_cloud_tokens.py sum --transcript <path> --since <ISO>
  python3 measure_cloud_tokens.py sum --session <id> --since <ISO> --parent-only
  python3 measure_cloud_tokens.py sum --session <id> --since <ISO> --subagent agent-<id>
  python3 measure_cloud_tokens.py sum --session <id> --since <ISO> --list-subagents
  python3 measure_cloud_tokens.py sum --session <id> --since <ISO> --json
  python3 measure_cloud_tokens.py sum --last-minutes 30           # --since の代わりに直近 N 分を窓にする
  （--session も --transcript も無いときは環境変数 CLAUDE_CODE_SESSION_ID を使う。
    旧 CLAUDE_SESSION_ID も後方互換で読む）

料金は tools/local-ai-bridge/bench/rates.json のモデル別の表を使う。
表に無いモデルが窓に入っていたら、推定せずエラーで止める。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

RATE_KEYS = (
    "input_per_mtok",
    "output_per_mtok",
    "cache_read_multiplier",
    "cache_write_5m_multiplier",
    "cache_write_1h_multiplier",
)

# rates.json が無いときの最低限の控え。正は bench/rates.json。
DEFAULT_MODEL_RATES = {
    "claude-opus-5": {
        "input_per_mtok": 5.00,
        "output_per_mtok": 25.00,
        "cache_read_multiplier": 0.1,
        "cache_write_5m_multiplier": 1.25,
        "cache_write_1h_multiplier": 2.0,
        "assumption": False,
        "source": "claude-api skill shared/models.md（$5/$25 per MTok）",
    },
    "claude-fable-5-1": {
        "input_per_mtok": 10.00,
        "output_per_mtok": 50.00,
        "cache_read_multiplier": 0.025,
        "cache_write_5m_multiplier": 1.25,
        "cache_write_1h_multiplier": 2.0,
        "assumption": True,
        "source": "claude-api skill shared/models.md（$10/$50 per MTok、cache reads $0.25/MTok = 0.025x）。書き倍率は一般則",
    },
}


def load_rates(path: Path | None) -> dict:
    """モデル別の単価表を読む。{"models": {モデル名: 単価}, "path": ...} を返す。"""
    if path and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.get("models")
        if not isinstance(models, dict) or not models:
            raise SystemExit(
                f"単価表の形式が違います（models の辞書がありません）: {path}"
            )
        for name, entry in models.items():
            missing = [key for key in RATE_KEYS if key not in entry]
            if missing:
                raise SystemExit(
                    f"単価表のモデル {name} に項目が足りません: {', '.join(missing)}（{path}）"
                )
        return {"models": models, "path": str(path)}
    return {"models": {name: dict(entry) for name, entry in DEFAULT_MODEL_RATES.items()}, "path": None}


def rate_for(rates: dict, model: str) -> dict:
    """モデル名から単価を引く。表に無ければ推定せずエラーで止める。"""
    table = rates["models"]
    entry = table.get(model)
    if entry is None:
        known = ", ".join(sorted(table)) or "(空)"
        where = rates.get("path") or "既定の単価表（rates.json が見つからない）"
        raise SystemExit(
            f"単価表に無いモデルが記録に入っています: {model}\n"
            f"  単価表: {where}\n"
            f"  表にあるモデル: {known}\n"
            "  推定では計算しません。rates.json に実際の単価を足してください。"
        )
    return entry


def projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def find_transcript(
    explicit: Path | None,
    session: str | None = None,
    *,
    root: Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """測る対象のセッション記録を決める。自動選択はしない。

    優先順は --transcript > --session > 環境変数 CLAUDE_CODE_SESSION_ID
    （無ければ後方互換で CLAUDE_SESSION_ID）。
    どれも無ければエラーで止める。「一番新しい jsonl」を選ぶ推測は、
    並行して動く別セッションの記録を掴んで誤った実測値を出すため廃止した。
    """
    if explicit:
        if not explicit.is_file():
            raise SystemExit(f"指定されたセッション記録がありません: {explicit}")
        return explicit
    environment = os.environ if env is None else env
    session_id = (
        session
        or environment.get("CLAUDE_CODE_SESSION_ID")
        or environment.get("CLAUDE_SESSION_ID")
        or ""
    )
    session_id = session_id.strip()
    base = root or projects_root()
    if not session_id:
        raise SystemExit(
            "測る対象のセッションが決まりません。--session <session-id> か --transcript <path>"
            " を指定してください（環境変数 CLAUDE_CODE_SESSION_ID でも可。"
            "旧 CLAUDE_SESSION_ID も後方互換で読みます）。\n"
            "更新時刻が一番新しい jsonl を自動で選ぶ動きは廃止しました。"
            "並行して動く別セッションの記録を掴み、無関係な消費を計上したためです。"
        )
    candidates = sorted(base.glob(f"*/{session_id}.jsonl"))
    if not candidates:
        raise SystemExit(f"セッション {session_id} の記録が {base} に見つかりません。")
    if len(candidates) > 1:
        # 同じ session-id が複数プロジェクトにある想定は無いが、黙って選ばない。
        listing = "\n".join(f"  {path}" for path in candidates)
        raise SystemExit(
            f"セッション {session_id} の記録が複数あります。--transcript で 1 つ選んでください:\n{listing}"
        )
    return candidates[0]


def subagent_transcripts(parent: Path) -> list[Path]:
    """親の記録に対応する subagents/ 配下の記録一覧。無ければ空。"""
    directory = parent.parent / parent.stem / "subagents"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.jsonl"))


def subagent_transcript(parent: Path, agent_id: str) -> Path:
    """親の記録に対応する subagents/ から 1 本だけ選ぶ。

    agent_id は "agent-xxxx" でも "xxxx" でも "agent-xxxx.jsonl" でも受ける。
    """
    name = agent_id.strip()
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
    if not name.startswith("agent-"):
        name = f"agent-{name}"
    candidates = subagent_transcripts(parent)
    for path in candidates:
        if path.stem == name:
            return path
    listing = "\n".join(f"  {path.stem}" for path in candidates) or "  (1 件も無い)"
    raise SystemExit(
        f"サブエージェント記録 {name}.jsonl が見つかりません。\n"
        f"親の記録: {parent}\n候補:\n{listing}"
    )


def parse_time(text: str) -> datetime:
    value = text.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _empty_totals() -> dict:
    return {
        "turns": 0,
        "input_tokens": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "models": {},
        "by_model": {},
        "first_ts": None,
        "last_ts": None,
        "duplicate_lines": 0,
    }


def _accumulate(totals: dict, usage: dict) -> None:
    """1 メッセージ分の usage を足す。モデル別と全体で同じ処理を使う。"""
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


def unique_messages(paths: Sequence[Path]) -> tuple[list[tuple[datetime, dict, str]], int]:
    """(時刻, usage, model) の一覧と、落とした重複行の数を返す。

    同じ assistant メッセージが内容ブロックごとに複数行へ分かれて書かれ、どの行も
    同じ ``message.usage`` を持つ。``message.id``（無ければ ``requestId``、
    それも無ければ ``uuid``）で重複を落とす。時刻は最初に書かれた行のものを採る
    （時間窓の判定を、後続ブロックの書き込み時刻でずらさないため）。
    """
    seen: dict[str, dict] = {}
    order: list[str] = []
    duplicates = 0
    for path in paths:
        if not path.is_file():
            continue
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
                key = message.get("id") or entry.get("requestId") or entry.get("uuid")
                if not key:
                    continue
                stamp = parse_time(raw_ts)
                known = seen.get(key)
                if known is None:
                    seen[key] = {
                        "stamp": stamp,
                        "usage": usage,
                        "model": message.get("model") or "(不明)",
                    }
                    order.append(key)
                    continue
                duplicates += 1
                if stamp < known["stamp"]:
                    known["stamp"] = stamp
    records = [(seen[key]["stamp"], seen[key]["usage"], seen[key]["model"]) for key in order]
    records.sort(key=lambda item: item[0])
    return records, duplicates


def collect(paths: Path | Sequence[Path], since: datetime, until: datetime | None) -> dict:
    """指定した記録群の、時間窓に入るトークンを合計する。重複行は 1 回だけ数える。"""
    if isinstance(paths, Path):
        paths = [paths]
    totals = _empty_totals()
    records, duplicates = unique_messages(paths)
    totals["duplicate_lines"] = duplicates
    for stamp, usage, model in records:
        if stamp < since:
            continue
        if until and stamp > until:
            continue
        _accumulate(totals, usage)
        # 単価はモデルごとに違う。モデル別に分けて持たないと正しく値付けできない。
        bucket = totals["by_model"].setdefault(model, _empty_totals())
        _accumulate(bucket, usage)
        totals["models"][model] = totals["models"].get(model, 0) + 1
        iso = stamp.isoformat()
        totals["first_ts"] = totals["first_ts"] or iso
        totals["last_ts"] = iso
    return totals


def price_one(totals: dict, rate: dict) -> dict:
    """1 モデル分の値付け。丸めない生の値を返す。"""
    per_token_in = rate["input_per_mtok"] / 1_000_000
    per_token_out = rate["output_per_mtok"] / 1_000_000
    parts = {
        "input": totals["input_tokens"] * per_token_in,
        "cache_write_5m": totals["cache_write_5m"] * per_token_in * rate["cache_write_5m_multiplier"],
        "cache_write_1h": totals["cache_write_1h"] * per_token_in * rate["cache_write_1h_multiplier"],
        "cache_read": totals["cache_read"] * per_token_in * rate["cache_read_multiplier"],
        "output": totals["output_tokens"] * per_token_out,
    }
    parts["total"] = sum(parts.values())
    return parts


def price(totals: dict, rates: dict) -> dict:
    """モデルごとに単価を引いて合計する。表に無いモデルがあれば止まる。"""
    parts = {key: 0.0 for key in ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output", "total")}
    for model, bucket in (totals.get("by_model") or {}).items():
        for key, value in price_one(bucket, rate_for(rates, model)).items():
            parts[key] += value
    return {key: round(value, 6) for key, value in parts.items()}


def price_by_model(totals: dict, rates: dict) -> dict:
    """モデル別の内訳（ターン数・費用・素のトークン数）。"""
    breakdown = {}
    for model, bucket in (totals.get("by_model") or {}).items():
        costs = price_one(bucket, rate_for(rates, model))
        breakdown[model] = {
            "turns": bucket["turns"],
            "usd": round(costs["total"], 6),
            "billed_tokens": billed_tokens(bucket),
        }
    return dict(sorted(breakdown.items(), key=lambda item: -item[1]["usd"]))


def billed_tokens(totals: dict) -> int:
    """素のトークン合計。倍率をかけない「消費量」の指標。"""
    return (
        totals["input_tokens"]
        + totals["cache_write_5m"]
        + totals["cache_write_1h"]
        + totals["cache_read"]
        + totals["output_tokens"]
    )


def section(totals: dict, rates: dict) -> dict:
    return {
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
        "usd": price(totals, rates),
        "by_model": price_by_model(totals, rates),
        "models": totals["models"],
        "first_turn": totals["first_ts"],
        "last_turn": totals["last_ts"],
    }


def _print_section(title: str, data: dict) -> None:
    tokens = data["tokens"]
    costs = data["usd"]
    print(f"  {title}  ターン {data['turns']}")
    print(f"    入力(非キャッシュ) {tokens['input']:>10,}")
    print(f"    キャッシュ書き 1h  {tokens['cache_write_1h']:>10,}   5m {tokens['cache_write_5m']:,}")
    print(f"    キャッシュ読み     {tokens['cache_read']:>10,}")
    print(f"    出力               {tokens['output']:>10,}   (うち思考 {tokens['thinking']:,})")
    print(f"    素の合計           {tokens['billed_total']:>10,} トークン")
    print(f"    費用               ${costs['total']:.4f}"
          f"  (読み ${costs['cache_read']:.4f} / 書き ${costs['cache_write_1h']+costs['cache_write_5m']:.4f}"
          f" / 出力 ${costs['output']:.4f} / 入力 ${costs['input']:.4f})")
    breakdown = data.get("by_model") or {}
    if breakdown:
        print("    モデル別内訳")
        for model, entry in breakdown.items():
            print(f"      {model:<22} ターン {entry['turns']:>3}   ${entry['usd']:.4f}")


def _list_subagents(parent: Path, since, until, rates: dict, args) -> int:
    """窓に入るサブエージェント記録の一覧を出す。0 ターンの記録は出さない。"""
    rows = []
    for child in subagent_transcripts(parent):
        totals = collect([child], since, until)
        if not totals["turns"]:
            continue
        rows.append(
            {
                "file": child.name,
                "agent_id": child.stem,
                "turns": totals["turns"],
                "models": sorted(totals["models"]),
                "usd": price(totals, rates)["total"],
                "billed_tokens": billed_tokens(totals),
                "first_turn": totals["first_ts"],
                "last_turn": totals["last_ts"],
            }
        )
    rows.sort(key=lambda row: -row["usd"])
    if args.json:
        print(json.dumps(
            {
                "label": args.label,
                "transcript": str(parent),
                "window": {"since": args.since, "until": args.until},
                "subagents": rows,
                "total_usd": round(sum(row["usd"] for row in rows), 6),
            },
            ensure_ascii=False,
        ))
        return 0
    print(f"[{args.label or '区間'}] 記録 {parent.name} のサブエージェント {len(rows)} 件"
          f"（窓に 1 ターンも無い記録は出さない）")
    for row in rows:
        print(f"  {row['file']:<30} ターン {row['turns']:>3}"
              f"  モデル {','.join(row['models']):<22} ${row['usd']:.4f}")
    print(f"  合計 ${sum(row['usd'] for row in rows):.4f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mark", help="今の UTC 時刻を印として出す")
    summary = sub.add_parser("sum", help="期間内の実トークンを合計する")
    summary.add_argument("--since", default=None)
    summary.add_argument(
        "--last-minutes",
        type=float,
        default=None,
        help="--since の代わりに直近 N 分を窓にする（両方あれば --since を優先する）",
    )
    summary.add_argument("--until", default=None)
    summary.add_argument("--session", default=None, help="測る対象の session-id")
    summary.add_argument("--transcript", type=Path, default=None)
    summary.add_argument("--parent-only", action="store_true", help="サブエージェントの記録を合算しない")
    summary.add_argument(
        "--subagent",
        default=None,
        help="サブエージェント記録 1 本だけを測る（agent-<id>。--session と併用）",
    )
    summary.add_argument(
        "--list-subagents",
        action="store_true",
        help="窓に入るサブエージェント記録の一覧を出す（ファイル名・ターン数・モデル・費用）",
    )
    summary.add_argument("--rates", type=Path, default=Path(__file__).parent / "rates.json")
    summary.add_argument("--label", default="")
    summary.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "mark":
        print(datetime.now(timezone.utc).isoformat())
        return 0

    path = find_transcript(args.transcript, args.session)
    rates = load_rates(args.rates)
    if args.since:
        since = parse_time(args.since)
    elif args.last_minutes is not None:
        since = datetime.now(timezone.utc) - timedelta(minutes=args.last_minutes)
    else:
        raise SystemExit("--since か --last-minutes のどちらかを指定してください。")
    args.since = since.isoformat()  # --last-minutes で決めた実際の窓を JSON・一覧の出力へ反映する
    until = parse_time(args.until) if args.until else None

    if args.list_subagents:
        return _list_subagents(path, since, until, rates, args)

    if args.subagent:
        if args.parent_only:
            raise SystemExit("--subagent と --parent-only は同時に使えません。")
        # 1 本だけを測る。親は対象外なので親の記録は読まない。
        parents: list[Path] = []
        children = [subagent_transcript(path, args.subagent)]
    else:
        parents = [path]
        children = [] if args.parent_only else subagent_transcripts(path)

    parent_totals = collect(parents, since, until)
    child_totals = collect(children, since, until)
    all_totals = collect([*parents, *children], since, until)

    parent = section(parent_totals, rates)
    subagents = section(child_totals, rates)
    total = section(all_totals, rates)

    payload = {
        "label": args.label,
        "transcript": str(path),
        "subagent_transcripts": [str(child) for child in children],
        "window": {
            "since": args.since,
            "until": args.until,
            "first_turn": total["first_turn"],
            "last_turn": total["last_turn"],
        },
        "parent": parent,
        "subagents": subagents,
        "total": total,
        # 後方互換: 以前の版は合計を最上位に置いていた。
        "turns": total["turns"],
        "tokens": total["tokens"],
        "usd": total["usd"],
        "models": total["models"],
        "by_model": total["by_model"],
        "rates": {
            model: {key: rates["models"][model][key] for key in RATE_KEYS}
            for model in sorted(total["models"])
            if model in rates["models"]
        },
        "rates_path": rates.get("path"),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.subagent:
        note = f"（--subagent {children[0].stem} のみ。親は対象外）"
    elif args.parent_only:
        note = "（--parent-only のため合算しない）"
    else:
        note = ""
    print(f"[{args.label or '区間'}] 記録 {path.name}"
          f"  サブエージェント記録 {len(children)} 件{note}")
    _print_section("親        ", parent)
    _print_section("サブエージェント", subagents)
    _print_section("合計      ", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
