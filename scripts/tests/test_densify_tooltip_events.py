"""The dense-window planner must preserve source and partition boundaries."""
from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "densify_tooltip_events.py"
spec = importlib.util.spec_from_file_location("densify_tooltip_events", MODULE)
assert spec and spec.loader
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def event(second: int, source: str = "vod-train", partition: str = "training_pool_unlabeled",
          confidence: float = 96) -> dict:
    return {
        "source_id": source, "partition": partition,
        "source_seconds_nominal": second,
        "tooltip_unit_id": "DA_18_Camille",
        "tooltip_unit_candidates": ["DA_18_Camille"],
        "identity_requires_variant_review": False,
        "ocr_name_confidence": confidence,
        "selection_ring_status": "unique_shape_candidate",
        "selected_ring_marker_candidate": 2,
        "association_candidates": [
            {"marker_id": 2, "selection_ring": {"shape_pass": True}}
        ],
    }


def test_merges_overlapping_windows_but_keeps_distant_events():
    windows = planner.plan_windows([event(120), event(135), event(420)],
                                   "vod-train", "training_pool_unlabeled", 600, 90, 30)
    assert [(w["start_seconds"], w["end_seconds"]) for w in windows] == [
        (90, 166), (390, 451)
    ]
    assert [len(w["events"]) for w in windows] == [2, 1]


def test_wrong_source_partition_and_weak_halo_are_excluded():
    wrong_halo = event(200)
    wrong_halo["association_candidates"][0]["selection_ring"]["shape_pass"] = False
    windows = planner.plan_windows([
        event(120, source="vod-eval"),
        event(130, partition="evaluation_unlabeled"),
        event(140, confidence=89),
        wrong_halo,
        event(150),
    ], "vod-train", "training_pool_unlabeled", 180, 90, 30)
    assert windows == [{"start_seconds": 120, "end_seconds": 180,
                        "events": [{"second": 150, "unit_id": "DA_18_Camille"}]}]


def test_dense_collection_decodes_real_frames_instead_of_repeating_keyframes(tmp_path):
    base = {"decode_mode": "keyframes", "partition": "evaluation_unlabeled"}
    dense = planner.dense_collection_spec(base, tmp_path / "dense", 390, 451)
    assert dense["decode_mode"] == "all"
    assert dense["sample_interval_seconds"] == 1
    assert dense["review_interval_seconds"] == 1
    assert dense["duration_seconds"] == 61
    assert base["decode_mode"] == "keyframes"
