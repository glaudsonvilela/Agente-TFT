"""Resolve artwork aliases and associate items inside one captured frame."""

import math


def item_candidate(slot, max_rms=35, min_gap=8):
    result = dict(
        slot=slot["slot"],
        candidate_id=None,
        candidate_name=None,
        identity_verified=False,
        status="unknown",
    )
    rows = slot.get("candidates", [])
    if slot.get("status") not in ("icon_candidate", "candidate_only") or len(rows) < 2:
        return result
    best, second = rows[:2]
    values = [best.get("rms"), second.get("rms")]
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values
    ):
        return result
    if values[0] > max_rms or values[1] - values[0] < min_gap:
        return result
    # Same artwork can occur under several provider IDs. Only a unique exact
    # binding to the active mechanics catalog supplies a candidate API name.
    options = [
        v
        for v in best.get("catalog_options", [])
        if v.get("attribute_id") and v.get("attribute_binding") == "exact_api_name"
    ]
    ids = {v["attribute_id"] for v in options}
    names = {v.get("name") for v in options}
    if len(ids) == 1 and len(names) == 1:
        result.update(
            candidate_id=next(iter(ids)),
            candidate_name=next(iter(names)),
            status="item_candidate",
            rms=values[0],
            gap_rms=values[1] - values[0],
        )
    return result


def associate_equipment(markers, identities):
    """Marker IDs are local to a frame; never carry associations into another."""
    return [
        dict(
            marker_id=m["marker_id"],
            unit_candidate=identities.get(m["marker_id"]),
            equipped=[item_candidate(slot) for slot in m["equipped_slots"]],
            association="same_frame_bar_geometry",
            association_verified=False,
        )
        for m in markers
    ]
