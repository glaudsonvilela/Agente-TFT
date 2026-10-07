from __future__ import annotations

from trainer.scripts.manage_shadow_promotion import gate


def _row(session: str, *, gold=2, cand=2, champ=1, accepted=1, wrong=0):
    return {
        "evaluation_session": session,
        "gold_anchors": gold,
        "candidate_correct": cand,
        "champion_correct": champ,
        "candidate_wrong_accepted": wrong,
        "candidate_accepted_correct": accepted,
        "candidate_not_worse": cand >= champ,
    }


def test_shadow_promotion_requires_useful_independent_accepts():
    meta = {"evaluations": [
        _row("a"),
        _row("b"),
        _row("c"),
    ]}
    assert gate(meta) is True

    no_runtime_accepts = {"evaluations": [
        _row("a", accepted=0),
        _row("b", accepted=0),
        _row("c", accepted=0),
    ]}
    assert gate(no_runtime_accepts) is False

    one_session_abstains = {"evaluations": [
        _row("a", accepted=1),
        _row("b", accepted=0),
        _row("c", accepted=2),
    ]}
    assert gate(one_session_abstains) is False


def test_shadow_promotion_rejects_regression_or_wrong_accept():
    regressed = {"evaluations": [
        _row("a"),
        _row("b", cand=0, champ=1, accepted=1),
        _row("c"),
    ]}
    assert gate(regressed) is False

    wrong = {"evaluations": [
        _row("a"),
        _row("b", wrong=1),
        _row("c"),
    ]}
    assert gate(wrong) is False


def test_shadow_promotion_requires_three_sessions_and_six_gold():
    too_few_sessions = {"evaluations": [
        _row("a", gold=3, accepted=2),
        _row("b", gold=3, accepted=2),
    ]}
    assert gate(too_few_sessions) is False

    too_few_gold = {"evaluations": [
        _row("a", gold=1),
        _row("b", gold=1),
        _row("c", gold=1),
    ]}
    assert gate(too_few_gold) is False
