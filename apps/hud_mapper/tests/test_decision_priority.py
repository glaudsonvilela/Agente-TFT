import types
import unittest

from hm.replay_decision import ReplayDecisionEngine


class DecisionPriorityTests(unittest.TestCase):
    def test_live_choice_is_selected_by_native_motor(self):
        class Motor:
            ready = {'rank_advice': True}
            def request(self, request, timeout):
                self.last = request
                return {'id': request['id'], 'origin': 'rust_live_opportunity_v1',
                        'selected_index': 1, 'ranked': [{'index': 1, 'utility': .7}],
                        'native_ms': .1}

        motor = Motor()
        options = [{'policy': 'partial_state_live_v1', 'action': {'type': 'prepare_level'}},
                   {'policy': 'partial_state_live_v1', 'action': {'type': 'buy_pair'}}]
        answer = {'id': 8, 'source_ms': 100, 'hud': [], 'decision_options': options}
        ReplayDecisionEngine.rank_with_native(answer, motor)
        self.assertEqual(answer['decision']['action']['type'], 'buy_pair')
        self.assertEqual(answer['decision']['calculation_source'], 'rust_live_opportunity_v1')
        self.assertNotIn('decision_options', answer)

    def test_native_failure_abstains_instead_of_using_python_priority(self):
        class Motor:
            ready = {'rank_advice': True}
            def request(self, request, timeout):
                raise TimeoutError('motor unavailable')

        answer = {'id': 8, 'source_ms': 100, 'hud': [], 'decision_options': [
            {'policy': 'partial_state_live_v1', 'action': {'type': 'buy_pair'}}]}
        ReplayDecisionEngine.rank_with_native(answer, Motor())
        self.assertEqual(answer['decision']['action']['type'], 'wait')
        self.assertEqual(answer['decision_rank']['status'], 'abstained')

    def test_outdated_native_motor_abstains_without_ending_worker(self):
        class Motor:
            ready = {'protocol': 1}
            def request(self, request, timeout):
                raise AssertionError('incompatible motor must not receive rank_advice')

        answer = {'id': 8, 'source_ms': 100, 'hud': [], 'decision_options': [
            {'policy': 'partial_state_live_v1', 'action': {'type': 'buy_pair'}}]}
        ReplayDecisionEngine.rank_with_native(answer, Motor())
        self.assertEqual(answer['decision']['action']['type'], 'wait')
        self.assertEqual(answer['decision_rank']['reason'], 'RUST_MOTOR_VERSION_UNSUPPORTED')

    def test_native_abstention_is_not_reported_as_motor_failure(self):
        class Motor:
            ready = {'rank_advice': True}
            def request(self, request, timeout):
                return {'origin': 'rust_live_opportunity_v1',
                        'selected_index': None, 'ranked': [], 'native_ms': .1}

        answer = {'id': 8, 'source_ms': 100, 'hud': [], 'decision_options': [
            {'policy': 'partial_state_live_v1', 'action': {'type': 'trait_shop_review'}}]}
        ReplayDecisionEngine.rank_with_native(answer, Motor())
        self.assertEqual(answer['decision']['action']['type'], 'wait')
        self.assertEqual(answer['decision_rank']['reason'], 'NO_ACTIONABLE_NATIVE_CANDIDATE')

    def test_fresh_champion_call_beats_recurring_economy_reminder(self):
        engine = object.__new__(ReplayDecisionEngine)
        shop_call = {'family': 'synergy', 'action': {'type': 'buy_synergy'},
                     'text': 'Compre Sejuani.'}
        engine.live_advice = types.SimpleNamespace(
            propose=lambda *_: shop_call)
        engine._economy = lambda _: {'action': {'type': 'buy_xp'},
                                     'text': 'Suba de nível.'}
        self.assertIs(engine._fallback_decision({}, 'test'), shop_call)

    def test_urgent_level_beats_nonurgent_shop_review(self):
        engine = object.__new__(ReplayDecisionEngine)
        review = {'family': 'synergy', 'action': {'type': 'trait_shop_review'},
                  'rank_score': .57, 'text': 'Não compre só pelo traço.'}
        level = {'action': {'type': 'buy_xp'}, 'text': 'Suba de nível.'}
        engine.live_advice = types.SimpleNamespace(propose_all=lambda *_: [review])
        engine._economy = lambda _: level
        answer = {}
        self.assertEqual(engine._fallback_decision(answer, 'test')['action']['type'], 'buy_xp')
        self.assertEqual(len(answer['decision_candidates']), 2)


if __name__ == '__main__':
    unittest.main()
