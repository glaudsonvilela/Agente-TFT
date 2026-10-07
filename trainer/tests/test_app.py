from __future__ import annotations

from pathlib import Path
import hashlib
import json
import zipfile
from fastapi.testclient import TestClient

from remote_trainer.app import create_app
from remote_trainer.neural import FileQueueNeuralBackend
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


def test_dashboard_shows_storage_without_claiming_learning(tmp_path: Path):
    database = tmp_path / "trainer.sqlite3"
    imports = tmp_path / "imports"
    imports.mkdir()
    (imports / "sample.rar").write_bytes(b"diagnostic")
    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=database),
        clock_ms=lambda: 1000, api_token="secret-token",
    ))
    before = client.get("/v1/training/dashboard-metrics").json()
    assert before["evidence_files"] == 1
    assert before["paths_completed"] == 0
    assert before["paths_in_running_jobs"] == 0
    assert "container" in before["resources"] and "host" in before["resources"]
    assert before["neural_training_status"] == "not_started"
    assert before["simulator_ready"] is False

    session = client.post("/v1/training/sessions", json=session_payload(),
                          headers={"Authorization": "Bearer secret-token"}).json()
    payload = job_payload(session["session_id"])
    payload["rollout_count"] = 50
    assert client.post("/v1/training/jobs", json=payload,
                       headers={"Authorization": "Bearer secret-token"}).status_code == 202
    after = client.get("/v1/training/dashboard-metrics").json()
    assert after["sessions"] == 1
    assert after["paths_requested"] == 50
    assert after["paths_completed"] == 0
    assert after["paths_in_running_jobs"] == 0
    assert after["jobs_by_status"]["failed"] == 1
    assert after["recent_jobs"][0]["error"] == "simulator_not_configured"
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Caminhos simulados" in page.text
    assert "Uso do BigBANANA" in page.text
    assert "Execuções recentes" in page.text


def test_dashboard_counts_only_sealed_neural_candidate(tmp_path: Path):
    folder = tmp_path / "experiments" / "hm45-l3-test"
    train = folder / "training-v2"
    evaluation = folder / "evaluation-v2"
    train.mkdir(parents=True)
    evaluation.mkdir()
    (train / "training-report.json").write_text(json.dumps(
        {"model_trained": True, "optimizer_steps": 600}))
    (train / "model.npz").write_bytes(b"trained weights")
    (evaluation / "report.json").write_text(json.dumps({"summary": {
        "model_trained": True, "profile_promoted": False, "frames": 121,
        "real_inference_ms_p95": .66, "independent_match_accuracy": None}}))
    (evaluation / "model.onnx").write_bytes(b"exported candidate")
    for directory, seal_name, names in (
        (train, "TRAINED.json", ("training-report.json", "model.npz")),
        (evaluation, "COMPLETE.json", ("report.json", "model.onnx"))):
        (directory / seal_name).write_text(json.dumps({
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in names}))
    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=tmp_path / "trainer.sqlite3")))
    candidate = client.get("/v1/training/dashboard-metrics").json()
    assert candidate["neural_training_status"] == "candidate_trained_unpromoted"
    assert candidate["neural_experiments"][0]["optimizer_steps"] == 600
    assert candidate["simulator_ready"] is False
    (folder / "compare-previous.json").write_text(json.dumps({
        "frames": 46, "previous": {"shop:proposal": 43},
        "candidate": {"shop:proposal": 5}, "candidate_promoted": False}))
    regression = client.get("/v1/training/dashboard-metrics").json()
    assert regression["neural_training_status"] == "regression_rejected"
    assert regression["neural_experiments"][0]["comparison"]["frames"] == 46
    (evaluation / "model.onnx").write_bytes(b"corrupted")
    unsealed = client.get("/v1/training/dashboard-metrics").json()
    assert unsealed["neural_training_status"] == "not_started"


