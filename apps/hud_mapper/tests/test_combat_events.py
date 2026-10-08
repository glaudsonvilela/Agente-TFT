import unittest

from hm.combat_events import CombatEvents


def answer(stage, hp, *, confidence=.96, fresh=True):
    return {'hud': [{'field': 'stage', 'status': 'single_frame_observation',
                     'confidence': confidence, 'value': stage}],
            'hp': {'status': 'accepted', 'confidence': .96, 'hp': hp},
            'hp_delivery': {'fresh': fresh}}


class CombatEventsTest(unittest.TestCase):
    def test_animated_hp_drop_announces_once_after_stabilizing(self):
        tracker = CombatEvents()
        results = [tracker.update(answer('2-6', hp), epoch=1, source_ms=ms)
                   for ms, hp in [(0, 90), (1000, 90), (2000, 88),
                                  (3000, 86), (4000, 86), (5000, 86),
                                  (6000, 86)]]
        self.assertEqual([row['damage'] for row in results if row], [4])

    def test_seek_or_stage_jump_does_not_announce(self):
        tracker = CombatEvents()
        rows = [(0, '2-6', 90), (1000, '2-6', 90), (2000, '4-2', 40),
                (3000, '4-2', 40), (4000, '3-1', 30), (5000, '3-1', 30)]
        self.assertFalse(any(tracker.update(answer(stage, hp), epoch=1, source_ms=ms)
                             for ms, stage, hp in rows))

    def test_stale_hp_or_low_stage_confidence_cannot_announce(self):
        tracker = CombatEvents()
        tracker.update(answer('2-6', 90), epoch=1, source_ms=0)
        tracker.update(answer('2-6', 90), epoch=1, source_ms=1000)
        self.assertIsNone(tracker.update(answer('2-6', 80, fresh=False), epoch=1,
                                         source_ms=2000))
        self.assertIsNone(tracker.update(answer('2-6', 80, confidence=.4), epoch=1,
                                         source_ms=3000))
        self.assertIsNone(tracker.update(answer('2-6', 80), epoch=2, source_ms=4000))


if __name__ == '__main__':
    unittest.main()
