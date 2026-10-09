"""Attach one review frame to each selected high-level VOD speech moment.

Existing local video copies are SHA-verified; no remote media is fetched. A
frame is a visual reference, not evidence that the spoken play was executed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from training.expert_video_review_frames import digest, frame, parse_source


def build(moments: Path, output: Path, sources: dict[str, Path], workers: int):
    if not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    rows = [json.loads(line) for line in moments.open()]
    needed = {row["source_sha256"] for row in rows}
    if needed - sources.keys():
        raise ValueError("a qualified video file is missing")
    print(f"AGENTE TFT · verificando {len(needed)} vídeos de alto nível", flush=True)
    for source in needed:
        if not sources[source].is_file() or digest(sources[source]) != source:
            raise ValueError(f"video identity mismatch: {sources[source]}")
        print(f"Fonte {source[:12]} confirmada", flush=True)
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    def extract(row):
        path = output / f"moment-{row['moment']:04d}.jpg"
        if not path.is_file():
            frame(sources[row["source_sha256"]], (row["start"] + row["end"]) / 2, path)
        return {"moment": row["moment"], "source_sha256": row["source_sha256"],
                "source_seconds": round((row["start"] + row["end"]) / 2, 2),
                "image": path.name, "status": "visual_reference_only",
                "executed_action_label": None}

    records = []
    print(f"Extraindo {len(rows)} momentos com {workers} processos leves; a tela mostra o progresso real.", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(extract, row): row["moment"] for row in rows}
        for future in as_completed(futures):
            try:
                records.append(future.result())
            except Exception as exc:
                records.append({"moment": futures[future], "status": "extraction_failed", "error": str(exc)})
            count = len(records)
            if count == 1 or count % 25 == 0 or count == len(rows):
                elapsed = time.perf_counter() - started
                print(f"{count:4d}/{len(rows)} | {count/elapsed:.1f} momentos/s | {elapsed/60:.1f} min", flush=True)
    records.sort(key=lambda row: row["moment"])
    with (output / "moment_frames.jsonl").open("w") as log:
        for row in records:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    complete = sum(row["status"] == "visual_reference_only" for row in records)
    report = {"requested": len(rows), "frames_ready": complete,
              "failures": len(rows) - complete, "executed_action_labels": 0,
              "elapsed_seconds": round(time.perf_counter() - started, 2)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Concluído: {complete}/{len(rows)} quadros de referência. Nenhuma jogada inferida só pela fala.", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    build(args.moments, args.output, dict(parse_source(value) for value in args.source), args.workers)


if __name__ == "__main__":
    main()
