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
        'policy': 'async_shop_source_bound_v1'}
    assert 'cadence_delivery' not in original
    assert async_shop_delivery(SimpleNamespace(epoch=2, pts_ms=1800, id=19), latest) == {}
    assert async_shop_delivery(SimpleNamespace(epoch=1, pts_ms=4600, id=46), latest) == {}
