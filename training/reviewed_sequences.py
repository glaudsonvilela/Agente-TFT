"""Build partial demonstration examples from reviewed video transitions.

The policy input is the earlier frame only. Unknown observations stay absent;
neither a narrated recommendation nor a later result becomes an action label.
These examples support offline imitation research, not runtime promotion.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from training.board_review import REVIEWS, integer, require, sha, validate

ACTION_KINDS = {
    "buy",
    "sell",
    "move",
    "equip",
    "xp",
    "reroll",
    "lock",
    "augment",
    "wisp",
    "carousel",
    "reward",
}


def input_observation(frame):
    """Whitelist prevents future annotations/placement/reviewer notes leaking in."""

    def keep(row, fields):
        return {key: deepcopy(row[key]) for key in fields if key in row}

    def identity(row):
        return keep(row, ("state", "id", "visible_name"))

    def slots(row):
        return dict(
            coverage=row["coverage"],
            slots=[
                dict(slot=s["slot"], identity=identity(s["identity"]))
                for s in row["slots"]
            ],
        )

    result = keep(frame, ("scene", "phase"))
    if "hud" in frame:
        result["hud"] = keep(
            frame["hud"], ("hp", "gold", "level", "xp", "xp_cap", "stage")
        )
    if "layout" in frame:
        result["layout"] = dict(
            units=[
                keep(u, ("key", "zone", "owner", "box", "hex", "bench_slot"))
                for u in frame["layout"].get("units", [])
            ]
        )
    if "entities" in frame:
        result["entities"] = []
        for u in frame["entities"]:
            row = keep(u, ("key", "stars"))
            row["identity"] = identity(u["identity"])
            if "equipped" in u:
                row["equipped"] = slots(u["equipped"])
            result["entities"].append(row)
    if "inventory" in frame:
        result["inventory"] = slots(frame["inventory"])
    if "shop" in frame:
        result["shop"] = [
            dict(keep(s, ("slot", "kind", "cost")), identity=identity(s["identity"]))
            for s in frame["shop"]
        ]
    return result


def location(value):
    require(isinstance(value, dict), "action location required")
    if value.get("zone") == "bench":
        require(
            set(value) == {"zone", "slot"}
            and integer(value["slot"])
            and 0 <= value["slot"] < 9,
            "invalid bench action location",
        )
    else:
        require(
            set(value) == {"zone", "hex"}
            and value["zone"] == "board"
            and isinstance(value["hex"], list)
            and len(value["hex"]) == 2
            and all(integer(v) for v in value["hex"])
            and 0 <= value["hex"][0] < 4
            and 0 <= value["hex"][1] < 7,
            "invalid board action location",
        )


def anchored_unit(frame, key, where):
    unit = next(
        (u for u in frame.get("layout", {}).get("units", []) if u["key"] == key), None
    )
    require(
        unit is not None and unit["owner"] == "self" and unit["zone"] == where["zone"],
        "move must have a reviewed owned unit in both frames",
    )
    field = "bench_slot" if where["zone"] == "bench" else "hex"
    require(
        unit.get(field) == where["slot" if field == "bench_slot" else "hex"],
        "move label disagrees with observed location",
    )


def validate_action(action, before, after):
    require(
        isinstance(action, dict) and action.get("kind") in ACTION_KINDS,
        "unknown action kind",
    )
    require(
        set(action)
        <= {
            "kind",
            "unit_key",
            "from",
            "to",
            "shop_slot",
            "inventory_slot",
            "choice_slot",
            "locked",
        },
        "unknown action label field",
    )
    if action["kind"] == "move":
        require(
            set(action) == {"kind", "unit_key", "from", "to"},
            "complete move anchors required",
        )
        for point in ("from", "to"):
            location(action[point])
        require(action["from"] != action["to"], "move must change location")
        anchored_unit(before, action["unit_key"], action["from"])
        anchored_unit(after, action["unit_key"], action["to"])
    else:
        # Additional action arguments need their own semantic validation before
        # this exporter can emit them. Only the visually reviewed kind is kept.
        require(
            set(action) == {"kind"}, "only move arguments are supported in this schema"
        )


def build(document, board_document, root=None):
    review_report = validate(board_document, root)
    require(
        document.get("schema_version") == 1
        and document.get("kind") == "reviewed_action_sequences",
        "unsupported action review",
    )
    source = document.get("source_sha256")
    require(
        sha(source) and source == board_document.get("source_sha256"),
        "video identity mismatch",
    )
    require(
        document.get("source_url") == board_document.get("source_url"),
        "source URL mismatch",
    )
    frames = {f["sha256"]: f for f in board_document["frames"]}
    transitions = document.get("transitions")
    require(
        isinstance(transitions, list) and transitions, "reviewed transitions required"
    )
    rows, seen, windows = [], set(), []
    for t in transitions:
        ident = t.get("id")
        require(
            isinstance(ident, str) and ident and ident not in seen,
            "unique transition ID required",
        )
        seen.add(ident)
        require(
            t.get("before") in frames and t.get("after") in frames,
            "transition frame missing",
        )
        before, after = frames[t["before"]], frames[t["after"]]
        require(
            before["source_ms"] < after["source_ms"],
            "transition must go forward in time",
        )
        require(
            before["session_id"] == after["session_id"], "transition crosses sessions"
        )
        require(
            before.get("phase") == after.get("phase") == "planning",
            "planning actions require planning frames",
        )
        require(
            before.get("patch_binding") == after.get("patch_binding"),
            "transition crosses rule versions",
        )
        require(
            before.get("match_group") == after.get("match_group"),
            "transition crosses matches",
        )
        stages = {f.get("hud", {}).get("stage") for f in (before, after)} - {None}
        require(len(stages) <= 1, "transition crosses rounds")
        review = t.get("review", {})
        require(
            review.get("method") in REVIEWS
            and review.get("model_predictions_used_as_labels") is False,
            "explicit visual action review required",
        )
        require(
            t.get("evidence_kind") == "visible_execution",
            "narration is not an executed action",
        )
        evidence = t.get("evidence_frames")
        require(
            isinstance(evidence, list)
            and evidence
            and len(set(evidence)) == len(evidence),
            "unique execution evidence frames required",
        )
        for key in evidence:
            require(
                key in frames
                and before["source_ms"] < frames[key]["source_ms"] < after["source_ms"],
                "execution evidence must lie strictly between before and after",
            )
            require(
                frames[key]["session_id"] == before["session_id"]
                and frames[key].get("match_group") == before.get("match_group"),
                "execution evidence crosses session or match",
            )
            require(
                frames[key].get("phase") == "planning"
                and frames[key].get("patch_binding") == before.get("patch_binding"),
                "execution evidence crosses phase or rule version",
            )
            stage = frames[key].get("hud", {}).get("stage")
            require(
                not stages or stage is None or stage in stages,
                "execution evidence crosses rounds",
            )
        window = (before["source_ms"], after["source_ms"])
        require(
            all(window[1] <= left or window[0] >= right for left, right in windows),
            "overlapping action windows need disambiguation",
        )
        windows.append(window)
        validate_action(t.get("action"), before, after)
        binding = before.get("patch_binding")
        rows.append(
            dict(
                id=ident,
                source_sha256=source,
                source_url=document["source_url"],
                match_group=before.get("match_group"),
                patch_binding=deepcopy(binding),
                input=dict(
                    frame_sha256=before["sha256"],
                    pixel_sha256=before["pixel_sha256"],
                    image=before["image"],
                    source_ms=before["source_ms"],
                    observed=input_observation(before),
                ),
                target=dict(action=deepcopy(t["action"])),
                validation_only=dict(
                    next_frame_sha256=after["sha256"],
                    next_pixel_sha256=after["pixel_sha256"],
                    next_observed=input_observation(after),
                    evidence_frames=list(evidence),
                    evidence_pixels=[frames[key]["pixel_sha256"] for key in evidence],
                ),
                review=deepcopy(review),
                eligible_for_action_imitation=True,
                eligible_for_full_state_policy=False,
                eligible_for_outcome_value=False,
                runtime_promoted=False,
            )
        )
    return rows, dict(
        schema_version=1,
        kind="demonstration_export",
        source_sha256=source,
        reviewed_transitions=len(rows),
        actions=dict(Counter(r["target"]["action"]["kind"] for r in rows)),
        frame_review=review_report,
        patch_bound_transitions=sum(bool(r["patch_binding"]) for r in rows),
        full_state_policy_examples=0,
        outcome_value_examples=0,
        runtime_promoted=False,
    )


def assign_splits(rows, *, validation_sources=(), test_sources=()):
    """Keep entire sources, known duplicate matches and shared pixels together.

    Source holdout is intentionally conservative until exact match boundaries
    are reviewed. Explicit holdouts avoid tuning a seed for flattering results.
    """
    val, test = set(validation_sources), set(test_sources)
    known = {r["source_sha256"] for r in rows}
    require(
        not val & test and val | test <= known, "unknown or conflicting holdout source"
    )
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    anchors = {}
    for i, r in enumerate(rows):
        keys = [
            ("source", r["source_sha256"]),
            ("pixel", r["input"]["pixel_sha256"]),
            ("pixel", r["validation_only"]["next_pixel_sha256"]),
        ]
        keys += [("pixel", key) for key in r["validation_only"]["evidence_pixels"]]
        if r.get("match_group"):
            keys.append(("match", r["match_group"]))
        for key in keys:
            if key in anchors:
                parent[find(i)] = find(anchors[key])
            else:
                anchors[key] = i
    chosen = {}
    for i, r in enumerate(rows):
        source = r["source_sha256"]
        requested = (
            "test" if source in test else "validation" if source in val else None
        )
        if requested:
            group = find(i)
            require(
                chosen.get(group, requested) == requested,
                "duplicate match connects different holdouts",
            )
            chosen[group] = requested
    return [
        dict(deepcopy(row), split=chosen.get(find(i), "train"))
        for i, row in enumerate(rows)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frames, actions = json.loads(args.frames.read_bytes()), json.loads(
        args.actions.read_bytes()
    )
    digest = hashlib.sha256()
    with args.video.open("rb") as video:
        for chunk in iter(lambda: video.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    require(digest.hexdigest() == actions.get("source_sha256"), "source video changed")
    rows, report = build(actions, frames, args.frames.parent)
    require(not args.output.exists(), "use a new output directory")
    args.output.mkdir(parents=True)
    rows = assign_splits(rows)
    (args.output / "examples.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    report.update(
        split_counts=dict(Counter(r["split"] for r in rows)),
        action_annotation_sha256=hashlib.sha256(args.actions.read_bytes()).hexdigest(),
        frame_annotation_sha256=hashlib.sha256(args.frames.read_bytes()).hexdigest(),
        sufficient_for_training=False,
    )
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
