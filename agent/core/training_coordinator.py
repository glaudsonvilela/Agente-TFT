from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from .remote_training import RemoteTrainingClient, RemoteJobRecord
from schemas.contracts import DecisionPacket, GameState


class RemoteTrainingPhase(str, Enum):
    IDLE = "idle"
    SESSION_STARTING = "session_starting"
    WAITING_FOR_MATCH = "waiting_for_match"
    MATCH_ACTIVE = "match_active"
    MATCH_ENDED = "match_ended"
    DEGRADED_LOCAL_ONLY = "degraded_local_only"


@dataclass
class RemoteTrainingCoordinator:
    client: RemoteTrainingClient
    phase: RemoteTrainingPhase = RemoteTrainingPhase.IDLE
    episode_id: str | None = None
    shadow_id: str | None = None
    last_error: str | None = None

    async def on_matchmaking_requested(
        self,
        *,
        now_ms: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Called by the local UI/runtime when the user explicitly enables remote
        training for a new matchmaking attempt.

        Failure never blocks local play; it degrades to local-only mode.
        """
        self.phase = RemoteTrainingPhase.SESSION_STARTING
        self.last_error = None
        self.episode_id = str(uuid4())
        self.shadow_id = None

        try:
            await self.client.create_session(
                requested_at_ms=now_ms,
                metadata={
                    "trigger": "matchmaking_requested",
                    **(metadata or {}),
                },
            )
        except Exception as exc:
            self.phase = RemoteTrainingPhase.DEGRADED_LOCAL_ONLY
            self.last_error = f"{type(exc).__name__}:{exc}"
            return

        self.phase = RemoteTrainingPhase.WAITING_FOR_MATCH

    def on_match_detected(self) -> None:
        if self.phase == RemoteTrainingPhase.WAITING_FOR_MATCH:
            self.phase = RemoteTrainingPhase.MATCH_ACTIVE

    async def submit_shadow_decision(
        self,
        *,
        state: GameState,
        decision: DecisionPacket,
        now_ms: int,
        rollout_count: int = 128,
        horizon_steps: int = 200,
        scripted_bots: tuple[str, ...] = (),
        historical_policy_versions: tuple[str, ...] = (),
        opportunities: tuple[dict[str, Any], ...] = (),
    ) -> RemoteJobRecord | None:
        """
        Submit a decision for counterfactual simulation.

        This is intentionally shadow-only: no result is converted into a
        mouse/keyboard action by this coordinator.
        """
        if self.phase != RemoteTrainingPhase.MATCH_ACTIVE:
            return None
        if self.episode_id is None:
            return None

        try:
            return await self.client.submit_decision_job(
                state=state,
                decision=decision,
                created_at_ms=now_ms,
                rollout_count=rollout_count,
                horizon_steps=horizon_steps,
                scripted_bots=scripted_bots,
                historical_policy_versions=historical_policy_versions,
                episode_id=self.episode_id,
                metadata={"trigger": "shadow_decision"},
                opportunities=opportunities,
            )
        except Exception as exc:
            self.phase = RemoteTrainingPhase.DEGRADED_LOCAL_ONLY
            self.last_error = f"{type(exc).__name__}:{exc}"
            return None



    async def start_realtime_shadow(
        self,
        *,
        state: GameState,
        now_ms: int,
    ) -> bool:
        if self.phase != RemoteTrainingPhase.MATCH_ACTIVE:
            return False
        if self.episode_id is None:
            return False

        try:
            record = await self.client.create_shadow_session(
                state=state,
                created_at_ms=now_ms,
                episode_id=self.episode_id,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}:{exc}"
            return False

        self.shadow_id = record.shadow_id
        if record.status != "active":
            self.last_error = record.error or f"shadow_status:{record.status}"
            return False

        return True

    async def sync_realtime_shadow(
        self,
        *,
        state: GameState,
        now_ms: int,
    ) -> bool:
        if not self.shadow_id:
            return False

        try:
            record = await self.client.sync_shadow(
                self.shadow_id,
                state=state,
                observed_at_ms=now_ms,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}:{exc}"
            return False

        if record.status != "active":
            self.last_error = record.error or f"shadow_status:{record.status}"
            return False
        return True

    async def step_realtime_shadow(
        self,
        *,
        decision: DecisionPacket,
        now_ms: int,
    ) -> dict[str, Any] | None:
        if not self.shadow_id:
            return None

        try:
            record = await self.client.step_shadow(
                self.shadow_id,
                decision=decision,
                observed_at_ms=now_ms,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}:{exc}"
            return None

        if record.status != "active":
            self.last_error = record.error or f"shadow_status:{record.status}"
            return None

        return record.last_step

    async def end_realtime_shadow(self) -> None:
        shadow_id = self.shadow_id
        self.shadow_id = None
        if not shadow_id:
            return

        try:
            await self.client.end_shadow(shadow_id)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}:{exc}"

    async def submit_counterfactual_job(
        self,
        *,
        state: GameState,
        decision: DecisionPacket,
        now_ms: int,
        rollout_count: int = 128,
        horizon_steps: int = 200,
        scripted_bots: tuple[str, ...] = (),
        historical_policy_versions: tuple[str, ...] = (),
        opportunities: tuple[dict[str, Any], ...] = (),
    ) -> RemoteJobRecord | None:
        return await self.submit_shadow_decision(
            state=state,
            decision=decision,
            now_ms=now_ms,
            rollout_count=rollout_count,
            horizon_steps=horizon_steps,
            scripted_bots=scripted_bots,
            historical_policy_versions=historical_policy_versions,
            opportunities=opportunities,
        )

    def on_match_ended(self) -> None:
        if self.phase in {
            RemoteTrainingPhase.MATCH_ACTIVE,
            RemoteTrainingPhase.WAITING_FOR_MATCH,
        }:
            self.phase = RemoteTrainingPhase.MATCH_ENDED

    def reset(self) -> None:
        self.phase = RemoteTrainingPhase.IDLE
        self.episode_id = None
        self.shadow_id = None
        self.last_error = None