def test_dashboard_distinguishes_imported_windows_diagnostic_from_training(tmp_path: Path):
    imports = tmp_path / "imports"
    imports.mkdir()
    archive = imports / "hm4-20261004-test.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("hm4-20261004-test/summary.json", json.dumps({
            "execution_complete": True, "neural_mode": "shadow_diagnostic",
            "model_trained": False, "board_cells_validated": False,
            "versions": {"neural_enabled": True}, "counts": {"mapped_frames": 2707}}))
    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=tmp_path / "trainer.sqlite3")))
    metrics = client.get("/v1/training/dashboard-metrics").json()
    assert metrics["evidence_files"] == 1
    assert metrics["neural_training_status"] == "not_started"
    assert metrics["latest_imported_runtime"]["diagnostic_active"] is True
    assert metrics["latest_imported_runtime"]["model_trained"] is False
    assert metrics["latest_imported_runtime"]["mapped_frames"] == 2707



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


def test_policy_lab_is_visible_without_activating_hud_simulator(tmp_path):
    folder = tmp_path/'policy-runs'/'lab'; folder.mkdir(parents=True)
    (folder/'progress.json').write_text(json.dumps(dict(kind='policy_selfplay',
        runtime_promoted=False, status='completed', matches_completed=26, transitions=106652)))
    (tmp_path/'simulation-coverage.json').write_text(json.dumps(dict(kind='simulation_coverage',
        patch='18.3', champions=74, executable_abilities=0, current_patch_training_ready=False)))
    client = TestClient(create_app(store=TrainerStore(backend=NullTrainerBackend(), db_path=tmp_path/'trainer.sqlite3')))
    metrics = client.get('/v1/training/dashboard-metrics').json()
    assert metrics['policy_learning_jobs'][0]['matches_completed'] == 26
    assert metrics['simulation_coverage']['current_patch_training_ready'] is False
    assert metrics['simulator_ready'] is False
    assert metrics['paths_completed'] == 0
    assert 'Rede de decisões' in client.get('/dashboard').text


class FakeNeuralBackend:
    async def infer(self, metadata, image_bytes):
        from remote_trainer.schemas import NeuralInferenceResult
        return NeuralInferenceResult(
            neural_session_id=metadata.neural_session_id,
            frame_id=metadata.frame_id,
            source_ms=metadata.source_ms,
            status="accepted",
            champion_model_sha256="a" * 64,
            game_state={"revision": metadata.frame_id},
            observations=({"kind": "fixture"},),
            confidence=0.9,
            inference_ms=4.0,
        )

    async def learn_from_sealed_session(self, neural_session_id, evidence_root):
        assert evidence_root.is_dir()
        return {
            "champion_model_sha256": "a" * 64,
            "shadow_candidate_sha256": "b" * 64,
        }


def _neural_client(client, installation_id="install-a"):
    token = client.post(
        "/v1/neural/client-session",
        json={"installation_id": installation_id},
    )
    assert token.status_code == 200
    value = token.json()["token"]
    return {"Authorization": "Bearer " + value}


def test_neural_client_session_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("NEURAL_CLIENT_SESSIONS_ENABLED", raising=False)
    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=tmp_path / "trainer.sqlite3")
    ))
    response = client.post(
        "/v1/neural/client-session",
        json={"installation_id": "install-a"},
    )
    assert response.status_code == 503


