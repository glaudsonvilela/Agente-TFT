from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from types import SimpleNamespace

from hm.learning_capture import ShadowLearningRecorder
from hm.post_session_learning import _eligible, launch_post_session_learning
from hm.model_update import ModelUpdater, active_model_metadata


def frame(index: int, source_ms: float):
    width, height = 64, 36
    rgb = bytes([(index * 17) % 255, 40, 90]) * (width * height)
    return SimpleNamespace(
        id=index,
        pts_ms=source_ms,
        width=width,
        height=height,
        rgb=rgb,
        epoch=0,
    )


def test_shadow_learning_recorder_is_bounded_and_sealed(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    recorder = ShadowLearningRecorder(
        session,
        interval_ms=2000,
        max_frames=60,
        max_bytes=128 * 1024**2,
        jpeg_quality=88,
    )
    assert recorder.submit(frame(1, 0))
    assert not recorder.submit(frame(2, 500))
    assert recorder.submit(frame(3, 2000))
    sealed = recorder.close(
        session_id="abc",
        source={"source_kind": "native_capture"},
        runtime_model_sha256="deadbeef",
    )
    assert sealed["ready_for_post_session_learning"] is True
    manifest = json.loads((session / "shadow-learning" / "capture-manifest.json").read_text())
    assert manifest["counts"]["saved"] == 2
    assert manifest["counts"]["normalized_frames"] == 2
    assert manifest["learning_geometry"] == "canonical_1920x1080_rgb_jpeg_v1"
    assert all((row["width"], row["height"]) == (1920, 1080) for row in manifest["frames"])
    assert all(row["normalized_to_1920x1080"] is True for row in manifest["frames"])
    assert manifest["training_performed_during_session"] is False
    assert manifest["active_model_changed_during_session"] is False
    assert [row["image"] for row in manifest["frames"]] == [
        "frames/000000.jpg",
        "frames/000001.jpg",
    ]


def test_paused_replay_does_not_upload_duplicate_training_frames(tmp_path):
    session = tmp_path / "replay"
    session.mkdir()
    recorder = ShadowLearningRecorder(session, interval_ms=5000,
        max_frames=60, max_bytes=128 * 1024**2, jpeg_quality=88)
    assert recorder.submit(frame(1, 0))
    paused = frame(2, 5000)
    paused.rgb = frame(1, 0).rgb
    assert recorder.submit(paused)
    assert recorder.submit(frame(3, 10000))
    sealed = recorder.close("replay", {"input_kind": "recorded_replay_on_screen"}, None)
    assert sealed["frames"] == 2
    manifest = json.loads((session / "shadow-learning" / "capture-manifest.json").read_text())
    assert manifest["counts"]["skipped_duplicate"] == 1
    assert manifest["source"]["input_kind"] == "recorded_replay_on_screen"


def test_shop_and_bench_changes_are_saved_before_periodic_deadline(tmp_path):
    session = tmp_path / "events"
    session.mkdir()
    recorder = ShadowLearningRecorder(session, interval_ms=5000,
        max_frames=60, max_bytes=128 * 1024**2, jpeg_quality=88)

    def changed_frame(index, source_ms, regions):
        width, height = 192, 108
        pixels = bytearray(width * height * 3)
        for x0, y0, x1, y1 in regions:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    offset = (y * width + x) * 3
                    pixels[offset:offset + 3] = b"\xff\xff\xff"
        return SimpleNamespace(id=index, pts_ms=source_ms, width=width,
                               height=height, rgb=bytes(pixels), epoch=0)

    assert recorder.submit(changed_frame(1, 0, []))
    shop = [(55, 103, 157, 108)]
    assert recorder.submit(changed_frame(2, 1000, shop))
    assert not recorder.submit(changed_frame(3, 1500, shop))
    assert recorder.submit(changed_frame(4, 2000, shop + [(34, 76, 158, 95)]))
    recorder.close("events", {"source_kind": "native_capture"}, None)
    manifest = json.loads((session / "shadow-learning" / "capture-manifest.json").read_text())
    assert [row["capture_event"] for row in manifest["frames"]] == [
        "periodic", "shop_change", "bench_or_item_change",
    ]
    assert all(row["ground_truth"] is False for row in manifest["frames"])


def test_replay_seek_resets_learning_deadline(tmp_path):
    session = tmp_path / "seek"
    session.mkdir()
    recorder = ShadowLearningRecorder(session, interval_ms=5000,
        max_frames=60, max_bytes=128 * 1024**2, jpeg_quality=88)
    assert recorder.submit(frame(1, 10000))
    rewind = frame(2, 1000)
    rewind.epoch = 1
    assert recorder.submit(rewind)
    sealed = recorder.close("seek", {"input_kind": "recorded_replay_on_screen"}, None)
    assert sealed["frames"] == 2


def test_post_session_launcher_fails_closed_without_complete_session(tmp_path):
    session = tmp_path / "session"
    (session / "shadow-learning").mkdir(parents=True)
    value = launch_post_session_learning(session)
    assert value["status"] == "not_eligible"
    assert value["local_training_performed"] is False
    assert value["active_model_changed"] is False


def test_post_session_launcher_queues_server_upload_without_local_training(tmp_path, monkeypatch):
    session = tmp_path / "session"
    session.mkdir()
    recorder = ShadowLearningRecorder(
        session,
        interval_ms=2000,
        max_frames=60,
        max_bytes=128 * 1024**2,
        jpeg_quality=88,
    )
    assert recorder.submit(frame(1, 0))
    assert recorder.submit(frame(2, 2000))
    recorder.close(
        session_id="abc",
        source={"source_kind": "native_capture"},
        runtime_model_sha256=None,
    )
    (session / "summary.json").write_text(json.dumps({
        "execution_complete": True,
        "session_id": "abc",
        "active_model_changed_during_session": False,
        "source": {"source_kind": "native_capture"},
    }))
    (session / "COMPLETE.json").write_text("{}")

    summary, manifest, manifest_path = _eligible(session)
    assert summary["execution_complete"] is True
    sealed = json.loads((session / "shadow-learning" / "SEALED.json").read_text())
    assert sealed["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert len(manifest["frames"]) == 2

    import hm.post_session_learning as post
    monkeypatch.setattr(post, "_upload_worker", lambda *args, **kwargs: None)
    value = post.launch_post_session_learning(session)
    assert value["status"] == "queued_server_upload"
    assert value["training_location"] == "server"
    assert value["local_neural_weights_bundled"] is True
    assert value["local_training_performed"] is False
    assert value["active_model_changed"] is False



def _champion_zip(path: Path, *, generation: int, version: str, identity: str):
    metadata = b'{"schema_version":2,"coordinate_format":"normalized_tlbr","panels":["bench","shop"]}'
    model = b"fake-onnx"
    rows = [
        {"path": "models/deployment-candidate.json",
         "sha256": hashlib.sha256(metadata).hexdigest(),
         "bytes": len(metadata), "role": "l3_metadata"},
        {"path": "models/candidate-model.onnx",
         "sha256": hashlib.sha256(model).hexdigest(),
         "bytes": len(model), "role": "l3_onnx"},
    ]
    manifest = {
        "schema_version": 1,
        "package_type": "agente_tft_neural_runtime_bundle",
        "version": version,
        "generation": generation,
        "runtime_min_version": "0.7.0",
        "model_identity_sha256": identity,
        "files": rows,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model-package.json", json.dumps(manifest))
        archive.writestr("models/deployment-candidate.json", metadata)
        archive.writestr("models/candidate-model.onnx", model)


class _FakeChampionClient:
    def __init__(self, package: Path, generation: int, version: str, identity: str):
        self.package = package
        self.generation = generation
        self.version = version
        self.identity = identity

    def connect(self):
        return {"token": "x" * 64, "expires_at_ms": 999999999}

    def champion_manifest(self, channel="stable"):
        assert channel == "stable"
        return {
            "schema_version": 1,
            "channel": "stable",
            "version": self.version,
            "generation": self.generation,
            "published_at_ms": 1,
            "package_sha256": hashlib.sha256(self.package.read_bytes()).hexdigest(),
            "package_bytes": self.package.stat().st_size,
            "package_path": f"/v1/neural/champion/package/stable/{self.generation}",
            "runtime_min_version": "0.7.0",
            "model_identity_sha256": self.identity,
            "approved": True,
            "training_provenance": {},
        }

    def download_champion_package(self, channel, generation, destination, max_bytes=512*1024*1024):
        assert channel == "stable" and generation == self.generation
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.package, destination)
        return {
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "bytes": destination.stat().st_size,
            "path": str(destination),
        }


def test_zero_click_model_update_activates_only_when_idle(tmp_path, monkeypatch):
    import hm.model_update as update

    package = tmp_path / "champion.zip"
    identity = "a" * 64
    _champion_zip(package, generation=2, version="v2", identity=identity)
    monkeypatch.setattr(update, "_probe_l3", lambda path: identity)

    idle = {"value": False}
    updater = ModelUpdater(
        root=tmp_path / "models",
        is_idle=lambda: idle["value"],
        client_factory=lambda: _FakeChampionClient(package, 2, "v2", identity),
    )
    result = updater.check_once()
    assert result["status"] == "ready_waiting_for_idle"
    assert not (tmp_path / "models" / "active.json").exists()
    assert (tmp_path / "models" / "pending.json").is_file()

    idle["value"] = True
    activated = updater.activate_pending_if_idle()
    assert activated["status"] == "active"
    assert activated["generation"] == 2
    active = json.loads((tmp_path / "models" / "active.json").read_text())
    assert active["generation"] == 2
    assert Path(active["l3_metadata"]).is_file()


def test_model_update_rolls_back_to_previous_on_active_health_failure(tmp_path, monkeypatch):
    import hm.model_update as update

    root = tmp_path / "models"
    old_dir = root / "versions" / "000000000001-v1"
    new_dir = root / "versions" / "000000000002-v2"
    for folder in (old_dir, new_dir):
        (folder / "models").mkdir(parents=True)
        (folder / "models" / "deployment-candidate.json").write_text("{}")
        (folder / "models" / "candidate-model.onnx").write_bytes(b"x")

    old = {
        "generation": 1,
        "version": "v1",
        "model_identity_sha256": "1" * 64,
        "bundle_root": str(old_dir),
        "l3_metadata": str(old_dir / "models" / "deployment-candidate.json"),
    }
    new = {
        "generation": 2,
        "version": "v2",
        "model_identity_sha256": "2" * 64,
        "bundle_root": str(new_dir),
        "l3_metadata": str(new_dir / "models" / "deployment-candidate.json"),
    }
    root.mkdir(exist_ok=True)
    (root / "previous.json").write_text(json.dumps(old))
    (root / "active.json").write_text(json.dumps(new))

    def probe(path):
        if "000000000002" in str(path):
            raise update.ModelUpdateError("broken")
        return "1" * 64

    monkeypatch.setattr(update, "_probe_l3", probe)
    selected = active_model_metadata(root)
    assert selected == (old_dir / "models" / "deployment-candidate.json").resolve()
    restored = json.loads((root / "active.json").read_text())
    assert restored["generation"] == 1
    assert restored["status"] == "active_rollback"


def test_board_overlay_is_bound_to_session_model(tmp_path, monkeypatch):
    import hm.model_update as update

    root = tmp_path / "models"
    bundle = root / "versions" / "000000000003-v3"
    metadata = bundle / "models" / "deployment-candidate.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("{}")
    (root / "active.json").write_text(json.dumps({
        "model_identity_sha256": "3" * 64,
        "bundle_root": str(bundle),
        "l3_metadata": str(metadata),
    }))
    monkeypatch.setattr(update, "_probe_l3", lambda path: "3" * 64)
    assert update.active_bundle_for_model(metadata, root) == bundle.resolve()
    assert update.active_bundle_for_model(tmp_path / "other-model.json", root) is None


def test_model_update_refuses_low_local_disk_before_download(tmp_path, monkeypatch):
    import hm.model_update as update

    package = tmp_path / "champion.zip"
    identity = "a" * 64
    _champion_zip(package, generation=3, version="v3", identity=identity)
    monkeypatch.setattr(update, "_probe_l3", lambda path: identity)
    monkeypatch.setattr(
        update.shutil,
        "disk_usage",
        lambda _: type("Disk", (), {
            "total": 2 * 1024**3,
            "used": 1536 * 1024**2,
            "free": 512 * 1024**2,
        })(),
    )
    updater = ModelUpdater(
        root=tmp_path / "models",
        is_idle=lambda: True,
        client_factory=lambda: _FakeChampionClient(package, 3, "v3", identity),
    )
    try:
        updater.check_once()
    except update.ModelUpdateError as exc:
        assert "Espaço local insuficiente" in str(exc)
    else:
        raise AssertionError("low-disk neural update must fail closed")


def test_model_update_removes_stale_partial_before_download(tmp_path, monkeypatch):
    import hm.model_update as update

    package = tmp_path / "champion.zip"
    identity = "b" * 64
    _champion_zip(package, generation=4, version="v4", identity=identity)
    monkeypatch.setattr(update, "_probe_l3", lambda path: identity)
    monkeypatch.setattr(
        update.shutil,
        "disk_usage",
        lambda _: type("Disk", (), {
            "total": 10 * 1024**3,
            "used": 1 * 1024**3,
            "free": 9 * 1024**3,
        })(),
    )
    root = tmp_path / "models"
    downloads = root / "downloads"
    downloads.mkdir(parents=True)
    stale = downloads / "old.zip.partial"
    stale.write_bytes(b"partial")

    updater = ModelUpdater(
        root=root,
        is_idle=lambda: True,
        client_factory=lambda: _FakeChampionClient(package, 4, "v4", identity),
    )
    result = updater.check_once()
    assert result["status"] == "active"
    assert result["generation"] == 4
    assert not stale.exists()
