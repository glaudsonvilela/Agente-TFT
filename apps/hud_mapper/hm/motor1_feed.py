"""Lossless, latest-only Motor 1 -> Motor 2 evidence transport.

The HUB publishes its complete structured snapshot once. Compression runs on
the HUB lane; the HUD/decision lane only reads the immutable encoded result.
Every visual hypothesis keeps its original status and provenance.
"""
from __future__ import annotations

import base64
from collections import deque
import hashlib
import json
import threading
import zlib


MAX_SNAPSHOT_BYTES = 1_000_000
MAX_ENCODED_BYTES = 64_000  # Three evidence sources fit the 256 KiB request budget.


def encode_snapshot(snapshot):
    raw = json.dumps(snapshot, ensure_ascii=False, allow_nan=False,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError('Motor 1 snapshot exceeds transport budget')
    encoded = base64.b64encode(zlib.compress(raw, level=1)).decode('ascii')
    if len(encoded) > MAX_ENCODED_BYTES:
        raise ValueError('Motor 1 compressed snapshot exceeds transport budget')
    return dict(codec='zlib_json_base64_v1', data=encoded,
                raw_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class Motor1Feed:
    """Bounded complete HUB history; readers never block capture."""
    def __init__(self):
        self._lock = threading.Lock()
        self._history = deque(maxlen=24)
        self.last_error = None

    def publish(self, snapshot, *, source_ms, epoch):
        try:
            packed = encode_snapshot(snapshot)
        except (TypeError, ValueError) as exc:
            with self._lock:
                self.last_error = str(exc)
            return False
        with self._lock:
            self._history.append(dict(packed, source_ms=source_ms, epoch=epoch))
            self.last_error = None
        return True

    def read(self, *, now_ms, epoch):
        with self._lock:
            if type(now_ms) not in (int, float):
                return None
            candidates = [row for row in self._history
                          if row['epoch'] == epoch and
                          0 <= now_ms - row['source_ms'] <= 3500]
            latest = max(candidates, key=lambda row: row['source_ms'], default=None)
        return ({**latest, 'age_ms': now_ms - latest['source_ms']}
                if latest is not None else None)
