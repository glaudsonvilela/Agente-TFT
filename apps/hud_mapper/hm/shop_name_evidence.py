"""Conservative shop-name acceptance; OCR scores are not calibrated probabilities."""
from __future__ import annotations

import math


TEMPORAL_SOURCES = frozenset({"strip_temporal_consensus", "atlas_strip_temporal_consensus"})


def readable_name(slot: dict) -> bool:
    name = slot.get("observed_name")
    score = slot.get("name_confidence")
    if not isinstance(name, str) or not name.strip() or type(score) not in (int, float):
        return False
    if not math.isfinite(score) or slot.get("name_evidence") == "atlas_strip_conflict":
        return False
    return score >= 0.90 or (slot.get("name_evidence") in TEMPORAL_SOURCES and score >= 0.85)
