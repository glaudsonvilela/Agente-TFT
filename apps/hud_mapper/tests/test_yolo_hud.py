from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from hm.yolo_hud import YoloHudObserver


class YoloHudTests(unittest.TestCase):
    def test_busy_hud_does_not_hide_bench_candidate(self):
        output = np.zeros((1, 12, 201), dtype=np.float32)
        output[0, :4, :] = np.array([400, 300, 50, 50])[:, None]
        output[0, 6, :200] = .9  # Many player-entry anchors.
        output[0, :4, 200] = [230, 390, 45, 50]
        output[0, 5, 200] = .16  # Bench below the HUD score range.

        class Session:
            def run(self, *_args):
                return [output]

        observer = object.__new__(YoloHudObserver)
        observer.detector = Session()
        observer.detector_names = ['board_unit', 'bench_unit', 'player_entry',
                                   'player_avatar', 'stage_display', 'gold_display',
                                   'level_display', 'shop_offer']
        rows = observer._detect(Image.new('RGB', (1920, 1080)))
        self.assertTrue(any(row['class_name'] == 'bench_unit' for row in rows))

    def test_detected_bench_is_classified_without_a_health_bar_marker(self):
        observer = object.__new__(YoloHudObserver)
        observer._detect = lambda *_args, **_kwargs: [
            {'class_name': 'bench_unit', 'box': [600, 700, 730, 850], 'confidence': .18}]
        observer._classify = lambda *_args: [(0, .82)]
        observer.champions = object()
        observer.items = object()
        observer.champion_names = ['Akali']
        observer.champion_ids = {'Akali': 'TFT_Akali'}
        observer.sha = 'test'
        with patch('hm.yolo_hud._enemy_health_bars_visible', return_value=False), \
             patch('hm.mascot_bars.observe', return_value=[]):
            units, _items = observer.observe(Image.new('RGB', (1920, 1080)),
                {'markers': []}, {'slots': []},
                {'icon_inner_offset': {'x': 0, 'y': 0},
                 'icon_inner_size': {'width': 1, 'height': 1}})
        self.assertEqual(units['records'], [])
        self.assertEqual(units['bench_records'][0]['candidate_name'], 'Akali')
        self.assertEqual(units['bench_records'][0]['side'], 'visible_board_unverified')


if __name__ == '__main__':
    unittest.main()
