from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingMode(str, Enum):
    REPLAY = "replay"
    SIMULATOR = "simulator"
    SELF_PLAY = "self_play"
    BOT_POOL = "bot_pool"


class TrainingJobStatus(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OpponentPoolConfig(StrictModel):
    scripted_bots: tuple[str, ...] = ()
    historical_policy_versions: tuple[str, ...] = ()
    include_current_policy: bool = True


class TrainingSessionRequest(StrictModel):
    client_id: str = Field(min_length=1, max_length=128)
    requested_at_ms: int = Field(ge=0)
    profile: str = Field(default="lab", min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingSession(StrictModel):
    session_id: str
    created_at_ms: int
    client_id: str
    profile: str
    active: bool = True


class TrainingJobRequest(StrictModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    session_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    created_at_ms: int = Field(ge=0)
    mode: TrainingMode
    state: dict[str, Any]
    decision: dict[str, Any]
    opportunities: tuple[dict[str, Any], ...] = ()
    rollout_count: int = Field(ge=1, le=4096)
    horizon_steps: int = Field(ge=1, le=10000)
    opponent_pool: OpponentPoolConfig = Field(default_factory=OpponentPoolConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision")
    @classmethod
    def decision_must_have_revision(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "state_revision" not in value:
            raise ValueError("decision.state_revision is required")
        return value

    def validate_revision_match(self) -> None:
        state_revision = self.state.get("revision")
        decision_revision = self.decision.get("state_revision")
        if state_revision != decision_revision:
            raise ValueError(
                f"state revision {state_revision!r} does not match "
                f"decision revision {decision_revision!r}"
            )


class ActionOutcome(StrictModel):
    action_index: int = Field(ge=0)
    placement_mean: float | None = None
    placement_p25: float | None = None
    placement_p75: float | None = None
    top4_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    first_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    hp_mean_after_horizon: float | None = None
    gold_mean_after_horizon: float | None = None
    reward_mean: float
    reward_stddev: float = Field(ge=0.0)
    samples: int = Field(ge=0)


class TrainingJobResult(StrictModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    session_id: str
    job_id: str
    episode_id: str
    status: TrainingJobStatus
    completed_at_ms: int = Field(ge=0)
    simulator_version: str
    policy_version: str
    outcomes: tuple[ActionOutcome, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TrainingJobRecord(StrictModel):
    request: TrainingJobRequest
    status: TrainingJobStatus
    accepted_at_ms: int
    updated_at_ms: int
    result: TrainingJobResult | None = None
    error: str | None = None


class CancelResponse(StrictModel):
    job_id: str
    status: TrainingJobStatus



class ShadowStatus(str, Enum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    DEGRADED = "degraded"
    ENDED = "ended"


class ShadowSessionRequest(StrictModel):
    training_session_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    created_at_ms: int = Field(ge=0)
    state: dict[str, Any]


class ShadowSyncRequest(StrictModel):
    observed_at_ms: int = Field(ge=0)
    state: dict[str, Any]


class ShadowStepRequest(StrictModel):
    observed_at_ms: int = Field(ge=0)
    decision: dict[str, Any]

    @field_validator("decision")
    @classmethod
    def require_state_revision(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "state_revision" not in value:
            raise ValueError("decision.state_revision is required")
        if "action" not in value:
            raise ValueError("decision.action is required")
        return value


class ShadowSessionRecord(StrictModel):
    shadow_id: str
    training_session_id: str
    episode_id: str
    status: ShadowStatus
    created_at_ms: int
    updated_at_ms: int
    real_revision: int = Field(ge=0)
    simulated_revision: int | None = Field(default=None, ge=0)
    last_divergence: dict[str, Any] | None = None
    last_step: dict[str, Any] | None = None
    error: str | None = None


class NeuralSessionStatus(str, Enum):
    ACTIVE = "active"
    SEALED = "sealed"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class NeuralSessionRequest(StrictModel):
    client_id: str = Field(min_length=1, max_length=128)
    match_id: str = Field(min_length=1, max_length=128)
    created_at_ms: int = Field(ge=0)
    patch: str | None = Field(default=None, max_length=32)
    set_key: str | None = Field(default=None, max_length=64)
    capture_policy: str = Field(min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NeuralSessionRecord(StrictModel):
    neural_session_id: str
    client_id: str
    match_id: str
    created_at_ms: int
    updated_at_ms: int
    status: NeuralSessionStatus
    frames_received: int = Field(ge=0)
    bytes_received: int = Field(ge=0)
    last_source_ms: int | None = Field(default=None, ge=0)
    champion_model_sha256: str | None = None
    shadow_candidate_sha256: str | None = None
    error: str | None = None


class NeuralFrameMetadata(StrictModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    neural_session_id: str = Field(min_length=1)
    frame_id: int = Field(ge=0)
    source_ms: int = Field(ge=0)
    width: int = Field(ge=1, le=3840)
    height: int = Field(ge=1, le=2160)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    content_type: Literal["image/jpeg", "image/png"]
    capture_role: Literal["live_inference", "post_match_learning_evidence"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class NeuralInferenceResult(StrictModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    neural_session_id: str
    frame_id: int = Field(ge=0)
    source_ms: int = Field(ge=0)
    status: Literal["accepted", "queued", "abstain", "error"]
    champion_model_sha256: str | None = None
    game_state: dict[str, Any] | None = None
    observations: tuple[dict[str, Any], ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    inference_ms: float | None = Field(default=None, ge=0.0)
    error: str | None = None


class NeuralSealRequest(StrictModel):
    sealed_at_ms: int = Field(ge=0)
    match_end_reason: str = Field(min_length=1, max_length=128)
    capture_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(ge=1, le=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NeuralLearningStatus(StrictModel):
    neural_session_id: str
    status: NeuralSessionStatus
    champion_model_sha256: str | None = None
    challenger_model_sha256: str | None = None
    challenger_selected: bool = False
    shadow_candidate_created: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class NeuralClientSessionRequest(StrictModel):
    installation_id: str = Field(min_length=1, max_length=128)


class NeuralClientSessionResponse(StrictModel):
    token: str = Field(min_length=32, max_length=4096)
    expires_at_ms: int = Field(ge=0)
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
