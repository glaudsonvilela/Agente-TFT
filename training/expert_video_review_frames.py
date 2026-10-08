"""Make visual review triplets around prioritized expert speech.

Only preexisting, hash-verified local copies are read. Images are review aids,
never action labels; this command does not download or train on predictions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def frame(video: Path, second: float, path: Path):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{second:.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3", str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def parse_source(entry: str) -> tuple[str, Path]:
    source, separator, path = entry.partition("=")
    if separator != "=" or len(source) != 64 or not path:
        raise ValueError("--source requires SHA256=/absolute/video/path")
    return source, Path(path)


def build(queue: Path, output: Path, sources: dict[str, Path], *, limit: int):
    if output.exists():
        raise ValueError("use a new output directory")
    rows = [json.loads(line) for line in queue.open()][:limit]
    if not rows:
        raise ValueError("empty review queue")
    needed = {row["source_sha256"] for row in rows}
    if needed - sources.keys():
        raise ValueError(f"missing local video for: {sorted(needed - sources.keys())}")
    print(f"AGENTE TFT · verificando {len(needed)} vídeos já disponíveis", flush=True)
    for source in needed:
        if not sources[source].is_file() or digest(sources[source]) != source:
            raise ValueError(f"source video identity mismatch: {sources[source]}")
        print(f"Fonte {source[:12]} confirmada", flush=True)
    output.mkdir(parents=True)
    index = output / "visual_review_index.jsonl"
    print(f"AGENTE TFT · revisão visual de {len(rows)} momentos de YouTube/Twitch", flush=True)
    print("Vídeos locais já autorizados e verificados por hash; nenhuma mídia será baixada.", flush=True)
    completed = 0
    with index.open("w") as log:
        for number, row in enumerate(rows, 1):
            center = max(0.0, (row["start"] + row["end"]) / 2)
            images = []
            try:
                for label, second in (("before", max(0.0, row["start"] - 4)),
                                      ("during", center), ("after", row["end"] + 4)):
                    name = f"{number:04d}-{label}.jpg"
                    frame(sources[row["source_sha256"]], second, output / name)
                    images.append({"role": label, "second": round(second, 2), "image": name})
                completed += 1
                status = "ready_for_visual_review"
                error = None
            except (subprocess.CalledProcessError, OSError) as exc:
                status, error = "extraction_failed", str(exc)
            log.write(json.dumps({
                "passage_index": row["passage_index"],
                "source_sha256": row["source_sha256"],
                "source_url": row["source_url"],
                "start": row["start"], "end": row["end"],
                "families": row["families"],
                "images": images, "status": status, "error": error,
                "executed_action_label": None,
            }, ensure_ascii=False) + "\n")
            log.flush()
            if number == 1 or number % 5 == 0 or number == len(rows):
                print(f"{number:3d}/{len(rows)} | {row['source_kind']:7} {row['start']/60:6.1f} min | {','.join(row['families'])} | {row['text'][:80]}", flush=True)
    report = {"requested": len(rows), "visual_triplets_ready": completed,
              "frames_ready": sum(1 for _ in output.glob("*.jpg")),
              "action_labels_created": 0, "runtime_promoted": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Concluído: {completed}/{len(rows)} momentos prontos para revisão. Ações rotuladas: 0.", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--limit", type=int, default=160)
    args = parser.parse_args()
    build(args.queue, args.output, dict(parse_source(value) for value in args.source), limit=args.limit)


if __name__ == "__main__":
    main()
