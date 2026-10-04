from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import zipfile
from typing import Callable

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse

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
from .resources import ResourceSampler
from .policy_learning import policy_learning_jobs, simulation_coverage


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def item_learning_jobs(db_path: Path | None) -> list[dict]:
    if db_path is None:
        return []
    jobs=[]
    for folder in sorted((Path(db_path).parent/'experiments').glob('hm45-item-icons-*'),reverse=True)[:5]:
        root=folder/'training-v1'
        try:
            path=root/'progress.json'
            if path.stat().st_size>65536:continue
            progress=json.loads(path.read_text())
            if progress.get('kind')!='item_icon_classifier':continue
            row={k:progress.get(k) for k in ['status','optimizer_steps','optimizer_steps_total',
                'classes','elapsed_seconds','loss','peak_rss_mib','process_cpu_seconds']}
            row.update(id=folder.name,scope='item_art_only',strategic_learning=False,
                       runtime_promoted=False,simulation_paths=0)
            if row['status']=='training' and time.time()-path.stat().st_mtime>180:
                row['status']='progress_not_recent'
            if row['status']=='trained_evaluated':
                seal=json.loads((root/'COMPLETE.json').read_text())
                for name in ['item-icons.onnx','metadata.json','report.json']:
                    if (root/name).stat().st_size>2*1024*1024:raise ValueError('Artifact too large')
                    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=seal[name]:
                        raise ValueError('Item model seal mismatch')
                report=json.loads((root/'report.json').read_text())
                row.update({k:report[k] for k in ['changed_parameter_tensors','first_50_loss_mean',
                    'last_50_loss_mean','replay_correct','replay_total','replay_distinct_items',
                    'synthetic_augmented_top1','independent_match_validation']})
                row['model_sha256']=seal['item-icons.onnx']
            jobs.append(row)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return jobs


def verified_neural_experiments(db_path: Path | None) -> list[dict[str, object]]:
    """Read sealed local candidates; simulator jobs remain a separate metric."""
    if db_path is None:
        return []
    root = Path(db_path).parent / "experiments"
    results = []
    for folder in sorted(root.glob("*"), reverse=True)[:10]:
        if not folder.is_dir():
            continue
        try:
            train = folder / "training-v2"
            evaluation = folder / "evaluation-v2"
            seal = json.loads((train / "TRAINED.json").read_text(encoding="utf-8"))
            complete = json.loads((evaluation / "COMPLETE.json").read_text(encoding="utf-8"))
            for name in ("training-report.json", "model.npz"):
                path = train / name
                if hashlib.sha256(path.read_bytes()).hexdigest() != seal[name]:
                    raise ValueError("Training seal mismatch")
            for name in ("report.json", "model.onnx"):
                path = evaluation / name
                if hashlib.sha256(path.read_bytes()).hexdigest() != complete[name]:
                    raise ValueError("Evaluation seal mismatch")
            report = json.loads((train / "training-report.json").read_text(encoding="utf-8"))
            result = json.loads((evaluation / "report.json").read_text(encoding="utf-8"))["summary"]
            if (report.get("model_trained") is not True or
                    result.get("model_trained") is not True or
                    result.get("profile_promoted") is not False):
                continue
            status = "candidate_trained_unpromoted"
            comparison = None
            comparison_file = folder / "compare-previous.json"
            if comparison_file.is_file() and comparison_file.stat().st_size <= 65536:
                try:
                    comparison = json.loads(comparison_file.read_text(encoding="utf-8"))
                    previous_shop = int(comparison["previous"].get("shop:proposal", 0))
                    candidate_shop = int(comparison["candidate"].get("shop:proposal", 0))
                    if (comparison.get("frames", 0) > 0 and candidate_shop < previous_shop and
                            comparison.get("candidate_promoted") is False):
                        status = "regression_rejected"
                except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
                    comparison = None
            results.append({
                "id": folder.name, "status": status,
                "scope": "bench_shop_region_only",
                "source_frames": result["frames"],
                "optimizer_steps": report["optimizer_steps"],
                "inference_p95_ms": result["real_inference_ms_p95"],
                "independent_match_accuracy": result["independent_match_accuracy"],
                "model_sha256": complete["model.onnx"],
                "comparison": comparison,
            })
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return results


def latest_imported_runtime(db_path: Path | None) -> dict[str, object] | None:
    """Read only a bounded sealed-session summary, never execute uploaded data."""
    if db_path is None:
        return None
    imports = Path(db_path).parent / "imports"
    for archive in sorted(imports.glob("hm4-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
        try:
            with zipfile.ZipFile(archive) as bundle:
                summaries = [item for item in bundle.infolist()
                             if item.filename.endswith("/summary.json") and
                             len(Path(item.filename).parts) == 2 and
                             item.file_size <= 1024 * 1024]
                if len(summaries) != 1:
                    continue
                summary = json.loads(bundle.read(summaries[0]))
            counts = summary.get("counts") or {}
            versions = summary.get("versions") or {}
            mapped = counts.get("mapped_frames")
            if type(mapped) is not int or mapped < 0:
                continue
            return {
                "archive": archive.name,
                "session_complete": summary.get("execution_complete") is True,
                "neural_mode": summary.get("neural_mode"),
                "diagnostic_active": (summary.get("execution_complete") is True and
                                      summary.get("neural_mode") == "shadow_diagnostic" and
                                      versions.get("neural_enabled") is True and mapped > 0),
                "mapped_frames": mapped,
                "model_trained": summary.get("model_trained") is True,
                "board_cells_validated": summary.get("board_cells_validated") is True,
            }
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError):
            continue
    return None


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
    app.state.store = store or TrainerStore(
        backend=NullTrainerBackend(),
        db_path=os.environ.get("TRAINER_DB_PATH") or None,
    )
    app.state.clock_ms = clock_ms
    app.state.resources = ResourceSampler()
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
            "storage": "sqlite" if app.state.store.db_path else "memory",
            "simulator_ready": not isinstance(app.state.store.backend, NullTrainerBackend),
        }

    @app.get("/v1/training/dashboard-metrics")
    async def dashboard_metrics() -> dict[str, object]:
        snapshot = await app.state.store.dashboard_metrics()
        snapshot["simulator_ready"] = not isinstance(app.state.store.backend, NullTrainerBackend)
        experiments = verified_neural_experiments(app.state.store.db_path)
        snapshot["neural_training_status"] = (
            experiments[0]["status"] if experiments else "not_started"
        )
        snapshot["neural_experiments"] = experiments
        snapshot["item_learning_jobs"] = item_learning_jobs(app.state.store.db_path)
        snapshot["policy_learning_jobs"] = policy_learning_jobs(app.state.store.db_path)
        snapshot["simulation_coverage"] = simulation_coverage(app.state.store.db_path)
        snapshot["latest_imported_runtime"] = latest_imported_runtime(app.state.store.db_path)
        snapshot["resources"] = app.state.resources.sample()
        snapshot["generated_at_ms"] = app.state.clock_ms()
        return snapshot

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        page = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
        return HTMLResponse(page, headers={"Cache-Control": "no-store",
                                           "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; object-src 'none'"})

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
