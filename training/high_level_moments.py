"""Select 2,000 distinct expert speech moments with source-level eligibility.

This is a review corpus. Neither the English speech nor its translation is an
executed action label or a verified strategy. Source approval is explicit.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from training.expert_video_memory import FILLER, fit_memory, sparse_tfidf, tactical_score, tokens


def build(asr_root: Path, qualification: Path, output: Path, *, count: int):
    if output.exists():
        raise ValueError("use a new output directory")
    approved = json.loads(qualification.read_text())
    if approved.get("kind") != "reviewed_high_level_vod_sources":
        raise ValueError("high-level source review required")
    sources = {row["source_sha256"]: row for row in approved["sources"]}
    manifest = json.loads((asr_root / "progress.json").read_text())
    source_metadata = {row["source_sha256"]: row for row in manifest["sources"]}
    all_rows = []
    for source, review in sources.items():
        if source not in source_metadata:
            raise ValueError(f"source absent from manifest: {source}")
        folder = asr_root / source[:16]
        for part in sorted(folder.glob("*.json")):
            document = json.loads(part.read_text())
            if document.get("source_sha256") != source:
                raise ValueError(f"ASR source mismatch: {part}")
            for segment in document.get("segments", []):
                words = tokens(segment.get("text", ""))
                if len(words) < 5:
                    continue
                score, families = tactical_score(segment["text"], segment.get("average_log_probability"))
                if not families and set(words).intersection(FILLER):
                    continue
                start, end = segment["start"], segment["end"]
                all_rows.append({
                    "source_sha256": source,
                    "source_url": source_metadata[source]["url"],
                    "source_kind": "twitch" if "twitch.tv" in source_metadata[source]["url"] else "youtube",
                    "qualification": review["qualification"],
                    "start": round(start, 2), "end": round(end, 2),
                    "phrase_en": segment["text"].strip(),
                    "cue_score": score, "themes": families or ["contexto_geral"],
                    "phrase_pt_br": None,
                    "translation_status": "pending",
                    "learned_scope": "expert_speech_context_only",
                    "executed_action_label": None,
                })
    unique = {}
    for row in all_rows:
        key = (row["source_sha256"], row["start"], row["end"], row["phrase_en"])
        unique[key] = row
    rows = list(unique.values())
    if len(rows) < count:
        raise ValueError(f"only {len(rows)} eligible distinct speech moments for requested {count}")
    # Include all strong tactical passages first, then nearby explanatory speech.
    by_source = {}
    for source in sources:
        subset = [row for row in rows if row["source_sha256"] == source]
        tactical_times = [row["start"] for row in subset if row["cue_score"] >= 3]
        for row in subset:
            proximity = min((abs(row["start"] - t) for t in tactical_times), default=float("inf"))
            row["selection_score"] = round(row["cue_score"] + (1.5 if proximity <= 45 else 0), 3)
        by_source[source] = sorted(subset, key=lambda row: (-row["selection_score"], row["start"]))
    # Proportional quotas prevent one long VOD from hiding the other players.
    quota = {source: count * len(group) // len(rows) for source, group in by_source.items()}
    leftover = count - sum(quota.values())
    for source in sorted(quota, key=lambda key: -(count * len(by_source[key]) % len(rows)))[:leftover]:
        quota[source] += 1
    selected = [row for source, group in by_source.items() for row in group[:quota[source]]]
    selected.sort(key=lambda row: (row["source_sha256"], row["start"], row["end"]))
    output.mkdir(parents=True)
    with (output / "moments.jsonl").open("w") as log:
        for number, row in enumerate(selected, 1):
            log.write(json.dumps({"moment": number, **row}, ensure_ascii=False) + "\n")
    passages = [
        {"source_sha256": row["source_sha256"], "start": row["start"],
         "end": row["end"], "text": row["phrase_en"],
         "families": row["themes"], "cue_score": row["cue_score"]}
        for row in selected
    ]
    with (output / "passages.jsonl").open("w") as log:
        for row in passages:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    matrix, vocabulary, _ = sparse_tfidf(passages)
    embeddings, singular = fit_memory(matrix, dimensions=32)
    np.savez_compressed(output / "latent_memory.npz", embeddings=embeddings,
                        singular_values=np.asarray(singular), vocabulary=np.asarray(vocabulary))
    report = {
        "kind": "high_level_expert_speech_moments",
        "requested": count, "selected": len(selected),
        "eligible_sources": len(sources),
        "source_counts": dict(Counter(row["source_sha256"] for row in selected)),
        "theme_counts": dict(Counter(theme for row in selected for theme in row["themes"])),
        "vocabulary_terms": len(vocabulary), "latent_dimensions": embeddings.shape[1],
        "translated": 0, "executed_action_labels": 0,
        "policy_trained": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-root", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=2000)
    args = parser.parse_args()
    build(args.asr_root, args.qualification, args.output, count=args.count)


if __name__ == "__main__":
    main()
