"""A dense purchase must retain shop names and subsecond bench evidence."""
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "autolabel_shop_purchase_consensus.py"
spec = importlib.util.spec_from_file_location("shop_consensus", MODULE)
assert spec and spec.loader
shop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shop)


def test_repeated_exact_shop_name_survives_a_low_single_frame_ocr_score():
    evidence = {
        "shop_ocr_name_confidence": 90.0,
        "shop_name_distinct_frame_confirmations": 4,
        "shop_name_min_ocr_confidence": 88.0,
        "shop_name_confirmation_span_ms": 750,
    }
    assert shop.shop_name_verified(evidence, 94.0)
    assert not shop.shop_name_verified({**evidence, "shop_name_distinct_frame_confirmations": 2}, 94.0)
    assert not shop.shop_name_verified({**evidence, "shop_name_min_ocr_confidence": 72.0}, 94.0)
    assert not shop.shop_name_verified({**evidence, "shop_name_confirmation_span_ms": 0}, 94.0)
    assert shop.shop_name_verified({"shop_ocr_name_confidence": 96.0}, 94.0)


def test_bench_persistence_counts_later_frames_within_the_same_second():
    observations = [
        {"source_seconds_nominal": 12, "source_milliseconds_nominal": 12500,
         "units": [{"box": [400, 740, 528, 884], "crop": "initial"}]},
        {"source_seconds_nominal": 12, "source_milliseconds_nominal": 12750,
         "units": [{"box": [403, 741, 531, 885], "crop": "later"}]},
    ]
    evidence = shop.persistence_evidence(observations, 12500, [400, 740, 528, 884], 2, 70)
    assert evidence["persistent"]
    assert evidence["matches"][0]["source_milliseconds_nominal"] == 12750
