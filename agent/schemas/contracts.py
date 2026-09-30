from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "0.1.0"
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObservationSource(str, Enum):
    VISION = "vision"
    RIOT_API = "riot_api"
    KNOWLEDGE_PACK = "knowledge_pack"
    DERIVED = "derived"
    USER_OBSERVATION = "user_observation"
    SIMULATOR = "simulator"


class Observed(StrictModel):
    value: object
    confidence: Confidence
    source: ObservationSource
    observed_at_ms: int = Field(ge=0)


class HexPosition(StrictModel):
    row: int = Field(ge=0, le=255)
    col: int = Field(ge=0, le=255)


class MatchPhase(str, Enum):
    IDLE = "idle"
    MATCH_DETECTED = "match_detected"
    PLANNING = "planning"
    COMBAT = "combat"
    AUGMENT_SELECTION = "augment_selection"
    CAROUSEL_OR_SPECIAL = "carousel_or_special"
    POST_COMBAT = "post_combat"
    MATCH_ENDED = "match_ended"


class UnitInstance(StrictModel):
    instance_id: str
    unit_id: str
    stars: int = Field(ge=1, le=4)
    position: HexPosition | None = None
    items: tuple[str, ...] = ()


class ShopSlot(StrictModel):
    slot: int = Field(ge=0, le=8)
    unit_id: str | None = None


class PlayerState(StrictModel):
    hp: Observed | None = None
    gold: Observed | None = None
    level: Observed | None = None
    xp: Observed | None = None
    stage: Observed | None = None
    board: tuple[UnitInstance, ...] = ()
    bench: tuple[UnitInstance, ...] = ()
    shop: tuple[Observed, ...] = ()
    items: tuple[str, ...] = ()
    augments: tuple[str, ...] = ()
    augment_options: tuple[Observed, ...] = ()


class OpponentState(StrictModel):
    player_id: str
    display_name: str | None = None
    hp: Observed | None = None
    level: Observed | None = None
    board: tuple[UnitInstance, ...] = ()
    last_seen_ms: int = Field(ge=0)
    confidence: Confidence


class GameState(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    revision: int = Field(ge=0)
    match_id: str | None = None
    patch: str | None = None
    set: str | None = None
    phase: MatchPhase
    observed_at_ms: int = Field(ge=0)
    player: PlayerState
    lobby: tuple[OpponentState, ...] = ()
    overall_confidence: Confidence


class MatchStarted(StrictModel):
    type: Literal["match_started"] = "match_started"


class MatchEnded(StrictModel):
    type: Literal["match_ended"] = "match_ended"


class RoundChanged(StrictModel):
    type: Literal["round_changed"] = "round_changed"
    from_: str | None = Field(default=None, alias="from")
    to: str


class ShopChanged(StrictModel):
    type: Literal["shop_changed"] = "shop_changed"


class BoardChanged(StrictModel):
    type: Literal["board_changed"] = "board_changed"


class BenchChanged(StrictModel):
    type: Literal["bench_changed"] = "bench_changed"


class GoldChanged(StrictModel):
    type: Literal["gold_changed"] = "gold_changed"
    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)


class HpChanged(StrictModel):
    type: Literal["hp_changed"] = "hp_changed"
    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)


class LevelChanged(StrictModel):
    type: Literal["level_changed"] = "level_changed"
    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)


class ItemAdded(StrictModel):
    type: Literal["item_added"] = "item_added"
    item_id: str


class ItemEquipped(StrictModel):
    type: Literal["item_equipped"] = "item_equipped"
    item_id: str
    unit_instance_id: str


class AugmentScreen(StrictModel):
    type: Literal["augment_screen"] = "augment_screen"


class CombatStarted(StrictModel):
    type: Literal["combat_started"] = "combat_started"


class CombatEnded(StrictModel):
    type: Literal["combat_ended"] = "combat_ended"


class OpponentObserved(StrictModel):
    type: Literal["opponent_observed"] = "opponent_observed"
    player_id: str


