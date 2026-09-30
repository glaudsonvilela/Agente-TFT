from __future__ import annotations

import asyncio
import os
import secrets
import time
from typing import Callable

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status

from .schemas import (
    CancelResponse,
    ShadowSessionRecord,
    ShadowSessionRequest,
    ShadowStatus,
    ShadowStepRequest,
    ShadowSyncRequest,
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
    api_token: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Agente TFT Remote Trainer",
        version="0.1.0",
    )
    app.state.store = store or TrainerStore(backend=NullTrainerBackend())
    app.state.clock_ms = clock_ms
    app.state.api_token = (
        api_token
        if api_token is not None
        else os.environ.get("TRAINER_API_TOKEN")
    )

    async def require_token(
        authorization: str | None = Header(default=None),
    ) -> None:
        expected = app.state.api_token
        if not expected:
            return

        prefix = "Bearer "
        if not authorization or not authorization.startswith(prefix):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
            )

        supplied = authorization[len(prefix):]
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            )

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
        dependencies=[Depends(require_token)],
    )
    async def create_session(request: TrainingSessionRequest) -> TrainingSession:
        return await app.state.store.create_session(request)

    @app.post(
        "/v1/training/jobs",
        response_model=TrainingJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
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
        dependencies=[Depends(require_token)],
    )
    async def get_job(job_id: str) -> TrainingJobRecord:
        record = await app.state.store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    @app.post(
        "/v1/training/jobs/{job_id}/cancel",
        response_model=CancelResponse,
        dependencies=[Depends(require_token)],
    )
    async def cancel_job(job_id: str) -> CancelResponse:
        record = await app.state.store.cancel_job(
            job_id,
            app.state.clock_ms(),
        )
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return CancelResponse(job_id=job_id, status=record.status)


    @app.post(
        "/v1/shadow/sessions",
        response_model=ShadowSessionRecord,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    async def create_shadow_session(
        request: ShadowSessionRequest,
    ) -> ShadowSessionRecord:
        try:
            record = await app.state.store.create_shadow_session(
                request,
                app.state.clock_ms(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            result = await app.state.store.shadow_backend.initialize(
                record.shadow_id,
                request.state,
            )
        except SimulatorNotConfigured as exc:
            return await app.state.store.degrade_shadow(
                record.shadow_id,
                str(exc),
                app.state.clock_ms(),
            )
        except Exception as exc:
            return await app.state.store.degrade_shadow(
                record.shadow_id,
                f"backend_error:{type(exc).__name__}",
                app.state.clock_ms(),
            )

        return await app.state.store.activate_shadow(
            record.shadow_id,
            result,
            app.state.clock_ms(),
        )

    @app.get(
        "/v1/shadow/sessions/{shadow_id}",
        response_model=ShadowSessionRecord,
        dependencies=[Depends(require_token)],
    )
    async def get_shadow_session(shadow_id: str) -> ShadowSessionRecord:
        record = await app.state.store.get_shadow_session(shadow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="shadow session not found")
        return record

    @app.post(
        "/v1/shadow/sessions/{shadow_id}/sync",
        response_model=ShadowSessionRecord,
        dependencies=[Depends(require_token)],
    )
    async def sync_shadow_session(
        shadow_id: str,
        request: ShadowSyncRequest,
    ) -> ShadowSessionRecord:
        record = await app.state.store.get_shadow_session(shadow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="shadow session not found")
        if record.status == ShadowStatus.ENDED:
            raise HTTPException(status_code=409, detail="shadow session already ended")

        revision = request.state.get("revision")
        if not isinstance(revision, int) or revision < record.real_revision:
            raise HTTPException(
                status_code=409,
                detail="shadow real revision moved backwards or is invalid",
            )

        try:
            result = await app.state.store.shadow_backend.reconcile(
                shadow_id,
                request.state,
            )
        except SimulatorNotConfigured as exc:
            return await app.state.store.degrade_shadow(
                shadow_id,
                str(exc),
                app.state.clock_ms(),
            )
        except Exception as exc:
            return await app.state.store.degrade_shadow(
                shadow_id,
                f"backend_error:{type(exc).__name__}",
                app.state.clock_ms(),
            )

        try:
            return await app.state.store.update_shadow_after_sync(
                shadow_id,
                request.state,
                result,
                app.state.clock_ms(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/shadow/sessions/{shadow_id}/step",
        response_model=ShadowSessionRecord,
        dependencies=[Depends(require_token)],
    )
    async def step_shadow_session(
        shadow_id: str,
        request: ShadowStepRequest,
    ) -> ShadowSessionRecord:
        record = await app.state.store.get_shadow_session(shadow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="shadow session not found")
        if record.status != ShadowStatus.ACTIVE:
            raise HTTPException(
                status_code=409,
                detail=f"shadow session is not active: {record.status.value}",
            )
        if request.decision.get("state_revision") != record.real_revision:
            raise HTTPException(
                status_code=409,
                detail="shadow decision revision does not match latest real revision",
            )

        try:
            result = await app.state.store.shadow_backend.step(
                shadow_id,
                request.decision,
            )
        except SimulatorNotConfigured as exc:
            return await app.state.store.degrade_shadow(
                shadow_id,
                str(exc),
                app.state.clock_ms(),
            )
        except Exception as exc:
            return await app.state.store.degrade_shadow(
                shadow_id,
                f"backend_error:{type(exc).__name__}",
                app.state.clock_ms(),
            )

        try:
            return await app.state.store.update_shadow_after_step(
                shadow_id,
                request.decision,
                result,
                app.state.clock_ms(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/shadow/sessions/{shadow_id}/end",
        response_model=ShadowSessionRecord,
        dependencies=[Depends(require_token)],
    )
    async def end_shadow_session(shadow_id: str) -> ShadowSessionRecord:
        record = await app.state.store.get_shadow_session(shadow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="shadow session not found")

        try:
            await app.state.store.shadow_backend.end(shadow_id)
        except Exception:
            # Ending the local record must remain possible even if the simulator
            # backend is already unavailable.
            pass

        ended = await app.state.store.end_shadow(
            shadow_id,
            app.state.clock_ms(),
        )
        assert ended is not None
        return ended

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
