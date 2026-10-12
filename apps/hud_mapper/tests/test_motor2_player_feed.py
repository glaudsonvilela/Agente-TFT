import unittest

from hm.motor2_player_feed import ACTION_TYPES, FEATURE_NAMES, make_frame
from hm.replay_decision import ReplayDecisionEngine


class Motor2PlayerFeedTests(unittest.TestCase):
    def result(self):
        return dict(origin="rust_live_opportunity_v1", id=17, source_ms=3000,
            whole_state=dict(stage="3-2", gold=40, hp=56, level=6, xp=12,
                fresh_shop_offers=5, board_candidates=6,
                board_identity_verified=False, item_candidates=2,
                opponent_candidates=7, opponent_linked=False,
                trait_counts={"Coven": 3}),
            macro_state=dict(phase="middle", pressure="normal",
                observed_hp_loss_90s=5, observed_gold_change_90s=None),
            candidates=[dict(policy="partial_state_live_v1",
                action=dict(type="buy_pair", unit_id="TFT18_Test"),
                basis=["shop.two_fresh_exact_names"])],
            ranked=[dict(index=0, action_type="buy_pair", decision_key="pair:a",
                base_utility=.3, utility=.4, plan_alignment_bonus=.1,
                recent_repeats=0)], selected_index=0)

    def test_rust_action_state_and_missingness_reach_policy_without_label(self):
        frame = make_frame(self.result(), patch="18.4B", set_key="TFTSet18",
                           match_id="match", epoch=0)
        self.assertEqual(frame["whole_state"]["trait_counts"], {"Coven": 3})
        self.assertEqual(frame["candidates"][0]["action"]["type"], "buy_pair")
        self.assertEqual(len(frame["candidates"][0]["features"]), len(FEATURE_NAMES))
        self.assertEqual(frame["candidates"][0]["features"][-len(ACTION_TYPES):],
                         [float(name == "buy_pair") for name in ACTION_TYPES])
        self.assertEqual(frame["candidates"][0]["features"][FEATURE_NAMES.index("gold_change_known")], 0)
        self.assertFalse(frame["training_eligible"])
        self.assertFalse(frame["candidates"][0]["game_legality_verified"])
        self.assertEqual(len(frame["observation_sha256"]), 64)

    def test_mismatched_action_or_index_is_rejected(self):
        result = self.result()
        result["ranked"][0]["action_type"] = "roll"
        with self.assertRaisesRegex(ValueError, "identity"):
            make_frame(result, patch="18.4B", set_key="TFTSet18",
                       match_id="match", epoch=0)

    def test_replay_bridge_attaches_frame_without_changing_rust_choice(self):
        result = self.result()
        class Motor:
            ready = {"rank_advice": True}
            def request(self, request, timeout):
                return result
        answer = dict(id=17, source_ms=3000, hud=[], decision_options=result["candidates"])
        ReplayDecisionEngine.rank_with_native(answer, Motor(), patch="18.4B",
                                              set_key="TFTSet18")
        self.assertEqual(answer["decision"]["action"]["type"], "buy_pair")
        self.assertEqual(answer["player_policy_frame"]["candidates"][0]
                         ["decision_key"], "pair:a")
        self.assertFalse(answer["player_policy_frame"]["runtime_policy_active"])

    def test_old_worker_missing_feed_keeps_rust_choice(self):
        result = self.result()
        result.pop("candidates")
        class Motor:
            ready = {"rank_advice": True}
            def request(self, request, timeout):
                return result
        answer = dict(id=17, source_ms=3000, hud=[], decision_options=[
            dict(policy="partial_state_live_v1", action=dict(type="buy_pair"))])
        ReplayDecisionEngine.rank_with_native(answer, Motor(), patch="18.4B",
                                              set_key="TFTSet18")
        self.assertEqual(answer["decision"]["action"]["type"], "buy_pair")
        self.assertIn("player_policy_feed_error", answer)
        result = self.result()
        result["ranked"][0]["index"] = 8
        with self.assertRaisesRegex(ValueError, "index"):
            make_frame(result, patch="18.4B", set_key="TFTSet18",
                       match_id="match", epoch=0)


if __name__ == "__main__":
    unittest.main()
