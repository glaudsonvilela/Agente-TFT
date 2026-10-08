from types import SimpleNamespace

from hm.runtime_session import fast_player_hp


def test_fast_avatar_display_uses_only_recent_same_epoch_player_hp():
    frame = SimpleNamespace(epoch=2, id=22, due_ns=2_000_000_000,
                            pts_ms=2000, width=1920, height=1080)
    latest = dict(epoch=2, frame_id=20, due_ns=1_500_000_000,
                  source_ms=1500, input_transform={'reader_size': [1920, 1080]},
                  response={'hp': {'status': 'accepted', 'hp': 42, 'confidence': .94,
                                   'location': {'candidates': [{'hp_rect': {
                                       'x': 1788, 'y': 191, 'width': 44, 'height': 25}}]}}})
    observed = fast_player_hp(frame, latest)
    assert observed['value'] == 42
    assert observed['box'] == [1788, 191, 1832, 216]
    assert observed['age_ms'] == 500
    assert observed['fresh'] is True
    assert observed['avatar_link_verified'] is False
    assert fast_player_hp(SimpleNamespace(**{**vars(frame), 'epoch': 3}), latest)['value'] is None
    assert fast_player_hp(SimpleNamespace(**{**vars(frame), 'due_ns': 4_000_000_000}),
                          latest)['value'] is None


def test_fast_avatar_display_does_not_promote_uncertain_hp():
    frame = SimpleNamespace(epoch=2, id=22, due_ns=2_000_000_000,
                            pts_ms=2000, width=1920, height=1080)
    latest = dict(epoch=2, frame_id=20, due_ns=1_500_000_000,
                  source_ms=1500, response={'hp': {'status': 'ocr_uncertain', 'hp': 42}})
    assert fast_player_hp(frame, latest)['value'] is None
    previous = dict(epoch=2, source_ms=1000, source_frame_id=10, value=55)
    held = fast_player_hp(frame, latest, previous)
    assert held['status'] == 'last_observed'
    assert held['value'] == 55 and held['fresh'] is False and held['box'] is None
    assert held['age_ms'] == 1000
    assert fast_player_hp(SimpleNamespace(**{**vars(frame), 'pts_ms': 4100}),
                          latest, previous)['value'] is None
