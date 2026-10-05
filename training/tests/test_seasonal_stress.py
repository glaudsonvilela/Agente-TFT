from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training.seasonal_stress import run_batch
from training.tests.test_hex_simulator import fixture


ROOT = Path(__file__).resolve().parents[2]


class SeasonalStressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.events = json.loads(
            (
                ROOT / "configs/simulation/seasons/TFTSet18/events/18.3B-economy.json"
            ).read_text()
        )
        self.calendar = json.loads(
            (ROOT / "configs/simulation/core/standard-calendar-v1.json").read_text()
        )
        self.economy = json.loads(
            (ROOT / "configs/simulation/core/standard-economy-v2.json").read_text()
        )
        self.content = fixture()
        self.content["patch"] = self.events["patch"]
        profile = json.loads(
            (ROOT / "configs/simulation/seasons/TFTSet18/18.3/profile.json").read_text()
        )
        self.content["economy"] = deepcopy(profile["planning"]["economy"])
        for cost in range(2, 6):
            row = deepcopy(self.content["champions"]["fixture"])
            row.update(cost=cost, sale_prices={"1": cost})
            self.content["champions"][str(cost)] = row

    def run_cases(self, directory, cases):
        return run_batch(
            self.content,
            self.events,
            self.calendar,
            self.economy,
            self.folder / directory,
            cases=cases,
            seed=9,
        )

    def test_all_offer_variants_and_families_reproduce_without_training_labels(self):
        first = self.run_cases("a", 140)
        second = self.run_cases("b", 140)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["completed_cases"], 140)
        self.assertEqual(first["cases_sha256"], second["cases_sha256"])
        self.assertEqual(len(first["wisp_variant_counts"]), 27 * 4)
        self.assertEqual(
            first["family_counts"],
            {"wisp_resource": 112, "shop_item_sale": 14, "delayed_reward_carousel": 14},
        )
        self.assertEqual(first["complete_matches"], 0)
        self.assertEqual(first["training_labels"], 0)
        self.assertFalse(first["training_started"])
        self.assertTrue(first["engine_sha256"])

    def test_failure_stops_batch_and_retains_seed_and_progress(self):
        with patch(
            "training.seasonal_stress.offer_case",
            side_effect=AssertionError("injected pool drift"),
        ):
            result = self.run_cases("failure", 10000)
        self.assertEqual((result["completed_cases"], result["failed_cases"]), (0, 1))
        progress = json.loads((self.folder / "failure/progress.json").read_text())
        self.assertEqual(progress["failure"]["seed"], 9)
        self.assertEqual(progress["status"], "failed")
        self.assertEqual(
            len((self.folder / "failure/cases.jsonl").read_text().splitlines()), 1
        )

    def test_repeated_command_cannot_overwrite_a_previous_run(self):
        self.run_cases("same", 1)
        before = (self.folder / "same/progress.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_cases("same", 1)
        self.assertEqual((self.folder / "same/progress.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
