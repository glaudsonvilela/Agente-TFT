"""Show a TFT replay with live YOLO detections and tentative champion names.

The detector locates units. A separate classifier names each unit crop. Neither
prediction is a ground-truth label; all predictions are logged for inspection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time

import cv2
import numpy as np
from ultralytics import YOLO


UNIT_CLASSES = {"board_unit", "bench_unit", "enemy_candidate"}
COLORS = {
    "board_unit": (95, 235, 70),
    "bench_unit": (70, 205, 240),
    "enemy_candidate": (70, 70, 245),
    "shop_offer": (230, 155, 40),
    "player_avatar": (230, 80, 230),
}


def intersection_over_union(first, second):
    x0, y0 = max(first[0], second[0]), max(first[1], second[1])
    x1, y1 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, x1-x0) * max(0, y1-y0)
    first_area = max(0, first[2]-first[0]) * max(0, first[3]-first[1])
    second_area = max(0, second[2]-second[0]) * max(0, second[3]-second[1])
    return intersection / max(1, first_area + second_area - intersection)


def enemy_health_bar_candidates(frame, existing):
    """Propose enemy crops from red health bars; never treat them as verified IDs."""
    height, width = frame.shape[:2]
    if (width, height) != (1920, 1080):
        return []
    blue, green, red = cv2.split(frame)
    red_pixels = ((red.astype(np.int16) > green.astype(np.int16) * 1.55)
                  & (red.astype(np.int16) > blue.astype(np.int16) * 1.35)
                  & (red > 65) & (green < 115)).astype(np.uint8) * 255
    red_pixels[:90] = 0
    red_pixels[680:] = 0
    red_pixels[:, :350] = 0
    red_pixels[:, 1550:] = 0
    bars = cv2.morphologyEx(red_pixels, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (24, 2)))
    contours, _ = cv2.findContours(bars, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    output = []
    for contour in contours:
        x, y, bar_width, bar_height = cv2.boundingRect(contour)
        if not (28 <= bar_width <= 130 and 2 <= bar_height <= 12):
            continue
        dark_above = np.mean(gray[y-3:y, x:x+bar_width] < 70)
        dark_below = np.mean(gray[y+bar_height:y+bar_height+3, x:x+bar_width] < 70)
        dark_inner = np.mean(gray[y:y+bar_height, x:x+bar_width] < 70)
        if dark_above < 0.6 or dark_below < 0.35 or dark_inner < 0.8:
            continue
        box = [max(0, x-25), max(0, y-5), min(width, x+bar_width+25),
               min(height, y+145)]
        if any(intersection_over_union(box, row["box"]) > 0.25 for row in existing
               if row["class"] in UNIT_CLASSES):
            continue
        output.append({"class": "enemy_candidate", "box": box,
                       "det_confidence": None,
                       "source": "red_health_bar_pixel_proposal",
                       "health_bar": [x, y, x+bar_width, y+bar_height]})
    return output[:15]


def classify_units(model, frame, detections):
    crops, indexes = [], []
    height, width = frame.shape[:2]
    for index, entry in enumerate(detections):
        if entry["class"] not in UNIT_CLASSES:
            continue
        x0, y0, x1, y1 = entry["box"]
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        if x1 - x0 < 12 or y1 - y0 < 12:
            continue
        crops.append(frame[y0:y1, x0:x1].copy())
        indexes.append(index)
    if not crops:
        return
    results = model.predict(source=crops, device=0, imgsz=224,
                            batch=min(32, len(crops)), verbose=False)
    for index, result in zip(indexes, results):
        detections[index]["name"] = model.names[int(result.probs.top1)]
        detections[index]["name_confidence"] = round(float(result.probs.top1conf), 3)


def inference_loop(requests, shared, lock, stop, detector_path, classifier_path, log_path):
    try:
        detector = YOLO(str(detector_path))
        classifier = YOLO(str(classifier_path))
        with log_path.open("w", encoding="utf-8") as log:
            while not stop.is_set():
                try:
                    stamp, frame = requests.get(timeout=0.2)
                except Empty:
                    continue
                started = time.monotonic()
                result = detector.predict(source=frame, device=0, imgsz=640,
                                          conf=0.15, iou=0.45, verbose=False)[0]
                detections = []
                for box in result.boxes:
                    name = detector.names[int(box.cls.item())]
                    detections.append({
                        "class": name,
                        "box": [int(round(value)) for value in box.xyxy[0].tolist()],
                        "det_confidence": round(float(box.conf.item()), 3),
                    })
                detections.extend(enemy_health_bar_candidates(frame, detections))
                classify_units(classifier, frame, detections)
                observation = {"video_seconds": round(stamp, 2),
                               "inference_seconds": round(time.monotonic() - started, 3),
                               "detections": detections}
                log.write(json.dumps(observation, ensure_ascii=False) + "\n")
                log.flush()
                with lock:
                    shared["latest"] = observation
                    shared["error"] = None
    except Exception as exc:
        with lock:
            shared["error"] = f"{type(exc).__name__}: {exc}"


def overlay(frame, observation, video_seconds, error):
    target_width = 1280
    ratio = target_width / frame.shape[1]
    video = cv2.resize(frame, (target_width, round(frame.shape[0] * ratio)),
                       interpolation=cv2.INTER_AREA)
    output = cv2.copyMakeBorder(video, 48, 0, 0, 0, cv2.BORDER_CONSTANT, value=(18, 18, 18))
    age = video_seconds - observation["video_seconds"] if observation else float("inf")
    if error:
        header = f"ERRO: {error[:110]}"
    elif observation is None:
        header = "YOLO carregando | deteccoes ainda nao disponiveis"
    else:
        units = sum(row["class"] in UNIT_CLASSES for row in observation["detections"])
        header = (f"Partida {video_seconds/60:.1f} min | YOLO {units} unidades | "
                  f"calculo {observation['inference_seconds']:.2f}s | atraso {age:.2f}s")
    cv2.putText(output, header, (12, 31), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (245, 245, 245), 2, cv2.LINE_AA)
    if not observation or age > 1.5 or age < -0.2:
        return output
    for row in observation["detections"]:
        if row["class"] not in UNIT_CLASSES and row["class"] not in ("shop_offer", "player_avatar"):
            continue
        x0, y0, x1, y1 = row["box"]
        x0, x1 = round(x0 * ratio), round(x1 * ratio)
        y0, y1 = round(y0 * ratio) + 48, round(y1 * ratio) + 48
        color = COLORS[row["class"]]
        cv2.rectangle(output, (x0, y0), (x1, y1), color, 2)
        label = row.get("name", row["class"])
        if row["class"] == "enemy_candidate":
            label = "INIMIGO? " + label
        if "name_confidence" in row:
            label += f" {row['name_confidence']:.2f}"
            if row["name_confidence"] < 0.5:
                color = (0, 200, 255)
        else:
            if row["det_confidence"] is not None:
                label += f" {row['det_confidence']:.2f}"
        text_y = max(60, y0 - 7)
        cv2.putText(output, label, (max(0, x0), text_y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.43, color, 1, cv2.LINE_AA)
    return output


def offer(requests, stamp, frame):
    try:
        requests.put_nowait((stamp, frame.copy()))
    except Full:
        try:
            requests.get_nowait()
        except Empty:
            pass
        try:
            requests.put_nowait((stamp, frame.copy()))
        except Full:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("detector", type=Path)
    parser.add_argument("classifier", type=Path)
    parser.add_argument("log", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=180.0)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Video nao abriu: {args.video}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not 1 <= fps <= 120:
        raise RuntimeError(f"FPS invalido: {fps}")
    capture.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)
    requests = Queue(maxsize=1)
    shared = {"latest": None, "error": None}
    lock, stop = Lock(), Event()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    worker = Thread(target=inference_loop, args=(requests, shared, lock, stop,
                                                  args.detector, args.classifier,
                                                  args.log), daemon=True)
    worker.start()
    window_name = "Agente TFT - leitura YOLO da partida"
    if not args.headless:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 1280, 768)
    first_frame = int(round(args.start * fps))
    start_wall = time.monotonic()
    next_inference = -1.0
    frame_count = 0
    try:
        while not stop.is_set():
            elapsed = time.monotonic() - start_wall
            if elapsed >= args.duration:
                break
            target_frame = first_frame + int(elapsed * fps)
            current_frame = int(capture.get(cv2.CAP_PROP_POS_FRAMES))
            while current_frame < target_frame - 1:
                if not capture.grab():
                    return
                current_frame += 1
            ok, frame = capture.read()
            if not ok:
                break
            stamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if stamp <= 0:
                stamp = args.start + elapsed
            if elapsed >= next_inference:
                offer(requests, stamp, frame)
                next_inference = elapsed + 0.25
            with lock:
                observation, error = shared["latest"], shared["error"]
            if args.headless:
                if error:
                    raise RuntimeError(error)
            else:
                cv2.imshow(window_name, overlay(frame, observation, stamp, error))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
            frame_count += 1
            remaining = (current_frame + 1 - first_frame) / fps - (time.monotonic() - start_wall)
            if remaining > 0:
                time.sleep(min(remaining, 0.03))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        capture.release()
        if not args.headless:
            cv2.destroyWindow(window_name)
        worker.join(timeout=3)
        print(f"Reproducao encerrada: {frame_count} quadros; log: {args.log}", flush=True)


if __name__ == "__main__":
    main()
