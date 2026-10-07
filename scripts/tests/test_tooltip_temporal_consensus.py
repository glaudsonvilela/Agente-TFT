"""Regression checks for the autonomous selected-unit label gate."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "autolabel_tooltip_temporal_consensus.py"
spec = importlib.util.spec_from_file_location("tooltip_consensus", MODULE)
assert spec and spec.loader
consensus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consensus)


def proposal(source: str, second: int, selected: int = 1,
             partition: str = "training_pool_unlabeled") -> dict:
    selected_crop = {
        "marker_id": 1, "box": [100, 100, 228, 244], "cyan_pixels": 40,
        "crop": f"crops/{second}.png", "pixel_sha256": f"{second:064x}",
        "selection_ring": {"shape_pass": True, "cyan_pixels": 800, "selection_signal_pixels": 800},
    }
    coloured_but_not_selected = {
        "marker_id": 0, "box": [300, 100, 428, 244], "cyan_pixels": 500,
        "crop": "crops/wrong.png", "pixel_sha256": "f" * 64,
        "selection_ring": {"shape_pass": False, "cyan_pixels": 100, "selection_signal_pixels": 100},
    }
    return {
        "source_id": source, "partition": partition, "source_seconds_nominal": second,
        "tooltip_unit_id": "DA_18_Camille", "tooltip_unit_candidates": ["DA_18_Camille"],
        "identity_requires_variant_review": False, "ocr_name_confidence": 96.0,
        "association_candidates": [coloured_but_not_selected, selected_crop],
        "selected_ring_marker_candidate": selected,
        "selection_ring_status": "unique_shape_candidate",
        "frame": f"frames/{second}.png", "frame_pixel_sha256": f"{second + 100:064x}",
        "tooltip_text": "Camille",
    }


def run(tmp_path: Path, monkeypatch, rows: list[dict]) -> dict:
    proposals = tmp_path / "proposals.json"
    proposals.write_text(json.dumps(rows), encoding="utf-8")
    output = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [str(MODULE), "--proposals", str(proposals), "--output", str(output)])
    assert consensus.main() == 0
    return {
        "labels": json.loads((output / "auto-labels.json").read_text()),
        "report": json.loads((output / "report.json").read_text()),
    }


def test_ring_overrides_raw_cyan_and_requires_two_frames(tmp_path, monkeypatch):
    one = proposal("vod-a", 123)
    two = proposal("vod-a", 124)
    result = run(tmp_path, monkeypatch, [one, two])
    assert [row["crop"] for row in result["labels"]] == ["crops/123.png", "crops/124.png"]
    assert result["report"]["auto_labels"] == 2
    assert result["report"]["training_eligible_labels"] == 2


def test_singletons_and_different_sources_never_join(tmp_path, monkeypatch):
    result = run(tmp_path, monkeypatch, [proposal("vod-a", 123), proposal("vod-b", 124)])
    assert result["labels"] == []
    assert result["report"]["rejected_singleton_clusters"] == 2


def test_evaluation_labels_are_held_out(tmp_path, monkeypatch):
    result = run(tmp_path, monkeypatch, [
        proposal("eval-vod", 123, partition="evaluation_unlabeled"),
        proposal("eval-vod", 124, partition="evaluation_unlabeled"),
    ])
    assert len(result["labels"]) == 2
    assert all(row["training_eligible"] is False for row in result["labels"])
    assert result["report"]["evaluation_labels"] == 2
    assert result["report"]["training_eligible_labels"] == 0


def test_missing_partition_never_becomes_training_label(tmp_path, monkeypatch):
    rows = [proposal("vod-a", 123), proposal("vod-a", 124)]
    for row in rows:
        del row["partition"]
    result = run(tmp_path, monkeypatch, rows)
    assert result["labels"] == []
    assert result["report"]["excluded"]["missing_or_invalid_partition"] == 2
