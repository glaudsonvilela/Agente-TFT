from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from remote_trainer.app import create_app
from remote_trainer.store import NullTrainerBackend, TrainerStore


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
    assert response.json()["simulator_ready"] is False


def test_sqlite_preserves_training_data_after_server_restart(tmp_path: Path):
    database = tmp_path / "trainer.sqlite3"
    first = TestClient(create_app(store=TrainerStore(backend=NullTrainerBackend(), db_path=database),
                                  clock_ms=lambda: 1000))
    session = first.post("/v1/training/sessions", json=session_payload()).json()
    payload = job_payload(session["session_id"])
    payload["rollout_count"] = 500
    assert first.post("/v1/training/jobs", json=payload).status_code == 202
    second = TestClient(create_app(store=TrainerStore(backend=NullTrainerBackend(), db_path=database),
                                   clock_ms=lambda: 2000))
    retained = second.get("/v1/training/jobs/job-1").json()
    assert retained["request"]["rollout_count"] == 500
    assert retained["status"] == "failed"
    assert retained["error"] == "simulator_not_configured"
    assert second.post("/v1/training/jobs", json=payload).status_code == 202
    assert second.get("/v1/training/health").json()["storage"] == "sqlite"


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



def test_protected_endpoints_require_bearer_token():
    app = create_app(
        clock_ms=lambda: 1000,
        api_token="secret-token",
    )
    client = TestClient(app)

    unauthorized = client.post(
        "/v1/training/sessions",
        json=session_payload(),
    )
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/v1/training/sessions",
        json=session_payload(),
        headers={"Authorization": "Bearer secret-token"},
    )
    assert authorized.status_code == 201


def test_health_remains_public_when_token_is_enabled():
    app = create_app(
        clock_ms=lambda: 1000,
        api_token="secret-token",
    )
    client = TestClient(app)

    response = client.get("/v1/training/health")
    assert response.status_code == 200



class FakeShadowBackend:
    def __init__(self):
        self.states = {}

    async def initialize(self, shadow_id: str, state: dict) -> dict:
        self.states[shadow_id] = dict(state)
        return {
            "simulated_revision": state["revision"],
            "divergence": None,
        }

    async def reconcile(self, shadow_id: str, state: dict) -> dict:
        previous = self.states[shadow_id]
        self.states[shadow_id] = dict(state)
        return {
            "simulated_revision": state["revision"],
            "divergence": {
                "revision_delta": state["revision"] - previous["revision"],
            },
        }

    async def step(self, shadow_id: str, decision: dict) -> dict:
        state = dict(self.states[shadow_id])
        state["revision"] = state["revision"] + 1
        self.states[shadow_id] = state
        return {
            "simulated_revision": state["revision"],
            "action": decision["action"],
            "reward": 0.25,
            "metrics": {"fixture": True},
        }

    async def end(self, shadow_id: str) -> None:
        return None


def shadow_payload(training_session_id: str):
    return {
        "training_session_id": training_session_id,
        "episode_id": "episode-1",
        "created_at_ms": 1100,
        "state": {
            "schema_version": "0.1.0",
            "revision": 7,
        },
    }


def test_null_shadow_backend_is_explicitly_degraded():
    client = TestClient(create_app(clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()

    response = client.post(
        "/v1/shadow/sessions",
        json=shadow_payload(session["session_id"]),
    )
    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "degraded"
    assert record["error"] == "simulator_not_configured"


def test_shadow_session_sync_and_step_with_backend():
    store = TrainerStore(
        backend=NullTrainerBackend(),
        shadow_backend=FakeShadowBackend(),
    )
    client = TestClient(create_app(store=store, clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()

    created = client.post(
        "/v1/shadow/sessions",
        json=shadow_payload(session["session_id"]),
    )
    assert created.status_code == 201
    shadow = created.json()
    assert shadow["status"] == "active"
    assert shadow["real_revision"] == 7
    shadow_id = shadow["shadow_id"]

    stepped = client.post(
        f"/v1/shadow/sessions/{shadow_id}/step",
        json={
            "observed_at_ms": 1200,
            "decision": {
                "state_revision": 7,
                "action": {"type": "hold_econ"},
            },
        },
    )
    assert stepped.status_code == 200
    stepped_body = stepped.json()
    assert stepped_body["simulated_revision"] == 8
    assert stepped_body["last_step"]["reward"] == 0.25

    synced = client.post(
        f"/v1/shadow/sessions/{shadow_id}/sync",
        json={
            "observed_at_ms": 1300,
            "state": {
                "schema_version": "0.1.0",
                "revision": 8,
            },
        },
    )
    assert synced.status_code == 200
    synced_body = synced.json()
    assert synced_body["real_revision"] == 8
    assert synced_body["simulated_revision"] == 8
    assert synced_body["last_divergence"]["revision_delta"] == 0

    ended = client.post(f"/v1/shadow/sessions/{shadow_id}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"


def test_shadow_step_rejects_stale_decision_revision():
    store = TrainerStore(
        backend=NullTrainerBackend(),
        shadow_backend=FakeShadowBackend(),
    )
    client = TestClient(create_app(store=store, clock_ms=lambda: 1000))
    session = client.post("/v1/training/sessions", json=session_payload()).json()
    shadow = client.post(
        "/v1/shadow/sessions",
        json=shadow_payload(session["session_id"]),
    ).json()

    response = client.post(
        f"/v1/shadow/sessions/{shadow['shadow_id']}/step",
        json={
            "observed_at_ms": 1200,
            "decision": {
                "state_revision": 6,
                "action": {"type": "hold_econ"},
            },
        },
    )
    assert response.status_code == 409
