from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Protocol

from .schemas import NeuralFrameMetadata, NeuralInferenceResult


class NeuralBackendNotConfigured(RuntimeError):
    pass


class NeuralBackend(Protocol):
    async def infer(
        self,
        metadata: NeuralFrameMetadata,
        image_bytes: bytes,
    ) -> NeuralInferenceResult:
        ...

    async def learn_from_sealed_session(
        self,
        neural_session_id: str,
        evidence_root: Path,
    ) -> dict:
        ...

    def consume_result(self, neural_session_id: str) -> dict | None:
        ...

    def acknowledge_result(self, neural_session_id: str) -> None:
        ...


class NullNeuralBackend:
    async def infer(
        self,
        metadata: NeuralFrameMetadata,
        image_bytes: bytes,
    ) -> NeuralInferenceResult:
        return NeuralInferenceResult(
            neural_session_id=metadata.neural_session_id,
            frame_id=metadata.frame_id,
            source_ms=metadata.source_ms,
            status="abstain",
            champion_model_sha256=None,
            game_state=None,
            observations=(),
            confidence=None,
            inference_ms=None,
            error="neural_backend_not_configured",
        )

    async def learn_from_sealed_session(
        self,
        neural_session_id: str,
        evidence_root: Path,
    ) -> dict:
        raise NeuralBackendNotConfigured("neural_backend_not_configured")

    def consume_result(self, neural_session_id: str) -> dict | None:
        return None

    def acknowledge_result(self, neural_session_id: str) -> None:
        return None


class FileQueueNeuralBackend:
    """Queue sealed matches for a separate BigBANANA neural worker.

    Live inference remains local in the installed client, so server infer()
    intentionally abstains. Post-match learning is durable and independent of
    the player's computer after evidence upload completes.
    """

    def __init__(self, data_root: Path):
        self.root = Path(data_root) / "neural-jobs"
        self.inbox = self.root / "inbox"
        self.outbox = self.root / "outbox"
        self.failed = self.root / "failed"
        for folder in (self.inbox, self.outbox, self.failed):
            folder.mkdir(parents=True, exist_ok=True)

    async def infer(
        self,
        metadata: NeuralFrameMetadata,
        image_bytes: bytes,
    ) -> NeuralInferenceResult:
        del image_bytes
        return NeuralInferenceResult(
            neural_session_id=metadata.neural_session_id,
            frame_id=metadata.frame_id,
            source_ms=metadata.source_ms,
            status="queued",
            error=None,
        )

    async def learn_from_sealed_session(
        self,
        neural_session_id: str,
        evidence_root: Path,
    ) -> dict:
        result = self.consume_result(neural_session_id)
        if result is not None:
            return result
        evidence_root = Path(evidence_root).resolve()
        job = {
            "schema_version": 1,
            "neural_session_id": neural_session_id,
            "evidence_root": str(evidence_root),
            "queued_at_ms": time.time_ns() // 1_000_000,
            "training_location": "BigBANANA",
            "client_compute_required": False,
        }
        target = self.inbox / f"{neural_session_id}.json"
        if not target.exists():
            tmp = target.with_suffix(".json.tmp")
            with tmp.open("x", encoding="utf-8") as handle:
                json.dump(job, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        return {"queued": True}

    def consume_result(self, neural_session_id: str) -> dict | None:
        path = self.outbox / f"{neural_session_id}.json"
        if not path.is_file():
            failed = self.failed / f"{neural_session_id}.json"
            if failed.is_file() and failed.stat().st_size <= 1024 * 1024:
                value = json.loads(failed.read_text(encoding="utf-8"))
                return {
                    "worker_failed": True,
                    "error": str(value.get("error") or "neural_worker_failed")[:300],
                }
            return None
        if path.stat().st_size > 1024 * 1024:
            return {"worker_failed": True, "error": "neural_worker_result_too_large"}
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("neural_session_id") != neural_session_id:
            return {"worker_failed": True, "error": "invalid_neural_worker_result"}
        return value

    def acknowledge_result(self, neural_session_id: str) -> None:
        for folder in (self.outbox, self.failed):
            (folder / f"{neural_session_id}.json").unlink(missing_ok=True)
