import json
from pathlib import Path
import tempfile
import unittest

from knowledge.strategy_knowledge import StrategyKnowledge


ROOT = Path(__file__).parents[2]


class StrategyKnowledgeTests(unittest.TestCase):
    def test_pack_is_patch_bound_and_keeps_rules_as_reference(self):
        book = StrategyKnowledge.for_patch(ROOT, set_key="TFTSet18", patch="18.4B")
        self.assertIsNotNone(book)
        self.assertEqual(book.data["coverage"]["shop_champions"], 65)
        self.assertEqual(book.data["coverage"]["traits"], 36)
        self.assertEqual(book.data["coverage"]["set_champion_entries"], 91)
        self.assertFalse(book.data["runtime_combat_rules_verified"])
        self.assertIsNone(StrategyKnowledge.for_patch(ROOT, set_key="TFTSet18", patch="18.3"))
        ahri = book.champion("DA_18_Ahri")
        self.assertEqual(ahri["catalog_class"], "shop")
        self.assertIn("stats", ahri)
        self.assertIn("ability", ahri)
        self.assertTrue(ahri["traits"])
        self.assertEqual(ahri["mechanic_status"], "reference_only_not_executable")
        varus = book.champion("DA_18_Varus")
        self.assertEqual(varus["stats_status"],
                         "provider_snapshot_not_reconciled_with_official_18.4_changes")
        self.assertTrue(any(row["subject"] == "Varus"
                            for row in varus["official_base_patch_changes"]))
        self.assertTrue(any("20/110" in row["change"]
                            for row in varus["official_mid_patch_changes"]))

    def test_only_exact_readable_shop_ids_receive_reference(self):
        book = StrategyKnowledge.for_patch(ROOT, set_key="TFTSet18", patch="18.4B")
        result = book.observed_shop_context([
            {"slot": 0, "unit_id": "DA_18_Ahri", "catalog_status": "unique_name_bound",
             "status": "offer_text_readable"},
            {"slot": 1, "unit_id": "DA_18_Ahri", "catalog_status": "ambiguous_name",
             "status": "offer_text_readable"},
            {"slot": 2, "unit_id": "DA_18_Ahri", "catalog_status": "unique_name_bound",
             "status": "partially_readable"},
            {"slot": 3, "unit_id": "missing", "catalog_status": "unique_name_bound",
             "status": "offer_text_readable"},
        ])
        self.assertEqual(len(result["offers"]), 1)
        self.assertEqual(result["offers"][0]["slot"], 0)
        self.assertFalse(result["combat_rules_verified"])
        self.assertEqual(result["fact_type"], "patch_reference_not_observed_ownership")

    def test_modified_pack_is_rejected(self):
        source = ROOT / "configs/strategy/TFTSet18/18.4B"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / "manifest.json").write_bytes((source / "manifest.json").read_bytes())
            raw = json.loads((source / "knowledge.json").read_text())
            raw["patch"] = "18.3"
            (target / "knowledge.json").write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                StrategyKnowledge(target, set_key="TFTSet18", patch="18.4B")

    def test_verified_owned_unit_links_equipped_item_without_guessing(self):
        book = StrategyKnowledge.for_patch(ROOT, set_key="TFTSet18", patch="18.4B")
        state = dict(verified=True, perspective="self", set_key="TFTSet18",
                     patch="18.4B", age_ms=100, units=[
                         dict(uid="board-1", unit_id="DA_18_Ahri", stars=2,
                              zone="board", identity_verified=True,
                              items=["TFT_Item_WarmogsArmor"]),
                         dict(uid="board-2", unit_id="DA_18_Ahri", stars=1,
                              zone="board", identity_verified=False, items=[])])
        linked = book.observed_shop_context([], state)["verified_owned"]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]["champion"]["unit_id"], "DA_18_Ahri")
        self.assertEqual(linked[0]["items"][0]["effect_id"],
                         "TFT_Item_WarmogsArmor")
        state["patch"] = "18.3"
        self.assertEqual(book.verified_owned_context(state), [])


if __name__ == "__main__":
    unittest.main()
