import pytest

from training.full_video_imitation_source import window_frames


@pytest.mark.parametrize("count", [1, 60, 120, 121, 180, 251, 1234])
def test_every_source_frame_is_covered(count):
    windows = window_frames(count)
    covered = bytearray(count)
    for start, end in windows:
        assert 0 <= start < end <= count
        covered[start:end] = b"\x01" * (end - start)
    assert all(covered)
    assert windows[0][0] == 0
    assert windows[-1][1] == count


def test_window_index_rejects_gaps():
    with pytest.raises(ValueError):
        window_frames(100, length=10, stride=11)
