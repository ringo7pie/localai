"""bench/measure_cloud_tokens.py の単体試験。実際のセッション記録は読まない。

実行: .venv/bin/python -m pytest tests/test_measure.py -q
"""

from __future__ import annotations

import json
import sys
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

import measure_cloud_tokens as measure  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"


def _usage(output: int) -> dict:
    return {
        "input_tokens": 1,
        "cache_read_input_tokens": 100,
        "output_tokens": output,
        "output_tokens_details": {"thinking_tokens": 0},
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 10},
    }


def _line(
    message_id: str,
    timestamp: str,
    output: int,
    request_id: str | None = None,
    model: str = "claude-opus-5",
) -> str:
    entry = {
        "type": "assistant",
        "timestamp": timestamp,
        "requestId": request_id or f"req-{message_id}",
        "uuid": f"{message_id}-{timestamp}",
        "message": {"id": message_id, "model": model, "usage": _usage(output)},
    }
    return json.dumps(entry, ensure_ascii=False) + "\n"


RATES_PATH = Path(__file__).resolve().parents[1] / "bench" / "rates.json"
RATES = measure.load_rates(RATES_PATH)
WHOLE_DAY = ("--since", "2026-09-21T00:00:00Z", "--until", "2026-09-21T02:00:00Z")


def _collect_one(path: Path) -> dict:
    return measure.collect(
        [path],
        measure.parse_time("2026-09-21T00:00:00Z"),
        measure.parse_time("2026-09-21T02:00:00Z"),
    )


def _make_projects(root: Path) -> Path:
    """擬似的な ~/.claude/projects を作り、親記録のパスを返す。

    親は 3 行（同じ message.id の重複 2 行 + 別の 1 行）。うち 1 行は時間窓の外。
    サブエージェントは 2 行で、片方が窓の外。
    """
    project = root / "projects" / "-home-mt-Proj-localai"
    project.mkdir(parents=True)
    parent = project / f"{SESSION}.jsonl"
    parent.write_text(
        _line("msg_a", "2026-09-21T01:00:00.000Z", 500)
        + _line("msg_a", "2026-09-21T01:00:02.000Z", 500)  # 同一メッセージの続き（重複）
        + _line("msg_b", "2026-09-21T09:00:00.000Z", 700),  # 窓の外
        encoding="utf-8",
    )
    subagents = project / SESSION / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-x.jsonl").write_text(
        _line("msg_s1", "2026-09-21T01:00:30.000Z", 40)
        + _line("msg_s2", "2026-09-21T23:00:00.000Z", 40),  # 窓の外
        encoding="utf-8",
    )
    return parent


# --- (a) 重複計上をしない -------------------------------------------------
def test_duplicate_message_ids_are_counted_once(tmp_path):
    parent = _make_projects(tmp_path)
    totals = measure.collect(
        [parent],
        measure.parse_time("2026-09-21T00:00:00Z"),
        measure.parse_time("2026-09-21T02:00:00Z"),
    )
    assert totals["turns"] == 1
    assert totals["output_tokens"] == 500  # 2 回足されていない
    assert totals["duplicate_lines"] == 1


def test_window_uses_first_line_of_a_message(tmp_path):
    # 重複行の時刻でなく、最初に書かれた行の時刻で窓を判定する。
    parent = _make_projects(tmp_path)
    totals = measure.collect(
        [parent],
        measure.parse_time("2026-09-21T01:00:01Z"),
        measure.parse_time("2026-09-21T02:00:00Z"),
    )
    assert totals["turns"] == 0


# --- (b) 記録ファイルの選び方 ---------------------------------------------
def test_session_id_selects_the_matching_transcript(tmp_path):
    parent = _make_projects(tmp_path)
    # 別プロジェクトに、より新しい無関係な記録があっても選ばれない。
    other = tmp_path / "projects" / "-home-mt-Proj-other"
    other.mkdir(parents=True)
    (other / "99999999-0000-0000-0000-000000000000.jsonl").write_text(
        _line("msg_z", "2026-09-21T12:00:00.000Z", 9999), encoding="utf-8"
    )
    found = measure.find_transcript(None, SESSION, root=tmp_path / "projects", env={})
    assert found == parent


def test_without_session_or_env_it_stops_with_an_error(tmp_path):
    _make_projects(tmp_path)
    with pytest.raises(SystemExit) as raised:
        measure.find_transcript(None, None, root=tmp_path / "projects", env={})
    assert "--session" in str(raised.value)


def test_env_session_id_is_used_when_no_argument(tmp_path):
    parent = _make_projects(tmp_path)
    found = measure.find_transcript(
        None, None, root=tmp_path / "projects", env={"CLAUDE_SESSION_ID": SESSION}
    )
    assert found == parent


