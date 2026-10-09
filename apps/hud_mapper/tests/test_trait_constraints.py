import json
from pathlib import Path

from hm.trait_constraints import TraitCountConsensus, bind_observed_traits, roster_hypotheses


def test_trait_count_needs_two_fresh_matching_reads():
    tracker = TraitCountConsensus()
    binding = {'traits': [dict(name='Inferno', method='exact_text', confidence=.96,
                               row_box=[140, 375, 190, 387])]}
    raw = {'status': 'raw_ocr', 'words': [dict(text='3', confidence=.97,
                                             box=[118, 382, 126, 395])]}
    assert tracker.update(raw, binding, epoch=1, source_ms=1000) == {}
    assert tracker.update(raw, binding, epoch=1, source_ms=2000) == {'Inferno': 3}
    assert tracker.update(raw, binding, epoch=2, source_ms=3000) == {}
    assert tracker.update(raw, binding, epoch=2, source_ms=7000) == {}
    assert tracker.update({**raw, 'words': [dict(text='4', confidence=.4,
        box=[118, 382, 126, 395])]}, binding, epoch=2, source_ms=8000) == {}


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


def test_async_trait_refresh_does_not_make_panel_blink_before_next_read():
    names, _ = _catalog()
    cached = bind_observed_traits({'status': 'cached_ocr', 'age_ms': 3000,
                                   'words': [dict(text='Solar', confidence=.99,
                                                  box=[140, 428, 180, 440])]}, names)
    assert cached['traits'][0]['name'] == 'Solar'


def test_low_confidence_full_trait_word_can_bind_without_accepting_noise():
    names, _ = _catalog()
    words = [dict(text='Enfeiticador', confidence=.36, box=[140, 325, 228, 337]),
             dict(text='cosy', confidence=.28, box=[140, 440, 166, 452])]
    binding = bind_observed_traits({'status': 'raw_ocr', 'words': words}, names)
    assert [row['name'] for row in binding['traits']] == ['Enfeitiçador']
    assert binding['traits'][0]['method'] == 'exact_text'


def test_short_word_on_separate_trait_row_blocks_roster_exhaustiveness():
    names, units = _catalog()
    words = [dict(text='Enfeitigador', confidence=.80, box=[140, 268, 221, 285]),
             dict(text='FI', confidence=.81, box=[141, 322, 149, 334])]
    binding = bind_observed_traits({'status': 'raw_ocr', 'words': words}, names)
    assert binding['status'] == 'partial_panel'
    assert binding['detected_text_rows'] == 2
    assert roster_hypotheses(binding, [dict(color='green', rect={'y': 573})], units)['rosters'] == []


def test_english_vod_trait_names_bind_to_same_seasonal_ids():
    root = Path(__file__).resolve().parents[3]
    active = json.loads((root / 'configs/catalog/active-knowledge-release-v1.json').read_text())
    release = root / active['reference']
    pt = {row['api_name']: row['name'] for row in json.loads((release / 'traits.json').read_text())['traits']}
    aliases = json.loads((root / 'configs/catalog/trait-aliases-set18-en-us-16.20.json').read_text())
    assert aliases['target_release_sha256'] == json.loads((release / 'release.json').read_text())['release_sha256']
    names = {name: name for name in pt.values()}
    names.update({row['name']: pt[row['api_name']] for row in aliases['traits']})
    words = [dict(text='Juggernaut', confidence=.66, box=[138, 375, 212, 391]),
             dict(text='Lunar', confidence=.96, box=[140, 428, 178, 440])]
    binding = bind_observed_traits({'status': 'raw_ocr', 'words': words}, names)
    assert {row['name'] for row in binding['traits']} == {'Colosso', 'Lunar'}


def test_later_trait_rows_are_not_silently_ignored():
    names, _ = _catalog()
    binding = bind_observed_traits({'status': 'raw_ocr', 'words': [
        dict(text='Solar', confidence=.95, box=[140, 428, 173, 440]),
        dict(text='FI', confidence=.82, box=[141, 640, 149, 652]),
    ]}, names)
    assert binding['status'] == 'partial_panel'
    assert binding['detected_text_rows'] == 2


def test_many_visible_traits_do_not_create_small_roster_identity():
    names, units = _catalog()
    binding = {'status': 'candidates', 'unmatched': [],
               'traits': [{'name': name} for name in
                          ('Florescer', 'Enfeitiçador', 'Defendente', 'Solar', 'Lunar')]}
    result = roster_hypotheses(binding, [dict(color='green', rect={'y': 350})], units)
    assert result['status'] == 'large_roster_not_exhaustive'
