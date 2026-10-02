import unittest
from types import SimpleNamespace as N
from hm.runtime_session import reader_signature, READER_CACHE_MAX_MS

class DummyRegistry:
    def fixed(self,w,h):
        if (w,h)!=(1920,1080):return []
        return [
          dict(id="hud.gold",box=[10,10,30,30]),
          dict(id="shop.0.name",box=[100,900,180,930]),
          dict(id="control.refresh",box=[200,950,240,990]),
        ]

class HM3RuntimeContracts(unittest.TestCase):
    def frame(self,data,w=1920,h=1080):
        return N(width=w,height=h,rgb=bytes(data))
    def test_reader_cache_window_is_short(self):
        self.assertGreater(READER_CACHE_MAX_MS,0);self.assertLessEqual(READER_CACHE_MAX_MS,1000)
    def test_exact_pixels_equal_signature(self):
        b=bytes(1920*1080*3);r=DummyRegistry()
        self.assertEqual(reader_signature(self.frame(b),r),reader_signature(self.frame(b),r))
    def test_relevant_pixel_change_invalidates_signature(self):
        a=bytearray(1920*1080*3);b=bytearray(a);index=(10*1920+10)*3;b[index]=1;r=DummyRegistry()
        self.assertNotEqual(reader_signature(self.frame(a),r),reader_signature(self.frame(b),r))
    def test_unrelated_pixel_does_not_fake_reader_change(self):
        a=bytearray(1920*1080*3);b=bytearray(a);b[0]=1;r=DummyRegistry()
        self.assertEqual(reader_signature(self.frame(a),r),reader_signature(self.frame(b),r))
    def test_incompatible_resolution_has_no_cache_signature(self):
        self.assertIsNone(reader_signature(N(width=100,height=100,rgb=bytes(30000)),DummyRegistry()))
