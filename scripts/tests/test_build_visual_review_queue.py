import json
from pathlib import Path

from PIL import Image

from build_visual_review_queue import build_queue, capture_from_collection


def test_review_queue_separates_unit_crops_from_unlocalized_item_context(tmp_path: Path):
    collection = tmp_path / "dense"
    (collection / "crops").mkdir(parents=True)
    (collection / "frames").mkdir()
    for index, shade in enumerate((20, 170)):
        Image.new("RGB", (16, 16), (shade, shade, shade)).save(
            collection / "crops" / f"{index}.png")
        Image.new("RGB", (32, 32), (shade, shade, shade)).save(
            collection / "frames" / f"{index}.png")
    rows = [
        {"frame_index": index, "review_frame": f"frames/{index}.png",
         "units": [{"crop": f"crops/{index}.png", "pixel_sha256": str(index),
                    "candidates": []}]}
        for index in range(2)
    ]
    (collection / "observations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (collection / "report.json").write_text(json.dumps({"source_id": "vod:one"}))
    inferred = capture_from_collection(collection)
    assert inferred["session_id"] == "vod:one"
    assert [row["source_ms"] for row in inferred["frames"]] == [0, 2000]
    capture = {"session_id": "test-match", "frames": [
        {"frame_id": 1, "source_ms": 0, "capture_event": "periodic"},
        {"frame_id": 2, "source_ms": 15000, "capture_event": "bench_or_item_change"},
    ]}
    queue = build_queue(capture, collection)
    assert queue["counts"] == {"unique_unit_candidates": 2,
                               "unit_review": 2, "item_context_review": 1}
    assert queue["unit_crops"][0]["capture_event"] == "bench_or_item_change"
    assert queue["item_contexts"][0]["kind"] == "item_context_unlocalized"
    assert queue["labels_created"] == 0
    assert queue["model_predictions_used_as_labels"] is False
