from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from hm.yolo_hud import YoloHudObserver, _resolve_unit_sides


class YoloHudTests(unittest.TestCase):
    def test_combat_overlap_uses_bar_side_and_preserves_unresolved_body(self):
        detections = [
            {'class_name': 'board_unit', 'box': [100, 100, 220, 250]},
            {'class_name': 'enemy_unit', 'box': [105, 95, 215, 245]},
            {'class_name': 'board_unit', 'box': [300, 100, 420, 250]},
            {'class_name': 'enemy_unit', 'box': [305, 95, 415, 245]},
            {'class_name': 'board_unit', 'box': [500, 100, 620, 250]},
        ]
        markers = [
            {'color': 'green', 'rect': {'x': 125, 'y': 91, 'width': 60}},
            {'color': 'red', 'rect': {'x': 325, 'y': 90, 'width': 60}},
        ]
        resolved = _resolve_unit_sides(detections, markers)
        self.assertEqual([row['class_name'] for row in resolved],
                         ['board_unit', 'unit_unassigned', 'unit_unassigned',
                          'enemy_unit', 'board_unit'])

    def test_combat_without_allied_bar_does_not_claim_mascot_as_champion(self):
        detections = [{'class_name': 'board_unit', 'box': [700, 500, 840, 650]},
                      {'class_name': 'enemy_unit', 'box': [1100, 200, 1220, 350]}]
        markers = [{'color': 'green', 'rect': {'x': 366, 'y': 307, 'width': 16}},
                   {'color': 'red', 'rect': {'x': 1130, 'y': 198, 'width': 58}}]
        resolved = _resolve_unit_sides(detections, markers)
        self.assertEqual(resolved[0]['class_name'], 'unit_unassigned')
        self.assertEqual(resolved[1]['class_name'], 'enemy_unit')

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
        observer.rust_decoder = None
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

    def test_lower_reserve_health_bar_survives_missing_yolo_box(self):
        observer = object.__new__(YoloHudObserver)
        observer._detect = lambda *_args, **_kwargs: []
        observer._classify = lambda *_args: [(0, .82)]
        observer.champions = object()
        observer.items = object()
        observer.champion_names = ['Akali']
        observer.champion_ids = {'Akali': 'TFT_Akali'}
        observer.sha = 'test'
        marker = {'id': 3, 'color': 'green',
                  'rect': {'x': 600, 'y': 714, 'width': 64, 'height': 5}}
        with patch('hm.yolo_hud._enemy_health_bars_visible', return_value=False), \
             patch('hm.mascot_bars.observe', return_value=[]):
            units, _items = observer.observe(Image.new('RGB', (1920, 1080)),
                {'markers': [marker]}, {'slots': []},
                {'icon_inner_offset': {'x': 0, 'y': 0},
                 'icon_inner_size': {'width': 1, 'height': 1}})
        self.assertEqual(units['records'][0]['zone'], 'bench_unit')
        self.assertEqual(len(units['bench_records']), 1)
        self.assertEqual(units['bench_records'][0]['localization_source'],
                         'lower_reserve_health_bar')

    def test_unlocalized_green_pixel_does_not_become_a_champion(self):
        observer = object.__new__(YoloHudObserver)
        observer._detect = lambda *_args, **_kwargs: []
        observer._classify = lambda *_args: [(0, .82)]
        observer.champions = object()
        observer.items = object()
        observer.champion_names = ['Akali']
        observer.champion_ids = {'Akali': 'TFT_Akali'}
        observer.sha = 'test'
        marker = {'id': 3, 'color': 'green',
                  'rect': {'x': 366, 'y': 307, 'width': 16, 'height': 4}}
        with patch('hm.yolo_hud._enemy_health_bars_visible', return_value=False), \
             patch('hm.mascot_bars.observe', return_value=[]):
            units, _items = observer.observe(Image.new('RGB', (1920, 1080)),
                {'markers': [marker]}, {'slots': []},
                {'icon_inner_offset': {'x': 0, 'y': 0},
                 'icon_inner_size': {'width': 1, 'height': 1}})
        self.assertEqual(units['records'], [])


if __name__ == '__main__':
    unittest.main()
