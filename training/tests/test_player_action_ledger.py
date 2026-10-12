import pytest

from training.player_action_ledger import build_ledger


def change(number):
    return {"before_frame": f"frame-{number:06}.jpg",
            "after_frame": f"frame-{number + 1:06}.jpg",
            "region_change": {"gold": 0.1, "shop": 0.2}}


def test_ledger_keeps_unmapped_actions_and_ambiguous_changes():
    review = {"actions": [dict(before="frame-000001.jpg", after="frame-000002.jpg",
                               type="equip_item", item="Warmog")], "hard_cases": []}
    rows, report = build_ledger([change(2), change(1)], review,
                                match_id="match", source_sha256="a" * 64)
    assert [row["action_type"] for row in rows] == ["equip_item", None]
    assert rows[0]["motor2_equivalent_type"] is None
    assert rows[0]["training_eligible"] is False
    assert report["unreviewed_transitions"] == 1
    assert report["all_actual_player_actions_identified"] is False


def test_ledger_rejects_missing_transition_and_review():
    with pytest.raises(ValueError, match="gap"):
        build_ledger([change(1), change(3)], {"actions": [], "hard_cases": []},
                     match_id="match", source_sha256="a" * 64)
    with pytest.raises(ValueError, match="absent"):
        build_ledger([change(1)], {"actions": [dict(before="frame-000010.jpg",
                                                     after="frame-000011.jpg",
                                                     type="reroll")], "hard_cases": []},
                     match_id="match", source_sha256="a" * 64)
