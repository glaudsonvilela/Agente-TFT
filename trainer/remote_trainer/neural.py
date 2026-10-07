from __future__ import annotations

from pathlib import Path
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
