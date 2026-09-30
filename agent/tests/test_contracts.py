import pytest
from pydantic import ValidationError

from schemas.contracts import GameEvent, Recommendation


def test_recommendation_contract_accepts_direct_action():
    rec = Recommendation.model_validate(
        {
            "recommendation_id": "rec-1",
            "state_revision": 9,
            "generated_at_ms": 1234,
            "action": {
                "type": "roll",
                "budget_gold": 20,
                "stop_condition": "X reaches 2 stars",
            },
            "reason_short": "Player 2 started contesting X; waiting reduces availability.",
            "next_step": "Stop when X reaches 2 stars.",
            "confidence": 0.84,
        }
    )
    assert rec.action.type == "roll"
    assert rec.confidence == 0.84


def test_recommendation_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        Recommendation.model_validate(
            {
                "recommendation_id": "rec-1",
                "state_revision": 9,
                "generated_at_ms": 1234,
                "action": {"type": "hold_econ"},
                "reason_short": "Hold economy.",
                "confidence": 1.2,
            }
        )


def test_event_uses_discriminator():
    event = GameEvent.model_validate(
        {
            "event_id": "evt-1",
            "state_revision": 10,
            "occurred_at_ms": 999,
            "kind": {"type": "gold_changed", "from": 50, "to": 48},
        }
    )
    assert event.kind.type == "gold_changed"