def test_claude_code_session_id_env_var_is_used_and_takes_priority(tmp_path):
    # CLAUDE_CODE_SESSION_ID が第一候補。旧 CLAUDE_SESSION_ID に別の値が
    # 入っていても、CLAUDE_CODE_SESSION_ID の方が優先される。
    parent = _make_projects(tmp_path)
    found = measure.find_transcript(
        None,
        None,
        root=tmp_path / "projects",
        env={"CLAUDE_CODE_SESSION_ID": SESSION, "CLAUDE_SESSION_ID": "no-such-session"},
    )
    assert found == parent


def test_unknown_session_is_an_error(tmp_path):
    _make_projects(tmp_path)
    with pytest.raises(SystemExit):
        measure.find_transcript(None, "no-such-session", root=tmp_path / "projects", env={})


# --- (c) サブエージェント分 -----------------------------------------------
def test_subagent_transcripts_are_found(tmp_path):
    parent = _make_projects(tmp_path)
    children = measure.subagent_transcripts(parent)
    assert [child.name for child in children] == ["agent-x.jsonl"]


def test_summary_splits_parent_subagents_and_total(tmp_path, capsys, monkeypatch):
    parent = _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    code = measure.main(
        [
            "sum",
            "--session",
            SESSION,
            "--since",
            "2026-09-21T00:00:00Z",
            "--until",
            "2026-09-21T02:00:00Z",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parent"]["turns"] == 1
    assert payload["subagents"]["turns"] == 1  # 窓の外の 1 行は落ちる
    assert payload["total"]["turns"] == 2
    assert payload["parent"]["tokens"]["output"] == 500
    assert payload["subagents"]["tokens"]["output"] == 40
    assert payload["total"]["tokens"]["output"] == 540
    assert payload["transcript"] == str(parent)
    assert len(payload["subagent_transcripts"]) == 1


def test_parent_only_drops_subagents(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(
        [
            "sum",
            "--session",
            SESSION,
            "--since",
            "2026-09-21T00:00:00Z",
            "--until",
            "2026-09-21T02:00:00Z",
            "--parent-only",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["subagent_transcripts"] == []
    assert payload["subagents"]["turns"] == 0
    assert payload["total"]["turns"] == 1


def test_text_output_has_three_blocks(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(
        ["sum", "--session", SESSION, "--since", "2026-09-21T00:00:00Z", "--label", "試験"]
    )
    out = capsys.readouterr().out
    assert "親" in out and "サブエージェント" in out and "合計" in out
    assert "試験" in out


# --- (d) モデル別の単価 ---------------------------------------------------
def test_rates_file_has_a_per_model_table():
    assert RATES_PATH.is_file()
    assert "claude-opus-5" in RATES["models"]
    fable = RATES["models"]["claude-fable-5-1"]
    assert fable["input_per_mtok"] == 10.0
    assert fable["output_per_mtok"] == 50.0
    assert fable["cache_read_multiplier"] == 0.025  # Opus の 0.1x ではない


def test_fable_messages_are_priced_with_fable_rates(tmp_path):
    path = tmp_path / "fable.jsonl"
    path.write_text(
        _line("msg_f", "2026-09-21T01:00:00.000Z", 1000, model="claude-fable-5-1"),
        encoding="utf-8",
    )
    totals = _collect_one(path)
    costs = measure.price(totals, RATES)
    # 入力 1×$10/MTok + キャッシュ読み 100×$10/MTok×0.025 + 1h 書き 10×$10/MTok×2
    # + 出力 1000×$50/MTok
    assert costs["output"] == pytest.approx(0.05)
    assert costs["cache_read"] == pytest.approx(0.000025)
    assert costs["cache_write_1h"] == pytest.approx(0.0002)
    assert costs["total"] == pytest.approx(0.050235)


def test_the_same_message_on_opus_costs_half_the_output(tmp_path):
    path = tmp_path / "opus.jsonl"
    path.write_text(_line("msg_o", "2026-09-21T01:00:00.000Z", 1000), encoding="utf-8")
    costs = measure.price(_collect_one(path), RATES)
    assert costs["output"] == pytest.approx(0.025)
    assert costs["total"] == pytest.approx(0.025155)


def test_mixed_models_are_priced_separately(tmp_path):
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        _line("msg_f", "2026-09-21T01:00:00.000Z", 1000, model="claude-fable-5-1")
        + _line("msg_o", "2026-09-21T01:00:10.000Z", 1000),
        encoding="utf-8",
    )
    totals = _collect_one(path)
    breakdown = measure.price_by_model(totals, RATES)
    assert set(breakdown) == {"claude-fable-5-1", "claude-opus-5"}
    assert breakdown["claude-fable-5-1"]["usd"] == pytest.approx(0.050235)
    assert breakdown["claude-opus-5"]["usd"] == pytest.approx(0.025155)
    assert measure.price(totals, RATES)["total"] == pytest.approx(0.050235 + 0.025155)


def test_unknown_model_stops_with_an_error_naming_it(tmp_path):
    path = tmp_path / "unknown.jsonl"
    path.write_text(
        _line("msg_u", "2026-09-21T01:00:00.000Z", 10, model="claude-nonesuch-9"),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as raised:
        measure.price(_collect_one(path), RATES)
    assert "claude-nonesuch-9" in str(raised.value)


def test_rate_table_without_models_is_rejected(tmp_path):
    broken = tmp_path / "rates.json"
    broken.write_text(json.dumps({"input_per_mtok": 5.0}), encoding="utf-8")
    with pytest.raises(SystemExit):
        measure.load_rates(broken)


def test_model_breakdown_is_in_the_text_output(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(["sum", "--session", SESSION, *WHOLE_DAY])
    out = capsys.readouterr().out
    assert "モデル別内訳" in out
    assert "claude-opus-5" in out


def test_json_output_has_by_model(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(["sum", "--session", SESSION, *WHOLE_DAY, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["by_model"]["claude-opus-5"]["turns"] == 2
    assert payload["parent"]["by_model"]["claude-opus-5"]["turns"] == 1
    assert payload["rates"]["claude-opus-5"]["input_per_mtok"] == 5.0


# --- (e) サブエージェント 1 本だけを測る ---------------------------------
def test_subagent_option_measures_only_that_record(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(["sum", "--session", SESSION, *WHOLE_DAY, "--subagent", "agent-x", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["parent"]["turns"] == 0  # 親は対象外
    assert payload["subagents"]["turns"] == 1
    assert payload["total"]["turns"] == 1
    assert payload["total"]["tokens"]["output"] == 40
    assert [Path(p).name for p in payload["subagent_transcripts"]] == ["agent-x.jsonl"]


def test_subagent_id_may_omit_the_prefix(tmp_path):
    parent = _make_projects(tmp_path)
    for spelling in ("agent-x", "x", "agent-x.jsonl"):
        assert measure.subagent_transcript(parent, spelling).name == "agent-x.jsonl"


def test_unknown_subagent_is_an_error(tmp_path):
    parent = _make_projects(tmp_path)
    with pytest.raises(SystemExit) as raised:
        measure.subagent_transcript(parent, "agent-nope")
    assert "agent-nope" in str(raised.value)


def test_subagent_with_parent_only_is_rejected(tmp_path, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    with pytest.raises(SystemExit):
        measure.main(
            ["sum", "--session", SESSION, *WHOLE_DAY, "--subagent", "agent-x", "--parent-only"]
        )


# --- (f) サブエージェント一覧 --------------------------------------------
def test_list_subagents_text_output(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    code = measure.main(["sum", "--session", SESSION, *WHOLE_DAY, "--list-subagents"])
    assert code == 0
    out = capsys.readouterr().out
    assert "agent-x.jsonl" in out
    assert "ターン" in out and "claude-opus-5" in out and "$" in out


def test_list_subagents_json_output(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(["sum", "--session", SESSION, *WHOLE_DAY, "--list-subagents", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["subagents"]) == 1
    row = payload["subagents"][0]
    assert row["file"] == "agent-x.jsonl"
    assert row["turns"] == 1  # 窓の外の 1 行は数えない
    assert row["models"] == ["claude-opus-5"]
    assert row["usd"] > 0


def test_last_minutes_cuts_the_window(tmp_path, capsys, monkeypatch):
    # --since の代わりに --last-minutes を使うと、「今」から N 分前より前の
    # ターンは窓の外になる。「今」は固定した時刻に差し替えて測る。
    project = tmp_path / "projects" / "-home-mt-Proj-lastmin"
    project.mkdir(parents=True)
    session = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    parent = project / f"{session}.jsonl"
    parent.write_text(
        _line("msg_old", "2026-09-21T00:00:00.000Z", 10)  # 90 分前（窓の外）
        + _line("msg_new", "2026-09-21T01:20:00.000Z", 20),  # 10 分前（窓の中）
        encoding="utf-8",
    )
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")

    class _FrozenNow(measure.datetime):
        @classmethod
        def now(cls, tz=None):
            base = _datetime(2026, 9, 21, 1, 30, 0, tzinfo=_timezone.utc)
            return base.astimezone(tz) if tz else base

    monkeypatch.setattr(measure, "datetime", _FrozenNow)

    code = measure.main(
        ["sum", "--session", session, "--last-minutes", "30", "--parent-only", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parent"]["turns"] == 1
    assert payload["parent"]["tokens"]["output"] == 20  # msg_old(90 分前)は入らない
    assert payload["window"]["since"].startswith("2026-09-21T01:00:00")


def test_list_subagents_skips_records_with_no_turn_in_the_window(tmp_path, capsys, monkeypatch):
    _make_projects(tmp_path)
    monkeypatch.setattr(measure, "projects_root", lambda: tmp_path / "projects")
    measure.main(
        [
            "sum",
            "--session",
            SESSION,
            "--since",
            "2026-09-21T03:00:00Z",
            "--until",
            "2026-09-21T04:00:00Z",
            "--list-subagents",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["subagents"] == []
