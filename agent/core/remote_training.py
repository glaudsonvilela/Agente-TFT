from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from schemas.contracts import DecisionPacket, GameState


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemoteSession(StrictModel):
    session_id: str
    created_at_ms: int
    client_id: str
    profile: str
    active: bool


class RemoteJobRecord(StrictModel):
    request: dict[str, Any]
    status: str
    accepted_at_ms: int
    updated_at_ms: int
    result: dict[str, Any] | None = None
    error: str | None = None


class RemoteShadowRecord(StrictModel):
    shadow_id: str
    training_session_id: str
    episode_id: str
    status: str
    created_at_ms: int
    updated_at_ms: int
    real_revision: int
    simulated_revision: int | None = None
    last_divergence: dict[str, Any] | None = None
    last_step: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class RemoteTrainingConfig:
    base_url: str
    timeout_seconds: float = 2.0
    client_id: str = "agente-tft-local"
    profile: str = "lab"
    api_token: str | None = None


class RemoteTrainingClient:
    """
    Optional client for the BigBANANA remote training plane.

    This client never sends mouse/keyboard/desktop commands. It sends only
    structured state/decision data for simulation and evaluation.
    """

    def __init__(
        self,
        config: RemoteTrainingConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        headers = {}
        if config.api_token:
            headers["Authorization"] = f"Bearer {config.api_token}"

        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/") + "/",
            timeout=config.timeout_seconds,
            transport=transport,
            headers=headers,
        )
        self.session: RemoteSession | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create_session(
        self,
        *,
        requested_at_ms: int,
        metadata: dict[str, Any] | None = None,
    ) -> RemoteSession:
        response = await self._http.post(
            "v1/training/sessions",
            json={
                "client_id": self.config.client_id,
                "requested_at_ms": requested_at_ms,
                "profile": self.config.profile,
                "metadata": metadata or {},
            },
        )
        response.raise_for_status()
        session = RemoteSession.model_validate(response.json())
        self.session = session
        return session

    async def submit_decision_job(
        self,
        *,
        state: GameState,
        decision: DecisionPacket,
        created_at_ms: int,
        mode: str = "simulator",
        rollout_count: int = 128,
        horizon_steps: int = 200,
        scripted_bots: tuple[str, ...] = (),
        historical_policy_versions: tuple[str, ...] = (),
        include_current_policy: bool = True,
        episode_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        opportunities: tuple[dict[str, Any], ...] = (),
    ) -> RemoteJobRecord:
        if self.session is None or not self.session.active:
            raise RuntimeError("remote training session is not active")

        if state.revision != decision.state_revision:
            raise ValueError(
                f"state revision {state.revision} does not match "
                f"decision revision {decision.state_revision}"
            )

        payload = {
            "protocol_version": 1,
            "session_id": self.session.session_id,
            "job_id": job_id or str(uuid4()),
            "episode_id": episode_id or str(uuid4()),
            "created_at_ms": created_at_ms,
            "mode": mode,
            "state": state.model_dump(mode="json", by_alias=True),
            "decision": decision.model_dump(mode="json", by_alias=True),
            "opportunities": list(opportunities),
            "rollout_count": rollout_count,
            "horizon_steps": horizon_steps,
            "opponent_pool": {
                "scripted_bots": list(scripted_bots),
                "historical_policy_versions": list(historical_policy_versions),
                "include_current_policy": include_current_policy,
            },
            "metadata": metadata or {},
        }

        response = await self._http.post(
            "v1/training/jobs",
            json=payload,
        )
        response.raise_for_status()
        return RemoteJobRecord.model_validate(response.json())

    async def get_job(self, job_id: str) -> RemoteJobRecord:
        response = await self._http.get(f"v1/training/jobs/{job_id}")
        response.raise_for_status()
        return RemoteJobRecord.model_validate(response.json())

    async def cancel_job(self, job_id: str) -> str:
        response = await self._http.post(
            f"v1/training/jobs/{job_id}/cancel"
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["status"])


    async def create_shadow_session(
        self,
        *,
        state: GameState,
        created_at_ms: int,
        episode_id: str,
    ) -> RemoteShadowRecord:
        if self.session is None or not self.session.active:
            raise RuntimeError("remote training session is not active")

        response = await self._http.post(
            "v1/shadow/sessions",
            json={
                "training_session_id": self.session.session_id,
                "episode_id": episode_id,
                "created_at_ms": created_at_ms,
                "state": state.model_dump(mode="json", by_alias=True),
            },
        )
        response.raise_for_status()
        return RemoteShadowRecord.model_validate(response.json())

    async def sync_shadow(
        self,
        shadow_id: str,
        *,
        state: GameState,
        observed_at_ms: int,
    ) -> RemoteShadowRecord:
        response = await self._http.post(
            f"v1/shadow/sessions/{shadow_id}/sync",
            json={
                "observed_at_ms": observed_at_ms,
                "state": state.model_dump(mode="json", by_alias=True),
            },
        )
        response.raise_for_status()
        return RemoteShadowRecord.model_validate(response.json())

    async def step_shadow(
        self,
        shadow_id: str,
        *,
        decision: DecisionPacket,
        observed_at_ms: int,
    ) -> RemoteShadowRecord:
        response = await self._http.post(
            f"v1/shadow/sessions/{shadow_id}/step",
            json={
                "observed_at_ms": observed_at_ms,
                "decision": decision.model_dump(mode="json", by_alias=True),
            },
        )
        response.raise_for_status()
        return RemoteShadowRecord.model_validate(response.json())

    async def get_shadow(
        self,
        shadow_id: str,
    ) -> RemoteShadowRecord:
        response = await self._http.get(
            f"v1/shadow/sessions/{shadow_id}"
        )
        response.raise_for_status()
        return RemoteShadowRecord.model_validate(response.json())

    async def end_shadow(
        self,
        shadow_id: str,
    ) -> RemoteShadowRecord:
        response = await self._http.post(
            f"v1/shadow/sessions/{shadow_id}/end"
        )
        response.raise_for_status()
        return RemoteShadowRecord.model_validate(response.json())
