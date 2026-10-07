import json
from pathlib import Path

from hm.trait_constraints import bind_observed_traits, roster_hypotheses


def _catalog():
    root = Path(__file__).resolve().parents[3]
    active = json.loads((root / 'configs/catalog/active-knowledge-release-v1.json').read_text())
    release = root / active['reference']
    names = {row['name'] for row in json.loads((release / 'traits.json').read_text())['traits']}
    units = {row['api_name']: set(row['traits'])
             for row in json.loads((release / 'units.json').read_text())['champions']}
    return names, units


def test_actual_windows_trait_words_reduce_two_unit_roster_without_identity_claim():
    names, units = _catalog()
    words = [dict(text=text, confidence=.9, box=[140, y, 230, y + 12])
             for text, y in [('Defendente', 269), ('Enfeiti¢ador', 321),
                             ('Florescer', 375), ('Solar', 428)]]
    binding = bind_observed_traits({'status': 'raw_ocr', 'words': words}, names)
    assert {row['name'] for row in binding['traits']} == {
        'Defendente', 'Enfeitiçador', 'Florescer', 'Solar'}
    markers = [dict(color='green', rect={'y': 286}),
               dict(color='green', rect={'y': 562})]
    hypotheses = roster_hypotheses(binding, markers, units)
    assert hypotheses['rosters'] == [
        ['DA_18_Ahri', 'DA_18_Leona'], ['DA_18_Leona', 'DA_Karma18']]
    assert hypotheses['identity_verified'] is False
    assert hypotheses['perspective_verified'] is False


def test_stale_or_unmatched_trait_text_does_not_constrain_roster():
    names, units = _catalog()
    stale = bind_observed_traits({'status': 'cached_ocr', 'age_ms': 5000,
                                  'words': [dict(text='Solar', confidence=.99,
                                                 box=[140, 428, 180, 440])]}, names)
    assert stale['status'] == 'stale'
    assert roster_hypotheses(stale, [dict(color='green', rect={'y': 300})], units)['rosters'] == []
