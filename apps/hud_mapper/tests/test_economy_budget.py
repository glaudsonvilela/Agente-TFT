import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hm.economy_budget import EconomyBudget
from hm.replay_coach import coach_prompt
from hm.replay_decision import ReplayDecisionEngine


ROOT = Path(__file__).resolve().parents[3]


class EconomyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.engine = EconomyBudget(ROOT, patch="18.3", set_key="TFTSet18")

    def test_xp_threshold_interest_and_reserve_use_same_simulator_rules(self):
        quote = self.engine.level_quote(
            gold=50, level=7, xp=50, observed_threshold=56, reserve=40
        )
        self.assertEqual(
            (quote["purchases"], quote["gold_cost"], quote["gold_after"]), (2, 8, 42)
        )
        self.assertEqual((quote["target_level"], quote["target_xp"]), (8, 2))
        self.assertEqual((quote["interest_now"], quote["interest_after"]), (5, 4))
        self.assertTrue(quote["reserve_met"])
        self.assertFalse(quote["learned_policy"])

    def test_insufficient_money_is_a_quote_not_negative_real_gold(self):
        quote = self.engine.level_quote(
            gold=3, level=3, xp=2, observed_threshold=6, reserve=10
        )
        self.assertFalse(quote["affordable"])
        self.assertIsNone(quote["gold_after"])
        self.assertEqual((quote["required_gold"], quote["missing_gold"]), (14, 11))

    def test_bad_patch_table_or_ocr_denominator_cannot_issue_level_quote(self):
        with self.assertRaisesRegex(ValueError, "another patch"):
            EconomyBudget(ROOT, patch="other", set_key="TFTSet18")
        with self.assertRaisesRegex(ValueError, "threshold"):
            self.engine.level_quote(
                gold=100, level=7, xp=50, observed_threshold=60, reserve=0
            )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "configs/contexts").mkdir(parents=True)
            manifest = json.loads(
                (ROOT / "configs/contexts/replay-resource-engine-v1.json").read_text()
            )
            for row in manifest["components"].values():
                path = root / row["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / row["path"]).read_bytes() + b" ")
            (root / "configs/contexts/replay-resource-engine-v1.json").write_text(
                json.dumps(manifest)
            )
            with self.assertRaisesRegex(ValueError, "checksum"):
                EconomyBudget(root, patch="18.3", set_key="TFTSet18")

    def test_capture_decision_to_voice_saving_and_level_use_current_gold(self):
        engine = ReplayDecisionEngine(str(ROOT / "configs"))
        answer = dict(
            origin="observed_pixels",
            source_ms=1000,
            hud=[
                dict(
                    field=k,
                    value=v,
                    text=t,
                    status="single_frame_observation",
                    confidence=0.97,
                )
                for k, v, t in [
                    ("stage", "2-5", "2-5"),
                    ("gold", 20, "20"),
                    ("level", 4, "4"),
                    ("xp", 8, "8/10"),
                ]
            ],
            controls=dict(
                cadence_delivery=dict(fresh=True),
                controls=[
                    dict(id="buy_xp", status="observed", appearance="active_appearance")
                ],
                numeric_fields=[
                    dict(id="buy_xp_price", status="observed", confidence=0.95, value=4)
                ],
            ),
        )
        self.assertFalse(coach_prompt(engine.evaluate(answer))["actionable"])
        answer["source_ms"] = 1500
        saving = engine.evaluate(answer)
        self.assertEqual(saving["decision"]["action"]["target_gold"], 24)
        self.assertEqual(
            coach_prompt(saving)["speech_text"],
            "Guarde até 24 de ouro para subir ao nível 5.",
        )
        answer["hud"][1]["value"] = 24
        answer["source_ms"] = 2000
        with patch.object(
            Path, "read_bytes", side_effect=AssertionError("I/O in frame loop")
        ), patch.object(
            Path, "read_text", side_effect=AssertionError("I/O in frame loop")
        ):
            leveling = engine.evaluate(answer)
        self.assertEqual(leveling["decision"]["action"]["type"], "buy_xp")
        self.assertEqual(leveling["decision"]["resource_quote"]["gold_after"], 20)
        self.assertIn("Suba para o nível 5", coach_prompt(leveling)["speech_text"])
        answer["source_ms"] = 2500
        answer["controls"]["cadence_delivery"]["fresh"] = False
        provisional = coach_prompt(engine.evaluate(answer))
        self.assertTrue(provisional["actionable"])
        self.assertEqual(provisional["evidence_level"], "provisional")
        self.assertIn("Confira o botão de XP", provisional["text"])


if __name__ == "__main__":
    unittest.main()
