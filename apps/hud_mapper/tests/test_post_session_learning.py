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
    assert value["training_started"] is False
    assert value["active_model_changed"] is False


def test_post_session_launcher_does_not_claim_packaged_training(tmp_path, monkeypatch):
    session = tmp_path / "session"
    learning = session / "shadow-learning"
    learning.mkdir(parents=True)
    (session / "COMPLETE.json").write_text("{}")
    (session / "summary.json").write_text(json.dumps({
        "execution_complete": True,
        "session_id": "abc",
        "active_model_changed_during_session": False,
    }))
    (learning / "SEALED.json").write_text(json.dumps({
        "ready_for_post_session_learning": True
    }))

    # Force the source-checkout discovery path to fail without changing host OS.
    import hm.post_session_learning as post
    original = Path

    class FakePath(type(Path())):
        pass

    # Simpler: point __file__ under a temporary packaged-like tree with no scripts/tools.
    monkeypatch.setattr(post, "__file__", str(tmp_path / "packed" / "hm" / "post_session_learning.py"))
    value = post.launch_post_session_learning(session)
    assert value["status"] == "queued_waiting_for_packaged_wsl_trainer"
    assert value["training_started"] is False
    assert value["active_model_changed"] is False