class ContestationChanged(StrictModel):
    type: Literal["contestation_changed"] = "contestation_changed"
    unit_id: str
    observed_copies_before: int = Field(ge=0)
    observed_copies_after: int = Field(ge=0)


EventKind = Annotated[
    Union[
        MatchStarted,
        MatchEnded,
        RoundChanged,
        ShopChanged,
        BoardChanged,
        BenchChanged,
        GoldChanged,
        HpChanged,
        LevelChanged,
        ItemAdded,
        ItemEquipped,
        AugmentScreen,
        CombatStarted,
        CombatEnded,
        OpponentObserved,
        ContestationChanged,
    ],
    Field(discriminator="type"),
]


class GameEvent(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    event_id: str
    match_id: str | None = None
    state_revision: int = Field(ge=0)
    occurred_at_ms: int = Field(ge=0)
    kind: EventKind


class BuyAction(StrictModel):
    type: Literal["buy"] = "buy"
    shop_slot: int = Field(ge=0)
    unit_id: str


class SkipBuyAction(StrictModel):
    type: Literal["skip_buy"] = "skip_buy"
    shop_slot: int = Field(ge=0)


class SellAction(StrictModel):
    type: Literal["sell"] = "sell"
    unit_instance_id: str


class RollAction(StrictModel):
    type: Literal["roll"] = "roll"
    budget_gold: int = Field(ge=0)
    stop_condition: str | None = None


class LevelAction(StrictModel):
    type: Literal["level"] = "level"
    target_level: int = Field(ge=1, le=12)


class HoldEconAction(StrictModel):
    type: Literal["hold_econ"] = "hold_econ"


class EquipItemAction(StrictModel):
    type: Literal["equip_item"] = "equip_item"
    item_id: str
    unit_instance_id: str


class ChooseAugmentAction(StrictModel):
    type: Literal["choose_augment"] = "choose_augment"
    augment_id: str


class PivotAction(StrictModel):
    type: Literal["pivot"] = "pivot"
    target: str


class PartialPivotAction(StrictModel):
    type: Literal["partial_pivot"] = "partial_pivot"
    target: str


class PositionMove(StrictModel):
    unit_instance_id: str
    to: HexPosition


class PositionAction(StrictModel):
    type: Literal["position"] = "position"
    moves: tuple[PositionMove, ...]


class ScoutAction(StrictModel):
    type: Literal["scout"] = "scout"
    player_id: str


class WaitAction(StrictModel):
    type: Literal["wait"] = "wait"


Action = Annotated[
    Union[
        BuyAction,
        SkipBuyAction,
        SellAction,
        RollAction,
        LevelAction,
        HoldEconAction,
        EquipItemAction,
        ChooseAugmentAction,
        PivotAction,
        PartialPivotAction,
        PositionAction,
        ScoutAction,
        WaitAction,
    ],
    Field(discriminator="type"),
]


class AlternativeAction(StrictModel):
    action: Action
    score: float


class Evidence(StrictModel):
    code: str
    detail: str


class DecisionPacket(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    state_revision: int = Field(ge=0)
    action: Action
    confidence: Confidence
    alternatives: tuple[AlternativeAction, ...] = ()
    evidence: tuple[Evidence, ...] = ()


class Recommendation(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    recommendation_id: str
    state_revision: int = Field(ge=0)
    generated_at_ms: int = Field(ge=0)
    action: Action
    reason_short: str
    next_step: str | None = None
    confidence: Confidence
    alternatives: tuple[AlternativeAction, ...] = ()
    evidence: tuple[Evidence, ...] = ()

    @field_validator("reason_short")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip() or len(value) > 160:
            raise ValueError("reason_short must be non-empty and <= 160 characters")
        return value

    @field_validator("next_step")
    @classmethod
    def validate_next_step(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 160:
            raise ValueError("next_step must be <= 160 characters")
        return value
