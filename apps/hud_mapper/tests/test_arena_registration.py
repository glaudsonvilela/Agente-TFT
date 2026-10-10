from __future__ import annotations

import json
from pathlib import Path
import unittest

from PIL import Image

from hm.arena_registration import ArenaRegistrar


class ArenaRegistrationTests(unittest.TestCase):
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
