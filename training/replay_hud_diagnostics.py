"""Replay the real HUD readers beside their timing and tentative observations.

The window and recording contain the same pixels. Analysis uses the native Rust
readers and the installed-style YOLO overlay; it never treats predictions as
ground truth or feeds them back into training.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
# Tesseract starts several OpenMP threads per HUD region. The native reader
# runs regions in parallel, so unrestricted OpenMP starves video playback.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OMP_THREAD_LIMIT"] = "1"
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
from threading import Event, Lock, Thread
import time
from types import SimpleNamespace

import cv2
import numpy as np
import psutil

from e1.protocol import NativeWorker
from hm.board_hub_live import BoardHubLive
from hm.board_worker import BoardWorker
from hm.replay_decision import ReplayDecisionEngine


WIDTH, HEIGHT = 1600, 900
VIDEO_WIDTH, VIDEO_HEIGHT = WIDTH, HEIGHT
FONT = cv2.FONT_HERSHEY_SIMPLEX


def put(image, text, x, y, color=(0, 255, 0), size=.55):
    cv2.putText(image, str(text)[:100], (x, y), FONT, size, color, 1, cv2.LINE_AA)


def latest(queue, value):
    try:
        queue.put_nowait(value)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        queue.put_nowait(value)


def gpu_usage():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"], capture_output=True, text=True,
            timeout=1, check=True)
        return [int(part.strip()) for part in result.stdout.splitlines()[0].split(",")]
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def monitor(stop, shared, lock):
    parent = psutil.Process(os.getpid())
    parent.cpu_percent(None)
    psutil.cpu_percent(None)
    try:
        cpu_model = next(line.split(":", 1)[1].strip() for line in
                         Path("/proc/cpuinfo").read_text().splitlines()
                         if line.startswith("model name"))
    except (OSError, StopIteration):
        cpu_model = "CPU"
    try:
        gpu_name = subprocess.run(["nvidia-smi", "--query-gpu=name",
            "--format=csv,noheader"], capture_output=True, text=True,
            timeout=1, check=True).stdout.splitlines()[0].strip()
    except (OSError, IndexError, subprocess.SubprocessError):
        gpu_name = "GPU"
    while not stop.is_set():
        cpu = psutil.cpu_percent(None)
        system_ram = psutil.virtual_memory()
        resident = parent.memory_info().rss
        for child in parent.children(recursive=True):
            try:
                resident += child.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        resident_mib = resident / 1024**2
        gpu = gpu_usage()
        with lock:
            shared["hardware"] = dict(cpu=cpu, gpu=gpu,
                                      ram_mib=round(resident_mib),
                                      system_ram_used_gib=round(system_ram.used / 1024**3, 1),
                                      system_ram_total_gib=round(system_ram.total / 1024**3, 1),
                                      cpu_model=cpu_model, gpu_name=gpu_name)
        stop.wait(1)


def analyze(project, bundle, video, binary, requests, numeric_requests, stop, shared, lock):
    board = cap = None
    try:
        board = BoardWorker(str(binary), str(project / "configs"))
        hub = BoardHubLive(str(project / "configs"), neural_root=bundle)
        if hub.yolo is None:
            raise RuntimeError(f"YOLO indisponível: {hub.yolo_error}")
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise ValueError(f"Video de analise nao abriu: {video}")
        source_fps = cap.get(cv2.CAP_PROP_FPS)
        while not stop.is_set():
            try:
                second = requests.get(timeout=.2)
            except Empty:
                continue
            frame_id = int(round(second * source_fps)) + 1
            with lock:
                shared["phase"] = f"quadro {second:.1f}s: tabuleiro/YOLO"
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id - 1)
            ok, bgr = cap.read()
            if not ok:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes()
            frame = SimpleNamespace(id=frame_id, width=1920, height=1080,
                                    rgb=rgb, pts_ms=round(second * 1000), epoch=1)
            started = time.perf_counter()
            board_read = board.observe(frame)
            board_ms = (time.perf_counter() - started) * 1000
            observed = hub.observe(frame, board_read)
            vision_ms = (time.perf_counter() - started) * 1000 - board_ms
            snapshot = observed["snapshot"]
            units = snapshot.get("neural_units") or {}
            items = snapshot.get("neural_items") or {}
            bars = []
            for marker in board_read.get("markers") or []:
                rect = marker.get("rect") or {}
                if all(key in rect for key in ("x", "y", "width", "height")):
                    bars.append(dict(box=[rect["x"], rect["y"],
                                          rect["x"] + rect["width"],
                                          rect["y"] + rect["height"]],
                                     class_name=f"hp_{marker.get('color', '?')}"))
            visual = dict(second=round(second, 2), frame_id=frame_id,
                marker_count=len(bars), bars=bars,
                timings_ms={"board_rust": round(board_ms), "vision_hub": round(vision_ms)},
                units=[{key: r.get(key) for key in ("box", "candidate_name", "confidence_uncalibrated")}
                       for r in units.get("records") or []],
                bench=[{key: r.get(key) for key in ("box", "candidate_name", "confidence_uncalibrated")}
                       for r in units.get("bench_records") or []],
                enemies=[{key: r.get(key) for key in ("box", "candidate_name", "confidence_uncalibrated")}
                         for r in units.get("enemy_records") or []],
                detections=[{key: r.get(key) for key in ("box", "class_name", "confidence")}
                            for r in units.get("detections") or []],
                mascots=[{key: r.get(key) for key in ("box", "class_name")}
                         for r in units.get("mascot_candidates") or []],
                items=[{key: r.get(key) for key in ("box", "slot", "candidates")}
                       for r in items.get("records") or []],
                model_active=bool(units.get("active")),
                visual_readiness=snapshot.get("visual_readiness"))
            with lock:
                shared["visual_history"].append(visual)
                shared["visual_at"] = time.monotonic()
                shared["visual_count"] += 1
                shared["phase"] = "visao atualizada"
            latest(numeric_requests, (visual, rgb, snapshot.get("temporal_candidates")))
    except Exception as exc:
        with lock:
            shared["error"] = f"{type(exc).__name__}: {exc}"
        stop.set()
    finally:
        if cap:
            cap.release()
        if board:
            board.close()


def calculate(project, binary, requests, stop, shared, lock, log):
    worker = None
    try:
        # Match the app runtime: keep Tesseract resident when available.
        worker_env = {**os.environ}
        worker_env.setdefault("AGENTE_TFT_RESIDENT_OCR", "auto")
        worker = NativeWorker(str(binary), str(project / "configs"), env=worker_env)
        with lock:
            shared["ocr_backend"] = worker.ready.get("numeric_hud_ocr_backend")
        decisions = ReplayDecisionEngine(str(project / "configs"))
        with log.open("w", encoding="utf-8") as stream:
            while not stop.is_set():
                try:
                    visual, rgb, candidates = requests.get(timeout=.2)
                except Empty:
                    continue
                second, frame_id = visual["second"], visual["frame_id"]
                started = time.perf_counter()
                answer = worker.request(dict(op="frame", id=frame_id,
                    source_ms=round(second * 1000), width=1920, height=1080,
                    bytes=len(rgb), include_shop=True), rgb, timeout=20)
                native_ms = (time.perf_counter() - started) * 1000
                evaluated = decisions.evaluate(answer, visual_candidates=candidates)
                decision_ms = (time.perf_counter() - started) * 1000 - native_ms
                row = dict(visual,
                    timings_ms=dict(visual["timings_ms"], hud_rust_ocr=round(native_ms),
                                    decision=round(decision_ms)),
                    hud=[{key: r.get(key) for key in ("field", "value", "confidence", "status")}
                         for r in evaluated.get("hud") or []],
                    shop=[{key: r.get(key) for key in ("slot", "observed_name", "name_confidence",
                                                      "observed_cost", "catalog_status")}
                          for r in (evaluated.get("shop") or {}).get("slots") or []],
                    decision=evaluated.get("decision"),
                    decision_capabilities=evaluated.get("decision_capabilities"),
                    native_spans=[{key: s.get(key) for key in ("stage", "duration_ms", "cache_exact_hit")}
                                  for s in answer.get("spans") or []])
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                with lock:
                    shared["analysis_history"].append(row)
                    shared["analysis_at"] = time.monotonic()
                    shared["analysis_count"] += 1
    except Exception as exc:
        with lock:
            shared["error"] = f"{type(exc).__name__}: {exc}"
        stop.set()
    finally:
        if worker:
            worker.close()


def paint(frame, second, fps, vision_hz, analysis_hz, visual, analysis, hardware, error, phase):
    canvas = frame.copy() if frame.shape[:2] == (HEIGHT, WIDTH) else cv2.resize(
        frame, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    age = second - visual["second"] if visual else None
    if visual and 0 <= age <= 1.5:
        groups = (("bars", (45, 185, 45)),
                  ("detections", (200, 160, 45)),
                  ("units", (55, 200, 70)),
                  ("bench", (60, 180, 210)),
                  ("enemies", (60, 70, 205)),
                  ("mascots", (180, 120, 190)),
                  ("items", (195, 150, 55)))
        hud_targets = {"shop_offer", "player_avatar", "stage_display",
                       "gold_display", "level_display"}
        for kind, color in groups:
            for row in visual.get(kind) or []:
                category = row.get("class_name") or ""
                if kind == "detections" and category not in hud_targets:
                    continue
                box = row.get("box")
                if not box or len(box) != 4:
                    continue
                x0, y0, x1, y1 = [max(0, min(WIDTH if i % 2 == 0 else HEIGHT,
                    int(value * (WIDTH / 1920 if i % 2 == 0 else HEIGHT / 1080))))
                    for i, value in enumerate(box)]
                if x1 <= x0 or y1 <= y0:
                    continue
                if kind == "bars":
                    bar_color = (45, 185, 45) if category == "hp_green" else (55, 55, 200)
                    cv2.rectangle(canvas, (x0, y0), (x1, y1), bar_color, 3)
                    continue
                cv2.rectangle(canvas, (x0, y0), (x1, y1), color,
                              3 if kind in ("items", "mascots") or category == "shop_offer" else 2)
                if kind == "detections":
                    continue
                confidence = row.get("confidence_uncalibrated")
                label = row.get("candidate_name")
                if kind == "items":
                    candidates = row.get("candidates") or []
                    names = candidates[0].get("names") if candidates else []
                    label = names[0] if names else None
                if label:
                    if isinstance(confidence, (int, float)) and confidence < .2:
                        label = "?"
                    elif isinstance(confidence, (int, float)) and confidence < .45:
                        label += "?"
                    y = max(13, y0 - 4)
                    cv2.putText(canvas, label[:18], (x0 + 1, y), FONT, .52,
                                (0, 0, 0), 2, cv2.LINE_AA)
                    put(canvas, label[:18], x0 + 1, y, color, .52)
    hud = {row["field"]: row.get("value") for row in (analysis or {}).get("hud") or []}
    timings = dict((visual or {}).get("timings_ms") or {})
    timings.update({key: value for key, value in
                    (analysis or {}).get("timings_ms", {}).items()
                    if key in ("hud_rust_ocr", "decision")})
    decision = (analysis or {}).get("decision") or {}
    action = (decision.get("action") or {}).get("type") or "..."
    reason = (decision.get("economy") or {}).get("code") or ",".join(
        row.get("code", "") for row in decision.get("evidence") or [])
    panel = canvas[60:149, 218:758]
    cv2.convertScaleAbs(panel, dst=panel, alpha=.42)
    put(canvas, f"{fps:.0f} FPS   YOLO {timings.get('vision_hub', '...')} ms   HUD+loja {timings.get('hud_rust_ocr', '...')} ms",
        230, 87, (195, 245, 195), .52)
    put(canvas, f"{hud.get('stage') or '?'}   {hud.get('gold') if hud.get('gold') is not None else '?'} ouro"
        f"   nivel {hud.get('level') if hud.get('level') is not None else '?'}",
        230, 114, (195, 245, 195), .52)
    put(canvas, f"{action}  {reason[:32] if reason else ''}", 230, 141,
        (195, 245, 195), .52)
    if hardware:
        machine = canvas[60:124, 1044:1446]
        cv2.convertScaleAbs(machine, dst=machine, alpha=.42)
        cpu_words = hardware.get("cpu_model", "CPU").split()
        cpu_name = next((word for word in cpu_words
                         if word.startswith(("i3-", "i5-", "i7-", "i9-"))),
                        " ".join(cpu_words[:3]))
        gpu_name = hardware.get("gpu_name", "GPU").replace("NVIDIA GeForce ", "")
        put(canvas, f"CPU {cpu_name} {hardware['cpu']:.0f}%  RAM "
            f"{hardware['system_ram_used_gib']}/{hardware['system_ram_total_gib']} GiB",
            1054, 86, (195, 245, 195), .43)
        gpu = hardware.get("gpu")
        if gpu:
            put(canvas, f"GPU {gpu_name[:16]} {gpu[0]}%  VRAM {gpu[1]}/{gpu[2]} MiB",
                1054, 110, (195, 245, 195), .43)
    if error:
        put(canvas, "ERRO: " + error[:40], 230, 169, (80, 80, 255), .52)
    return canvas


def run(args):
    project, bundle, video = (Path(value).resolve() for value in
                              (args.project, args.bundle, args.video))
    binary = (args.binary or project / "tools/e1-native/target/release/agente-tft-e1-worker").resolve()
    preview = Path(args.preview).resolve() if args.preview else video
    if not video.is_file() or not (bundle / "configs/catalog/active-yolo-hud-v1.json").is_file():
        raise ValueError("Video ou pacote YOLO ausente")
    if not preview.is_file():
        raise ValueError(f"Previa ausente: {preview}")
    if not binary.is_file():
        raise ValueError(f"Motor Rust ausente: {binary}")
    args.output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(preview))
    if not cap.isOpened():
        raise ValueError(f"Video nao abriu: {video}")
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if not 1 <= source_fps <= 120:
        raise ValueError("FPS de origem invalido")
    duration = min(args.seconds, total / source_fps)
    writer = None if args.no_record else cv2.VideoWriter(
        str(args.output / "diagnostico.mp4"),
        cv2.VideoWriter_fourcc(*"mp4v"), 22, (WIDTH, HEIGHT))
    if writer is not None and not writer.isOpened():
        raise RuntimeError("Gravador MP4 indisponivel")
    requests = Queue(maxsize=1)
    numeric_requests = Queue(maxsize=1)
    stop = Event()
    lock = Lock()
    shared = {"analysis_history": deque(maxlen=32), "visual_history": deque(maxlen=32),
              "analysis_at": None, "analysis_count": 0, "visual_at": None, "visual_count": 0,
              "hardware": None, "ocr_backend": None, "error": None,
              "phase": "iniciando leitores"}
    analyzer = Thread(target=analyze, args=(project, bundle, video, binary, requests, numeric_requests,
        stop, shared, lock), daemon=True, name="tft-replay-vision")
    calculator = Thread(target=calculate, args=(project, binary, numeric_requests, stop, shared, lock,
        args.output / "calculos.jsonl"), daemon=True, name="tft-replay-calculation")
    hardware_monitor = Thread(target=monitor, args=(stop, shared, lock), daemon=True,
                              name="tft-hardware-monitor")
    analyzer.start()
    calculator.start()
    hardware_monitor.start()
    name = "Agente TFT - diagnostico da partida"
    if args.show:
        cv2.namedWindow(name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(name, WIDTH, HEIGHT)
    for second in (0., 1., 2., 3.):
        ready = False
        latest(requests, second)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not stop.is_set():
            with lock:
                ready = any(row["second"] >= second for row in shared["visual_history"])
            if ready:
                break
            time.sleep(.02)
        if not ready:
            raise RuntimeError(f"Visao nao preparou quadro {second:.0f}s: {shared['error']}")
    started = time.monotonic()
    display_times = deque(maxlen=80)
    visual_times = deque(maxlen=80)
    analysis_times = deque(maxlen=80)
    last_visual_count = 0
    last_count = 0
    last_request = 0.0
    rendered = 0
    try:
        while not stop.is_set():
            elapsed = time.monotonic() - started
            if elapsed >= duration:
                break
            target = int(elapsed * source_fps)
            current = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            while current < target:
                if not cap.grab():
                    stop.set(); break
                current += 1
            if stop.is_set():
                break
            ok, frame = cap.read()
            if not ok:
                break
            second = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if second <= 0:
                second = elapsed
            if elapsed - last_request >= .6:
                latest(requests, min(duration - .1, second + 3.0))
                last_request = elapsed
            now = time.monotonic()
            display_times.append(now)
            with lock:
                analysis = next((row for row in reversed(shared["analysis_history"])
                                 if row["second"] <= second + .05), None)
                visual = next((row for row in reversed(shared["visual_history"])
                               if row["second"] <= second + .05), None)
                hardware = shared["hardware"]
                error = shared["error"]
                phase = shared["phase"]
                count = shared["analysis_count"]
                completed = shared["analysis_at"]
                visual_count = shared["visual_count"]
                visual_completed = shared["visual_at"]
            if visual_count != last_visual_count and visual_completed:
                visual_times.append(visual_completed)
                last_visual_count = visual_count
            if count != last_count and completed:
                analysis_times.append(completed)
                last_count = count
            fps = sum(t >= now - 1 for t in display_times)
            vision_hz = sum(t >= now - 10 for t in visual_times) / 10
            analysis_hz = sum(t >= now - 10 for t in analysis_times) / 10
            image = paint(frame, second, fps, vision_hz, analysis_hz, visual,
                          analysis, hardware, error, phase)
            if writer is not None:
                writer.write(image)
            if args.show:
                cv2.imshow(name, image)
                if cv2.waitKey(1) & 0xff in (ord("q"), 27):
                    break
            rendered += 1
            target_wall = started + rendered / 22
            delay = target_wall - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, .04))
    finally:
        stop.set()
        analyzer.join(timeout=30)
        calculator.join(timeout=30)
        hardware_monitor.join(timeout=2)
        cap.release()
        if writer is not None:
            writer.release()
        if args.show:
            cv2.destroyWindow(name)
        with lock:
            result = dict(video=str(video), preview=str(preview),
                          seconds_played=round(time.monotonic()-started, 2),
                          frames_rendered=rendered,
                          frames_recorded=rendered if writer is not None else 0,
                          visual_reads=shared["visual_count"],
                          analyses=shared["analysis_count"],
                          ocr_backend=shared["ocr_backend"],
                          error=shared["error"],
                          recording=str(args.output / "diagnostico.mp4") if writer is not None else None)
        (args.output / "resumo.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--binary", type=Path, help="Executavel atual do motor Rust")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--preview", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--show", action="store_true")
    p.add_argument("--no-record", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
