from __future__ import annotations

from threading import Event
import time

from PIL import Image

from hm.async_unit_observer import AsyncUnitObserver


def test_slow_classifier_does_not_block_or_duplicate_observations():
    started = Event()
    release = Event()

    class SlowModel:
        def observe(self, image, read):
            started.set()
            release.wait(2)
            return {'records': [{'marker_id': read['markers'][0]['id'],
                                 'identity_verified': False}]}

    worker = AsyncUnitObserver(SlowModel())
    image = Image.new('RGB', (16, 16))
    try:
        before = time.perf_counter()
        assert worker.update(image, {'markers': [{'id': 7}]}, frame_id=1, source_ms=100,
                             epoch=1) is None
        assert started.wait(1)
        assert worker.update(image, {'markers': [{'id': 8}]}, frame_id=2, source_ms=200,
                             epoch=1) is None
        assert time.perf_counter() - before < .5
        assert worker.submitted == 1
        assert worker.dropped == 1
        release.set()
        deadline = time.monotonic() + 2
        while worker.pending is not None and not worker.pending.done() and time.monotonic() < deadline:
            time.sleep(.01)
        finished = worker.update(image, {'markers': [{'id': 9}]}, frame_id=3, source_ms=300,
                                 epoch=1)
        assert finished['frame_id'] == 1
        assert finished['source_ms'] == 100
        assert finished['result']['records'][0]['marker_id'] == 7
        assert worker.completed == 1
    finally:
        release.set()
        worker.close()
        image.close()