def test_server_resident_neural_session_upload_and_shadow_learning(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=tmp_path / "trainer.sqlite3",
    )
    client = TestClient(create_app(
        store=store,
        neural_backend=FakeNeuralBackend(),
        clock_ms=lambda: 10_000,
    ))
    headers = _neural_client(client)
    created = client.post(
        "/v1/neural/sessions",
        headers=headers,
        json={
            "client_id": "install-a",
            "match_id": "match-1",
            "created_at_ms": 1000,
            "patch": "18.3",
            "set_key": "TFTSet18",
            "capture_policy": "hm45_post_session_shadow_learning_capture_v1",
            "metadata": {"local_neural_weights_bundled": False},
        },
    )
    assert created.status_code == 201
    neural_id = created.json()["neural_session_id"]

    for frame_id, source_ms, body in ((11, 0, b"jpeg-one"), (12, 2000, b"jpeg-two")):
        digest = hashlib.sha256(body).hexdigest()
        response = client.post(
            f"/v1/neural/sessions/{neural_id}/frames",
            params={
                "frame_id": frame_id,
                "source_ms": source_ms,
                "width": 1920,
                "height": 1080,
                "image_sha256": digest,
                "capture_role": "post_match_learning_evidence",
            },
            headers={**headers, "Content-Type": "image/jpeg"},
            content=body,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        assert response.json()["champion_model_sha256"] == "a" * 64

    sealed = client.post(
        f"/v1/neural/sessions/{neural_id}/seal",
        headers=headers,
        json={
            "sealed_at_ms": 9000,
            "match_end_reason": "terminal_hp_confirmed",
            "capture_manifest_sha256": "c" * 64,
            "frame_count": 2,
            "metadata": {"active_model_changed_during_match": False},
        },
    )
    assert sealed.status_code == 200

    learning = client.get(
        f"/v1/neural/sessions/{neural_id}/learning",
        headers=headers,
    )
    assert learning.status_code == 200
    result = learning.json()
    assert result["status"] == "complete"
    assert result["champion_model_sha256"] == "a" * 64
    assert result["challenger_model_sha256"] == "b" * 64
    assert result["shadow_candidate_created"] is True

    evidence = tmp_path / "neural-evidence" / neural_id / "frames"
    assert (evidence / "000000000011.jpg").read_bytes() == b"jpeg-one"
    assert (evidence / "000000000012.jpg").read_bytes() == b"jpeg-two"


def test_neural_session_isolation_between_installations(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=tmp_path / "trainer.sqlite3"),
        neural_backend=FakeNeuralBackend(),
        clock_ms=lambda: 10_000,
    ))
    a = _neural_client(client, "install-a")
    b = _neural_client(client, "install-b")
    created = client.post(
        "/v1/neural/sessions",
        headers=a,
        json={
            "client_id": "install-a",
            "match_id": "match-1",
            "created_at_ms": 1000,
            "capture_policy": "test",
        },
    )
    neural_id = created.json()["neural_session_id"]
    assert client.get(f"/v1/neural/sessions/{neural_id}", headers=a).status_code == 200
    assert client.get(f"/v1/neural/sessions/{neural_id}", headers=b).status_code == 403


def _write_champion_bundle(path: Path, *, version: str, generation: int, model_identity: str):
    metadata = b'{"schema_version":2,"coordinate_format":"normalized_tlbr","panels":["bench","shop"]}'
    model = b"fake-onnx"
    files = [
        {
            "path": "models/deployment-candidate.json",
            "sha256": hashlib.sha256(metadata).hexdigest(),
            "bytes": len(metadata),
            "role": "l3_metadata",
        },
        {
            "path": "models/candidate-model.onnx",
            "sha256": hashlib.sha256(model).hexdigest(),
            "bytes": len(model),
            "role": "l3_onnx",
        },
    ]
    package = {
        "schema_version": 1,
        "package_type": "agente_tft_neural_runtime_bundle",
        "version": version,
        "generation": generation,
        "runtime_min_version": "0.7.0",
        "model_identity_sha256": model_identity,
        "files": files,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model-package.json", json.dumps(package))
        archive.writestr("models/deployment-candidate.json", metadata)
        archive.writestr("models/candidate-model.onnx", model)


def test_champion_registry_publish_and_client_download(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    database = tmp_path / "trainer.sqlite3"
    staging = tmp_path / "champion-staging"
    staging.mkdir()
    bundle = staging / "candidate.zip"
    identity = "d" * 64
    _write_champion_bundle(bundle, version="2026.10.06.1", generation=1, model_identity=identity)

    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=database),
        api_token="admin-secret",
        clock_ms=lambda: 20_000,
    ))
    publish = client.post(
        "/v1/neural/champion/publish",
        headers={"Authorization": "Bearer admin-secret"},
        json={
            "channel": "stable",
            "version": "2026.10.06.1",
            "generation": 1,
            "staged_filename": "candidate.zip",
            "runtime_min_version": "0.7.0",
            "model_identity_sha256": identity,
            "training_provenance": {"fixture": True},
        },
    )
    assert publish.status_code == 200
    manifest = publish.json()
    assert manifest["approved"] is True
    assert manifest["generation"] == 1
    assert manifest["model_identity_sha256"] == identity

    neural_headers = _neural_client(client, "install-champion")
    fetched = client.get("/v1/neural/champion?channel=stable", headers=neural_headers)
    assert fetched.status_code == 200
    assert fetched.json()["package_sha256"] == manifest["package_sha256"]

    package = client.get(
        "/v1/neural/champion/package/stable/1",
        headers=neural_headers,
    )
    assert package.status_code == 200
    assert hashlib.sha256(package.content).hexdigest() == manifest["package_sha256"]
    assert package.headers["x-tft-package-sha256"] == manifest["package_sha256"]

    forbidden = client.post(
        "/v1/neural/champion/publish",
        headers=neural_headers,
        json={
            "channel": "stable",
            "version": "bad",
            "generation": 2,
            "staged_filename": "missing.zip",
            "runtime_min_version": "0.7.0",
            "model_identity_sha256": "e" * 64,
        },
    )
    assert forbidden.status_code == 401


