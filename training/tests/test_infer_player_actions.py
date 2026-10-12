from training.infer_player_actions import infer_transition, stage_action_history


SHA = "a" * 64


def state(ms, *, gold=40, xp=8, shop=None, bench=None, board=None):
    return {"match_id": "one-match", "video_sha256": SHA, "player_id": "setsuko",
            "source_ms": ms, "scene": "planning", "stage": "3-2",
            "gold": gold, "xp": xp, "xp_cap": 20, "level": 5,
            "shop": shop if shop is not None else ["A", "B", "C", "D", "E"],
            "bench_unit_ids": bench if bench is not None else [],
            "board_positions": board if board is not None else {"u1": [2, 2]},
            "inventory_item_ids": [], "equipped_items": {"u1": []},
            "active_augment_ids": [], "augment_offer_ids": []}


def test_xp_action_records_stage_and_motor1_context():
    before = state(1000)
    after = state(1200, gold=36, xp=12)
    actions = infer_transition(before, after)
    assert [(row.kind, row.target) for row in actions] == [("buy_xp", {"count": 1})]
    motor2 = [{"match_id": "one-match", "source_ms": 900, "frame_id": 7,
               "candidates": [{"action": {"type": "buy_xp"},
                               "decision_key": "xp-at-3-2"}]}]
    history = stage_action_history([before, after], motor2)
    assert history[0]["stage"] == "3-2"
    assert history[0]["motor1_before"]["gold"] == 40
    assert history[0]["motor2_decision_key"] == "xp-at-3-2"
    assert history[0]["training_eligible"] is False  # Target still needs review.


def test_reroll_needs_shop_change_and_retains_unmatched_action():
    before = state(1000)
    after = state(1200, gold=38, shop=["F", "G", "H", "I", "J"])
    assert [row.kind for row in infer_transition(before, after)] == ["reroll"]
    history = stage_action_history([before, after], [])
    assert history[0]["action_kind"] == "reroll"
    assert history[0]["motor2_status"] == "motor2_state_missing"


def test_moving_same_unit_preserves_identity():
    before = state(1000)
    after = state(1200, board={"u1": [3, 3]})
    assert infer_transition(before, after)[0].target == {
        "unit_track_id": "u1", "from": [2, 2], "to": [3, 3]}


def test_camera_or_stage_change_never_becomes_action():
    before = state(1000)
    after = {**state(1200), "stage": "3-3"}
    assert infer_transition(before, after)[0].kind == "unresolved"


def test_multiple_explanations_do_not_become_false_training_label():
    before = state(1000)
    after = state(1200, gold=36, xp=12, board={"u1": [3, 3]})
    assert [row.kind for row in infer_transition(before, after)] == ["unresolved"]
