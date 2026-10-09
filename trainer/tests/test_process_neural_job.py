import hashlib
import json

from PIL import Image

from process_neural_job import build_session


def test_reconstructed_session_preserves_capture_event(tmp_path):
    data_root = tmp_path / "data"
    session_id = "session-event-test"
    evidence = data_root / "neural-evidence" / session_id
    frames = evidence / "frames"
    frames.mkdir(parents=True)
    (evidence / "seal.json").write_text(json.dumps({"match_end_reason": "test"}))
    for index, event in enumerate(("periodic", "shop_change")):
        image = frames / f"{index:012d}.jpg"
        Image.new("RGB", (1920, 1080), (index * 80, 0, 0)).save(image)
        (frames / f"{index:012d}.json").write_text(json.dumps({
            "neural_session_id": session_id,
            "frame_id": index,
            "source_ms": index * 1000,
            "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "metadata": {"capture_event": event},
        }))
    work = data_root / "work"
    work.mkdir()
    session = build_session({"neural_session_id": session_id,
                             "evidence_root": str(evidence)}, data_root, work)
    manifest = json.loads((session / "shadow-learning" / "capture-manifest.json").read_text())
    assert [row["capture_event"] for row in manifest["frames"]] == ["periodic", "shop_change"]
    assert all(row["training_label"] is None for row in manifest["frames"])
