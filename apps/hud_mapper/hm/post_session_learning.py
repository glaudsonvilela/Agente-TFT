"""Upload a sealed HM4 match to the server-resident neural learner.

The Windows client never trains and never owns neural weights. Upload is
resumable; network failure preserves the local sealed evidence for retry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time

from .neural_service import NeuralServiceClient, NeuralServiceError


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _manifest_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _eligible(session: Path) -> tuple[dict, dict, Path]:
    summary_path = session / "summary.json"
    sealed_path = session / "shadow-learning" / "SEALED.json"
    manifest_path = session / "shadow-learning" / "capture-manifest.json"
    complete_path = session / "COMPLETE.json"
    if not all(p.is_file() for p in (summary_path, sealed_path, manifest_path, complete_path)):
        raise ValueError("sealed_complete_session_required")
    summary = _read(summary_path)
    sealed = _read(sealed_path)
    manifest = _read(manifest_path)
    if summary.get("execution_complete") is not True:
        raise ValueError("session_not_complete")
    if sealed.get("ready_for_post_session_learning") is not True:
        raise ValueError("learning_capture_not_ready")
    if sealed.get("manifest_sha256") != _manifest_sha(manifest_path):
        raise ValueError("learning_manifest_checksum_mismatch")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError("insufficient_learning_frames")
    if manifest.get("active_model_changed_during_session") is not False:
        raise ValueError("live_model_mutability_contract_failed")
    if manifest.get("training_performed_during_session") is not False:
        raise ValueError("local_training_contract_failed")
    return summary, manifest, manifest_path


def _upload_worker(session: Path, job_path: Path) -> None:
    try:
        summary, manifest, manifest_path = _eligible(session)
        state = _read(job_path)
        client = NeuralServiceClient()
        client.connect()

        neural_session_id = state.get("neural_session_id")
        if not isinstance(neural_session_id, str) or not neural_session_id:
            created = client.create_session(
                match_id=str(summary.get("session_id") or session.name),
                created_at_ms=int(time.time() * 1000),
                patch=None,
                set_key=None,
                capture_policy=str(manifest.get("policy") or "hm45_shadow_learning"),
                metadata={
                    "source_kind": (summary.get("source") or {}).get("source_kind"),
                    "stopped_by_match_end": bool(summary.get("stopped_by_match_end")),
                    "match_end_reason": summary.get("match_end_reason"),
                    "client_neural_weights_bundled": True,
                    "client_training_performed": False,
                },
            )
            neural_session_id = created.get("neural_session_id")
            if not isinstance(neural_session_id, str) or not neural_session_id:
                raise NeuralServiceError("Servidor não criou sessão neural válida.")
            state.update(
                neural_session_id=neural_session_id,
                next_frame_index=0,
                status="uploading",
                server_neural_location=True,
            )
            _write(job_path, state)

        frames = manifest["frames"]
        start = int(state.get("next_frame_index") or 0)
        if not 0 <= start <= len(frames):
            raise ValueError("invalid_resume_index")

        for index in range(start, len(frames)):
            row = frames[index]
            image_path = session / "shadow-learning" / str(row["image"])
            image = image_path.read_bytes()
            if hashlib.sha256(image).hexdigest() != row["image_sha256"]:
                raise ValueError(f"learning_frame_checksum_mismatch:{index}")
            result = client.upload_frame(
                neural_session_id,
                frame_id=int(row["frame_id"]),
                source_ms=int(round(float(row["source_ms"]))),
                width=int(row["width"]),
                height=int(row["height"]),
                image=image,
                content_type="image/jpeg",
                capture_role="post_match_learning_evidence",
            )
            state.update(
                status="uploading",
                next_frame_index=index + 1,
                frames_uploaded=index + 1,
                latest_server_inference_status=result.get("status"),
                last_error=None,
            )
            _write(job_path, state)

        client.seal(
            neural_session_id,
            sealed_at_ms=int(time.time() * 1000),
            match_end_reason=str(
                summary.get("match_end_reason")
                or ("user_stop" if summary.get("stopped_by_user") else "capture_end")
            ),
            capture_manifest_sha256=_manifest_sha(manifest_path),
            frame_count=len(frames),
            metadata={
                "local_session_id": summary.get("session_id"),
                "active_model_changed_during_match": False,
                "local_training_performed": False,
            },
        )
        state.update(
            status="server_learning_started",
            next_frame_index=len(frames),
            frames_uploaded=len(frames),
            sealed_remote=True,
            training_location="server",
            local_training_performed=False,
            active_model_changed=False,
            last_error=None,
        )
        _write(job_path, state)
    except Exception as exc:
        try:
            state = _read(job_path)
        except Exception:
            state = {}
        state.update(
            status="retry_server_upload",
            training_location="server",
            local_training_performed=False,
            active_model_changed=False,
            last_error=f"{type(exc).__name__}:{str(exc)[:300]}",
        )
        _write(job_path, state)


def launch_post_session_learning(session_dir: str | Path) -> dict:
    session = Path(session_dir).resolve()
    job_path = session / "shadow-learning" / "post-session-job.json"
    try:
        summary, manifest, _ = _eligible(session)
    except Exception as exc:
        value = {
            "schema_version": 2,
            "status": "not_eligible",
            "reason": str(exc),
            "training_location": "server",
            "local_training_performed": False,
            "active_model_changed": False,
        }
        _write(job_path, value)
        return value

    existing = _read(job_path) if job_path.is_file() else {}
    if existing.get("status") == "server_learning_started":
        return existing
    if existing.get("worker_active") is True:
        return existing

    value = {
        **existing,
        "schema_version": 2,
        "status": "queued_server_upload",
        "worker_active": True,
        "match_id": str(summary.get("session_id") or session.name),
        "frame_count": len(manifest["frames"]),
        "next_frame_index": int(existing.get("next_frame_index") or 0),
        "training_location": "server",
        "server_service": "tft.bigbanana.io",
        "local_neural_weights_bundled": True,
        "local_training_performed": False,
        "active_model_changed": False,
        "human_review_required": False,
        "runtime_approved": False,
    }
    _write(job_path, value)

    def work():
        try:
            _upload_worker(session, job_path)
        finally:
            try:
                state = _read(job_path)
                state["worker_active"] = False
                _write(job_path, state)
            except Exception:
                pass

    threading.Thread(
        target=work,
        daemon=True,
        name="tft-server-neural-upload",
    ).start()
    return value


def resume_pending_post_session_uploads(
    sessions_root: str | Path,
    *,
    limit: int = 8,
) -> list[dict]:
    """Resume recent sealed uploads after app restart without player action."""
    root = Path(sessions_root)
    if not root.is_dir():
        return []
    sessions = sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[: max(1, min(limit, 32))]
    results = []
    for session in sessions:
        job_path = session / "shadow-learning" / "post-session-job.json"
        if job_path.is_file():
            try:
                state = _read(job_path)
            except Exception:
                state = {}
            if state.get("status") in {"not_eligible"}:
                continue
            if state.get("status") == "server_learning_started":
                # Evidence is already safely on BigBANANA; model updater polling
                # handles a champion that may be published later.
                results.append(state)
                continue
            state["worker_active"] = False
            _write(job_path, state)
        try:
            results.append(launch_post_session_learning(session))
        except Exception as exc:
            results.append({
                "status": "resume_failed",
                "session": str(session),
                "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            })
    return results
