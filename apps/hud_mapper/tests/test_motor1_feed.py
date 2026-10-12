import base64
import json
import unittest
import zlib

from hm.motor1_feed import Motor1Feed
from hm.replay_decision import ReplayDecisionEngine


class Motor1FeedTests(unittest.TestCase):
    def test_complete_snapshot_crosses_into_rust_request_without_promoting_candidate(self):
        snapshot = {
            'spatial_map': {'own_cells': [{'id': 'A1', 'occupancy': 'unknown'}],
                            'enemy_bench': [{'id': 'R1', 'visual_candidate': {
                                'candidate_id': 'TFT_Zyra', 'identity_verified': False}}]},
            'item_evidence': {'equipped': [{'candidate_name': 'Warmog',
                                            'identity_verified': False}]},
            'shop_probability': {'actual_probability_known': False,
                                 'probabilities': {'3': 0.25}},
            'opponents': {'players': [{'name': 'rival', 'hp': 63}]},
        }
        feed = Motor1Feed()
        self.assertTrue(feed.publish(snapshot, source_ms=1000, epoch=2))

        class Motor:
            ready = {'rank_advice': True}
            def request(self, request, timeout):
                self.request_seen = request
                return {'origin': 'rust_live_opportunity_v1',
                        'selected_index': None, 'ranked': [],
                        'motor1_ingest': {'reader_received': True, 'hub_received': True}}

        motor = Motor()
        answer = {'id': 11, 'source_ms': 1200, 'hud': [],
                  'decision_options': [], 'shop': {'slots': []}}
        ReplayDecisionEngine.rank_with_native(answer, motor,
            match_id='0' * 32, epoch=2,
            motor1_hub=feed.read(now_ms=1200, epoch=2))
        packed = motor.request_seen['motor1']
        restored = json.loads(zlib.decompress(base64.b64decode(packed['hub']['data'])))
        self.assertEqual(restored, snapshot)
        self.assertFalse(restored['spatial_map']['enemy_bench'][0]
                         ['visual_candidate']['identity_verified'])
        self.assertTrue(answer['motor1_ingest']['hub_received'])

    def test_does_not_reuse_a_future_old_or_other_epoch_hub(self):
        feed = Motor1Feed()
        feed.publish({'marker': 1}, source_ms=1000, epoch=3)
        self.assertIsNone(feed.read(now_ms=999, epoch=3))
        self.assertIsNone(feed.read(now_ms=4501, epoch=3))
        self.assertIsNone(feed.read(now_ms=1001, epoch=4))

    def test_gold_xp_and_streak_keep_their_evidence_levels(self):
        hud = lambda field, value, text: dict(field=field, value=value, text=text,
            status='single_frame_observation', confidence=.98)
        observed = ReplayDecisionEngine._memory_observation(
            {'hud': [hud('gold', 42, '42'), hud('xp', 8, '8/60')],
             'shop': {'slots': []},
             'streak': {'status': 'icon_color_candidate', 'kind': 'loss',
                        'count': None, 'verified': False, 'source_ms': 1250}},
            motor1_aux={'fast_markers': {'source_ms': 1200,
                'streak': {'status': 'icon_color_candidate', 'kind': 'win',
                           'count': None, 'verified': False}}})
        self.assertEqual((observed['gold'], observed['xp'], observed['xp_threshold']),
                         (42, 8, 60))
        self.assertEqual(observed['streak']['kind'], 'loss')
        self.assertEqual(observed['streak']['source_ms'], 1250)
        self.assertIsNone(observed['streak']['count'])
        self.assertFalse(observed['streak']['verified'])


if __name__ == '__main__':
    unittest.main()
