"""Diagnose a rejected 46-class TFT classifier on a VOD.

Boxes come from green health-bar pixels, not a trained TFT detector. Names are
model guesses. This diagnostic viewer measures the whole replay path and never
stores predictions as ground truth.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time

import cv2
import numpy as np
import torch
from ultralytics import YOLO


def locate_health_bars(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    height, width = frame.shape[:2]
    view = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(view, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 105, 95), (95, 255, 255))
    mask[:110] = 0
    mask[950:] = 0
    mask[:, :230] = 0
    mask[:, 1680:] = 0
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (22, 2)))
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    sx, sy = width / 1920, height / 1080
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (32 <= w <= 120 and 2 <= h <= 13):
            continue
        # Include the bar and the body below it. The crop remains a hypothesis.
        left = max(0, round((x - 10) * sx))
        top = max(0, round((y - 5) * sy))
        right = min(width, round((x + w + 10) * sx))
        bottom = min(height, round((y + max(105, 2.3 * w)) * sy))
        if right - left >= 30 and bottom - top >= 40:
            boxes.append((left, top, right, bottom))
    return sorted(boxes, key=lambda b: (b[1], b[0]))[:24]


def infer(model: YOLO, frame: np.ndarray, pt_names: dict[str, str]) -> tuple[list[dict], float, float]:
    started = time.perf_counter()
    boxes = locate_health_bars(frame)
    detection_ms = (time.perf_counter() - started) * 1000
    if not boxes:
        return [], detection_ms, 0.0
    crops = [frame[y0:y1, x0:x1] for x0, y0, x1, y1 in boxes]
    torch.cuda.synchronize()
    started = time.perf_counter()
    results = model.predict(crops, device=0, imgsz=224,
                            batch=min(24, len(crops)), verbose=False)
    torch.cuda.synchronize()
    classification_ms = (time.perf_counter() - started) * 1000
    rows = []
    for box, result in zip(boxes, results):
        game_id = model.names[int(result.probs.top1)]
        rows.append({"box": box, "game_id": game_id,
                     "name": pt_names.get(game_id, game_id),
                     "score_uncalibrated": round(float(result.probs.top1conf), 3)})
    return rows, detection_ms, classification_ms


def worker(requests: Queue, shared: dict, lock: Lock, stop: Event,
           weights: Path, pt_names: dict[str, str], log_path: Path) -> None:
    try:
        model = YOLO(str(weights))
        with log_path.open("w", encoding="utf-8") as log:
            while not stop.is_set():
                try:
                    second, frame = requests.get(timeout=0.2)
                except Empty:
                    continue
                rows, bars_ms, cls_ms = infer(model, frame, pt_names)
                observation = {"video_second": round(second, 2),
                               "bar_detection_ms": round(bars_ms, 1),
                               "classification_ms": round(cls_ms, 1),
                               "unit_candidates": len(rows), "predictions": rows}
                log.write(json.dumps(observation, ensure_ascii=False) + "\n")
                log.flush()
                with lock:
                    shared["observation"] = observation
    except Exception as exc:
        with lock:
            shared["error"] = f"{type(exc).__name__}: {exc}"


def display(frame: np.ndarray, second: float, observation: dict | None,
            fps: float, error: str | None) -> np.ndarray:
    scale = 1280 / frame.shape[1]
    video = cv2.resize(frame, (1280, round(frame.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    out = cv2.copyMakeBorder(video, 48, 0, 0, 0, cv2.BORDER_CONSTANT,
                            value=(16, 16, 16))
    age = second - observation["video_second"] if observation else float("inf")
    if error:
        line = "ERRO: " + error[:120]
    elif observation:
        line = (f"MODELO REPROVADO / PALPITES  |  video {fps:.1f} FPS  |  barras {observation['bar_detection_ms']:.0f} ms"
                f"  |  nomes {observation['classification_ms']:.0f} ms"
                f"  |  {observation['unit_candidates']} candidatos  |  atraso {age:.1f} s")
    else:
        line = "MODELO REPROVADO / PALPITES  |  carregando diagnostico"
    cv2.putText(out, line, (12, 31), cv2.FONT_HERSHEY_SIMPLEX,
                0.57, (244, 244, 244), 2, cv2.LINE_AA)
    if observation and 0 <= age <= 1.2:
        for row in observation["predictions"]:
            x0, y0, x1, y1 = [round(n * scale) for n in row["box"]]
            y0 += 48
            y1 += 48
            color = (105, 230, 90)
            cv2.rectangle(out, (x0, y0), (x1, y1), color, 2)
            label = f"{row['name']}? {row['score_uncalibrated']:.2f}"
            cv2.putText(out, label, (x0, max(61, y0 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.43, color, 1, cv2.LINE_AA)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--start", type=float, default=1380)
    parser.add_argument("--duration", type=float, default=90)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--show-rejected-model", action="store_true",
                        help="Explicitly display guesses from the rejected experiment")
    args = parser.parse_args()
    if not args.show_rejected_model:
        parser.error("This model failed unseen-video and box-alignment checks; "
                     "use --show-rejected-model only for diagnostics")
    pt_names = {row["game_id"]: row["name_pt_br"]
                for row in json.loads(args.roster.read_text())["rows"]}
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise FileNotFoundError(args.video)
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if not 1 <= source_fps <= 120:
        raise RuntimeError(f"Invalid video FPS: {source_fps}")
    cap.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)
    requests: Queue = Queue(maxsize=1)
    shared: dict = {"observation": None, "error": None}
    lock, stop = Lock(), Event()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    thread = Thread(target=worker, args=(requests, shared, lock, stop,
                                         args.weights, pt_names, args.log), daemon=True)
    thread.start()
    title = "Agente TFT - leitura experimental 46 campeoes"
    if not args.headless:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title, 1280, 768)
    started = time.monotonic()
    next_read = 0.0
    recent_frames: deque[float] = deque(maxlen=60)
    displayed = 0
    saved_snapshot = False
    try:
        while time.monotonic() - started < args.duration:
            elapsed = time.monotonic() - started
            target = int((args.start + elapsed) * source_fps)
            current = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            while current < target - 1:
                if not cap.grab():
                    break
                current += 1
            ok, frame = cap.read()
            if not ok:
                break
            second = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 or args.start + elapsed
            if elapsed >= next_read:
                try:
                    requests.put_nowait((second, frame.copy()))
                except Full:
                    try:
                        requests.get_nowait()
                    except Empty:
                        pass
                    requests.put_nowait((second, frame.copy()))
                next_read = elapsed + 0.25
            with lock:
                observation, error = shared["observation"], shared["error"]
            if error:
                raise RuntimeError(error)
            now = time.monotonic()
            recent_frames.append(now)
            fps = ((len(recent_frames) - 1) / (recent_frames[-1] - recent_frames[0])
                   if len(recent_frames) > 1 and recent_frames[-1] > recent_frames[0] else 0.0)
            out = display(frame, second, observation, fps, error)
            if args.snapshot and observation and not saved_snapshot:
                cv2.imwrite(str(args.snapshot), out)
                saved_snapshot = True
            if not args.headless:
                cv2.imshow(title, out)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            displayed += 1
            remaining = (target + 1) / source_fps - (args.start + time.monotonic() - started)
            if remaining > 0:
                time.sleep(min(remaining, 0.03))
    finally:
        stop.set()
        cap.release()
        thread.join(timeout=3)
        if not args.headless:
            cv2.destroyWindow(title)
        print(f"preview frames={displayed} log={args.log}", flush=True)


if __name__ == "__main__":
    main()
