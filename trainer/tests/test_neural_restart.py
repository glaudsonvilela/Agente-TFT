from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from remote_trainer.app import create_app
from remote_trainer.schemas import NeuralSessionRequest, NeuralSessionStatus
from remote_trainer.store import NullTrainerBackend, TrainerStore


def test_api_startup_recovers_sealed_session_into_neural_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_WORKER_QUEUE_ENABLED", "1")
    database = tmp_path / "trainer.sqlite3"
    store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=database,
    )
    request = NeuralSessionRequest(
        client_id="install-restart",
        match_id="match-restart",
        created_at_ms=1000,
        capture_policy="restart-fixture",
    )
    record = asyncio.run(store.create_neural_session(request, 1000))
    asyncio.run(store.record_neural_frame(record.neural_session_id, 1000, 10, 1100))
    asyncio.run(store.record_neural_frame(record.neural_session_id, 3000, 10, 1200))
    asyncio.run(store.seal_neural_session(record.neural_session_id, 1300))

    evidence = tmp_path / "neural-evidence" / record.neural_session_id
    (evidence / "seal.json").write_text(json.dumps({
        "sealed_at_ms": 1300,
        "match_end_reason": "fixture",
        "capture_manifest_sha256": "a" * 64,
        "frame_count": 2,
    }))

    # New app instance simulates the API process coming back after the session
    # was durably sealed but before its background task had been queued.
    restarted_store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=database,
    )
    app = create_app(
        store=restarted_store,
        clock_ms=lambda: 2000,
    )
    with TestClient(app):
        restored = restarted_store.neural_sessions[record.neural_session_id]
        assert restored.status == NeuralSessionStatus.PROCESSING
        inbox = tmp_path / "neural-jobs" / "inbox" / f"{record.neural_session_id}.json"
        assert inbox.is_file()
        job = json.loads(inbox.read_text())
        assert job["neural_session_id"] == record.neural_session_id
        assert job["training_location"] == "BigBANANA"
        assert job["client_compute_required"] is False
