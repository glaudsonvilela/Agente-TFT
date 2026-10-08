"""The Ubuntu preview and analysis must share one capture timeline."""
from __future__ import annotations

import io
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hm.dataset import Latest
from hm.linux_capture import LinuxX11CaptureSource


class LinuxCaptureTimingTests(unittest.TestCase):
    def test_preview_and_analysis_keep_the_same_source_timestamp(self):
        source = object.__new__(LinuxX11CaptureSource)
        source.stop = threading.Event()
        source.reader_done = threading.Event()
        source.frame_bytes = 3
        source.ready = {'width': 1, 'height': 1}
        source.target = {'device': 'test-monitor'}
        source.proc = SimpleNamespace(stdout=io.BytesIO(b'abcdef'), poll=lambda: 0)
        source.preview_frames = Latest()
        source.pending = queue.Queue(maxsize=1)
        source.preview_received = 0
        source.source_replaced = 0
        source.last_preview_received_ns = None
        source.log_tail = []
        source.error = None

        with patch('hm.linux_capture.time.perf_counter_ns', side_effect=[1_000_000_000,
                                                                        2_000_000_000]):
            source._read()

        preview = source.preview_frames.get(.01)
        analysis = next(source.frames(threading.Event(), 10))
        self.assertEqual(preview.id, analysis.id)
        self.assertEqual(preview.pts_ms, 1000)
        self.assertEqual(analysis.pts_ms, preview.pts_ms)


if __name__ == '__main__':
    unittest.main()
