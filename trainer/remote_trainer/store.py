from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from .schemas import (
    ShadowSessionRecord,
    ShadowSessionRequest,
    ShadowStatus,
    TrainingJobRecord,
    TrainingJobRequest,
    TrainingJobResult,
    TrainingJobStatus,
    TrainingSession,
    TrainingSessionRequest,
)


class TrainerBackend(Protocol):
    async def run(self, request: TrainingJobRequest) -> TrainingJobResult:
        ...


class SimulatorNotConfigured(RuntimeError):
    pass


class ShadowBackend(Protocol):
    async def initialize(
        self,
        shadow_id: str,
        state: dict,
    ) -> dict:
        ...

    async def reconcile(
        self,
        shadow_id: str,
        state: dict,
    ) -> dict:
        ...

    async def step(
        self,
        shadow_id: str,
        decision: dict,
    ) -> dict:
        ...

    async def end(self, shadow_id: str) -> None:
        ...


class NullShadowBackend:
    async def initialize(self, shadow_id: str, state: dict) -> dict:
        raise SimulatorNotConfigured("simulator_not_configured")

    async def reconcile(self, shadow_id: str, state: dict) -> dict:
        raise SimulatorNotConfigured("simulator_not_configured")

    async def step(self, shadow_id: str, decision: dict) -> dict:
        raise SimulatorNotConfigured("simulator_not_configured")

    async def end(self, shadow_id: str) -> None:
        return None


class NullTrainerBackend:
    async def run(self, request: TrainingJobRequest) -> TrainingJobResult:
        raise SimulatorNotConfigured("simulator_not_configured")


