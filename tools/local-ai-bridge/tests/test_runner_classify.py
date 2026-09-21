"""runner の結果分類（classify_outcome）の単体試験。モデルも git も使わない。

実行: .venv/bin/python -m pytest tests/test_runner_classify.py -q

実測で見つかった欠陥の再現を含む: 基準コミットで 3 件落ちていた検証が、変更後も
同じ 3 件落ちている（何も直っていない）状態を、以前は awaiting_approval にして
「実装は完了」と要約していた。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.runner import classify_outcome  # noqa: E402

BASELINE3 = {"test_round_yen_half_up", "test_round_yen_bankers", "test_round_yen_zero"}


def _call(verify_passed, new_failures, unfixed, baseline, *, changes_empty=False, no_verify=False):
    return classify_outcome(
        verify_passed, new_failures, unfixed, baseline, changes_empty, no_verify
    )


# --- F4 の形: 基準 3 件 → 変更後も同じ 3 件 -------------------------------
def test_nothing_fixed_is_failed():
    state, headline = _call(False, set(), set(BASELINE3), BASELINE3)
    assert state == "failed"
    assert headline == "基準コミットで落ちていた検証が直っていない"
    assert "実装は完了" not in headline


# --- 一部だけ直った形 ------------------------------------------------------
def test_partially_fixed_is_awaiting_approval_with_unfixed_count():
    unfixed = {"test_round_yen_bankers"}
    state, headline = _call(False, set(), unfixed, BASELINE3)
    assert state == "awaiting_approval"
    assert "未修正" in headline
    assert "1 件" in headline
    assert "実装は完了" not in headline


def test_two_of_three_unfixed_reports_two():
    state, headline = _call(False, set(), set(list(BASELINE3)[:2]), BASELINE3)
    assert state == "awaiting_approval"
    assert "2 件が未修正" in headline


# --- 全部直った形 ----------------------------------------------------------
def test_all_fixed_keeps_the_old_pass_headline():
    state, headline = _call(True, set(), set(), BASELINE3)
    assert state == "awaiting_approval"
    assert headline == "実装と検証が完了。差分の適用には承認が必要"


# --- 新しく壊れたものがある形 ---------------------------------------------
def test_new_failure_is_failed():
    state, headline = _call(False, {"test_new_thing"}, set(BASELINE3), BASELINE3)
    assert state == "failed"
    assert headline == "検証が不合格のまま上限に達した"


def test_new_failure_with_clean_baseline_is_failed():
    state, headline = _call(False, {"test_new_thing"}, set(), set())
    assert state == "failed"
    assert headline == "検証が不合格のまま上限に達した"


# --- 従来どおりの分岐が変わっていないこと ---------------------------------
def test_empty_changes_is_failed():
    state, headline = _call(False, set(), set(), set(), changes_empty=True)
    assert (state, headline) == ("failed", "変更が生成されなかった")


def test_empty_changes_wins_over_a_passing_verification():
    state, _ = _call(True, set(), set(), set(), changes_empty=True)
    assert state == "failed"


def test_no_verify_profile_is_awaiting_approval():
    state, headline = _call(False, set(), set(), set(), no_verify=True)
    assert state == "awaiting_approval"
    assert "未登録" in headline


def test_unparsable_failure_names_fall_back_to_the_old_headline():
    # 失敗項目の名前が拾えない検証形式。直ったかどうか判断できないので従来どおり人へ回す。
    state, headline = _call(False, set(), set(), set())
    assert state == "failed"  # 基準が落ちていた情報が無ければ、このタスクの失敗
    state, headline = classify_outcome(
        False, set(), set(), set(), False, False, baseline_failed=True
    )
    assert state == "awaiting_approval"
    assert "基準コミットの時点で既に同じ失敗があった" in headline


def test_arguments_may_be_lists_or_none():
    state, _ = classify_outcome(False, [], list(BASELINE3), list(BASELINE3), False, False)
    assert state == "failed"
    state, _ = classify_outcome(True, None, None, None, False, False)
    assert state == "awaiting_approval"
