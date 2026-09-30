from __future__ import annotations

from fastapi.testclient import TestClient

from remote_trainer.app import create_app


def session_payload():
    return {
        "client_id": "ubuntu-dev",
        "requested_at_ms": 1000,
        "profile": "lab",
    }


def job_payload(session_id: str):
    return {
        "protocol_version": 1,
        "session_id": session_id,
        "job_id": "job-1",
        "episode_id": "episode-1",
        "created_at_ms": 1100,
        "mode": "simulator",
        "state": {
            "schema_version": "0.1.0",
            "revision": 7,
        },
        "decision": {
            "schema_version": "0.1.0",
            "state_revision": 7,
            "action": {"type": "hold_econ"},
            "confidence": 0.8,
        },
        "rollout_count": 64,
        "horizon_steps": 100,
        "opponent_pool": {
            "scripted_bots": ["econ", "aggressive"],
            "historical_policy_versions": [],
            "include_current_policy": True,
        },
    }


def test_health():
    client = TestClient(create_app(clock_ms=lambda: 1000))
    response = client.get("/v1/training/health")
    assert response.status_code == 200
    assert response.json()["protocol_version"] == 1


def test_session_and_job_are_idempotent():
    client = TestClient(create_app(clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()

    payload = job_payload(session["session_id"])
    first = client.post("/v1/training/jobs", json=payload)
    second = client.post("/v1/training/jobs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["request"]["job_id"] == "job-1"
    assert second.json()["request"]["job_id"] == "job-1"


def test_same_job_id_with_different_payload_conflicts():
    client = TestClient(create_app(clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()

    payload = job_payload(session["session_id"])
    assert client.post("/v1/training/jobs", json=payload).status_code == 202

    changed = job_payload(session["session_id"])
    changed["rollout_count"] = 32
    response = client.post("/v1/training/jobs", json=changed)

    assert response.status_code == 409


def test_revision_mismatch_is_rejected():
    client = TestClient(create_app(clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()

    payload = job_payload(session["session_id"])
    payload["decision"]["state_revision"] = 8

    response = client.post("/v1/training/jobs", json=payload)
    assert response.status_code == 409


def test_null_backend_never_fabricates_result():
    client = TestClient(create_app(clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()
    payload = job_payload(session["session_id"])

    response = client.post("/v1/training/jobs", json=payload)
    assert response.status_code == 202

    record = client.get("/v1/training/jobs/job-1").json()
    assert record["status"] == "failed"
    assert record["error"] == "simulator_not_configured"
    assert record["result"] is None
