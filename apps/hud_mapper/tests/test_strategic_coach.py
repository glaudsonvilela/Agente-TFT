from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from hm.replay_coach import coach_prompt
from hm.replay_decision import ReplayDecisionEngine
from hm.strategic_coach import StrategicCoach, alternatives, state_error
from hm.strategy_ranker import StrategyRanker


ROOT = Path(__file__).resolve().parents[3]


def state():
    def unit(uid, champion, pos, stars=1, zone="board", items=None):
        return dict(
            uid=uid,
            unit_id=champion,
            position=pos,
            stars=stars,
            zone=zone,
            items=items or [],
            identity_verified=True,
        )

    return dict(
        verified=True,
        complete=True,
        perspective="self",
        phase="planning",
        age_ms=0,
        evidence_id="reviewed:test-state",
        patch="18.3",
        set_key="TFTSet18",
        gold=70,
        hp=30,
        level=4,
        inventory=["TFT_Item_GiantsBelt", "TFT_Item_GiantsBelt"],
        units=[
            unit("a", "DA_18_Ahri", [0, 0]),
            unit("b", "DA_18_Akali_AD", [3, 5]),
            unit("c", "DA_18_Akali_AD", 0, zone="bench"),
            unit("d", "DA_18_Ahri", 1, stars=3, zone="bench"),
        ],
    )


class StrategicCoachTests(unittest.TestCase):
    def setUp(self):
        self.coach = StrategicCoach(ROOT)

    def test_all_families_have_legal_alternatives_without_mutating_observation(self):
        observed = state()
        saved = deepcopy(observed)
        choices = alternatives(observed, self.coach.catalog)
        self.assertEqual(
            {c["family"] for c in choices},
            {"hold", "roll", "composition", "position", "equip"},
        )
        self.assertEqual(observed, saved)
        for choice in choices:
            action = choice["action"]
            if action["type"] == "roll":
                self.assertLessEqual(
                    action["gold_budget"] + action["reserve_gold"], observed["gold"]
                )
                self.assertEqual(action["purchase_reserve"], 1)
                self.assertFalse(action["hidden_pool_observed"])
            elif action["type"] == "equip":
                self.assertEqual(action["inventory_slots"], [0, 1])
                self.assertEqual(action["item_id"], "TFT_Item_WarmogsArmor")

    def test_incomplete_stale_enemy_or_wrong_patch_cannot_generate_advice(self):
        for change in (
            dict(verified=False),
            dict(complete=False),
            dict(perspective="opponent"),
            dict(age_ms=2001),
            dict(age_ms=float("nan")),
            dict(patch="18.2"),
            dict(phase="combat"),
            dict(evidence_id=""),
            dict(augments=["unknown"]),
        ):
            with self.subTest(change=change):
                result = self.coach.evaluate({**state(), **change})
                self.assertFalse(result["recommendations"])
                self.assertTrue(result["blockers"])

    def test_full_item_slots_or_unknown_items_never_accept_equipment(self):
        observed = state()
        for unit in observed["units"]:
            unit["items"] = ["TFT_Item_WarmogsArmor"] * 3
        self.assertFalse(
            any(
                c["family"] == "equip"
                for c in alternatives(observed, self.coach.catalog)
            )
        )
        observed["inventory"] = ["item-from-another-season"]
        self.assertEqual(
            state_error(observed, self.coach.catalog), "ITEM_EFFECT_UNSUPPORTED"
        )

    def test_recipe_needs_two_distinct_inventory_instances(self):
        observed = state()
        observed["inventory"] = ["TFT_Item_GiantsBelt"]
        self.assertFalse(
            any(
                c["family"] == "equip"
                for c in alternatives(observed, self.coach.catalog)
            )
        )

    def test_roll_does_not_spend_purchase_money_or_cross_reserve(self):
        observed = state()
        observed.update(gold=32, hp=30)
        self.assertFalse(
            any(
                c["family"] == "roll"
                for c in alternatives(observed, self.coach.catalog)
            )
        )

    def test_duplicate_hex_or_unit_id_cannot_enter_planner(self):
        observed = state()
        observed["units"][1]["position"] = [0, 0]
        self.assertEqual(
            state_error(observed, self.coach.catalog), "DUPLICATE_POSITION"
        )
        observed = state()
        observed["units"][1]["uid"] = "a"
        self.assertEqual(
            state_error(observed, self.coach.catalog), "UNIT_UNVERIFIED_OR_UNSUPPORTED"
        )

    def test_real_decision_formatter_includes_text_voice_and_all_alternatives(self):
        engine = ReplayDecisionEngine(str(ROOT / "configs"))
        answer = dict(origin="observed_pixels", source_ms=1000, hud=[])
        result = engine.evaluate(answer, strategy_state=state())
        message = coach_prompt(result)
        self.assertTrue(message["actionable"])
        self.assertEqual(message["speech_text"], result["decision"]["text"])
        self.assertTrue(message["recommendations"])
        self.assertNotIn("analisando", message["text"].lower())
        self.assertFalse(coach_prompt(engine.evaluate(answer))["actionable"])

    def test_modified_catalog_cannot_load(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = json.loads((ROOT / "configs/coaching/active.json").read_text())
            (root / "configs/coaching").mkdir(parents=True)
            (root / "configs/coaching/active.json").write_text(json.dumps(manifest))
            path = root / manifest["catalog"]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / manifest["catalog"]["path"]).read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "identity"):
                StrategicCoach(root)

    def test_unreviewed_or_mismatched_weights_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "incompatible"):
            StrategyRanker({"schema_version": 1, "evaluation_passed": False}, "x")

    def test_new_gold_readout_invalidates_old_board_spending_advice(self):
        engine = ReplayDecisionEngine(str(ROOT / "configs"))
        answer = dict(
            origin="observed_pixels",
            source_ms=1000,
            hud=[
                dict(
                    field="gold",
                    value=0,
                    confidence=0.99,
                    status="single_frame_observation",
                )
            ],
        )
        result = engine.evaluate(answer, strategy_state=state())
        self.assertEqual(
            result["strategic_coaching"]["blockers"], ["BOARD_RESOURCE_FRAME_MISMATCH"]
        )
        self.assertFalse(coach_prompt(result)["actionable"])

    def test_zero_odds_or_bench_only_pair_is_not_a_roll_target(self):
        observed = state()
        for unit in observed["units"]:
            if unit["unit_id"] == "DA_18_Akali_AD":
                unit["unit_id"] = "DA_Lux18_Base"
        self.assertFalse(
            any(
                c["family"] == "roll"
                for c in alternatives(observed, self.coach.catalog)
            )
        )
        observed = state()
        observed["units"][1].update(zone="bench", position=2)
        self.assertFalse(
            any(
                c["family"] == "roll"
                for c in alternatives(observed, self.coach.catalog)
            )
        )

    def test_ordinary_copy_pool_is_not_exceeded(self):
        observed = state()
        observed["units"][0]["stars"] = 3
        self.assertEqual(
            state_error(observed, self.coach.catalog),
            "COPY_COUNT_REQUIRES_SPECIAL_EFFECT",
        )


if __name__ == "__main__":
    unittest.main()
