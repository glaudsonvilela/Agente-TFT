"""Convert reviewed Motor 2 decisions to the existing action-policy trainer.

The input review must identify the real action, all legal alternatives, and
the frame's patch/source. Motor 2's preferred action is never a label.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.decision_objectives import validate_partition


def export(frames, review, *, patch, content_sha256, engine_sha256):
    if review.get("schema_version") != 1 or review.get("kind") != "reviewed_motor2_actions":
        raise ValueError("reviewed_motor2_actions schema 1 required")
    if review.get("patch") != patch or review.get("set_key") != "TFTSet18":
        raise ValueError("review patch/set mismatch")
    indexed = {}
    names = None
    for frame in frames:
        if frame.get("kind") != "motor2_player_observation" or frame.get("patch") != patch:
            raise ValueError("Motor 2 frame patch mismatch")
        feature_names = frame.get("feature_names")
        if not isinstance(feature_names, (list, tuple)) or not feature_names:
            raise ValueError("frame features missing")
        names = names or list(feature_names)
        if list(feature_names) != names:
            raise ValueError("feature schema changed within dataset")
        identity = (frame.get("match_id"), frame.get("frame_id"))
        if identity in indexed:
            raise ValueError("duplicate Motor 2 frame")
        indexed[identity] = frame
    records = []
    for label in review.get("actions") or []:
        identity = (label.get("match_id"), label.get("frame_id"))
        frame = indexed.get(identity)
        if frame is None or label.get("observation_sha256") != frame.get("observation_sha256"):
            raise ValueError("reviewed action has no exact Motor 2 observation")
        if frame.get("set_key") != review["set_key"] or frame.get("training_eligible") is not False:
            raise ValueError("untrusted frame status")
        if label.get("state_coverage") != "complete_observable_state":
            raise ValueError("reviewer must confirm complete observable state")
        at, action_at, after = (label.get(key) for key in
                                ("before_ms", "action_ms", "after_ms"))
        if not all(type(value) is int for value in (at, action_at, after)) or \
                at != frame["source_ms"] or not at < action_at < after or \
                action_at - at > 10_000:
            raise ValueError("action must be observed after its exact state frame")
        options = frame.get("candidates") or []
        keys = [row.get("decision_key") for row in options]
        if len(keys) < 2 or len(set(keys)) != len(keys):
            raise ValueError("at least two distinct Rust-supported alternatives required")
        legal_keys = label.get("legal_decision_keys")
        if not isinstance(legal_keys, list) or not legal_keys or \
                len(set(legal_keys)) != len(legal_keys) or not set(legal_keys) <= set(keys):
            raise ValueError("explicit legal candidate identities required")
        chosen_key = label.get("chosen_decision_key")
        if chosen_key not in legal_keys:
            raise ValueError("observed expert action was not a legal candidate")
        for field in ("source_sha256", "review_evidence_id"):
            if not isinstance(label.get(field), str) or not label[field]:
                raise ValueError("source and review evidence required")
        provenance = dict(kind="reviewed_demonstration",
                          evidence_id=label["review_evidence_id"])
        records.append(dict(patch=patch, content_sha256=content_sha256,
            engine_sha256=engine_sha256, split=label.get("split"), mode="sft",
            state_coverage=label["state_coverage"],
            source_sha256=label["source_sha256"], match_id=label["match_id"],
            observation_sha256=frame["observation_sha256"],
            label_provenance=provenance,
            candidates=[dict(id=key, features=row["features"],
                             legal=key in legal_keys) for key, row in zip(keys, options)],
            chosen=keys.index(chosen_key)))
    validate_partition(records, patch=patch, content_sha256=content_sha256,
                       engine_sha256=engine_sha256)
    return dict(schema_version=1, kind="reviewed_action_features",
                feature_names=names, records=records,
                evidence_registry=review.get("evidence_registry") or {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--content-sha256", required=True)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.frames.open(encoding="utf-8") as handle:
        frames = [json.loads(line) for line in handle if line.strip()]
    review = json.loads(args.review.read_text(encoding="utf-8"))
    document = export(frames, review, patch=args.patch,
                      content_sha256=args.content_sha256,
                      engine_sha256=args.engine_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                     indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(rows=len(document["records"]), output=str(args.output)),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
