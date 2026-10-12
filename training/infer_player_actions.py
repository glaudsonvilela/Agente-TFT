"""Infer demonstrated TFT actions from adjacent, trusted Motor 1 states.

The inference is deliberately open-set: when the state change supports more
than one action, it returns unresolved evidence instead of a false label.
This module is the bridge from video-observed Motor 1 transitions to the
sequential imitation policy, not a source of strategic preference labels.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class InferredAction:
    kind: str
    target: Any
    evidence: tuple[str, ...]


def _change(before: dict, after: dict, name: str):
    left, right = before.get(name), after.get(name)
    return left is not None and right is not None and left != right


def _delta(before: dict, after: dict, name: str):
    left, right = before.get(name), after.get(name)
    return right - left if type(left) is int and type(right) is int else None


def _added(before: dict, after: dict, name: str) -> list[str] | None:
    left, right = before.get(name), after.get(name)
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    return list((Counter(right) - Counter(left)).elements())


def _removed(before: dict, after: dict, name: str) -> list[str] | None:
    return _added(after, before, name)


def infer_transition(before: dict, after: dict) -> list[InferredAction]:
    """Return supported actions, or one unresolved transition with evidence.

    Both snapshots must be from the same player's stable planning view. IDs of
    roster units and items are track IDs, not guessed champion names. Multiple
    actions within one interval remain unresolved unless each has distinct
    independent evidence; a caller should increase temporal resolution.
    """
    if (before.get("match_id") != after.get("match_id") or
            before.get("video_sha256") != after.get("video_sha256") or
            before.get("player_id") != after.get("player_id") or
            not all(row.get("scene") == "planning" for row in (before, after)) or
            before.get("stage") != after.get("stage") or
            type(before.get("source_ms")) is not int or
            type(after.get("source_ms")) is not int or
            not 0 < after["source_ms"] - before["source_ms"] <= 500):
        return [InferredAction("unresolved", None, ("unstable_or_unaligned_view",))]

    gold = _delta(before, after, "gold")
    observations: list[InferredAction] = []
    shop_changed = _change(before, after, "shop")
    bench_added = _added(before, after, "bench_unit_ids")
    bench_removed = _removed(before, after, "bench_unit_ids")
    inventory_added = _added(before, after, "inventory_item_ids")
    inventory_removed = _removed(before, after, "inventory_item_ids")
    board0, board1 = before.get("board_positions"), after.get("board_positions")
    equipped0, equipped1 = before.get("equipped_items"), after.get("equipped_items")

    # Economy: direct resource deltas plus a second independent HUD signal.
    xp0, xp1 = before.get("xp"), after.get("xp")
    level0, level1 = before.get("level"), after.get("level")
    cap0 = before.get("xp_cap")
    if all(type(v) is int for v in (xp0, xp1, level0, level1)):
        gained = (xp1 - xp0 if level1 == level0 else
                  cap0 - xp0 + xp1 if type(cap0) is int and level1 == level0 + 1 else None)
        if gained is not None and gained > 0 and gained % 4 == 0 and gold == -gained:
            observations.append(InferredAction("buy_xp", {"count": gained // 4},
                                               ("gold_spent", "xp_gained", "level_checked")))
    if (gold == -2 and shop_changed and before.get("shop") is not None and
            after.get("shop") is not None and bench_added == [] and
            isinstance(board0, dict) and board0 == board1):
        observations.append(InferredAction("reroll", None,
                                           ("gold_spent", "shop_replaced", "roster_stable")))
    if _change(before, after, "shop_locked") and gold == 0:
        observations.append(InferredAction("lock_shop" if after["shop_locked"] else
                                           "unlock_shop", None, ("lock_indicator_changed",)))

    # Concrete roster identity comes from tracked units, not pixel labels.
    if isinstance(board0, dict) and isinstance(board1, dict):
        same = board0.keys() & board1.keys()
        moved = [unit for unit in same if board0[unit] != board1[unit]]
        if len(moved) == 1 and gold == 0:
            unit = moved[0]
            observations.append(InferredAction("move_unit", {"unit_track_id": unit,
                "from": board0[unit], "to": board1[unit]}, ("same_unit_track", "hex_changed")))
        board_added = list(board1.keys() - board0.keys())
        board_removed = list(board0.keys() - board1.keys())
        if len(board_added) == 1 and board_added == bench_removed and gold == 0:
            observations.append(InferredAction("field_unit", board_added[0],
                                               ("bench_track_removed", "board_track_added")))
        if len(board_removed) == 1 and board_removed == bench_added and gold == 0:
            observations.append(InferredAction("bench_unit", board_removed[0],
                                               ("board_track_removed", "bench_track_added")))
    else:
        board_added = board_removed = []

    if (gold is not None and gold < 0 and shop_changed and len(bench_added or []) == 1
            and not board_added and isinstance(before.get("shop"), list)
            and isinstance(after.get("shop"), list)):
        vanished = [i for i, (old, new) in enumerate(zip(before["shop"], after["shop"]))
                    if old is not None and new is None]
        if len(vanished) == 1:
            observations.append(InferredAction("buy_unit", {"shop_slot": vanished[0],
                "unit_track_id": bench_added[0]},
                ("shop_slot_emptied", "bench_track_added", "gold_spent")))
    if gold is not None and gold > 0 and len(bench_removed or []) == 1 and not board_added:
        observations.append(InferredAction("sell_unit", bench_removed[0],
                                           ("bench_track_removed", "gold_gained")))

    # Items, augment choices, and scouting are separate action families.
    if isinstance(equipped0, dict) and isinstance(equipped1, dict) and \
            len(inventory_removed or []) == 1:
        item = inventory_removed[0]
        equipped_to = [unit for unit in equipped1 if
                       Counter(equipped1[unit]) - Counter(equipped0.get(unit, [])) == Counter([item])]
        if len(equipped_to) == 1:
            observations.append(InferredAction("equip_item", {"item_track_id": item,
                "unit_track_id": equipped_to[0]},
                ("inventory_track_removed", "unit_equipment_added")))
    chosen = _added(before, after, "active_augment_ids")
    offers = before.get("augment_offer_ids")
    if len(chosen or []) == 1 and isinstance(offers, list) and chosen[0] in offers:
        observations.append(InferredAction("choose_augment", chosen[0],
                                           ("offered_augment", "active_augment_added")))
    if _change(before, after, "viewed_opponent_id") and gold == 0:
        observations.append(InferredAction("scout_opponent", after["viewed_opponent_id"],
                                           ("opponent_view_changed",)))

    changed = {name for name in ("gold", "xp", "level", "shop", "shop_locked",
               "bench_unit_ids", "board_positions", "inventory_item_ids",
               "equipped_items", "active_augment_ids", "augment_offer_ids",
               "viewed_opponent_id") if _change(before, after, name)}
    expected = {
        "buy_xp": {"gold", "xp", "level"},
        "reroll": {"gold", "shop"},
        "lock_shop": {"shop_locked"}, "unlock_shop": {"shop_locked"},
        "move_unit": {"board_positions"},
        "field_unit": {"bench_unit_ids", "board_positions"},
        "bench_unit": {"bench_unit_ids", "board_positions"},
        "buy_unit": {"gold", "shop", "bench_unit_ids"},
        "sell_unit": {"gold", "bench_unit_ids"},
        "equip_item": {"inventory_item_ids", "equipped_items"},
        "choose_augment": {"active_augment_ids", "augment_offer_ids"},
        "scout_opponent": {"viewed_opponent_id"},
    }
    if len(observations) == 1:
        candidate = observations[0]
        extra = changed - expected[candidate.kind]
        if not extra:
            return observations
        return [InferredAction("unresolved", None,
                               ("unexplained_concurrent_change",) + tuple(sorted(extra)))]
    if len(observations) > 1:
        return [InferredAction("unresolved", None,
                               ("multiple_action_explanations",) +
                               tuple(row.kind for row in observations))]
    return ([InferredAction("unresolved", None, tuple(sorted(changed)))]
            if changed else [])


def stage_action_history(snapshots: list[dict], motor2_frames: list[dict]) -> list[dict]:
    """Record stage, pre-action Motor 1 facts, observed action and Motor 2 link.

    A missing Rust candidate is preserved as `motor2_status=unsupported_action`;
    it is not converted to Rust's preferred choice. Review/learning can use the
    event once visual evidence and observation reliability are checked.
    """
    ordered = sorted(snapshots, key=lambda row: row["source_ms"])
    motor2 = sorted(motor2_frames, key=lambda row: row["source_ms"])
    events = []
    position = 0
    for before, after in zip(ordered, ordered[1:]):
        while position + 1 < len(motor2) and motor2[position + 1]["source_ms"] <= before["source_ms"]:
            position += 1
        prior = (motor2[position] if motor2 and motor2[position]["source_ms"] <= before["source_ms"]
                 and motor2[position].get("match_id") == before.get("match_id") else None)
        for action in infer_transition(before, after):
            if action.kind == "unresolved":
                status, key = "needs_review", None
            elif prior is None:
                status, key = "motor2_state_missing", None
            else:
                matches = [row for row in prior.get("candidates", [])
                           if (row.get("action") or {}).get("type") ==
                           {"reroll": "roll"}.get(action.kind, action.kind)]
                if len(matches) != 1:
                    status, key = "unsupported_action", None
                else:
                    status, key = "candidate_type_match_needs_target_check", matches[0].get("decision_key")
            evidence_id = hashlib.sha256(json.dumps({
                "video": before.get("video_sha256"), "before": before["source_ms"],
                "after": after["source_ms"], "action": action.kind,
                "target": action.target}, sort_keys=True).encode()).hexdigest()
            events.append({
                "match_id": before.get("match_id"),
                "video_sha256": before.get("video_sha256"),
                "stage": before.get("stage"),
                "before_ms": before["source_ms"], "after_ms": after["source_ms"],
                "motor1_before": before, "motor1_after": after,
                "action_kind": action.kind, "action_target": action.target,
                "action_evidence": action.evidence, "evidence_id": evidence_id,
                "motor2_frame_id": prior.get("frame_id") if prior else None,
                "motor2_decision_key": key, "motor2_status": status,
                "reviewed": False, "training_eligible": False,
            })
    return events
