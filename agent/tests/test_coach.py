from __future__ import annotations

from pydantic_ai.models.test import TestModel

from core.coach import (
    CoachDeps,
    CoachExplanation,
    DecisionPacket,
    assemble_recommendation,
    coach_agent,
)
from schemas.contracts import (
    GameState,
    HoldEconAction,
    MatchPhase,
    PlayerState,
    RollAction,
)


def make_state() -> GameState:
    return GameState(
        revision=7,
        phase=MatchPhase.PLANNING,
        observed_at_ms=1000,
        player=PlayerState(),
        overall_confidence=0.95,
    )


def make_deps() -> CoachDeps:
    return CoachDeps(
        state=make_state(),
        decision=DecisionPacket(
            state_revision=7,
            action=RollAction(
                budget_gold=20,
                stop_condition="X reaches 2 stars",
            ),
            confidence=0.84,
            alternatives=(),
            evidence=(),
        ),
        economy_analysis={"gold": 46, "risk": "high"},
        board_analysis={"relative_strength": 0.58},
        knowledge_context={"patch": "fixture"},
    )


def test_assemble_recommendation_preserves_canonical_decision():
    deps = make_deps()

    recommendation = assemble_recommendation(
        deps.decision,
        CoachExplanation(
            reason_short="Player 2 started contesting X; waiting reduces availability.",
            next_step="Stop when X reaches 2 stars.",
        ),
        generated_at_ms=1200,
        recommendation_id="rec-1",
    )

    assert recommendation.action == deps.decision.action
    assert recommendation.confidence == deps.decision.confidence
    assert recommendation.state_revision == 7


def test_llm_cannot_change_action_because_explanation_has_no_action_field():
    explanation = CoachExplanation(
        reason_short="Preserve economy this round.",
        next_step=None,
    )
    assert not hasattr(explanation, "action")


def test_agent_registers_only_context_tools_and_structured_explanation_output():
    test_model = TestModel()
    result = coach_agent.run_sync(
        "Explique a decisão canônica.",
        model=test_model,
        deps=make_deps(),
    )

    assert isinstance(result.output, CoachExplanation)
    params = test_model.last_model_request_parameters
    assert params is not None

    tool_names = {tool.name for tool in params.function_tools}
    assert tool_names == {
        "get_game_state",
        "get_decision_packet",
        "get_economy_analysis",
        "get_board_analysis",
        "get_knowledge_context",
    }


def test_decision_packet_can_represent_non_roll_actions():
    packet = DecisionPacket(
        state_revision=3,
        action=HoldEconAction(),
        confidence=0.77,
    )
    assert packet.action.type == "hold_econ"
