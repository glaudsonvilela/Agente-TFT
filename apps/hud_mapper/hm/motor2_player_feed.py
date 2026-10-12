"""Causal, structured Motor 2 output for a future player policy.

This is an observation feed, not a training label or an action executor. The
policy can only rank candidates already admitted by the resident Rust motor.
"""
from __future__ import annotations

import hashlib
import json
import math


ACTION_TYPES = (
    "trait_shop_review", "buy_pair", "buy_synergy", "roll", "buy_xp",
    "prepare_level", "rebuild_after_level", "hold_econ",
)
FEATURE_NAMES = (
    "rust_base_utility", "rust_adjusted_utility", "plan_alignment_bonus",
    "recent_repeats", "gold", "gold_known", "hp", "hp_known",
    "level", "level_known", "xp", "xp_known", "stage", "stage_known",
    "fresh_shop_offers", "board_candidates", "board_identity_verified",
    "item_candidates", "opponent_candidates", "opponent_linked",
    "enemy_visible_item_icons", "enemy_equipped_unit_tracks",
    "streak_count", "streak_verified", "trait_count_max",
    "hp_loss_90s", "gold_change_90s", "gold_change_known",
    "pressure_survival", "pressure_recovering", "phase_late",
    "action_gold_cost", "action_rolls_max", "action_breakpoint_gap",
) + tuple("action_" + name for name in ACTION_TYPES)


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value) if low <= value <= high else None


def _observed(value, low, high):
    number = _number(value, low, high)
    return (number or 0.0, float(number is not None))


def _features(state, macro, action, ranking):
    gold, gold_known = _observed(state.get("gold"), 0, 300)
    hp, hp_known = _observed(state.get("hp"), 0, 100)
    level, level_known = _observed(state.get("level"), 1, 11)
    xp, xp_known = _observed(state.get("xp"), 0, 100)
    stage_text = state.get("stage")
    stage = int(stage_text[0]) if isinstance(stage_text, str) and len(stage_text) == 3 \
        and stage_text[0].isdigit() and stage_text[1] == "-" else None
    stage_num, stage_known = _observed(stage, 1, 9)
    streak = state.get("streak_count_verified")
    streak_num, streak_known = _observed(streak, 0, 100)
    gold_change, gold_change_known = _observed(macro.get("observed_gold_change_90s"), -300, 300)
    traits = state.get("trait_counts") or {}
    if not isinstance(traits, dict):
        traits = {}
    trait_max = max((value for value in traits.values() if type(value) is int and 0 <= value <= 12), default=0)
    kind = action.get("type")
    values = (
        _number(ranking.get("base_utility"), -100, 100) or 0.0,
        _number(ranking.get("utility"), -100, 100) or 0.0,
        _number(ranking.get("plan_alignment_bonus"), -100, 100) or 0.0,
        _number(ranking.get("recent_repeats"), 0, 100) or 0.0,
        gold, gold_known, hp, hp_known, level, level_known, xp, xp_known,
        stage_num, stage_known,
        _number(state.get("fresh_shop_offers"), 0, 5) or 0.0,
        _number(state.get("board_candidates"), 0, 100) or 0.0,
        float(state.get("board_identity_verified") is True),
        _number(state.get("item_candidates"), 0, 100) or 0.0,
        _number(state.get("opponent_candidates"), 0, 100) or 0.0,
        float(state.get("opponent_linked") is True),
        _number(state.get("enemy_visible_item_icons"), 0, 100) or 0.0,
        _number(state.get("enemy_equipped_unit_tracks"), 0, 100) or 0.0,
        streak_num, streak_known, float(trait_max),
        _number(macro.get("observed_hp_loss_90s"), 0, 100) or 0.0,
        gold_change, gold_change_known,
        float(macro.get("pressure") == "survival"),
        float(macro.get("pressure") == "recovering"),
        float(macro.get("phase") == "late"),
        _number(action.get("gold_cost"), 0, 300) or 0.0,
        _number(action.get("rolls_max"), 0, 50) or 0.0,
        max(0.0, (_number(action.get("next_breakpoint"), 0, 12) or 0.0) -
            (_number(action.get("visible_trait_count"), 0, 12) or 0.0))
        if kind == "trait_shop_review" else 0.0,
    ) + tuple(float(kind == name) for name in ACTION_TYPES)
    assert len(values) == len(FEATURE_NAMES)
    return list(values)


def make_frame(result, *, patch, set_key, match_id, epoch, motor1_full=None):
    """Preserve Rust evidence and features; never infer a demonstrated choice."""
    if result.get("origin") != "rust_live_opportunity_v1" or not isinstance(patch, str) \
            or not patch or not isinstance(set_key, str) or not set_key:
        raise ValueError("bound Rust result and patch are required")
    if type(result.get("id")) is not int or type(result.get("source_ms")) is not int:
        raise ValueError("frame identity missing")
    state, macro = result.get("whole_state"), result.get("macro_state")
    candidates, ranked = result.get("candidates"), result.get("ranked")
    if not isinstance(state, dict) or not isinstance(macro, dict) or \
            not isinstance(candidates, list) or not isinstance(ranked, list):
        raise ValueError("complete Motor 2 ranking response required")
    rows, seen = [], set()
    for ranking in ranked:
        index = ranking.get("index") if isinstance(ranking, dict) else None
        if type(index) is not int or index in seen or not 0 <= index < len(candidates):
            raise ValueError("ranked candidate index invalid")
        seen.add(index)
        candidate = candidates[index]
        action = candidate.get("action") if isinstance(candidate, dict) else None
        if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
            raise ValueError("unsupported ranked action")
        if not isinstance(ranking.get("decision_key"), str) or \
                ranking.get("action_type") != action["type"]:
            raise ValueError("ranked action identity mismatch")
        rows.append(dict(index=index, decision_key=ranking["decision_key"],
                         action=action, policy=candidate.get("policy"),
                         basis=candidate.get("basis"), rank=ranking,
                         features=_features(state, macro, action, ranking),
                         motor2_supported=True, game_legality_verified=False))
    payload = dict(schema_version=1, kind="motor2_player_observation",
                   origin=result["origin"], patch=patch, set_key=set_key,
                   match_id=match_id, epoch=epoch, frame_id=result["id"],
                   source_ms=result["source_ms"],
                   feature_names=FEATURE_NAMES, whole_state=state, macro_state=macro,
                   current_observation=result.get("current_observation"),
                   plan_state=result.get("plan_state"),
                   match_pool=result.get("match_pool"),
                   motor1_ingest=result.get("motor1_ingest"),
                   # This is the exact, lossless packet consumed by Rust:
                   # reader + HUB + auxiliaries, with hashes and source time.
                   # Numeric candidate features below are only a legacy view.
                   motor1_full=motor1_full,
                   candidates=rows, selected_index=result.get("selected_index"),
                   label_status="unreviewed_observation",
                   training_eligible=False, runtime_policy_active=False,
                   full_motor1_interpreted_by_policy=False)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    payload["observation_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload
