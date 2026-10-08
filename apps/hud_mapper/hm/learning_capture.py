"""Bounded shadow-learning capture for a live HM4/HM4.5 session.

The active runtime never trains. This recorder samples immutable source RGB
frames at a low cadence and on visible changes into an isolated evidence stream.
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
    original_source_ms: float
    width: int
    height: int
    rgb: bytes
    geometry_segment: int
    capture_event: str


class EvidenceEventDetector:
    """Cheap, resolution-independent change detector over three small regions.

    These are acquisition hints, never champion or item labels. Sampling raw
    bytes avoids image conversion on the capture thread.
    """

    regions = {
        "shop_change": (558, 1039, 1560, 1074, 32, 4, 0.055),
        "board_change": (410, 215, 1510, 765, 20, 10, 0.24),
        "bench_or_item_change": (340, 765, 1570, 940, 24, 5, 0.18),
    }

    def __init__(self, sample_interval_ms: float = 500.0):
        self.sample_interval_ms = sample_interval_ms
        self.next_sample_ms: float | None = None
        self.epoch: int | None = None
        self.previous: dict[str, bytes] = {}

    def observe(self, frame) -> tuple[str, ...]:
        source_ms = float(frame.pts_ms)
        epoch = int(getattr(frame, "epoch", 0))
        if epoch != self.epoch or (self.next_sample_ms is not None
                                   and source_ms < self.next_sample_ms - self.sample_interval_ms):
            self.epoch = epoch
            self.previous.clear()
            self.next_sample_ms = None
        if self.next_sample_ms is not None and source_ms < self.next_sample_ms:
            return ()
        self.next_sample_ms = source_ms + self.sample_interval_ms
        if not isinstance(frame.rgb, bytes) or len(frame.rgb) != frame.width * frame.height * 3:
            return ()
        pixels = memoryview(frame.rgb)
        changed = []
        for name, (x0, y0, x1, y1, cols, rows, threshold) in self.regions.items():
            sampled = bytearray()
            for row in range(rows):
                y = min(frame.height - 1, int((y0 + (row + .5) * (y1 - y0) / rows)
                                              * frame.height / 1080))
                for col in range(cols):
                    x = min(frame.width - 1, int((x0 + (col + .5) * (x1 - x0) / cols)
                                                  * frame.width / 1920))
                    offset = (y * frame.width + x) * 3
                    sampled.extend((pixels[offset] >> 5, pixels[offset + 1] >> 5,
                                    pixels[offset + 2] >> 5))
            current = bytes(sampled)
            old = self.previous.get(name)
            self.previous[name] = current
            if old is not None:
                changed_pixels = sum(
                    max(abs(current[i + channel] - old[i + channel]) for channel in range(3)) >= 2
                    for i in range(0, len(current), 3)
                )
                if changed_pixels / (cols * rows) >= threshold:
                    changed.append(name)
        return tuple(changed)


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
        self.skipped_duplicate = 0
        self.normalized_frames = 0
        self.error: str | None = None
        self.closed = False
        self._next_source_ms: float | None = None
        self._last_submitted_ms: float | None = None
        self._last_epoch: int | None = None
        self._source_offset_ms = 0.0
        self._last_timeline_ms: float | None = None
        self.event_detector = EvidenceEventDetector()
        self.event_counts: dict[str, int] = {}
        self._last_saved_source: tuple | None = None
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
        epoch = int(getattr(frame, "epoch", 0))
        if self._last_epoch != epoch or (self._last_submitted_ms is not None
                                         and source_ms < self._last_submitted_ms):
            self._next_source_ms = None
            self._last_submitted_ms = None
            self._last_epoch = epoch
            if self._last_timeline_ms is not None:
                self._source_offset_ms = max(
                    self._source_offset_ms,
                    self._last_timeline_ms + 1000.0 - source_ms,
                )
        events = self.event_detector.observe(frame)
        periodic_due = self._next_source_ms is None or source_ms >= self._next_source_ms
        event_due = bool(events) and (self._last_submitted_ms is None
                                      or source_ms - self._last_submitted_ms >= 750)
        if not periodic_due and not event_due:
            self.skipped_interval += 1
            return False
        if self.saved >= self.max_frames or self.bytes >= self.max_bytes:
            self.skipped_budget += 1
            return False
        if not isinstance(frame.rgb, bytes) or len(frame.rgb) != frame.width * frame.height * 3:
            raise ValueError("shadow-learning frame RGB payload is invalid")

        item = LearningFrame(
            frame_id=int(frame.id),
            source_ms=source_ms + self._source_offset_ms,
            original_source_ms=source_ms,
            width=int(frame.width),
            height=int(frame.height),
            rgb=frame.rgb,
            geometry_segment=epoch,
            capture_event=events[0] if event_due else "periodic",
        )
        self.submitted += 1
        try:
            self.pending.put_nowait(item)
            self._last_submitted_ms = source_ms
            self._last_timeline_ms = item.source_ms
            if periodic_due:
                self._next_source_ms = source_ms + self.interval_ms
            self.event_counts[item.capture_event] = self.event_counts.get(item.capture_event, 0) + 1
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
                source_rgb_sha = hashlib.sha256(item.rgb).hexdigest()
                source_identity = (item.geometry_segment, item.width, item.height, source_rgb_sha)
                if source_identity == self._last_saved_source:
                    self.skipped_duplicate += 1
                    continue
                image = Image.frombytes("RGB", (item.width, item.height), item.rgb)
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
                    "original_source_ms": item.original_source_ms,
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
                    "capture_event": item.capture_event,
                    "ground_truth": False,
                    "training_label": None,
                    "model_prediction_used_as_label": False,
                    "saved_ms": (time.perf_counter_ns() - started) / 1e6,
                }
                with self._lock:
                    self.rows.append(row)
                    self.saved += 1
                    self.bytes += size
                    self._last_saved_source = source_identity
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
                "skipped_duplicate": self.skipped_duplicate,
                "normalized_frames": self.normalized_frames,
                "submitted_by_event": self.event_counts,
            },
            "encoded_bytes": self.bytes,
            "learning_geometry": "canonical_1920x1080_rgb_jpeg_v1",
            "active_model_changed_during_session": False,
            "training_performed_during_session": False,
            "human_review_required": False,
            "runtime_approved": False,
        }
        raw = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        manifest_bytes = raw.encode("utf-8")
        # Hash the exact bytes persisted. Text-mode newline translation on
        # Windows previously turned LF into CRLF after the hash was computed,
        # making valid live sessions fail the post-match seal check.
        (self.root / "capture-manifest.json").write_bytes(manifest_bytes)
        digest = hashlib.sha256(manifest_bytes).hexdigest()
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
