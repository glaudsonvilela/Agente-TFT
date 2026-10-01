import unittest
from training import player_hp_candidate_audit as m
from training.tests.test_player_hp_candidate_audit import fixture


class ObservedIncreaseAuditTests(unittest.TestCase):
    def test_agreement_does_not_hide_common_mode_increase(self):
        s, cases = m.build_review(*fixture(((36, 36), (56, 56))))
        self.assertEqual(s['groups']['targeted_dense']['comparison'], {'both_readable_equal': 2})
        self.assertEqual(len(cases), 1)
        self.assertIn('observed_increase_not_proven_error', cases[0]['reasons'])
        self.assertEqual(len(cases[0]['observed_increases']), 2)
        self.assertIsNone(cases[0]['target_hp'])
        self.assertEqual(s['decision']['review_action'], 'keep_baseline_no_operational_gain')

    def test_increase_is_not_monotonic_hp_rule_or_value_correction(self):
        s, cases = m.build_review(*fixture(((12, 12), (25, 25))))
        self.assertEqual(cases[0]['candidate']['hp'], 25)
        self.assertFalse(s['profile_promoted'])
        self.assertNotIn('observed_increase_not_proven_error', s['decision']['reasons'])

    def test_sparse_increase_retains_gap_and_does_not_confirm_frames(self):
        s, cases = m.build_review(*fixture(((36, 36), (None, None), (56, 56)),
                                         'sparse_regression', 'sparse-regression', 50000))
        increases = [c for c in cases if c['observed_increases']]
        self.assertEqual(increases[0]['observed_increases'][0]['gap_ms'], 100000)
        self.assertEqual(s['groups']['sparse_regression']['candidate_confirmed_frames'], 0)


if __name__ == '__main__':
    unittest.main()
