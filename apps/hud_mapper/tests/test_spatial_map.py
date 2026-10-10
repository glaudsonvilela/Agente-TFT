from __future__ import annotations

import unittest
import json
from pathlib import Path
from PIL import Image, ImageDraw

from hm.spatial_map import build_spatial_map
from hm.spatial_calibration import observe_reserves


class SpatialMapTests(unittest.TestCase):
    def test_own_enemy_addresses_and_opponent_namespaces_stay_separate(self):
        cells = [dict(row=r, col=c, screen_center=[500 + c * 100, 400 + r * 70],
                      marker_candidates=[]) for r in range(4) for c in range(7)]
        bench = [dict(slot=i, screen_center=[400 + i * 100, 800],
                      marker_candidates=[]) for i in range(9)]
        opponents = dict(current_opponent='Jogador A',
                         current_opponent_status='temporal_candidate',
                         players=[dict(name='Jogador A'), dict(name='Jogador B')])
        result = build_spatial_map(cells, bench, opponents, source_ms=1234,
                                   projection_status='unresolved')
        self.assertEqual((len(result['own_cells']), len(result['enemy_cells']),
                          len(result['own_bench']), len(result['enemy_bench'])), (28, 28, 9, 9))
        self.assertEqual(result['own_cells'][0]['id'], 'A1')
        self.assertEqual(result['own_cells'][-1]['id'], 'D7')
        self.assertEqual(result['own_bench'][-1]['id'], 'R9')
        self.assertEqual([row['owner'] for row in result['roster_spaces']],
                         ['Jogador A', 'Jogador B'])
        self.assertTrue(all(row['board_assigned'] is False for row in result['roster_spaces']))
        self.assertTrue(all(row['center'] is None for row in result['enemy_cells']))
        self.assertTrue(all(row['occupancy'] == 'unknown' for row in result['own_cells']))

    def test_arena_gate_adds_both_grids_without_assigning_a_champion(self):
        root = Path(__file__).resolve().parents[3]
        profile = json.loads((root / 'configs/ui/cyber-arena-reserves-v1.json').read_text())
        image = Image.new('RGB', (1920, 1080), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for anchor in profile['anchors']:
            draw.rectangle(anchor['rect'], fill=tuple(anchor['mean_rgb']))
        match = observe_reserves(image, profile)
        self.assertEqual(match['status'], 'arena_candidate_match')
        rows = [dict(row=r, col=c, screen_center=[0, 0])
                for r in range(4) for c in range(7)]
        slots = [dict(slot=i, screen_center=[0, 0]) for i in range(9)]
        spatial = build_spatial_map(rows, slots, {}, source_ms=100,
                                    projection_status='unresolved',
                                    reserve_calibration=match)
        self.assertEqual(spatial['own_geometry_status'], 'arena_candidate')
        self.assertEqual(spatial['enemy_geometry_status'], 'arena_candidate')
        self.assertEqual(spatial['enemy_bench_geometry_status'], 'arena_candidate')
        self.assertEqual(spatial['enemy_cells'][0]['center'], [610.0, 210])
        self.assertEqual(spatial['enemy_bench'][0]['center'], [630, 130])
        self.assertIsNone(spatial['enemy_owner'])
        self.assertTrue(all(row['champion_id'] is None for row in spatial['enemy_cells']))
        image = Image.new('RGB', (1920, 1080), (0, 0, 0))
        self.assertEqual(observe_reserves(image, profile)['status'], 'arena_unmatched')

    def test_own_only_arena_does_not_project_invisible_enemy_cells(self):
        root = Path(__file__).resolve().parents[3]
        profile = json.loads((root / 'configs/ui/pond-arena-reserves-v1.json').read_text())
        image = Image.new('RGB', (1920, 1080), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for anchor in profile['anchors']:
            draw.rectangle(anchor['rect'], fill=tuple(anchor['mean_rgb']))
        match = observe_reserves(image, profile)
        cells = [dict(row=r, col=c) for r in range(4) for c in range(7)]
        slots = [dict(slot=i) for i in range(9)]
        spatial = build_spatial_map(cells, slots, {}, source_ms=100,
                                    projection_status='unresolved', reserve_calibration=match)
        self.assertEqual(spatial['own_geometry_status'], 'arena_candidate')
        self.assertEqual(spatial['own_cells'][0]['center'], [560.0, 444])
        self.assertEqual(spatial['enemy_geometry_status'], 'not_visible_or_calibrated')
        self.assertTrue(all(row['center'] is None for row in spatial['enemy_cells']))


if __name__ == '__main__':
    unittest.main()
