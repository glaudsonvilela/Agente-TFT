import json
from pathlib import Path
import unittest

from hm.item_recipes import CORE_COMPONENTS, core_recipes, crafted_item
from training.board_hub_item_candidates import load_reference, select_entries


ROOT = Path(__file__).parents[3]


class CoreRecipeTests(unittest.TestCase):
    def test_pinned_release_has_all_core_pairs(self):
        active = json.loads((ROOT / 'configs/catalog/active-knowledge-release-v1.json').read_text())
        release = ROOT / active['reference']
        rows = json.loads((release / 'items.json').read_text())['items']
        recipes = core_recipes(rows)
        self.assertEqual(len(recipes), len(CORE_COMPONENTS) * (len(CORE_COMPONENTS) + 1) // 2)
        self.assertEqual(crafted_item(recipes, 'TFT_Item_GiantsBelt', 'TFT_Item_GiantsBelt'),
                         {'item_id': 'TFT_Item_WarmogsArmor', 'name': 'Armadura de Warmog'})
        self.assertEqual(crafted_item(recipes, 'TFT_Item_NegatronCloak', 'TFT_Item_BFSword'),
                         {'item_id': 'TFT_Item_Bloodthirster', 'name': 'Sedenta por Sangue'})
        self.assertIsNone(crafted_item(recipes, 'unknown', 'TFT_Item_BFSword'))

    def test_missing_pair_fails_instead_of_claiming_complete(self):
        active = json.loads((ROOT / 'configs/catalog/active-knowledge-release-v1.json').read_text())
        rows = json.loads((ROOT / active['reference'] / 'items.json').read_text())['items']
        rows = [row for row in rows if row['api_name'] != 'TFT_Item_WarmogsArmor']
        with self.assertRaisesRegex(ValueError, 'Incomplete core item recipes'):
            core_recipes(rows)

    def test_every_craftable_core_item_has_active_visual_art(self):
        active = json.loads((ROOT / 'configs/catalog/active-knowledge-release-v1.json').read_text())
        rows = json.loads((ROOT / active['reference'] / 'items.json').read_text())['items']
        expected = {row['item_id'] for row in core_recipes(rows).values()}
        visual = json.loads((ROOT / 'configs/catalog/active-visual-reference-v1.json').read_text())
        manifest, entries = load_reference(ROOT / visual['reference'])
        selected = select_entries(entries, manifest['set_key'], visual['match_scope'])
        icon_root = ROOT / visual['icon_dir']
        if not icon_root.is_dir():
            icon_root = ROOT / 'build/hm4-live-assets' / visual['icon_dir']
        available = {row['id'] for row in selected if (icon_root / row['icon']).is_file()}
        self.assertEqual(expected - available, set())
