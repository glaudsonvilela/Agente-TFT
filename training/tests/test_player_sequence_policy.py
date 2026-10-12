import hashlib

import pytest
import torch

from training.player_sequence_policy import (
    SequencePolicy, align_video_actions, make_decisions, train_episode,
)


SHA = hashlib.sha256(b"intact match video").hexdigest()
NAMES = ["gold", "hp", "level", "phase_late", "action_buy_xp"]


def frame(at, number, gold, hp, *, options=("buy", "wait")):
    return {
        "kind": "motor2_player_observation", "match_id": "match-1",
        "source_video_sha256": SHA, "scene_status": "stable_planning",
        "frame_id": number, "source_ms": at, "feature_names": NAMES,
        "whole_state": {"gold": gold, "hp": hp},
        "selected_index": 1,  # A Rust preference must never be an expert label.
        "candidates": [
            {"decision_key": key, "features": [gold, hp, 6, 0, int(key == "buy")]}
            for key in options
        ],
    }


def label(at=1500, choice="buy"):
    return {"match_id": "match-1", "source_sha256": SHA,
            "action_ms": at, "chosen_decision_key": choice,
            "evidence_id": "verified-video-pair-1"}


def test_one_match_uses_video_action_and_causal_state():
    frames = [frame(1000, 1, 40, 90), frame(3000, 2, 36, 90),
              frame(61000, 3, 50, 82)]
    rows = make_decisions(frames, [label()])
    assert [row.chosen for row in rows] == [0, None, None]
    assert rows[0].future_hp_delta == -8
    assert rows[0].future_gold_delta == 10
    assert rows[-1].future_hp_delta is None
    assert rows[0].state == [40.0, 90.0, 6.0, 0.0]
    model = SequencePolicy(4, 5, hidden=8)
    metrics = train_episode(rows, model, torch.optim.Adam(model.parameters(), lr=0.001),
                            chunk_size=2)
    assert metrics["matched_video_actions"] == 1
    assert metrics["future_hud_targets"] == 2


def test_missing_candidate_fails_instead_of_relabeling():
    with pytest.raises(ValueError, match="absent"):
        make_decisions([frame(1000, 1, 40, 90, options=("wait", "roll"))], [label()])


def test_video_evidence_and_stable_planning_required():
    with pytest.raises(ValueError, match="evidence"):
        align_video_actions([frame(1000, 1, 40, 90)], [{**label(), "evidence_id": ""}])
    bad = frame(1000, 1, 40, 90)
    bad["scene_status"] = "combat"
    with pytest.raises(ValueError, match="verified planning"):
        align_video_actions([bad], [label()])


def test_action_cannot_use_future_observation_or_wrong_source():
    with pytest.raises(ValueError, match="causal"):
        align_video_actions([frame(2000, 1, 40, 90)], [label()])
    with pytest.raises(ValueError, match="source differ"):
        align_video_actions([frame(1000, 1, 40, 90)],
                            [{**label(), "source_sha256": "0" * 64}])


def test_no_label_does_not_train_from_rust_choice():
    rows = make_decisions([frame(1000, 1, 40, 90), frame(3000, 2, 40, 90)], [])
    model = SequencePolicy(4, 5, hidden=8)
    with pytest.raises(ValueError, match="not imitation"):
        train_episode(rows, model, torch.optim.Adam(model.parameters()), chunk_size=1)
