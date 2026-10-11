from __future__ import annotations

import unittest
import json
from pathlib import Path
from PIL import Image, ImageDraw

from hm.spatial_map import build_spatial_map
from hm.spatial_calibration import observe_reserves, choose_calibration, standard_geometry


class SpatialMapTests(unittest.TestCase):
    def test_standard_grid_ignores_skin_color_after_screen_layout_check(self):
        root = Path(__file__).resolve().parents[3]
        profile = json.loads((root / 'configs/ui/standard-screen-grid-v1.json').read_text())
        self.assertEqual(standard_geometry(profile, resolution=(1920, 1080))['status'],
                         'screen_layout_unconfirmed')
        calibration = standard_geometry(profile, resolution=(1920, 1080),
                                        screen_layout_confirmed=True)
        cells = [dict(row=r, col=c) for r in range(4) for c in range(7)]
        bench = [dict(slot=i) for i in range(9)]
        result = build_spatial_map(cells, bench, {}, source_ms=100,
                                   projection_status='unresolved',
                                   reserve_calibration=calibration)
        self.assertEqual(result['enemy_geometry_status'], 'standard_screen_geometry')
        self.assertEqual((len(result['own_cells']), len(result['enemy_cells']),
                          len(result['own_bench']), len(result['enemy_bench'])), (28, 28, 9, 9))
        self.assertEqual(result['own_cells'][0]['center'], [560.0, 444])
        self.assertEqual(result['own_bench'][0]['center'], [409, 792])
        self.assertEqual(result['enemy_cells'][0]['center'], [610.0, 210])
        self.assertEqual(result['enemy_cells'][-1]['center'], [1340.0, 411])
        self.assertEqual(result['enemy_bench'][0]['center'], [630, 130])
        self.assertEqual(result['enemy_bench'][-1]['center'], [1350, 130])
        self.assertTrue(all(row['center'] for row in result['enemy_cells']+result['enemy_bench']))
        self.assertTrue(all(row['occupancy'] == 'unknown' for row in result['enemy_cells']))

    def test_static_color_false_match_cannot_change_known_arena(self):
        proposals = [dict(profile='cyber', status='arena_candidate_match'),
                     dict(profile='pond', status='arena_unmatched')]
        unresolved = choose_calibration(proposals, None, 'pond', registration_available=True)
        self.assertEqual(unresolved['status'], 'arena_unmatched')
        self.assertEqual(unresolved['rejected_static_profiles'], ['cyber'])
        confirmed = choose_calibration(proposals,
                                       dict(profile='pond', status='arena_candidate_match'),
                                       'pond', registration_available=True)
        self.assertEqual(confirmed['profile'], 'pond')

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

    def test_upper_bench_detection_remains_an_unverified_slot_candidate(self):
        calibration = dict(status='arena_candidate_match', profile='cyber',
                           enemy_board_visible=True,
                           own_rows=[[610, 1280, y] for y in (478, 545, 612, 679)],
                           enemy_rows=[[610, 1280, y] for y in (210, 277, 344, 411)],
                           lower=[[465 + 113 * i, 800] for i in range(9)],
                           upper=[[630 + 90 * i, 130] for i in range(9)])
        cells = [dict(row=r, col=c) for r in range(4) for c in range(7)]
        bench = [dict(slot=i) for i in range(9)]
        neural = dict(active=True, bench_records=[
            dict(box=[605, 60, 655, 142], candidate_name='Rakan', candidate_id=None,
                 confidence_uncalibrated=.6),
            dict(box=[605, 260, 655, 345], candidate_name='Shen', candidate_id=None,
                 confidence_uncalibrated=.7)])
        spatial = build_spatial_map(cells, bench, {}, source_ms=100,
                                    projection_status='unresolved',
                                    reserve_calibration=calibration, neural_units=neural)
        first = spatial['enemy_bench'][0]
        self.assertEqual(first['visual_candidate']['candidate_name'], 'Rakan')
        self.assertFalse(first['visual_candidate']['identity_verified'])
        self.assertEqual(first['occupancy'], 'unknown')
        self.assertTrue(all('visual_candidate' not in row for row in spatial['enemy_bench'][1:]))


if __name__ == '__main__':
    unittest.main()
