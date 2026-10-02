"""Compositor anomalies must not masquerade as acquisition latency."""
import unittest
from types import SimpleNamespace as N
from hm.capture_source import frame_clock

class ClockContracts(unittest.TestCase):
    def bridge(self):
        return N(frequency=10_000_000, uncertainty_ns=500, convert=lambda ns:ns+1000)
    def header(self, compositor=99_000_000):
        return dict(qpc_frequency=10_000_000,qpc_acquired_ticks=1_000_000,
                    qpc_sent_ticks=1_010_000,capture_ns=compositor)
    def test_normal_clock_keeps_original_compositor(self):
        h=self.header();due,r=frame_clock(h,self.bridge(),102_001_000)
        self.assertEqual(due,100_001_000)
        self.assertEqual(r['compositor_to_rgb_ready_ms'],3.0)
        self.assertEqual(r['native_acquire_to_rgb_ready_ms'],2.0)
        self.assertEqual(h['capture_ns'],99_000_000)
    def test_future_compositor_is_reported_not_repaired(self):
        h=self.header(120_000_000);due,r=frame_clock(h,self.bridge(),102_001_000)
        self.assertEqual(r['compositor_time_status'],'compositor_after_native_send')
        self.assertIsNone(r['compositor_to_rgb_ready_ms'])
        self.assertLess(r['compositor_to_rgb_ready_raw_ms'],0)
        self.assertEqual(due,100_001_000)
        self.assertFalse(r['original_timestamp_modified'])
    def test_backward_compositor_does_not_retime_native(self):
        due,r=frame_clock(self.header(),self.bridge(),102_001_000,previous_compositor_ns=100_000_000)
        self.assertTrue(r['compositor_timestamp_regressed'])
        self.assertIsNone(r['compositor_to_rgb_ready_ms'])
        self.assertEqual(due,100_001_000)
    def test_native_send_after_receive_still_rejected(self):
        with self.assertRaises(ValueError):frame_clock(self.header(),self.bridge(),90_001_000)
    def test_missing_or_reversed_native_clock_rejected(self):
        for overrides in ({'qpc_acquired_ticks':None},{'qpc_acquired_ticks':2_000_000},{'qpc_frequency':999}):
            with self.assertRaises(ValueError):frame_clock(dict(self.header(),**overrides),self.bridge(),102_001_000)

if __name__=='__main__':unittest.main()
