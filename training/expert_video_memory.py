"""Index tactical speech from authorized VODs for fast, grounded review.

The learned latent text representation is a retrieval aid. Spoken plans are not
executed-action labels or evidence that a move won a match. Video timestamps
and source hashes let a reviewer inspect the actual play before labeling it.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds


CUES = {
    "economy": ("gold", "econ", "interest", "roll", "reroll", "level", "xp", "streak", "tempo"),
    "composition": ("comp", "trait", "carry", "unit", "board", "pivot", "line", "pair", "upgrade"),
    "items": ("item", "slam", "component", "rageblade", "guinsoo", "sword", "bow", "rod"),
    "positioning": ("position", "frontline", "backline", "corner", "scout", "opponent", "side"),
    "combat": ("fight", "combat", "win", "lose", "lost", "stronger", "weaker", "damage"),
    "choices": ("augment", "carousel", "wisp", "charm", "encounter", "reward", "pick"),
}
REASONING = {"because", "if", "when", "should", "need", "better", "instead", "why", "could", "want", "rather", "maybe"}
FILLER = {"subscribe", "follow", "chat", "stream", "donate", "thank", "thanks", "hello", "hey"}
STOP = {"the", "and", "for", "that", "this", "with", "from", "have", "just", "like", "your", "you", "are", "but", "not", "can", "was", "what", "our", "they", "get", "got", "all", "too", "its", "it's", "we're", "we", "i'm", "you'", "about", "would", "there", "then", "them", "into", "really", "actually", "okay", "yeah", "right"}
TOKEN = re.compile(r"[a-z][a-z0-9']{1,}", re.I)


def tokens(text: str) -> list[str]:
    return [word.lower() for word in TOKEN.findall(text)]


def tactical_score(text: str, log_probability: float | None) -> tuple[float, list[str]]:
    words = set(tokens(text))
    families = [name for name, cues in CUES.items() if words.intersection(cues)]
    if len(words) < 5 or not families:
        return 0.0, []
    reasoning = len(words.intersection(REASONING))
    filler = len(words.intersection(FILLER))
    quality = max(0.0, min(1.0, 1.0 + float(log_probability or -0.6)))
    score = 2.0 * len(families) + min(reasoning, 2) * 1.5 + quality - min(filler, 2)
    return score, families


def collect(root: Path) -> tuple[list[dict], dict]:
    manifest = json.loads((root / "progress.json").read_text())
    rows = []
    coverage = []
    for source in manifest["sources"]:
        directory = root / source["source_sha256"][:16]
        parts = sorted(directory.glob("*.json"))
        count = 0
        for part in parts:
            document = json.loads(part.read_text())
            if document.get("source_sha256") != source["source_sha256"]:
                raise ValueError(f"ASR source hash mismatch: {part}")
            for segment in document.get("segments", []):
                start, end = segment.get("start"), segment.get("end")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
                    continue
                score, families = tactical_score(segment.get("text", ""), segment.get("average_log_probability"))
                count += 1
                if score < 3.0:
                    continue
                rows.append({
                    "source_sha256": source["source_sha256"],
                    "source_url": source["url"],
                    "source_kind": "twitch" if "twitch.tv" in source["url"] else "youtube",
                    "start": round(start, 2), "end": round(end, 2),
                    "text": segment["text"].strip(),
                    "families": families, "cue_score": round(score, 3),
                    "evidence_kind": "speech_only",
                    "executed_action_label": None,
                    "outcome_label": None,
                })
        coverage.append({
            "source_sha256": source["source_sha256"],
            "duration_seconds": source["total_seconds"],
            "asr_segments": count,
            "candidate_segments": sum(r["source_sha256"] == source["source_sha256"] for r in rows),
            "asr_present": bool(parts),
        })
    rows.sort(key=lambda row: (row["source_sha256"], row["start"], row["end"]))
    return rows, {"sources": coverage, "candidate_segments": len(rows)}


def sparse_tfidf(rows: list[dict], *, max_terms: int = 3000):
    documents = [Counter(word for word in tokens(row["text"]) if word not in STOP) for row in rows]
    df = Counter(word for doc in documents for word in doc)
    vocabulary = [word for word, _ in df.most_common(max_terms) if df[word] >= 2]
    columns = {word: i for i, word in enumerate(vocabulary)}
    data, indices, indptr = [], [], [0]
    n = len(rows)
    for doc in documents:
        values = []
        for word, count in doc.items():
            if word in columns:
                idf = math.log((1 + n) / (1 + df[word])) + 1
                values.append((columns[word], (1 + math.log(count)) * idf))
        norm = math.sqrt(sum(value * value for _, value in values)) or 1
        for column, value in sorted(values):
            indices.append(column)
            data.append(value / norm)
        indptr.append(len(data))
    return csr_matrix((data, indices, indptr), shape=(n, len(vocabulary)), dtype=np.float32), vocabulary, df


def fit_memory(matrix: csr_matrix, dimensions: int) -> tuple[np.ndarray, list[float]]:
    if min(matrix.shape) < 3:
        raise ValueError("at least three tactical passages and terms required")
    k = min(dimensions, min(matrix.shape) - 1)
    left, singular, _ = svds(matrix, k=k, random_state=0)
    order = np.argsort(singular)[::-1]
    embedding = left[:, order] * singular[order]
    embedding /= np.maximum(np.linalg.norm(embedding, axis=1, keepdims=True), 1e-8)
    return embedding.astype(np.float32), singular[order].tolist()


def prioritize(rows: list[dict], embedding: np.ndarray, *, limit: int, per_source: int) -> list[int]:
    chosen = []
    source_counts = Counter()
    family_counts = Counter()
    best_similarity = np.zeros(len(rows), dtype=np.float32)
    available = set(range(len(rows)))
    while available and len(chosen) < limit:
        best, best_value = None, -1e9
        for i in available:
            row = rows[i]
            source = row["source_sha256"]
            if source_counts[source] >= per_source:
                continue
            family_bonus = sum(1 / (1 + family_counts[f]) for f in row["families"])
            value = row["cue_score"] + 2.5 * family_bonus - 4 * float(best_similarity[i])
            if value > best_value:
                best, best_value = i, value
        if best is None:
            break
        chosen.append(best)
        available.remove(best)
        row = rows[best]
        source_counts[row["source_sha256"]] += 1
        family_counts.update(row["families"])
        for i in list(available):
            if rows[i]["source_sha256"] == row["source_sha256"] and abs(rows[i]["start"] - row["start"]) < 45:
                available.remove(i)
        best_similarity = np.maximum(best_similarity, embedding @ embedding[best])
    return chosen


def run(root: Path, output: Path, *, limit: int = 160, dimensions: int = 32) -> dict:
    if output.exists():
        raise ValueError("use a new output directory")
    rows, report = collect(root)
    matrix, vocabulary, _ = sparse_tfidf(rows)
    embedding, singular = fit_memory(matrix, dimensions)
    source_count = sum(s["asr_present"] for s in report["sources"])
    selected = prioritize(rows, embedding, limit=limit, per_source=max(1, math.ceil(limit / max(1, source_count))))
    output.mkdir(parents=True)
    (output / "passages.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (output / "review_queue.jsonl").write_text("".join(json.dumps({"passage_index": i, **rows[i]}, ensure_ascii=False) + "\n" for i in selected))
    np.savez_compressed(output / "latent_memory.npz", embeddings=embedding, singular_values=np.asarray(singular), vocabulary=np.asarray(vocabulary))
    report.update({
        "kind": "authorized_vod_tactical_speech_memory",
        "indexed_passages": len(rows), "review_queue": len(selected),
        "dimensions": embedding.shape[1], "vocabulary_terms": len(vocabulary),
        "family_counts": dict(Counter(f for row in rows for f in row["families"])),
        "learned_scope": "latent_text_retrieval_for_review",
        "action_policy_trained": False, "runtime_promoted": False,
        "limitations": [
            "Speech may describe hypotheticals, other players, or past rounds.",
            "No spoken passage is an executed action or outcome label.",
            "Video review and patch binding are required before policy training.",
        ],
    })
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=160)
    args = parser.parse_args()
    print(json.dumps(run(args.asr_root, args.output, limit=args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
