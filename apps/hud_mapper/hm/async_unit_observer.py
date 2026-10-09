"""Bounded, source-bound unit inference outside the live board reader."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time


class AsyncUnitObserver:
    def __init__(self, observer):
        self.observer = observer
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tft-unit-head')
        self.pending = None
        self.submitted = 0
        self.completed = 0
        self.dropped = 0
        self.last_error = None

    @staticmethod
    def _infer(observer, image, read, frame_id, source_ms, epoch, positions):
        try:
            result = observer.observe(image, read)
            return dict(frame_id=frame_id, source_ms=source_ms, epoch=epoch,
                        positions=positions, result=result,
                        completed_ns=time.perf_counter_ns())
        finally:
            image.close()

    def update(self, image, read, *, frame_id, source_ms, epoch, positions=None):
        """Return one finished batch, then schedule the newest frame if idle.

        A pending inference is never submitted again and never reused as a
        second observation. Its predictions are diagnostic evidence only.
        """
        completed = None
        if self.pending is not None and self.pending.done():
            try:
                completed = self.pending.result()
                self.completed += 1
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
            self.pending = None
        if self.pending is None and self.last_error is None:
            self.pending = self.executor.submit(
                self._infer, self.observer, image.copy(), read, frame_id, source_ms, epoch,
                positions or [])
            self.submitted += 1
        elif self.pending is not None:
            self.dropped += 1
        return completed

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