@dataclass
class TrainerStore:
    backend: TrainerBackend
    shadow_backend: ShadowBackend = field(default_factory=NullShadowBackend)
    sessions: dict[str, TrainingSession] = field(default_factory=dict)
    jobs: dict[str, TrainingJobRecord] = field(default_factory=dict)
    shadow_sessions: dict[str, ShadowSessionRecord] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def create_session(
        self,
        request: TrainingSessionRequest,
    ) -> TrainingSession:
        session = TrainingSession(
            session_id=str(uuid4()),
            created_at_ms=request.requested_at_ms,
            client_id=request.client_id,
            profile=request.profile,
            active=True,
        )
        async with self.lock:
            self.sessions[session.session_id] = session
        return session

    async def get_session(self, session_id: str) -> TrainingSession | None:
        async with self.lock:
            return self.sessions.get(session_id)

    async def submit_job(
        self,
        request: TrainingJobRequest,
        now_ms: int,
    ) -> tuple[TrainingJobRecord, bool]:
        request.validate_revision_match()

        async with self.lock:
            existing = self.jobs.get(request.job_id)
            if existing is not None:
                if existing.request != request:
                    raise ValueError("job_id already exists with different payload")
                return existing, False

            session = self.sessions.get(request.session_id)
            if session is None or not session.active:
                raise KeyError("training session not found or inactive")

            record = TrainingJobRecord(
                request=request,
                status=TrainingJobStatus.ACCEPTED,
                accepted_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            self.jobs[request.job_id] = record
            return record, True

    async def mark_running(self, job_id: str, now_ms: int) -> None:
        async with self.lock:
            record = self.jobs[job_id]
            record.status = TrainingJobStatus.RUNNING
            record.updated_at_ms = now_ms

    async def mark_result(
        self,
        job_id: str,
        result: TrainingJobResult,
        now_ms: int,
    ) -> None:
        async with self.lock:
            record = self.jobs[job_id]
            record.status = result.status
            record.updated_at_ms = now_ms
            record.result = result
            record.error = result.error

    async def mark_failed(self, job_id: str, error: str, now_ms: int) -> None:
        async with self.lock:
            record = self.jobs[job_id]
            record.status = TrainingJobStatus.FAILED
            record.updated_at_ms = now_ms
            record.error = error

    async def get_job(self, job_id: str) -> TrainingJobRecord | None:
        async with self.lock:
            return self.jobs.get(job_id)

    async def cancel_job(self, job_id: str, now_ms: int) -> TrainingJobRecord | None:
        async with self.lock:
            record = self.jobs.get(job_id)
            if record is None:
                return None
            if record.status in {
                TrainingJobStatus.COMPLETED,
                TrainingJobStatus.FAILED,
                TrainingJobStatus.CANCELLED,
            }:
                return record
            record.status = TrainingJobStatus.CANCELLED
            record.updated_at_ms = now_ms
            return record


    async def create_shadow_session(
        self,
        request: ShadowSessionRequest,
        now_ms: int,
    ) -> ShadowSessionRecord:
        revision = request.state.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("shadow state.revision must be a non-negative integer")

        async with self.lock:
            parent = self.sessions.get(request.training_session_id)
            if parent is None or not parent.active:
                raise KeyError("training session not found or inactive")

            shadow_id = str(uuid4())
            record = ShadowSessionRecord(
                shadow_id=shadow_id,
                training_session_id=request.training_session_id,
                episode_id=request.episode_id,
                status=ShadowStatus.INITIALIZING,
                created_at_ms=request.created_at_ms,
                updated_at_ms=now_ms,
                real_revision=revision,
                simulated_revision=None,
            )
            self.shadow_sessions[shadow_id] = record
            return record

    async def get_shadow_session(
        self,
        shadow_id: str,
    ) -> ShadowSessionRecord | None:
        async with self.lock:
            return self.shadow_sessions.get(shadow_id)

    async def activate_shadow(
        self,
        shadow_id: str,
        result: dict,
        now_ms: int,
    ) -> ShadowSessionRecord:
        async with self.lock:
            record = self.shadow_sessions[shadow_id]
            simulated_revision = result.get(
                "simulated_revision",
                record.real_revision,
            )
            if not isinstance(simulated_revision, int) or simulated_revision < 0:
                raise ValueError("invalid simulated_revision from shadow backend")

            record.status = ShadowStatus.ACTIVE
            record.updated_at_ms = now_ms
            record.simulated_revision = simulated_revision
            record.last_divergence = result.get("divergence")
            record.error = None
            return record

    async def degrade_shadow(
        self,
        shadow_id: str,
        error: str,
        now_ms: int,
    ) -> ShadowSessionRecord:
        async with self.lock:
            record = self.shadow_sessions[shadow_id]
            record.status = ShadowStatus.DEGRADED
            record.updated_at_ms = now_ms
            record.error = error
            return record

    async def update_shadow_after_sync(
        self,
        shadow_id: str,
        state: dict,
        result: dict,
        now_ms: int,
    ) -> ShadowSessionRecord:
        revision = state.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("shadow state.revision must be a non-negative integer")

        async with self.lock:
            record = self.shadow_sessions[shadow_id]
            if revision < record.real_revision:
                raise ValueError("shadow real revision moved backwards")

            simulated_revision = result.get("simulated_revision", revision)
            if not isinstance(simulated_revision, int) or simulated_revision < 0:
                raise ValueError("invalid simulated_revision from shadow backend")

            record.real_revision = revision
            record.simulated_revision = simulated_revision
            record.last_divergence = result.get("divergence")
            record.updated_at_ms = now_ms
            record.status = ShadowStatus.ACTIVE
            record.error = None
            return record

    async def update_shadow_after_step(
        self,
        shadow_id: str,
        decision: dict,
        result: dict,
        now_ms: int,
    ) -> ShadowSessionRecord:
        decision_revision = decision.get("state_revision")
        async with self.lock:
            record = self.shadow_sessions[shadow_id]
            if decision_revision != record.real_revision:
                raise ValueError(
                    "shadow decision revision does not match latest real revision"
                )

            simulated_revision = result.get(
                "simulated_revision",
                record.simulated_revision,
            )
            if simulated_revision is not None and (
                not isinstance(simulated_revision, int)
                or simulated_revision < 0
            ):
                raise ValueError("invalid simulated_revision from shadow backend")

            record.simulated_revision = simulated_revision
            record.last_step = result
            record.updated_at_ms = now_ms
            record.status = ShadowStatus.ACTIVE
            record.error = None
            return record

    async def end_shadow(
        self,
        shadow_id: str,
        now_ms: int,
    ) -> ShadowSessionRecord | None:
        async with self.lock:
            record = self.shadow_sessions.get(shadow_id)
            if record is None:
                return None
            record.status = ShadowStatus.ENDED
            record.updated_at_ms = now_ms
            return record
