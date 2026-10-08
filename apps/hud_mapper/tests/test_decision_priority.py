import types
import unittest

from hm.replay_decision import ReplayDecisionEngine


class DecisionPriorityTests(unittest.TestCase):
    def test_fresh_champion_call_beats_recurring_economy_reminder(self):
        engine = object.__new__(ReplayDecisionEngine)
        shop_call = {'family': 'synergy', 'action': {'type': 'buy_synergy'},
                     'text': 'Compre Sejuani.'}
        engine.live_advice = types.SimpleNamespace(
            propose=lambda *_: shop_call)
        engine._economy = lambda _: {'action': {'type': 'buy_xp'},
                                     'text': 'Suba de nível.'}
        self.assertIs(engine._fallback_decision({}, 'test'), shop_call)


if __name__ == '__main__':
    unittest.main()
