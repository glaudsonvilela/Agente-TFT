import hashlib
import json

from PIL import Image

from stage_supported_visual_gold import stage


def test_stage_copies_only_verified_direct_gold(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    pixels = Image.new("RGB", (8, 8), (25, 60, 90))
    digest = hashlib.sha256(pixels.tobytes()).hexdigest()
    pixels.save(source / f"{digest}.png")
    direct = {"source_id": "vod:one", "decision": "supported",
              "label_source": "autonomous_tooltip_temporal_consensus_v1",
              "training_eligible": True, "human_review_required": False,
              "model_prediction_used_as_label": False,
              "partition": "training_pool_unlabeled", "pixel_sha256": digest,
              "crop": f"crops/{digest}.png", "unit_id": "UnitA"}
    supported = tmp_path / "supported.json"
    supported.write_text(json.dumps([direct, {**direct, "decision": "direct_gold_teacher_mixed"}]))
    output = tmp_path / "package"
    result = stage(supported, source, output)
    assert result["gold"] == 1
    assert json.loads((output / "gold.json").read_text()) == [direct]
    assert (output / "collection" / "crops" / f"{digest}.png").is_file()
    assert result["labels_created"] == 0
