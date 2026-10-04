"""The map must expose missing entities and must never promote incomplete rules."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ingestion.knowledge_release import read_release
from ingestion.simulation_bindings import load_bindings
from training.simulator_lab.rule_map import build_map, indexed


class RuleMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        selection = json.loads(
            (root / "configs/catalog/active-knowledge-release-v1.json").read_text()
        )
        cls.manifest, cls.catalogs = read_release(root / selection["reference"])
        pack = root / "configs/simulation/seasons/TFTSet18/18.3"
        cls.bindings = load_bindings(pack / "manifest.json")
        cls.requirements = json.loads((pack / "mapping-requirements.json").read_text())

    def test_full_inventory_preserves_blockers_and_unknown_membership(self):
        report = build_map(
            self.manifest, self.catalogs, self.bindings, self.requirements
        )
        for kind, component, collection in [
            ("champion", "units", "champions"),
            ("trait", "traits", "traits"),
            ("item_catalog", "items", "items"),
        ]:
            rows = [r for r in report["entries"] if r["kind"] == kind]
            self.assertEqual(
                {r["id"] for r in rows},
                {r["api_name"] for r in self.catalogs[component][collection]},
            )
            self.assertEqual(len(rows), len(self.catalogs[component][collection]))
        self.assertTrue(report["catalog_inventory_complete"])
        self.assertFalse(report["all_game_variables_mapped"])
        self.assertFalse(report["current_patch_training_ready"])
        self.assertFalse(report["runtime_promoted"])
        self.assertTrue(all(not r["replay_validated"] for r in report["entries"]))
        self.assertTrue(
            all(
                not r["set_membership_verified"]
                for r in report["entries"]
                if r["kind"] == "item_catalog"
            )
        )
        ivern = next(r for r in report["entries"] if r["id"] == "DA_18_Ivern")
        self.assertTrue(ivern["combat_candidate"])
        self.assertIn("DA_18_Greenfather", ivern["conditional_trait_blockers"])
        eclipse = next(r for r in report["entries"] if r["id"] == "DA_18_Eclipse")
        self.assertTrue(any(not t["bounds_valid"] for t in eclipse["tiers"]))

    def test_missing_trait_requirement_cannot_silently_disappear(self):
        requirements = deepcopy(self.requirements)
        del requirements["traits"]["DA_18_Greenfather"]
        with self.assertRaisesRegex(ValueError, "Every trait"):
            build_map(self.manifest, self.catalogs, self.bindings, requirements)

    def test_wrong_patch_and_duplicate_catalog_ids_are_rejected(self):
        requirements = dict(self.requirements, patch="18.4")
        with self.assertRaisesRegex(ValueError, "different seasonal"):
            build_map(self.manifest, self.catalogs, self.bindings, requirements)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            indexed([dict(api_name="duplicate"), dict(api_name="duplicate")])


if __name__ == "__main__":
    unittest.main()
