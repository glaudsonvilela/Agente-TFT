import unittest

from hm.combat_events import CombatEvents, combat_observation_tip


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

    def test_damage_panel_can_occlude_hp_during_one_fight(self):
        tracker = CombatEvents()
        self.assertIsNone(tracker.update(answer('3-5', 67), epoch=1, source_ms=1000))
        self.assertIsNone(tracker.update(answer('3-5', 67), epoch=1, source_ms=2000))
        self.assertIsNone(tracker.update(answer('3-5', 55), epoch=1, source_ms=20000))
        observed = tracker.update(answer('3-5', 55), epoch=1, source_ms=24000)
        self.assertEqual(observed['damage'], 12)
        self.assertEqual(observed['stage'], '3-5')
        self.assertEqual(observed['cause_status'], 'unresolved')
        self.assertNotIn('text', observed)

    def test_hp_gap_across_multiple_rounds_resets(self):
        tracker = CombatEvents()
        tracker.update(answer('3-5', 67), epoch=1, source_ms=1000)
        tracker.update(answer('3-5', 67), epoch=1, source_ms=2000)
        self.assertIsNone(tracker.update(answer('3-7', 45), epoch=1, source_ms=60000))
        self.assertIsNone(tracker.update(answer('3-7', 45), epoch=1, source_ms=61000))

    def test_hp_drop_is_displayed_without_a_fabricated_combat_cause(self):
        outcome=dict(hp_before=86,hp_after=79,damage=7,basis=['player.hp.temporal_drop'])
        facts=dict(origin='rust_combat_facts_v1',hp_before=86,hp_after=79,damage=7,
                   cause_status='unresolved',causal_explanation=None)
        tip=combat_observation_tip(outcome,facts)
        self.assertEqual(tip['text'],'Vida: 86 → 79 (-7). Causa não identificada.')
        self.assertFalse(tip['speakable'])
        self.assertNotIn('speech_text',tip)
        with self.assertRaises(ValueError):
            combat_observation_tip(outcome,dict(facts,causal_explanation='carry exposto'))


if __name__ == '__main__':
    unittest.main()
