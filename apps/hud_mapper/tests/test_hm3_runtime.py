import unittest
from types import SimpleNamespace as N
from hm.runtime_session import reader_signature, reusable, READER_CACHE_MAX_MS, RuntimeSession


class HM3RuntimeContracts(unittest.TestCase):
    def frame(self, data, w=1920, h=1080, epoch=0, ns=0):
        return N(width=w, height=h, rgb=data, epoch=epoch, due_ns=ns)

    def test_reader_cache_window_is_short(self):
        self.assertGreater(READER_CACHE_MAX_MS, 0)
        self.assertLessEqual(READER_CACHE_MAX_MS, 1000)

    def test_signature_reuses_immutable_buffer(self):
        pixels = bytes(1920*1080*3)
        self.assertIs(reader_signature(self.frame(pixels)), pixels)

    def test_no_fuzzy_or_partial_pixel_comparison(self):
        pixels = bytes(1920*1080*3)
        last = dict(signature=pixels, epoch=0, due_ns=0)
        for index in (0, 2, (1000*1920+1900)*3, len(pixels)-1):
            changed = bytearray(pixels)
            changed[index] = 1
            frame = self.frame(bytes(changed), ns=100_000_000)
            self.assertFalse(reusable(last, reader_signature(frame), frame))

    def test_identical_frame_reuse_is_not_renewed_forever(self):
        pixels = bytes(1920*1080*3)
        last = dict(signature=pixels, epoch=1, due_ns=10_000_000)
        frame = self.frame(pixels, epoch=1, ns=500_000_000)
        self.assertTrue(reusable(last, pixels, frame))
        frame.due_ns = 800_000_000
        self.assertFalse(reusable(last, pixels, frame))

    def test_geometry_or_clock_regression_refuses_reuse(self):
        pixels = bytes(1920*1080*3)
        last = dict(signature=pixels, epoch=1, due_ns=10)
        self.assertFalse(reusable(last, pixels, self.frame(pixels, epoch=2, ns=100)))
        self.assertFalse(reusable(last, pixels, self.frame(pixels, epoch=1, ns=5)))

    def test_incompatible_resolution_has_no_signature(self):
        self.assertIsNone(reader_signature(self.frame(bytes(30000), 100, 100)))

    def test_mutable_or_truncated_frame_refused(self):
        for data in (bytearray(1920*1080*3), bytes(20)):
            with self.assertRaises(ValueError):
                reader_signature(self.frame(data))

    def test_runtime_never_accepts_video_source(self):
        for source in ('test.mp4', 'https://example.org/v.mp4', ''):
            with self.assertRaises(ValueError):
                RuntimeSession(N(video=source))


if __name__ == '__main__':
    unittest.main()