def test_champion_registry_rejects_nonincreasing_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    database = tmp_path / "trainer.sqlite3"
    staging = tmp_path / "champion-staging"
    staging.mkdir()
    client = TestClient(create_app(
        store=TrainerStore(backend=NullTrainerBackend(), db_path=database),
        api_token="admin-secret",
        clock_ms=lambda: 20_000,
    ))
    for filename in ("one.zip", "same.zip"):
        _write_champion_bundle(staging / filename, version="v1", generation=1, model_identity="f" * 64)
    payload = {
        "channel": "stable",
        "version": "v1",
        "generation": 1,
        "staged_filename": "one.zip",
        "runtime_min_version": "0.7.0",
        "model_identity_sha256": "f" * 64,
    }
    assert client.post(
        "/v1/neural/champion/publish",
        headers={"Authorization": "Bearer admin-secret"},
        json=payload,
    ).status_code == 200
    payload["staged_filename"] = "same.zip"
    assert client.post(
        "/v1/neural/champion/publish",
        headers={"Authorization": "Bearer admin-secret"},
        json=payload,
    ).status_code == 409


def test_neural_admission_limit_returns_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=tmp_path / "trainer.sqlite3",
    )
    client = TestClient(create_app(store=store, clock_ms=lambda: 10_000))
    headers = _neural_client(client, "install-limit")
    for index in range(4):
        response = client.post(
            "/v1/neural/sessions",
            headers=headers,
            json={
                "client_id": "install-limit",
                "match_id": f"match-{index}",
                "created_at_ms": index + 1,
                "capture_policy": "test",
            },
        )
        assert response.status_code == 201
    rejected = client.post(
        "/v1/neural/sessions",
        headers=headers,
        json={
            "client_id": "install-limit",
            "match_id": "match-over-limit",
            "created_at_ms": 99,
            "capture_policy": "test",
        },
    )
    assert rejected.status_code == 409
    assert "unfinished" in rejected.json()["detail"]


