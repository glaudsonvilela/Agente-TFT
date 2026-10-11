from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import unittest

from PIL import Image

from hm.arena_registration import ArenaRegistrar, AsyncArenaRegistrar


class ArenaRegistrationTests(unittest.TestCase):
    def test_async_registration_does_not_block_or_repeat_each_frame(self):
        class SlowRegistrar:
            cv2 = object()

            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.calls = 0

            def observe(self, image):
                self.calls += 1
                self.started.set()
                self.release.wait(2)
                return {'status': 'arena_candidate_match', 'profile': 'known'}

        slow = SlowRegistrar()
        async_reader = AsyncArenaRegistrar(slow)
        image = Image.new('RGB', (32, 32))
        self.assertIsNone(async_reader.observe(image, epoch=1, source_ms=0, eligible=False))
        start = time.perf_counter()
        self.assertIsNone(async_reader.observe(image, epoch=1, source_ms=1000, eligible=True))
        self.assertLess(time.perf_counter() - start, .1)
        self.assertTrue(slow.started.wait(1))
        self.assertIsNone(async_reader.observe(image, epoch=1, source_ms=1500, eligible=True))
        self.assertEqual(slow.calls, 1)
        slow.release.set()
        result = None
        for _ in range(100):
            result = async_reader.observe(image, epoch=1, source_ms=2000, eligible=False)
            if result is not None:
                break
            threading.Event().wait(.01)
        self.assertEqual(result['profile'], 'known')
        self.assertIsNone(async_reader.observe(image, epoch=1, source_ms=2500, eligible=False))

    def test_known_arena_survives_zoom_without_assigning_owner(self):
        root = Path(__file__).resolve().parents[3]
        profiles = [json.loads((root / 'configs/ui' / name).read_text()) for name in (
            'cyber-arena-reserves-v1.json', 'red-arena-reserves-v1.json',
            'pond-arena-reserves-v1.json')]
        registrar = ArenaRegistrar(root, profiles)
        if registrar.cv2 is None:
            self.skipTest('OpenCV not installed in this runtime')
        self.assertEqual(len(registrar.references), 3)
        with Image.open(root / 'configs/ui/arena-references/pond-960.jpg') as source:
            zoomed = source.convert('RGB').crop((100, 50, 850, 470)).resize((1920, 1080))
        result = registrar.observe(zoomed)
        self.assertIsNotNone(result)
        self.assertEqual(result['profile'], 'pond-arena-reserves-v1')
        self.assertEqual(result['status'], 'arena_candidate_match')
        self.assertFalse(result['owner_verified'])
        self.assertFalse(result['training_label'])
        self.assertFalse(result['enemy_board_visible'])
        self.assertGreater(result['inlier_count'], 18)


if __name__ == '__main__':
    unittest.main()
