from __future__ import annotations

import json
from pathlib import Path
import unittest

from hm.champion_belief import ChampionBelief, TemporalVisualHypotheses


CATALOG = (Path(__file__).resolve().parents[3] /
           'configs/coaching/TFTSet18/18.3B-20260928/catalog.json')


class ChampionBeliefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.belief = ChampionBelief(json.loads(CATALOG.read_text(encoding='utf-8')))

    def test_one_shop_slot_is_normalized_and_opponent_copies_reduce_its_share(self):
        baseline = self.belief.shop_slot(level=6)['probabilities']
        champion = 'DA_18_Alistar'
        seen = [dict(player='rival_1', track_id='hex_B2', champion_id=champion,
                     stars=2, identity_verified=True),
                # The same unit seen on its bench is not another three copies.
                dict(player='rival_1', track_id='hex_B2', champion_id=champion,
                     stars=2, identity_verified=True)]
        after = self.belief.shop_slot(level=6, stage='4-2',
                                      confirmed_holdings=seen)
        self.assertAlmostEqual(sum(baseline.values()), 1.0, places=8)
        self.assertAlmostEqual(sum(after['probabilities'].values()), 1.0, places=8)
        self.assertLess(after['probabilities'][champion], baseline[champion])
        self.assertEqual(after['confirmed_holding_copies'][champion], 3)
        self.assertFalse(after['actual_probability_known'])

    def test_unverified_enemy_guess_cannot_change_pool(self):
        champion = 'DA_18_Alistar'
        guess = [dict(player='rival_1', track_id='B2', champion_id=champion,
                      stars=3, identity_verified=False)]
        self.assertEqual(self.belief.shop_slot(level=6)['probabilities'][champion],
                         self.belief.shop_slot(level=6,
                             confirmed_holdings=guess)['probabilities'][champion])

    def test_current_level_cannot_erase_old_board_champion(self):
        candidate = [dict(unit_id='DA_18_Ahri', score_uncalibrated=.9)]
        result = self.belief.rank(candidate, level=2, stage='4-2')
        self.assertEqual(result['hypotheses'][0]['unit_id'], 'DA_18_Ahri')
        self.assertEqual(result['hypotheses'][0]['shop_slot_if_no_hidden_holdings'], 0.0)
        self.assertFalse(result['identity_verified'])

    def test_confirmed_transfer_outranks_visual_guess(self):
        result = self.belief.rank(
            [dict(unit_id='DA_18_Ahri', score_uncalibrated=.99)],
            level=6, confirmed_identity='DA_18_Alistar')
        self.assertEqual(result['status'], 'carried_confirmed_identity')
        self.assertEqual(result['hypotheses'][0]['unit_id'], 'DA_18_Alistar')

    def test_shop_ocr_is_math_evidence_but_not_a_body_label(self):
        offers = [dict(slot=2, unit_id='DA_18_Alistar',
                       observed_name='Alistar', status='offer_text_readable',
                       catalog_status='unique_name_bound'),
                  dict(slot=3, unit_id='DA_18_Ahri',
                       observed_name='Ahri', status='partially_readable',
                       catalog_status='unique_name_bound')]
        result = self.belief.observed_offers(offers, level=7, stage='3-5')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['unit_id'], 'DA_18_Alistar')
        self.assertGreater(result[0]['chance_next_slot_if_no_hidden_holdings'], 0)
        self.assertFalse(result[0]['body_identity_verified'])

    def test_acquisition_combines_pool_prior_and_independent_likelihood(self):
        shen, alistar = 'DA_18_Shen', 'DA_18_Alistar'
        seen = [dict(player='rival_1', track_id='bench_B1', champion_id=alistar,
                     stars=2, identity_verified=True)]
        prior = self.belief.shop_slot(level=7, confirmed_holdings=seen)['probabilities']
        result = self.belief.acquisition_belief(
            level=7, stage='4-2', confirmed_holdings=seen,
            evidence=[dict(source_group='visual_crop', provenance='held_out_visual_confusion',
                           likelihoods={shen: .1, alistar: .6}),
                      dict(source_group='independent_track', provenance='held_out_transition',
                           likelihoods={shen: .8, alistar: .2})])
        probabilities = {row['unit_id']: row['probability'] for row in result['hypotheses']}
        denominator = sum(prior[unit_id] *
                          {shen: .1, alistar: .6}.get(unit_id, 1.0) *
                          {shen: .8, alistar: .2}.get(unit_id, 1.0)
                          for unit_id in prior)
        self.assertAlmostEqual(probabilities[shen], prior[shen] * .1 * .8 / denominator)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
        self.assertFalse(result['actual_probability_known'])

    def test_no_measured_evidence_does_not_invent_certainty(self):
        result = self.belief.acquisition_belief(level=6, stage='3-2')
        self.assertEqual(result['status'], 'prior_only')
        self.assertEqual(result['hypotheses'], [])
        self.assertFalse(result['identity_verified'])

    def test_same_pixels_cannot_be_multiplied_as_two_independent_sources(self):
        with self.assertRaises(ValueError):
            self.belief.acquisition_belief(level=6, evidence=[
                dict(source_group='same_crop', provenance='color',
                     likelihoods={'DA_18_Shen': .5}),
                dict(source_group='same_crop', provenance='shape',
                     likelihoods={'DA_18_Shen': .7})])

    def test_trait_delta_excludes_incompatible_new_purchase_only_when_transition_verified(self):
        transition = dict(same_player_verified=True, single_unit_added_verified=True,
                          other_units_unchanged_verified=True,
                          equipment_unchanged_verified=True,
                          counts_before={'DA_18_Defender': 1},
                          counts_after={'DA_18_Defender': 2})
        result = self.belief.acquisition_belief(level=7,
                                                trait_transition=transition)
        possibilities = {row['unit_id'] for row in result['hypotheses']}
        self.assertIn('DA_18_Shen', possibilities)
        self.assertNotIn('DA_18_Alistar', possibilities)
        self.assertFalse(result['identity_verified'])
        transition['single_unit_added_verified'] = False
        self.assertEqual(self.belief.acquisition_belief(
            level=7, trait_transition=transition)['status'], 'prior_only')

    def test_temporal_visual_vote_holds_name_through_single_frame_conflict(self):
        history = TemporalVisualHypotheses()
        def vote(name):
            return history.update('track-1', [dict(unit_id=name)])
        self.assertEqual(vote('Shen')['unit_id'], 'Shen')
        self.assertEqual(vote('Shen')['unit_id'], 'Shen')
        self.assertEqual(vote('Alistar')['unit_id'], 'Shen')
        self.assertEqual(vote('Shen')['unit_id'], 'Shen')
        self.assertEqual(vote('Alistar')['unit_id'], 'Shen')
        self.assertEqual(vote('Alistar')['unit_id'], 'Alistar')
        self.assertFalse(vote('Alistar')['identity_verified'])


if __name__ == '__main__':
    unittest.main()
