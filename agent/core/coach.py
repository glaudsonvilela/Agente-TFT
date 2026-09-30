from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, RunContext

from schemas.contracts import (
    Action,
    AlternativeAction,
    Evidence,
    GameState,
    Recommendation,
)


class DecisionPacket(BaseModel):
    """Canonical decision produced by math/policy before the LLM is invoked."""

    state_revision: int = Field(ge=0)
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: tuple[AlternativeAction, ...] = ()
    evidence: tuple[Evidence, ...] = ()


class CoachExplanation(BaseModel):
    """Language-only output. It cannot change action, scores or confidence."""

    reason_short: str
    next_step: str | None = None

    @field_validator("reason_short")
    @classmethod
    def validate_reason_short(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 160:
            raise ValueError("reason_short must be non-empty and <= 160 characters")
        return value

    @field_validator("next_step")
    @classmethod
    def validate_next_step(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 160:
            raise ValueError("next_step must be <= 160 characters")
        return value or None


@dataclass(frozen=True)
class CoachDeps:
    state: GameState
    decision: DecisionPacket
    economy_analysis: dict[str, Any]
    board_analysis: dict[str, Any]
    knowledge_context: dict[str, Any]


coach_agent = Agent(
    deps_type=CoachDeps,
    output_type=CoachExplanation,
    instructions=(
        "Você é a camada de explicação do Agente TFT. "
        "A ação e a confiança já foram escolhidas por código/modelos externos. "
        "Não escolha outra ação, não invente probabilidades e não altere a confiança. "
        "Use as ferramentas apenas para entender o contexto. "
        "Responda em português do Brasil, direto, sem introduções. "
        "reason_short deve explicar o motivo em uma frase curta. "
        "next_step deve dizer a condição de parada ou o próximo passo, quando houver."
    ),
)


@coach_agent.tool
def get_game_state(ctx: RunContext[CoachDeps]) -> dict[str, Any]:
    """Return the canonical current TFT GameState."""
    return ctx.deps.state.model_dump(mode="json", by_alias=True)


@coach_agent.tool
def get_decision_packet(ctx: RunContext[CoachDeps]) -> dict[str, Any]:
    """Return the canonical action, confidence, alternatives and evidence."""
    return ctx.deps.decision.model_dump(mode="json", by_alias=True)


@coach_agent.tool
def get_economy_analysis(ctx: RunContext[CoachDeps]) -> dict[str, Any]:
    """Return deterministic economy analysis for the current state."""
    return ctx.deps.economy_analysis


@coach_agent.tool
def get_board_analysis(ctx: RunContext[CoachDeps]) -> dict[str, Any]:
    """Return deterministic board and lobby analysis for the current state."""
    return ctx.deps.board_analysis


@coach_agent.tool
def get_knowledge_context(ctx: RunContext[CoachDeps]) -> dict[str, Any]:
    """Return local patch-aware knowledge selected for this decision."""
    return ctx.deps.knowledge_context


def assemble_recommendation(
    decision: DecisionPacket,
    explanation: CoachExplanation,
    *,
    generated_at_ms: int,
    recommendation_id: str | None = None,
) -> Recommendation:
    """
    Build the final Recommendation.

    Action, confidence, alternatives and evidence come only from DecisionPacket.
    The LLM contributes only reason_short / next_step.
    """
    return Recommendation(
        recommendation_id=recommendation_id or str(uuid4()),
        state_revision=decision.state_revision,
        generated_at_ms=generated_at_ms,
        action=decision.action,
        reason_short=explanation.reason_short,
        next_step=explanation.next_step,
        confidence=decision.confidence,
        alternatives=decision.alternatives,
        evidence=decision.evidence,
    )
