import unittest
from types import SimpleNamespace

from hm.runtime_session import HM4RuntimeSession


class RuntimeFreshnessTest(unittest.TestCase):
    def test_saved_replay_uses_acquisition_clock_for_latest_only_lanes(self):
        session = HM4RuntimeSession.__new__(HM4RuntimeSession)
        session.options = SimpleNamespace(replay_review=True, video='match.mp4')
        frame = SimpleNamespace(due_ns=1_000, ready_ns=5_000)
        self.assertEqual(session._freshness_ns(frame), 5_000)

    def test_live_capture_keeps_due_clock(self):
        session = HM4RuntimeSession.__new__(HM4RuntimeSession)
        frame = SimpleNamespace(due_ns=1_000, ready_ns=5_000)
        for video, replay in (('capture://screen', True), ('match.mp4', False)):
            session.options = SimpleNamespace(replay_review=replay, video=video)
            self.assertEqual(session._freshness_ns(frame), 1_000)


if __name__ == '__main__':
    unittest.main()
