from __future__ import annotations

import unittest

from hm.live_diagnostics import build_hub_diagnostic, build_live_diagnostic


class LiveDiagnosticTests(unittest.TestCase):
    def test_snapshot_keeps_reader_evidence_and_native_math_distinct(self):
        answer = {
            'origin': 'observed_pixels',
            'hud': [{'field': 'gold', 'value': 51, 'status': 'single_frame_observation',
                     'confidence': .94}],
            'shop': {'slots': [{'slot': 0, 'observed_name': 'Shen',
                                'observed_cost': 2, 'status': 'observed'}]},
            'decision_candidates': [{'action': {'type': 'buy', 'target': 'Shen'}}],
            'decision': {'action': {'type': 'buy'}},
            'decision_rank': {'status': 'selected', 'selected_index': 0,
                              'native_ms': 8.5,
                              'ranked': [{'index': 0, 'action_type': 'buy',
                                          'utility': .72, 'base_utility': .68,
                                          'novelty_penalty': .0}]},
        }
        regions = [
            {'id': 'hud.gold', 'box': [10, 20, 50, 40], 'status': 'single_frame_observation',
             'value': 51, 'confidence': .94},
            {'id': 'shop.0.name', 'box': [40, 80, 100, 100], 'status': 'observed',
             'value': 'Shen'},
            {'id': 'board.marker.1', 'box': [1, 1, 9, 9], 'status': 'bar_candidate'},
            {'id': 'shop.1.name', 'box': [200, 80, 260, 100], 'status': 'unknown'},
        ]
        result = build_live_diagnostic(answer, regions, frame_id=12, source_ms=3200,
                                       epoch=2, width=1920, height=1080,
                                       reader_ms=40.1, source_to_reader_ms=45.7)
        self.assertEqual(result['image_size'], [1920, 1080])
        self.assertEqual([row['id'] for row in result['boxes']],
                         ['hud.gold', 'shop.0.name', 'shop.1.name'])
        self.assertEqual(result['rust']['ranked'][0]['target'], 'Shen')
        self.assertEqual(result['rust']['ranked'][0]['utility'], .72)
        self.assertNotIn('ground_truth', result)

    def test_invalid_region_cannot_be_drawn(self):
        result = build_live_diagnostic({}, [
            {'id': 'hud.gold', 'box': [-1, 0, 10, 10], 'value': 12},
            {'id': 'shop.0.name', 'box': [10, 10, float('nan'), 20], 'value': 'X'},
        ], frame_id=1, source_ms=0, epoch=0, width=100, height=100,
            reader_ms=1, source_to_reader_ms=2)
        self.assertEqual(result['boxes'], [])

    def test_hub_marks_candidates_without_promoting_identity(self):
        position = {'status': 'candidate_only', 'zone': 'board',
                    'row': 1, 'cell_or_slot': 2}
        snapshot = {'observed_markers': [{'marker_id': 7, 'position_candidate': position}],
                    'temporal_candidates': {'units': [
            {'marker_id': 7, 'position': ['board', 1, 2], 'candidate_name': 'Rakan',
             'status': 'persistent_candidate',
             'support_frames': 3, 'identity_verified': False}]}}
        regions = [
            {'id': 'hub.marker.7', 'box': [100, 200, 160, 205],
             'value': position, 'marker_id': 7, 'status': 'position_candidate'},
            {'id': 'hub.inventory.0', 'box': [0, 20, 30, 50],
             'value': 'Lágrima da Deusa', 'status': 'icon_candidate'},
        ]
        result = build_hub_diagnostic(snapshot, regions, frame_id=22,
                                      source_ms=5400, epoch=1, width=1920,
                                      height=1080, processing_ms=18.4)
        self.assertEqual(result['candidate_units'], 1)
        self.assertEqual(result['verified_units'], 0)
        self.assertEqual(result['boxes'][0]['label'], 'Rakan')
        self.assertEqual(result['boxes'][0]['observed_box'], [100, 200, 160, 205])
        self.assertEqual(result['boxes'][0]['geometry'], 'bar_anchored_approximation')
        self.assertEqual(result['boxes'][1]['label'], 'Lágrima da Deusa')

    def test_hub_name_follows_board_cell_when_marker_ids_change(self):
        first = {'status': 'candidate_only', 'zone': 'board', 'row': 0, 'cell_or_slot': 2}
        second = {'status': 'candidate_only', 'zone': 'board', 'row': 0, 'cell_or_slot': 3}
        snapshot = {'observed_markers': [
            {'marker_id': 7, 'position_candidate': second},
            {'marker_id': 8, 'position_candidate': first}],
            'temporal_candidates': {'units': [
                {'marker_id': 7, 'position': ['board', 0, 2], 'candidate_name': 'Rakan',
                 'status': 'persistent_candidate', 'support_frames': 2,
                 'identity_verified': False}]}}
        regions = [
            {'id': 'hub.marker.7', 'box': [100, 200, 160, 205],
             'value': second, 'marker_id': 7, 'status': 'position_candidate'},
            {'id': 'hub.marker.8', 'box': [200, 200, 260, 205],
             'value': first, 'marker_id': 8, 'status': 'position_candidate'}]
        result = build_hub_diagnostic(snapshot, regions, frame_id=22,
            source_ms=5400, epoch=1, width=1920, height=1080, processing_ms=18.4)
        self.assertEqual(result['boxes'][0]['label'], 'unidade não identificada')
        self.assertEqual(result['boxes'][1]['label'], 'Rakan')

    def test_hub_suppresses_name_when_cell_has_two_markers(self):
        position = {'status': 'candidate_only', 'zone': 'board',
                    'row': 1, 'cell_or_slot': 2, 'marker_id': 7}
        snapshot = {'observed_markers': [
            {'marker_id': 7, 'position_candidate': position},
            {'marker_id': 8, 'position_candidate': position}],
            'temporal_candidates': {'units': [
                {'marker_id': 7, 'position': ['board', 1, 2], 'candidate_name': 'Rakan',
                 'status': 'persistent_candidate', 'support_frames': 3}]}}
        regions = [{'id': f'hub.marker.{marker_id}', 'box': [100, 200, 160, 205],
                    'value': position, 'marker_id': marker_id}
                   for marker_id in (7, 8)]
        result = build_hub_diagnostic(snapshot, regions, frame_id=22,
            source_ms=5400, epoch=1, width=1920, height=1080, processing_ms=18.4)
        self.assertTrue(all(row['label'] == 'unidade não identificada'
                            for row in result['boxes']))

    def test_hub_accepts_recorded_region_contract_with_marker_inside_position(self):
        position = {'status': 'candidate_only', 'zone': 'board',
                    'row': 1, 'cell_or_slot': 2, 'marker_id': 7}
        snapshot = {'observed_markers': [{'marker_id': 7, 'position_candidate': position}],
                    'temporal_candidates': {'units': [
                        {'marker_id': 7, 'position': ['board', 1, 2],
                         'candidate_name': 'Rakan', 'status': 'persistent_candidate',
                         'support_frames': 2}]}}
        result = build_hub_diagnostic(snapshot, [
            {'id': 'hub.marker.7', 'box': [100, 200, 160, 205], 'value': position}],
            frame_id=22, source_ms=5400, epoch=1, width=1920,
            height=1080, processing_ms=18.4)
        self.assertEqual(result['boxes'][0]['label'], 'Rakan')

    def test_async_unit_result_is_source_bound_and_never_verified(self):
        snapshot = {'neural_units': {'pending': True, 'completed': 1},
                    'unit_async_result': {'source_ms': 4000, 'epoch': 2,
                        'result': {'processing_ms': 1250, 'records': [{
                            'marker_id': 3, 'candidate_name': 'Shen',
                            'softmax_score_uncalibrated': .4,
                            'identity_verified': False}]}}}
        current = build_hub_diagnostic(snapshot, [], frame_id=8, source_ms=5000,
            epoch=2, width=1920, height=1080, processing_ms=50)
        stale = build_hub_diagnostic(snapshot, [], frame_id=9, source_ms=5000,
            epoch=3, width=1920, height=1080, processing_ms=50)
        self.assertEqual(current['unit_inference']['candidates'][0]['candidate_name'], 'Shen')
        self.assertFalse(current['unit_inference']['identity_verified'])
        self.assertEqual(stale['unit_inference']['candidates'], [])


if __name__ == '__main__':
    unittest.main()
