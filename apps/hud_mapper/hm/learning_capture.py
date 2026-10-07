"""Bounded shadow-learning capture for a live HM4/HM4.5 session.

The active runtime never trains. This recorder samples immutable source RGB
frames at a fixed low cadence into an isolated post-session evidence stream.
Writes occur on a dedicated thread; capture/reader queues never wait for JPEG
encoding or disk I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from PIL import Image


@dataclass(frozen=True)
class LearningFrame:
    frame_id: int
    source_ms: float
    width: int
    height: int
    rgb: bytes
    geometry_segment: int


class ShadowLearningRecorder:
    schema_version = 1
    policy = "hm45_post_session_shadow_learning_capture_v1"

    def __init__(
        self,
        session_root: str | Path,
        interval_ms: float = 2000.0,
        max_frames: int = 3600,
        max_bytes: int = 2 * 1024**3,
        jpeg_quality: int = 88,
    ):
        if not 500.0 <= interval_ms <= 10_000.0:
            raise ValueError("learning interval outside bounded range")
        if not 60 <= max_frames <= 10_000:
            raise ValueError("learning frame budget outside bounded range")
        if not 128 * 1024**2 <= max_bytes <= 8 * 1024**3:
            raise ValueError("learning byte budget outside bounded range")
        if not 70 <= jpeg_quality <= 95:
            raise ValueError("learning JPEG quality outside bounded range")

        self.root = Path(session_root) / "shadow-learning"
        self.frames = self.root / "frames"
        self.interval_ms = float(interval_ms)
        self.max_frames = int(max_frames)
        self.max_bytes = int(max_bytes)
        self.jpeg_quality = int(jpeg_quality)

        self.pending: queue.Queue[LearningFrame | None] = queue.Queue(maxsize=8)
        self.rows: list[dict] = []
        self.bytes = 0
        self.submitted = 0
        self.saved = 0
        self.dropped_queue = 0
        self.skipped_interval = 0
        self.skipped_budget = 0
        self.skipped_geometry = 0
        self.normalized_frames = 0
        self.error: str | None = None
        self.closed = False
        self._next_source_ms: float | None = None
        self._lock = threading.Lock()

        self.frames.mkdir(parents=True, exist_ok=False)
        self.thread = threading.Thread(
            target=self._writer,
            daemon=True,
            name="hm45-shadow-learning-writer",
        )
        self.thread.start()

    def submit(self, frame) -> bool:
        if self.closed:
            return False
        source_ms = float(frame.pts_ms)
        if self._next_source_ms is not None and source_ms < self._next_source_ms:
            self.skipped_interval += 1
            return False
        if self.saved >= self.max_frames or self.bytes >= self.max_bytes:
            self.skipped_budget += 1
            return False
        if not isinstance(frame.rgb, bytes) or len(frame.rgb) != frame.width * frame.height * 3:
            raise ValueError("shadow-learning frame RGB payload is invalid")

        item = LearningFrame(
            frame_id=int(frame.id),
            source_ms=source_ms,
            width=int(frame.width),
            height=int(frame.height),
            rgb=frame.rgb,
            geometry_segment=int(getattr(frame, "epoch", 0)),
        )
        self._next_source_ms = source_ms + self.interval_ms
        self.submitted += 1
        try:
            self.pending.put_nowait(item)
            return True
        except queue.Full:
            self.dropped_queue += 1
            return False

    def _writer(self) -> None:
        try:
            while True:
                item = self.pending.get()
                if item is None:
                    break
                if self.saved >= self.max_frames or self.bytes >= self.max_bytes:
                    self.skipped_budget += 1
                    continue
                started = time.perf_counter_ns()
                image = Image.frombytes("RGB", (item.width, item.height), item.rgb)
                source_rgb_sha = hashlib.sha256(item.rgb).hexdigest()
                ratio = item.width / item.height
                aspect_error = abs(ratio - (16 / 9)) / (16 / 9)
                normalized = False
                if (item.width, item.height) != (1920, 1080):
                    if aspect_error > 0.005:
                        self.skipped_geometry += 1
                        continue
                    image = image.resize((1920, 1080), Image.Resampling.LANCZOS)
                    normalized = True
                    self.normalized_frames += 1
                learning_rgb = image.tobytes()
                name = f"frames/{self.saved:06d}.jpg"
                path = self.root / name
                image.save(
                    path,
                    format="JPEG",
                    quality=self.jpeg_quality,
                    subsampling=0,
                    optimize=False,
                )
                size = path.stat().st_size
                if self.bytes + size > self.max_bytes:
                    path.unlink(missing_ok=True)
                    self.skipped_budget += 1
                    continue
                encoded = path.read_bytes()
                row = {
                    "index": self.saved,
                    "frame_id": item.frame_id,
                    "source_ms": item.source_ms,
                    "source_width": item.width,
                    "source_height": item.height,
                    "width": 1920,
                    "height": 1080,
                    "normalized_to_1920x1080": normalized,
                    "geometry_segment": item.geometry_segment,
                    "image": name,
                    "image_sha256": hashlib.sha256(encoded).hexdigest(),
                    "source_rgb_sha256": source_rgb_sha,
                    "learning_rgb_sha256": hashlib.sha256(learning_rgb).hexdigest(),
                    "capture_role": "post_session_learning_evidence",
                    "ground_truth": False,
                    "training_label": None,
                    "model_prediction_used_as_label": False,
                    "saved_ms": (time.perf_counter_ns() - started) / 1e6,
                }
                with self._lock:
                    self.rows.append(row)
                    self.saved += 1
                    self.bytes += size
        except Exception as exc:
            self.error = str(exc)

    def close(self, session_id: str, source: dict, runtime_model_sha256: str | None) -> dict:
        if self.closed:
            raise RuntimeError("shadow-learning recorder already closed")
        self.closed = True
        self.pending.put(None)
        self.thread.join(60)
        if self.thread.is_alive():
            raise RuntimeError("shadow-learning writer did not stop")
        if self.error:
            raise RuntimeError(self.error)

        with self._lock:
            rows = list(self.rows)
        manifest = {
            "schema_version": self.schema_version,
            "policy": self.policy,
            "session_id": session_id,
            "source": source,
            "runtime_model_sha256": runtime_model_sha256,
            "interval_ms": self.interval_ms,
            "jpeg_quality": self.jpeg_quality,
            "frames": rows,
            "counts": {
                "submitted": self.submitted,
                "saved": self.saved,
                "dropped_queue": self.dropped_queue,
                "skipped_interval": self.skipped_interval,
                "skipped_budget": self.skipped_budget,
                "skipped_geometry": self.skipped_geometry,
                "normalized_frames": self.normalized_frames,
            },
            "encoded_bytes": self.bytes,
            "learning_geometry": "canonical_1920x1080_rgb_jpeg_v1",
            "active_model_changed_during_session": False,
            "training_performed_during_session": False,
            "human_review_required": False,
            "runtime_approved": False,
        }
        raw = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        (self.root / "capture-manifest.json").write_text(raw, encoding="utf-8")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        sealed = {
            "schema_version": 1,
            "manifest_sha256": digest,
            "frames": self.saved,
            "encoded_bytes": self.bytes,
            "ready_for_post_session_learning": self.saved >= 2,
            "training_performed": False,
            "active_model_changed_during_session": False,
        }
        (self.root / "SEALED.json").write_text(
            json.dumps(sealed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return sealed
