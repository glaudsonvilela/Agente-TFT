"""Control evidence contracts, separate from recognition accuracy."""
import copy
import json
from pathlib import Path
import unittest

from training.shop_controls_evidence import validate_controls

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / 'configs/ui/match001-shop-controls-v1.json'


def fixture():
    p = json.loads(PROFILE.read_text())
    controls = []
    for spec in p['controls']:
        scores = [dict(state=t['state'], similarity=1.0 if i == 0 else -1.0,
                       rgb_mae=0.0 if i == 0 else 100.0, eligible=i == 0)
                  for i, t in enumerate(spec['templates'])]
        controls.append(dict(id=spec['id'], rect=spec['rect'], status='observed',
                             appearance=spec['templates'][0]['state'], scores=scores, action_allowed=None))
    fields = []
    for spec in p['controls']:
        for key, suffix in [('price_rect', 'price'), ('free_count_rect', 'free_count')]:
            if spec[key] is not None:
                active = suffix == 'price'
                fields.append(dict(id=f"{spec['id']}_{suffix}", rect=spec[key],
                    status='observed' if active else 'not_observed', value=0 if active else None,
                    confidence=0.9 if active else None,
                    attempts=[dict(scale=s, text='0', confidence=0.9, reason='eligible') for s in (3, 4)] if active else []))
    result = dict(profile=p['id'], timestamp_ms=250, controls=controls, numeric_fields=fields,
                  routing=[], ocr_process_calls=2, error=None, temporal_confirmation=False)
    return p, dict(records=[dict(read=dict(timestamp_ms=250, panel_status='located'), controls=result)])


class ControlsTests(unittest.TestCase):
    def test_valid_zero_prices_do_not_authorize_clicks(self):
        p, r = fixture()
        summary = validate_controls(r, p)
        self.assertEqual(summary['numeric_readable']['buy_xp_price'], 1)
        self.assertFalse(summary['action_authorization_provided'])
        self.assertFalse(summary['closed_lock_reference_available'])

    def test_visual_permission_is_rejected(self):
        p, r = fixture()
        r['records'][0]['controls']['controls'][0]['action_allowed'] = True
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_hidden_panel_does_not_inherit_controls(self):
        p, r = fixture()
        r['records'][0]['read']['panel_status'] = 'unresolved'
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_eligible_state_cannot_be_invented(self):
        p, r = fixture()
        r['records'][0]['controls']['controls'][0]['appearance'] = 'locked_appearance'
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_conflict_cannot_pick_a_favorite(self):
        p, r = fixture()
        score = r['records'][0]['controls']['controls'][1]['scores'][1]
        score.update(similarity=1.0, rgb_mae=0.0, eligible=True)
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_numeric_low_confidence_is_not_consensus(self):
        p, r = fixture()
        r['records'][0]['controls']['numeric_fields'][0]['attempts'][0]['confidence'] = 0.69
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_conflicting_numeric_reads_cannot_be_completed_from_catalog(self):
        p, r = fixture()
        r['records'][0]['controls']['numeric_fields'][0]['attempts'][1]['text'] = '4'
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_free_counter_not_inferred_from_price_zero(self):
        p, r = fixture()
        r['records'][0]['controls']['numeric_fields'][2].update(value=2, status='observed')
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_duplicate_scale_or_false_temporal_support_rejected(self):
        p, original = fixture()
        r = copy.deepcopy(original)
        r['records'][0]['controls']['numeric_fields'][0]['attempts'][1]['scale'] = 3
        with self.assertRaises(ValueError): validate_controls(r, p)
        original['records'][0]['controls']['temporal_confirmation'] = True
        with self.assertRaises(ValueError): validate_controls(original, p)

    def test_nan_boolean_prices_and_wrong_rect_rejected(self):
        p, original = fixture()
        for value in (float('nan'), True):
            r = copy.deepcopy(original)
            r['records'][0]['controls']['numeric_fields'][0]['value'] = value
            with self.assertRaises(ValueError): validate_controls(r, p)
        r = copy.deepcopy(original)
        r['records'][0]['controls']['numeric_fields'][0]['rect'] = {}
        with self.assertRaises(ValueError): validate_controls(r, p)

    def test_numeric_absence_stays_unknown(self):
        p, r = fixture()
        field = r['records'][0]['controls']['numeric_fields'][0]
        field.update(status='unknown', value=None, confidence=None,
                     attempts=[dict(scale=s, text=None, confidence=None, reason='no_text') for s in (3, 4)])
        self.assertNotIn('buy_xp_price', validate_controls(r, p)['numeric_readable'])

    def test_profile_has_no_season_roster_and_seed_roles_are_explicit(self):
        p, _ = fixture()
        self.assertNotIn('champions', p)
        self.assertNotIn('tft_patch', p)
        self.assertTrue(all(t['source']['role'] == 'visual_seed_not_ground_truth'
                            for s in p['controls'] for t in s['templates']))
