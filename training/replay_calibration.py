from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable


STATE_FIELDS = ("hp", "gold", "level", "xp", "stage")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0,1]")

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    position = q * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]

    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    malformed = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            malformed += 1

    return records, malformed


def _payload(record: dict[str, Any]) -> dict[str, Any] | None:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else None


def _action_type(decision: dict[str, Any]) -> str | None:
    action = decision.get("action")
    if not isinstance(action, dict):
        return None
    value = action.get("type")
    return str(value) if isinstance(value, str) else None


def _has_no_confident_candidate(decision: dict[str, Any]) -> bool:
    evidence = decision.get("evidence")
    if not isinstance(evidence, list):
        return False

    for row in evidence:
        if isinstance(row, dict) and row.get("code") == "NO_CONFIDENT_CANDIDATE":
            return True
    return False


def summarize(records: Iterable[dict[str, Any]], malformed: int = 0) -> dict[str, Any]:
    records = list(records)
    payload_counts: Counter[str] = Counter()

    state_snapshots = 0
    field_present = Counter()
    shop_slots_total = 0
    shop_slots_known = 0
    board_unit_counts: list[int] = []
    lobby_counts: list[int] = []

    opportunity_cycles = 0
    complete_cycles = 0
    decision_actions: Counter[str] = Counter()
    no_confident_decisions = 0
    remote_evaluate_cycles = 0

    feedback_snapshots = 0
    metric_values: dict[str, list[float]] = defaultdict(list)

    first_ms: int | None = None
    last_ms: int | None = None

    for record in records:
        recorded_at_ms = record.get("recorded_at_ms")
        if isinstance(recorded_at_ms, int):
            first_ms = recorded_at_ms if first_ms is None else min(first_ms, recorded_at_ms)
            last_ms = recorded_at_ms if last_ms is None else max(last_ms, recorded_at_ms)

        payload = _payload(record)
        if payload is None:
            continue

        payload_type = payload.get("type")
        if not isinstance(payload_type, str):
            continue
        payload_counts[payload_type] += 1

        if payload_type == "state_snapshot":
            state = payload.get("state")
            if not isinstance(state, dict):
                continue

            player = state.get("player")
            if not isinstance(player, dict):
                continue

            state_snapshots += 1
            for field in STATE_FIELDS:
                if player.get(field) is not None:
                    field_present[field] += 1

            shop = player.get("shop")
            if isinstance(shop, list):
                shop_slots_total += len(shop)
                for slot in shop:
                    if not isinstance(slot, dict):
                        continue
                    value = slot.get("value")
                    if isinstance(value, dict) and value.get("unit_id"):
                        shop_slots_known += 1

            board = player.get("board")
            if isinstance(board, list):
                board_unit_counts.append(len(board))

            lobby = state.get("lobby")
            if isinstance(lobby, list):
                lobby_counts.append(len(lobby))

        if payload_type in {"opportunity_cycle", "complete_opportunity_cycle"}:
            if payload_type == "complete_opportunity_cycle":
                complete_cycles += 1
            opportunity_cycles += 1

            cycle = payload.get("cycle")
            if not isinstance(cycle, dict):
                continue

            # CompleteOpportunityCycle nests OpportunityCycle under cycle.cycle.
            if payload_type == "complete_opportunity_cycle":
                nested = cycle.get("cycle")
                if isinstance(nested, dict):
                    cycle = nested

            decision = cycle.get("decision")
            if isinstance(decision, dict):
                action_type = _action_type(decision)
                if action_type:
                    decision_actions[action_type] += 1
                if _has_no_confident_candidate(decision):
                    no_confident_decisions += 1

            if cycle.get("should_remote_evaluate") is True:
                remote_evaluate_cycles += 1

        if payload_type == "evaluator_feedback_snapshot":
            feedback_snapshots += 1

        if payload_type == "metric":
            name = payload.get("name")
            value = payload.get("value")
            if isinstance(name, str) and isinstance(value, (int, float)):
                value = float(value)
                if math.isfinite(value):
                    metric_values[name].append(value)

    field_coverage = {
        field: (
            field_present[field] / state_snapshots
            if state_snapshots
            else None
        )
        for field in STATE_FIELDS
    }

    shop_known_rate = (
        shop_slots_known / shop_slots_total
        if shop_slots_total
        else None
    )

    metrics: dict[str, Any] = {}
    for name, values in sorted(metric_values.items()):
        metrics[name] = {
            "count": len(values),
            "p50": median(values) if values else None,
            "p95": percentile(values, 0.95),
            "max": max(values) if values else None,
        }

    duration_ms = (
        last_ms - first_ms
        if first_ms is not None and last_ms is not None
        else None
    )

    return {
        "schema_version": 1,
        "records": len(records),
        "malformed_lines": malformed,
        "duration_ms": duration_ms,
        "payload_counts": dict(sorted(payload_counts.items())),
        "state": {
            "snapshots": state_snapshots,
            "field_coverage": field_coverage,
            "shop_slots_total": shop_slots_total,
            "shop_slots_known": shop_slots_known,
            "shop_known_rate": shop_known_rate,
            "board_units_p50": (
                median(board_unit_counts)
                if board_unit_counts
                else None
            ),
            "lobby_players_p50": (
                median(lobby_counts)
                if lobby_counts
                else None
            ),
        },
        "opportunity": {
            "cycles": opportunity_cycles,
            "complete_cycles": complete_cycles,
            "decision_actions": dict(sorted(decision_actions.items())),
            "no_confident_decisions": no_confident_decisions,
            "no_confident_rate": (
                no_confident_decisions / opportunity_cycles
                if opportunity_cycles
                else None
            ),
            "remote_evaluate_cycles": remote_evaluate_cycles,
        },
        "training_feedback": {
            "evaluator_feedback_snapshots": feedback_snapshots,
        },
        "metrics": metrics,
        "notes": [
            "Coverage is not accuracy.",
            "Ground-truth accuracy requires annotated replay/screenshot labels.",
            "A missing field can reflect perception failure or an unavailable game state.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Agente TFT telemetry for replay calibration."
    )
    parser.add_argument("telemetry_jsonl", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    records, malformed = load_jsonl(args.telemetry_jsonl)
    report = summarize(records, malformed)

    encoded = json.dumps(
        report,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
