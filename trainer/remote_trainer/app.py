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

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from .schemas import (
    CancelResponse,
    NeuralClientSessionRequest,
    NeuralClientSessionResponse,
    NeuralFrameMetadata,
    NeuralInferenceResult,
    NeuralLearningStatus,
    NeuralSealRequest,
    NeuralSessionRecord,
    NeuralSessionRequest,
    NeuralSessionStatus,
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
from .neural import NeuralBackend, NeuralBackendNotConfigured, NullNeuralBackend
from .resources import ResourceSampler
from .policy_learning import policy_learning_jobs, simulation_coverage, scene_learning_jobs


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
    neural_backend: NeuralBackend | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Agente TFT Remote Trainer",
        version="0.2.0",
    )
    app.state.store = store or TrainerStore(
        backend=NullTrainerBackend(),
        db_path=os.environ.get("TRAINER_DB_PATH") or None,
    )
    app.state.clock_ms = clock_ms
    app.state.resources = ResourceSampler()
    app.state.neural_backend = neural_backend or NullNeuralBackend()
    app.state.neural_tokens = {}
    app.state.neural_client_sessions_enabled = (
        os.environ.get("NEURAL_CLIENT_SESSIONS_ENABLED", "0") == "1"
    )
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

    async def require_neural_token(
        authorization: str | None = Header(default=None),
    ) -> str:
        prefix = "Bearer "
        if not authorization or not authorization.startswith(prefix):
            raise HTTPException(status_code=401, detail="missing neural bearer token")
        supplied = authorization[len(prefix):]
        digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
        now = app.state.clock_ms()
        for key, (_, expires_at_ms) in list(app.state.neural_tokens.items()):
            if expires_at_ms <= now:
                app.state.neural_tokens.pop(key, None)
        record = app.state.neural_tokens.get(digest)
        if record is None:
            raise HTTPException(status_code=401, detail="invalid or expired neural token")
        installation_id, expires_at_ms = record
        if expires_at_ms <= now:
            app.state.neural_tokens.pop(digest, None)
            raise HTTPException(status_code=401, detail="expired neural token")
        return installation_id

    @app.post(
        "/v1/neural/client-session",
        response_model=NeuralClientSessionResponse,
    )
    async def create_neural_client_session(
        request: NeuralClientSessionRequest,
    ) -> NeuralClientSessionResponse:
        if not app.state.neural_client_sessions_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="neural client sessions are not enabled",
            )
        token = secrets.token_urlsafe(48)
        expires_at_ms = app.state.clock_ms() + 24 * 60 * 60 * 1000
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        app.state.neural_tokens[digest] = (request.installation_id, expires_at_ms)
        return NeuralClientSessionResponse(
            token=token,
            expires_at_ms=expires_at_ms,
        )

    @app.get("/v1/training/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "service": "agente-tft-remote-trainer",
            "protocol_version": 1,
            "storage": "sqlite" if app.state.store.db_path else "memory",
            "simulator_ready": not isinstance(app.state.store.backend, NullTrainerBackend),
            "neural_backend_ready": not isinstance(app.state.neural_backend, NullNeuralBackend),
            "neural_location": "server",
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
        snapshot["scene_learning_jobs"] = scene_learning_jobs(app.state.store.db_path)
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
        "/v1/neural/sessions",
        response_model=NeuralSessionRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_neural_session(
        request: NeuralSessionRequest,
        installation_id: str = Depends(require_neural_token),
    ) -> NeuralSessionRecord:
        if request.client_id != installation_id:
            raise HTTPException(status_code=403, detail="neural client_id/token mismatch")
        if app.state.store.evidence_root is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="persistent neural evidence storage is not configured",
            )
        return await app.state.store.create_neural_session(
            request,
            app.state.clock_ms(),
        )

    @app.get(
        "/v1/neural/sessions/{neural_session_id}",
        response_model=NeuralSessionRecord,
        dependencies=[Depends(require_neural_token)],
    )
    async def get_neural_session(
        neural_session_id: str,
    ) -> NeuralSessionRecord:
        record = await app.state.store.get_neural_session(neural_session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="neural session not found")
        return record

    @app.post(
        "/v1/neural/sessions/{neural_session_id}/frames",
        response_model=NeuralInferenceResult,
        dependencies=[Depends(require_neural_token)],
    )
    async def submit_neural_frame(
        neural_session_id: str,
        request: Request,
        frame_id: int,
        source_ms: int,
        width: int,
        height: int,
        image_sha256: str,
        capture_role: str,
        content_type: str = Header(alias="Content-Type"),
    ) -> NeuralInferenceResult:
        body = await request.body()
        try:
            metadata = NeuralFrameMetadata(
                neural_session_id=neural_session_id,
                frame_id=frame_id,
                source_ms=source_ms,
                width=width,
                height=height,
                image_sha256=image_sha256,
                image_bytes=len(body),
                content_type=content_type,
                capture_role=capture_role,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if hashlib.sha256(body).hexdigest() != metadata.image_sha256:
            raise HTTPException(status_code=409, detail="frame sha256 mismatch")

        root = app.state.store.evidence_root
        if root is None:
            raise HTTPException(status_code=503, detail="neural evidence storage unavailable")
        folder = root / neural_session_id / "frames"
        if not folder.is_dir():
            raise HTTPException(status_code=404, detail="neural session not found")
        suffix = ".jpg" if content_type == "image/jpeg" else ".png"
        final = folder / f"{frame_id:012d}{suffix}"
        meta_path = folder / f"{frame_id:012d}.json"
        if final.exists() or meta_path.exists():
            raise HTTPException(status_code=409, detail="frame_id already stored")
        temporary = final.with_suffix(final.suffix + ".partial")
        try:
            with temporary.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(final)
            meta_path.write_text(
                metadata.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            await app.state.store.record_neural_frame(
                neural_session_id,
                metadata.source_ms,
                metadata.image_bytes,
                app.state.clock_ms(),
            )
        except (KeyError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            code = 404 if isinstance(exc, KeyError) else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc

        try:
            return await app.state.neural_backend.infer(metadata, body)
        except Exception as exc:
            return NeuralInferenceResult(
                neural_session_id=neural_session_id,
                frame_id=metadata.frame_id,
                source_ms=metadata.source_ms,
                status="error",
                error=f"neural_backend_error:{type(exc).__name__}",
            )

    @app.post(
        "/v1/neural/sessions/{neural_session_id}/seal",
        response_model=NeuralSessionRecord,
        dependencies=[Depends(require_neural_token)],
    )
    async def seal_neural_session(
        neural_session_id: str,
        request: NeuralSealRequest,
        background_tasks: BackgroundTasks,
    ) -> NeuralSessionRecord:
        record = await app.state.store.get_neural_session(neural_session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="neural session not found")
        if record.frames_received != request.frame_count:
            raise HTTPException(
                status_code=409,
                detail="seal frame_count does not match received evidence",
            )
        root = app.state.store.evidence_root
        assert root is not None
        folder = root / neural_session_id
        seal_path = folder / "seal.json"
        seal_doc = request.model_dump()
        seal_doc.update(
            neural_session_id=neural_session_id,
            frames_received=record.frames_received,
            bytes_received=record.bytes_received,
        )
        seal_path.write_text(
            json.dumps(seal_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            sealed = await app.state.store.seal_neural_session(
                neural_session_id,
                app.state.clock_ms(),
            )
        except (KeyError, ValueError) as exc:
            code = 404 if isinstance(exc, KeyError) else 409
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        background_tasks.add_task(
            _process_neural_session,
            app.state.store,
            app.state.neural_backend,
            neural_session_id,
            app.state.clock_ms,
        )
        return sealed

    @app.get(
        "/v1/neural/sessions/{neural_session_id}/learning",
        response_model=NeuralLearningStatus,
        dependencies=[Depends(require_neural_token)],
    )
    async def neural_learning_status(
        neural_session_id: str,
    ) -> NeuralLearningStatus:
        record = await app.state.store.get_neural_session(neural_session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="neural session not found")
        return NeuralLearningStatus(
            neural_session_id=neural_session_id,
            status=record.status,
            champion_model_sha256=record.champion_model_sha256,
            challenger_model_sha256=record.shadow_candidate_sha256,
            challenger_selected=record.shadow_candidate_sha256 is not None,
            shadow_candidate_created=record.shadow_candidate_sha256 is not None,
            metrics={},
            error=record.error,
        )

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



async def _process_neural_session(
    store: TrainerStore,
    backend: NeuralBackend,
    neural_session_id: str,
    clock_ms: Callable[[], int],
) -> None:
    root = store.evidence_root
    if root is None:
        await store.update_neural_status(
            neural_session_id,
            NeuralSessionStatus.FAILED,
            clock_ms(),
            error="neural_evidence_storage_unavailable",
        )
        return
    await store.update_neural_status(
        neural_session_id,
        NeuralSessionStatus.PROCESSING,
        clock_ms(),
    )
    try:
        result = await backend.learn_from_sealed_session(
            neural_session_id,
            root / neural_session_id,
        )
    except NeuralBackendNotConfigured as exc:
        await store.update_neural_status(
            neural_session_id,
            NeuralSessionStatus.FAILED,
            clock_ms(),
            error=str(exc),
        )
        return
    except Exception as exc:
        await store.update_neural_status(
            neural_session_id,
            NeuralSessionStatus.FAILED,
            clock_ms(),
            error=f"neural_backend_error:{type(exc).__name__}",
        )
        return

    champion = result.get("champion_model_sha256")
    shadow = result.get("shadow_candidate_sha256")
    await store.update_neural_status(
        neural_session_id,
        NeuralSessionStatus.COMPLETE,
        clock_ms(),
        champion_model_sha256=champion if isinstance(champion, str) else None,
        shadow_candidate_sha256=shadow if isinstance(shadow, str) else None,
        error=None,
    )


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
