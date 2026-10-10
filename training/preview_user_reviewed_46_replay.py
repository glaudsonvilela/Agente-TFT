"""Diagnose a rejected 46-class TFT classifier on a VOD.

Boxes come from calibrated green and orange health-bar pixels, not a trained
TFT detector. Names, when explicitly enabled, remain rejected model guesses.
This diagnostic viewer never stores predictions as ground truth.
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


def locate_unit_candidates(frame: np.ndarray) -> list[dict]:
    """Propose bodies from the game's segmented, dark-backed health bars.

    The fixed body geometry is calibrated against reviewed boxes at the 1920x1080
    working resolution. A proposal is not proof that a champion is present.
    """
    height, width = frame.shape[:2]
    view = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(view, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
    sx, sy = width / 1920, height / 1080
    candidates = []
    for kind, low, high in (
        ("ally", (35, 105, 95), (95, 255, 255)),
        ("opponent", (5, 130, 90), (24, 255, 255)),
    ):
        mask = cv2.inRange(hsv, low, high)
        mask[:45] = 0
        # Reviewed bodies end by y≈878; their bars sit higher. The shop and
        # tooltips below this boundary produced false champion proposals.
        mask[820:] = 0
        mask[:, :230] = 0
        mask[:, 1680:] = 0
        # Dark cell dividers split a genuine bar into short color fragments.
        joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (7, 2)))
        horizontal = cv2.morphologyEx(joined, cv2.MORPH_OPEN,
                                      cv2.getStructuringElement(cv2.MORPH_RECT, (22, 2)))
        contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (30 <= w <= 85 and 3 <= h <= 9):
                continue
            color_fill = np.mean(mask[y:y+h, x:x+w] > 0)
            dark_above = np.mean(gray[y-3:y, x:x+w] < 80)
            dark_below = np.mean(gray[y+h:y+h+3, x:x+w] < 80)
            if color_fill < 0.35 or dark_above < 0.2 or dark_below < 0.5:
                continue
            if kind == "opponent":
                margin, body_bottom = 40, 210
            elif y >= 600:  # Bench bodies are smaller in screen pixels.
                margin, body_bottom = 20, 145
            else:
                margin, body_bottom = 30, 170
            # Damage shortens only the colored part, while the backing keeps
            # the unit anchored to a roughly 64 px full-width bar.
            full_bar_width = max(w, 64)
            box = (max(0, round((x - margin) * sx)),
                   max(0, round((y - 5) * sy)),
                   min(width, round((x + full_bar_width + margin) * sx)),
                   min(height, round((y + body_bottom) * sy)))
            candidates.append({"box": box, "bar_kind": kind,
                               "bar": (x, y, w, h)})
    return sorted(candidates, key=lambda row: (row["box"][1], row["box"][0]))


def locate_health_bars(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Compatibility wrapper for the reviewed-box localization audit."""
    return [row["box"] for row in locate_unit_candidates(frame)]


def infer(model: YOLO | None, frame: np.ndarray,
          pt_names: dict[str, str]) -> tuple[list[dict], float, float]:
    started = time.perf_counter()
    candidates = locate_unit_candidates(frame)
    detection_ms = (time.perf_counter() - started) * 1000
    if not candidates:
        return [], detection_ms, 0.0
    if model is None:
        return candidates, detection_ms, 0.0
    boxes = [row["box"] for row in candidates]
    crops = [frame[y0:y1, x0:x1] for x0, y0, x1, y1 in boxes]
    torch.cuda.synchronize()
    started = time.perf_counter()
    results = model.predict(crops, device=0, imgsz=224,
                            batch=min(24, len(crops)), verbose=False)
    torch.cuda.synchronize()
    classification_ms = (time.perf_counter() - started) * 1000
    rows = []
    for candidate, result in zip(candidates, results):
        game_id = model.names[int(result.probs.top1)]
        rows.append({**candidate, "game_id": game_id,
                     "name": pt_names.get(game_id, game_id),
                     "score_uncalibrated": round(float(result.probs.top1conf), 3)})
    return rows, detection_ms, classification_ms


def worker(requests: Queue, shared: dict, lock: Lock, stop: Event,
           weights: Path | None, pt_names: dict[str, str], log_path: Path) -> None:
    try:
        model = YOLO(str(weights)) if weights else None
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
            fps: float, error: str | None, calibration_only: bool) -> np.ndarray:
    scale = 1280 / frame.shape[1]
    video = cv2.resize(frame, (1280, round(frame.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    out = cv2.copyMakeBorder(video, 48, 0, 0, 0, cv2.BORDER_CONSTANT,
                            value=(16, 16, 16))
    age = second - observation["video_second"] if observation else float("inf")
    if error:
        line = "ERRO: " + error[:120]
    elif observation:
        mode = "CALIBRACAO DE CAIXAS" if calibration_only else "MODELO REPROVADO / PALPITES"
        line = (f"{mode}  |  video {fps:.1f} FPS  |  barras {observation['bar_detection_ms']:.0f} ms"
                f"  |  {observation['unit_candidates']} candidatos  |  atraso {age:.1f} s")
    else:
        line = "CALIBRACAO DE CAIXAS  |  carregando" if calibration_only else "MODELO REPROVADO / PALPITES  |  carregando"
    cv2.putText(out, line, (12, 31), cv2.FONT_HERSHEY_SIMPLEX,
                0.57, (244, 244, 244), 2, cv2.LINE_AA)
    if observation and 0 <= age <= 1.2:
        for row in observation["predictions"]:
            x0, y0, x1, y1 = [round(n * scale) for n in row["box"]]
            y0 += 48
            y1 += 48
            color = ((105, 230, 90) if row["bar_kind"] == "ally"
                     else (45, 165, 255))
            cv2.rectangle(out, (x0, y0), (x1, y1), color, 2)
            if calibration_only:
                label = "barra verde" if row["bar_kind"] == "ally" else "barra laranja"
            else:
                label = f"{row['name']}? {row['score_uncalibrated']:.2f}"
            cv2.putText(out, label, (x0, max(61, y0 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.43, color, 1, cv2.LINE_AA)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--roster", type=Path)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--start", type=float, default=1380)
    parser.add_argument("--duration", type=float, default=90)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--calibration-only", action="store_true",
                        help="Show box proposals without loading or naming champions")
    parser.add_argument("--show-rejected-model", action="store_true",
                        help="Explicitly display guesses from the rejected experiment")
    args = parser.parse_args()
    if not args.calibration_only and not args.show_rejected_model:
        parser.error("This model failed unseen-video and box-alignment checks; "
                     "use --show-rejected-model only for diagnostics")
    if not args.calibration_only and (args.weights is None or args.roster is None):
        parser.error("--weights and --roster are required to display model guesses")
    pt_names = ({row["game_id"]: row["name_pt_br"]
                 for row in json.loads(args.roster.read_text())["rows"]}
                if args.roster else {})
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
                                         None if args.calibration_only else args.weights,
                                         pt_names, args.log), daemon=True)
    thread.start()
    title = ("Agente TFT - calibracao de caixas"
             if args.calibration_only else "Agente TFT - leitura experimental 46 campeoes")
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
            out = display(frame, second, observation, fps, error, args.calibration_only)
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
