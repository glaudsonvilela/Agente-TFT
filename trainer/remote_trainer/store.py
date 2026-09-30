from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from .schemas import (
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


class NullTrainerBackend:
    async def run(self, request: TrainingJobRequest) -> TrainingJobResult:
        raise SimulatorNotConfigured("simulator_not_configured")


@dataclass
class TrainerStore:
    backend: TrainerBackend
    sessions: dict[str, TrainingSession] = field(default_factory=dict)
    jobs: dict[str, TrainingJobRecord] = field(default_factory=dict)
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
