from types import SimpleNamespace

from hm.runtime_session import async_shop_delivery


def test_shop_read_retains_source_age_and_cannot_cross_epochs():
    original = {'panel_status': 'located', 'slots': [{'observed_name': 'Shen'}]}
    latest = {'epoch': 1, 'source_ms': 1000, 'frame_id': 10,
              'answer': {'shop': original}}
    frame = SimpleNamespace(epoch=1, pts_ms=1800, id=18)
    result = async_shop_delivery(frame, latest)
    assert result['shop']['cadence_delivery'] == {
        'fresh': False, 'source_frame_id': 10, 'source_ms': 1000,
        'delivered_frame_id': 18, 'age_ms': 800,
        'policy': 'async_shop_source_bound_v2'}
    assert 'cadence_delivery' not in original
    assert async_shop_delivery(SimpleNamespace(epoch=2, pts_ms=1800, id=19), latest) == {}
    assert async_shop_delivery(SimpleNamespace(epoch=1, pts_ms=4600, id=46), latest) == {}


def test_shop_ocr_is_current_only_if_all_five_text_strips_remain_stable():
    signature = tuple(bytes([index] * 20) for index in range(5))
    latest = {'epoch': 1, 'source_ms': 1000, 'frame_id': 10,
              'signature': signature, 'answer': {'shop': {'slots': [{'observed_name': 'Diana'}]}}}
    frame = SimpleNamespace(epoch=1, pts_ms=1800, id=18)
    same = async_shop_delivery(frame, latest, signature)
    assert same['shop']['cadence_delivery']['fresh'] is True
    assert same['shop']['cadence_delivery']['age_ms'] == 800
    changed = tuple(bytes([255] * 15 + [index] * 5) if index == 2 else part
                    for index, part in enumerate(signature))
    assert async_shop_delivery(frame, latest, changed)['shop']['cadence_delivery']['fresh'] is False
    camera_noise = tuple(bytes([255] * 3 + [index] * 17) if index == 2 else part
                         for index, part in enumerate(signature))
    assert async_shop_delivery(frame, latest, camera_noise)['shop']['cadence_delivery']['fresh'] is True