def test_neural_frame_retry_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=tmp_path / "trainer.sqlite3",
    )
    client = TestClient(create_app(
        store=store,
        neural_backend=FakeNeuralBackend(),
        clock_ms=lambda: 10_000,
    ))
    headers = _neural_client(client, "install-idempotent")
    created = client.post(
        "/v1/neural/sessions",
        headers=headers,
        json={
            "client_id": "install-idempotent",
            "match_id": "match-retry",
            "created_at_ms": 1,
            "capture_policy": "test",
        },
    ).json()
    neural_id = created["neural_session_id"]
    body = b"same-jpeg"
    params = {
        "frame_id": 7,
        "source_ms": 2000,
        "width": 1920,
        "height": 1080,
        "image_sha256": hashlib.sha256(body).hexdigest(),
        "capture_role": "post_match_learning_evidence",
    }
    first = client.post(
        f"/v1/neural/sessions/{neural_id}/frames",
        params=params,
        headers={**headers, "Content-Type": "image/jpeg"},
        content=body,
    )
    second = client.post(
        f"/v1/neural/sessions/{neural_id}/frames",
        params=params,
        headers={**headers, "Content-Type": "image/jpeg"},
        content=body,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "queued"
    record = client.get(
        f"/v1/neural/sessions/{neural_id}",
        headers=headers,
    ).json()
    assert record["frames_received"] == 1
    assert record["bytes_received"] == len(body)


def test_central_neural_health_reports_file_queue_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_WORKER_QUEUE_ENABLED", "1")
    store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=tmp_path / "trainer.sqlite3",
    )
    with TestClient(create_app(store=store, clock_ms=lambda: 10_000)) as client:
        health = client.get("/v1/training/health")
        assert health.status_code == 200
        value = health.json()
        assert value["neural_backend_ready"] is True
        central = value["central_neural"]
        assert central["learning_backend"] == "file_queue_worker"
        assert central["stable_generation"] is None
        assert central["queue"] == {
            "inbox": 0,
            "working": 0,
            "outbox": 0,
            "failed": 0,
        }


def test_file_queue_neural_learning_survives_client_and_reconciles(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURAL_CLIENT_SESSIONS_ENABLED", "1")
    store = TrainerStore(
        backend=NullTrainerBackend(),
        db_path=tmp_path / "trainer.sqlite3",
    )
    backend = FileQueueNeuralBackend(tmp_path)
    app = create_app(
        store=store,
        neural_backend=backend,
        clock_ms=lambda: 10_000,
    )
    with TestClient(app) as client:
        headers = _neural_client(client, "install-queue")
        created = client.post(
            "/v1/neural/sessions",
            headers=headers,
            json={
                "client_id": "install-queue",
                "match_id": "match-queue",
                "created_at_ms": 1,
                "capture_policy": "test",
            },
        )
        assert created.status_code == 201
        neural_id = created.json()["neural_session_id"]

        for frame_id, source_ms in ((1, 0), (2, 2000)):
            body = f"jpeg-{frame_id}".encode()
            response = client.post(
                f"/v1/neural/sessions/{neural_id}/frames",
                params={
                    "frame_id": frame_id,
                    "source_ms": source_ms,
                    "width": 1920,
                    "height": 1080,
                    "image_sha256": hashlib.sha256(body).hexdigest(),
                    "capture_role": "post_match_learning_evidence",
                },
                headers={**headers, "Content-Type": "image/jpeg"},
                content=body,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

        sealed = client.post(
            f"/v1/neural/sessions/{neural_id}/seal",
            headers=headers,
            json={
                "sealed_at_ms": 9000,
                "match_end_reason": "capture_end",
                "capture_manifest_sha256": "c" * 64,
                "frame_count": 2,
            },
        )
        assert sealed.status_code == 200
        assert (backend.inbox / f"{neural_id}.json").is_file()
        status = client.get(
            f"/v1/neural/sessions/{neural_id}/learning",
            headers=headers,
        ).json()
        assert status["status"] == "processing"

        # The real worker is a separate process/container. Simulate its durable
        # outbox result, then let the API reconcile it.
        (backend.outbox / f"{neural_id}.json").write_text(json.dumps({
            "schema_version": 1,
            "neural_session_id": neural_id,
            "champion_model_sha256": "a" * 64,
            "shadow_candidate_sha256": "b" * 64,
            "training_location": "BigBANANA",
            "client_compute_required": False,
        }))
        reconciled = client.get(
            f"/v1/neural/sessions/{neural_id}/learning",
            headers=headers,
        )
        assert reconciled.status_code == 200
        value = reconciled.json()
        assert value["status"] == "complete"
        assert value["champion_model_sha256"] == "a" * 64
        assert value["challenger_model_sha256"] == "b" * 64
        assert value["shadow_candidate_created"] is True
        assert not (backend.outbox / f"{neural_id}.json").exists()
