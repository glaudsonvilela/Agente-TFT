from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, RunContext

from schemas.contracts import (
    DecisionPacket,
    GameState,
    Recommendation,
)


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
    opportunity_report: dict[str, Any]


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


@coach_agent.tool
def get_opportunity_report(ctx: RunContext[CoachDeps]) -> dict[str, Any]:
    """Return the Rust Opportunity Engine report: all candidates and shortlist."""
    return ctx.deps.opportunity_report


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



def _trim(text: str, limit: int = 160) -> str:
    text = " ".join(text.split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def fallback_explanation(decision: DecisionPacket) -> CoachExplanation:
    """
    Deterministic low-latency explanation used when the language model is
    unavailable or exceeds its latency budget.

    It never changes the action or confidence.
    """
    action = decision.action
    action_type = action.type

    reason_by_action = {
        "buy": "Comprar agora foi a ação com maior utilidade entre as alternativas avaliadas.",
        "skip_buy": "Não comprar agora preserva mais valor que ocupar esse slot.",
        "sell": "Vender agora foi a ação com maior utilidade no estado atual.",
        "roll": "Rolar agora teve maior utilidade que segurar ouro ou subir de nível.",
        "level": "Subir de nível agora teve maior utilidade que continuar no nível atual.",
        "hold_econ": "Preservar economia teve maior utilidade que gastar ouro agora.",
        "equip_item": "Equipar o item agora teve maior utilidade que continuar segurando o componente.",
        "choose_augment": "Esse augment teve maior utilidade entre as opções avaliadas.",
        "pivot": "A transição completa teve maior utilidade que manter a linha atual.",
        "partial_pivot": "A transição parcial teve maior utilidade sem abandonar todo o board.",
        "position": "Esse reposicionamento teve maior utilidade para o confronto avaliado.",
        "scout": "Observar esse jogador reduz a principal incerteza antes da próxima decisão.",
        "wait": "Nenhuma ação atingiu confiança suficiente para recomendar uma mudança agora.",
    }

    reason = reason_by_action.get(
        action_type,
        "Essa foi a ação com maior utilidade entre as alternativas avaliadas.",
    )

    # Deterministic evidence can make the fallback more specific without
    # allowing the language layer to invent facts.
    useful_evidence = [
        evidence.detail.strip()
        for evidence in decision.evidence
        if evidence.detail.strip()
        and evidence.code not in {"CLOSE_ALTERNATIVE", "NO_CONFIDENT_CANDIDATE"}
    ]
    if useful_evidence:
        reason = useful_evidence[0]

    next_step: str | None = None
    if action_type == "roll":
        next_step = getattr(action, "stop_condition", None) or "Reavalie após o roll."
    elif action_type == "level":
        next_step = f"Reavalie o board ao chegar no nível {action.target_level}."
    elif action_type == "scout":
        next_step = "Reavalie depois de atualizar o board desse jogador."
    elif action_type == "wait":
        next_step = "Espere uma mudança relevante de estado."

    return CoachExplanation(
        reason_short=_trim(reason),
        next_step=_trim(next_step) if next_step else None,
    )


def assemble_fallback_recommendation(
    decision: DecisionPacket,
    *,
    generated_at_ms: int,
    recommendation_id: str | None = None,
) -> Recommendation:
    return assemble_recommendation(
        decision,
        fallback_explanation(decision),
        generated_at_ms=generated_at_ms,
        recommendation_id=recommendation_id,
    )
