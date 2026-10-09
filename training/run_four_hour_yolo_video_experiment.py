#!/usr/bin/env python3
"""Time-boxed, isolated YOLO self-training experiment on local TFT videos.

Predicted boxes and names are weak labels, never reviewed ground truth. All
generated media, labels and weights stay outside Git in the requested SSD run.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import cv2
import torch
from ultralytics import YOLO


def emit(event: str, **details: object) -> None:
    print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                      "event": event, **details}, ensure_ascii=False), flush=True)


def monitor_gpu(path: Path, stop: threading.Event) -> None:
    with path.open("w", encoding="utf-8") as report:
        report.write("utc,utilization_percent,memory_used_mib,temperature_c\n")
        while not stop.is_set():
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                     "--format=csv,noheader,nounits"], capture_output=True,
                    text=True, check=True, timeout=5)
                report.write(datetime.now(timezone.utc).isoformat() + "," +
                             result.stdout.strip().replace(", ", ",") + "\n")
                report.flush()
            except (OSError, subprocess.SubprocessError):
                pass
            stop.wait(15)


def link_tree(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target, copy_function=os.link,
                    ignore=shutil.ignore_patterns("*.cache"))


def yolo_line(class_id: int, box: list[float], width: int, height: int) -> str:
    x0, y0, x1, y1 = box
    return (f"{class_id} {(x0+x1)/(2*width):.6f} "
            f"{(y0+y1)/(2*height):.6f} {(x1-x0)/width:.6f} "
            f"{(y1-y0)/height:.6f}")


def prepare(args: argparse.Namespace, deadline: float) -> dict:
    root = args.output
    videos = sorted(p for p in args.videos.iterdir()
                    if p.is_file() and p.suffix.lower() in {".mp4", ".webm"})
    if args.max_videos:
        videos = videos[:args.max_videos]
    if not videos:
        raise ValueError("No complete videos found")
    link_tree(args.hud_dataset, root / "hud")
    link_tree(args.champion_dataset, root / "champions")
    hud_yaml = (root / "hud" / "data.yaml")
    hud_config = hud_yaml.read_text().replace(str(args.hud_dataset),
                                               str(root / "hud"))
    hud_yaml.unlink()  # A hard-linked copy must not rewrite the source dataset.
    hud_yaml.write_text(hud_config)
    proposals = root / "proposals.jsonl"
    hud_model = YOLO(str(args.hud_weights))
    name_model = YOLO(str(args.champion_weights))
    counts = Counter()
    with proposals.open("w", encoding="utf-8") as record:
        for video_index, video in enumerate(videos):
            if not args.prepare_only and time.monotonic() >= deadline - 1800:
                emit("preparation_deadline", processed=video_index,
                     total=len(videos))
                break
            cap = cv2.VideoCapture(str(video))
            if not cap.isOpened():
                emit("video_open_failed", video=video.name)
                continue
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frames / fps if fps > 0 else 0
            if duration < 30:
                cap.release()
                emit("video_too_short", video=video.name, seconds=duration)
                continue
            emit("video_started", index=video_index+1, total=len(videos),
                 video=video.name, seconds=round(duration, 1))
            for sample in range(args.samples_per_video):
                second = duration * (sample + 1) / (args.samples_per_video + 1)
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * second)
                ok, frame = cap.read()
                if not ok:
                    counts["decode_failed"] += 1
                    continue
                height, width = frame.shape[:2]
                result = hud_model.predict(frame, device=0, imgsz=640,
                                           conf=0.12, verbose=False)[0]
                lines, crops, crop_details = [], [], []
                for box in result.boxes:
                    category = int(box.cls.item())
                    score = float(box.conf.item())
                    coords = [float(x) for x in box.xyxy[0].tolist()]
                    limit = 0.20 if category in (0, 1) else 0.55
                    if score >= limit:
                        lines.append(yolo_line(category, coords, width, height))
                    if category not in (0, 1) or score < 0.18:
                        continue
                    x0, y0, x1, y1 = [int(round(x)) for x in coords]
                    x0, y0 = max(0, x0), max(0, y0)
                    x1, y1 = min(width, x1), min(height, y1)
                    if x1-x0 < 20 or y1-y0 < 20:
                        continue
                    crops.append(frame[y0:y1, x0:x1].copy())
                    crop_details.append((category, score, [x0, y0, x1, y1]))
                stem = f"video-{video_index:03d}-{sample:03d}"
                if lines:
                    image_path = root / "hud" / "images" / "train" / f"{stem}.jpg"
                    label_path = root / "hud" / "labels" / "train" / f"{stem}.txt"
                    if not cv2.imwrite(str(image_path), frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, 90]):
                        raise OSError(image_path)
                    label_path.write_text("\n".join(lines) + "\n")
                    counts["hud_frames_weak"] += 1
                    counts["hud_boxes_weak"] += len(lines)
                if crops:
                    identities = name_model.predict(crops, device=0,
                                                    imgsz=224, batch=len(crops),
                                                    verbose=False)
                    for index, (crop, detail, guess) in enumerate(
                            zip(crops, crop_details, identities)):
                        category, detection_score, coords = detail
                        identity = name_model.names[int(guess.probs.top1)]
                        identity_score = float(guess.probs.top1conf)
                        weak_train = identity_score >= args.name_threshold
                        row = {"source": video.name, "second": round(second, 3),
                               "box": coords, "zone_proposal": "board" if category == 0 else "bench",
                               "proposed_name": identity,
                               "detector_score": round(detection_score, 4),
                               "identity_score": round(identity_score, 4),
                               "reviewed": False,
                               "origin": "model_prediction_unverified",
                               "experimental_training": weak_train}
                        record.write(json.dumps(row, ensure_ascii=False) + "\n")
                        counts["name_proposals"] += 1
                        if weak_train:
                            folder = root / "champions" / "train" / identity
                            folder.mkdir(parents=True, exist_ok=True)
                            path = folder / f"{stem}-{index:02d}.jpg"
                            if not cv2.imwrite(str(path), crop,
                                               [cv2.IMWRITE_JPEG_QUALITY, 95]):
                                raise OSError(path)
                            counts["name_crops_weak"] += 1
                if sample % 6 == 0:
                    record.flush()
            cap.release()
            counts["videos_processed"] += 1
            emit("video_finished", video=video.name,
                 frames=counts["hud_frames_weak"],
                 weak_names=counts["name_crops_weak"])
    report = {"sources": [p.name for p in videos], "counts": dict(counts),
              "weak_label_policy": "model proposals used only in isolated experimental training; not reviewed ground truth",
              "holdout": "existing reviewed validation/test splits were kept unchanged"}
    (root / "preparation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def train_stage(name: str, weights: Path, dataset: Path, runs: Path,
                hours: float, image_size: int, batch: int) -> None:
    if hours < 0.08:
        emit("stage_skipped", stage=name, reason="time_exhausted")
        return
    emit("stage_started", stage=name, hours=round(hours, 3),
         dataset=str(dataset), batch=batch)
    torch.cuda.empty_cache()
    model = YOLO(str(weights))
    model.train(data=str(dataset), epochs=1000, time=hours, patience=1000,
                imgsz=image_size, batch=batch, workers=2, device=0,
                amp=False, cache=False, plots=False, optimizer="AdamW",
                project=str(runs), name=name, exist_ok=False,
                save_period=10, seed=31)
    emit("stage_finished", stage=name)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--videos", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--hud-dataset", required=True, type=Path)
    p.add_argument("--champion-dataset", required=True, type=Path)
    p.add_argument("--item-dataset", required=True, type=Path)
    p.add_argument("--hud-weights", required=True, type=Path)
    p.add_argument("--champion-weights", required=True, type=Path)
    p.add_argument("--item-weights", required=True, type=Path)
    p.add_argument("--hours", type=float, default=4.0)
    p.add_argument("--samples-per-video", type=int, default=24)
    p.add_argument("--name-threshold", type=float, default=0.85)
    p.add_argument("--max-videos", type=int, default=0)
    p.add_argument("--prepare-only", action="store_true")
    args = p.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required")
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    started = time.monotonic()
    deadline = started + args.hours * 3600
    emit("experiment_started", hours=args.hours,
         gpu=torch.cuda.get_device_name(0), output=str(args.output))
    monitor_stop = threading.Event()
    threading.Thread(target=monitor_gpu,
                     args=(args.output / "gpu.csv", monitor_stop), daemon=True).start()
    torch.set_num_threads(2)
    prepare(args, deadline)
    if args.prepare_only:
        emit("preparation_only_finished")
        return
    runs = args.output / "runs"
    remaining = max(0.0, deadline - time.monotonic() - 300)
    train_stage("hud-weak-video", args.hud_weights,
                args.output / "hud" / "data.yaml", runs,
                min(1.0, remaining * 0.40 / 3600), 640, 6)
    remaining = max(0.0, deadline - time.monotonic() - 300)
    train_stage("champions-weak-video", args.champion_weights,
                args.output / "champions", runs,
                min(2.0, remaining * 0.75 / 3600), 224, 64)
    remaining = max(0.0, deadline - time.monotonic() - 300)
    train_stage("items-reviewed-existing", args.item_weights,
                args.item_dataset, runs, remaining / 3600, 96, 64)
    monitor_stop.set()
    emit("experiment_finished", elapsed_hours=round((time.monotonic()-started)/3600, 3))


if __name__ == "__main__":
    main()
