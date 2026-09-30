from __future__ import annotations

import asyncio
import time
from typing import Callable

from fastapi import BackgroundTasks, FastAPI, HTTPException, status

from .schemas import (
    CancelResponse,
    TrainingJobRecord,
    TrainingJobRequest,
    TrainingJobStatus,
    TrainingSession,
    TrainingSessionRequest,
)
from .store import NullTrainerBackend, SimulatorNotConfigured, TrainerStore


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def create_app(
    *,
    store: TrainerStore | None = None,
    clock_ms: Callable[[], int] = unix_ms,
) -> FastAPI:
    app = FastAPI(
        title="Agente TFT Remote Trainer",
        version="0.1.0",
    )
    app.state.store = store or TrainerStore(backend=NullTrainerBackend())
    app.state.clock_ms = clock_ms

    @app.get("/v1/training/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "service": "agente-tft-remote-trainer",
            "protocol_version": 1,
        }

    @app.post(
        "/v1/training/sessions",
        response_model=TrainingSession,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_session(request: TrainingSessionRequest) -> TrainingSession:
        return await app.state.store.create_session(request)

    @app.post(
        "/v1/training/jobs",
        response_model=TrainingJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_job(
        request: TrainingJobRequest,
        background_tasks: BackgroundTasks,
    ) -> TrainingJobRecord:
        try:
            record, created = await app.state.store.submit_job(
                request,
                app.state.clock_ms(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if created:
            background_tasks.add_task(
                _execute_job,
                app.state.store,
                request,
                app.state.clock_ms,
            )
        return record

    @app.get(
        "/v1/training/jobs/{job_id}",
        response_model=TrainingJobRecord,
    )
    async def get_job(job_id: str) -> TrainingJobRecord:
        record = await app.state.store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    @app.post(
        "/v1/training/jobs/{job_id}/cancel",
        response_model=CancelResponse,
    )
    async def cancel_job(job_id: str) -> CancelResponse:
        record = await app.state.store.cancel_job(
            job_id,
            app.state.clock_ms(),
        )
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return CancelResponse(job_id=job_id, status=record.status)

    return app


async def _execute_job(
    store: TrainerStore,
    request: TrainingJobRequest,
    clock_ms: Callable[[], int],
) -> None:
    record = await store.get_job(request.job_id)
    if record is None or record.status == TrainingJobStatus.CANCELLED:
        return

    await store.mark_running(request.job_id, clock_ms())

    try:
        result = await store.backend.run(request)
    except SimulatorNotConfigured as exc:
        await store.mark_failed(request.job_id, str(exc), clock_ms())
        return
    except asyncio.CancelledError:
        await store.cancel_job(request.job_id, clock_ms())
        raise
    except Exception as exc:
        await store.mark_failed(
            request.job_id,
            f"backend_error:{type(exc).__name__}",
            clock_ms(),
        )
        return

    await store.mark_result(
        request.job_id,
        result,
        clock_ms(),
    )


app = create_app()
