from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from hm.learning_capture import ShadowLearningRecorder
from hm.post_session_learning import launch_post_session_learning


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

    import hm.post_session_learning as post
    monkeypatch.setattr(post, "_upload_worker", lambda *args, **kwargs: None)
    value = post.launch_post_session_learning(session)
    assert value["status"] == "queued_server_upload"
    assert value["training_location"] == "server"
    assert value["local_neural_weights_bundled"] is False
    assert value["local_training_performed"] is False
    assert value["active_model_changed"] is False

