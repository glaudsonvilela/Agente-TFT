"""Evaluate the isolated classifier on reviewed crops from unseen videos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time

import torch
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    args = parser.parse_args()
    provenance = json.loads((args.experiment / "provenance.json").read_text())
    source_index = json.loads(Path(provenance["source_index"]).read_text())
    by_id = {row["review_id"]: row for row in source_index["records"]}
    model = YOLO(str(args.weights))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    for _ in range(2):
        model.predict(str(by_id[provenance["holdout_review_ids"][0]]["natural_crop"]),
                      device=0, imgsz=224, verbose=False)
    output = []
    elapsed_ms = []
    for review_id in provenance["holdout_review_ids"]:
        row = by_id[review_id]
        times = []
        result = None
        for _ in range(5):
            torch.cuda.synchronize()
            started = time.perf_counter()
            result = model.predict(str(row["natural_crop"]), device=0,
                                   imgsz=224, verbose=False)[0]
            torch.cuda.synchronize()
            times.append((time.perf_counter() - started) * 1000)
        assert result is not None
        top5 = [model.names[int(i)] for i in result.probs.top5]
        top1 = top5[0]
        output.append({"review_id": review_id, "truth": row["game_id"],
                       "predicted": top1, "top5": top5,
                       "score_uncalibrated": float(result.probs.top1conf),
                       "top1_correct": top1 == row["game_id"],
                       "top5_contains_truth": row["game_id"] in top5,
                       "source_video": row["source_video_local"],
                       "median_wall_ms": round(statistics.median(times), 1)})
        elapsed_ms.extend(times)
    report = {
        "scope": "held_out_source_videos",
        "weights": str(args.weights),
        "model_predictions_used_as_labels": False,
        "n": len(output),
        "top1_correct": sum(x["top1_correct"] for x in output),
        "top5_correct": sum(x["top5_contains_truth"] for x in output),
        "median_wall_ms_per_crop": round(statistics.median(elapsed_ms), 1),
        "maximum_wall_ms_per_crop": round(max(elapsed_ms), 1),
        "gpu": torch.cuda.get_device_name(0),
        "rows": output,
        "limitations": ["Only four reviewed crops from two unseen videos.",
                        "This times classification of an already cropped unit, not full-frame detection.",
                        "Scores are uncalibrated and do not prove 46-class accuracy."],
    }
    path = args.experiment / "heldout-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
