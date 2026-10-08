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

    def test_memory_receives_partial_observations_even_without_a_tip(self):
        class Motor:
            ready = {'rank_advice': True, 'match_memory': True}
            def request(self, request, timeout):
                self.request_seen = request
                return {'origin': 'rust_live_opportunity_v1',
                        'selected_index': None, 'ranked': [], 'native_ms': .1,
                        'memory': {'persistence': 'local_sqlite'}}

        motor = Motor()
        answer = {'id': 8, 'source_ms': 100, 'decision_options': [],
                  'hud': [{'field': 'gold', 'value': 30, 'confidence': .96,
                           'status': 'single_frame_observation'}],
                  'shop': {'slots': [{'slot': 0, 'unit_id': 'TFT_X',
                                      'catalog_status': 'unique_name_bound'}]}}
        visual = {'identity_verified': False,
                  'units': [{'candidate_id': 'TFT_Y', 'status': 'persistent_candidate',
                             'identity_verified': False}],
                  'inventory': [{'current_candidate_id': 'TFT_Item_X',
                                 'identity_verified': False}],
                  'opponents': {'current_opponent': None,
                                'opponent_board_assigned': False}}
        ReplayDecisionEngine.rank_with_native(answer, motor,
            match_id='0123456789abcdef0123456789abcdef', epoch=2,
            visual_candidates=visual)
        request = motor.request_seen
        self.assertEqual(request['epoch'], 2)
        self.assertEqual(request['observation']['gold'], 30)
        self.assertFalse(request['observation']['board_identity_verified'])
        self.assertFalse(request['observation']['board'][0]['identity_verified'])
        self.assertFalse(request['observation']['inventory'][0]['identity_verified'])
        self.assertEqual(answer['decision_rank']['memory']['persistence'], 'local_sqlite')

    def test_verified_strategy_decision_is_not_replaced_by_memory_write(self):
        class Motor:
            ready = {'rank_advice': True}
            def request(self, request, timeout):
                self.last = request
                return {'origin': 'rust_live_opportunity_v1',
                        'selected_index': None, 'ranked': [], 'native_ms': .1}
        motor = Motor()
        answer = {'id': 1, 'source_ms': 100, 'hud': [],
                  'decision': {'action': {'type': 'equip'}, 'text': 'Equipar item.'}}
        ReplayDecisionEngine.rank_with_native(answer, motor,
            match_id='0123456789abcdef0123456789abcdef')
        self.assertEqual(answer['decision']['action']['type'], 'equip')
        self.assertEqual(answer['decision_rank']['status'], 'memory_only')
        self.assertEqual(motor.last['candidates'], [])

    def test_candidate_assembly_keeps_both_actions_for_rust(self):
        engine = object.__new__(ReplayDecisionEngine)
        shop_call = {'family': 'synergy', 'action': {'type': 'buy_synergy'},
                     'text': 'Compre Sejuani.'}
        engine.live_advice = types.SimpleNamespace(
            propose=lambda *_: shop_call)
        engine._economy = lambda _: {'action': {'type': 'buy_xp'},
                                     'text': 'Suba de nível.'}
        output = {}
        self.assertEqual(engine._fallback_decision(output, 'test')['action']['type'], 'buy_xp')
        self.assertEqual({row['action']['type'] for row in output['decision_options']},
                         {'buy_xp', 'buy_synergy'})
        self.assertNotEqual(shop_call.get('rank_score'), .91)

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
