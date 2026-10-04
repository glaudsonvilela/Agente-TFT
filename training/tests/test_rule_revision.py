from copy import deepcopy
import json
from pathlib import Path
import unittest

import numpy as np

from ingestion.knowledge_release import read_release
from ingestion.rule_revision import compile_revision, reconcile, checksum
from ingestion.simulation_bindings import load_bindings
from trainer.simulation.event_combat import Battle
from trainer.simulation.state import UnsupportedRule
from trainer.simulation.value_model import BoardEncoder
from training.tests.test_event_combat import content, players

ROOT = Path(__file__).resolve().parents[2]


class RuleReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_bindings(
            ROOT / "configs/simulation/seasons/TFTSet18/18.3/manifest.json"
        )
        cls.revision = json.loads(
            (
                ROOT
                / "configs/simulation/seasons/TFTSet18/revisions/18.3B-20260928.json"
            ).read_text()
        )
        active = json.loads(
            (ROOT / "configs/catalog/active-knowledge-release-v1.json").read_text()
        )
        cls.manifest, cls.catalogs = read_release(ROOT / active["reference"])
        cls.compiled = compile_revision(
            cls.manifest, cls.catalogs, cls.base, cls.revision
        )

    def test_revision_preserves_base_and_separates_effective_patch(self):
        before = deepcopy(self.base)
        result = compile_revision(
            self.manifest, self.catalogs, self.base, self.revision
        )
        self.assertEqual(self.base, before)
        self.assertEqual(result["catalog_patch"], "18.3")
        self.assertEqual(result["patch"], "18.3B-20260928")
        self.assertFalse(result["coverage"]["revision_reconciliation_complete"])
        self.assertFalse(result["coverage"]["current_patch_training_ready"])
        self.assertEqual(result["coverage"]["abilities"]["candidate_programs"], 31)
        self.assertEqual(result["coverage"]["champions"]["candidate_effects"], 25)
        self.assertEqual(len(result["coverage"]["abilities"]["blocked"]), 43)

    def test_mutated_base_conflicting_paths_and_unanchored_values_rejected(self):
        bad = deepcopy(self.base)
        bad["profile"]["base_ap"] = 200
        with self.assertRaisesRegex(UnsupportedRule, "sealed base"):
            reconcile(bad, self.revision)
        r = deepcopy(self.revision)
        r["changes"].append(deepcopy(r["changes"][0]))
        with self.assertRaisesRegex(UnsupportedRule, "overlapping"):
            reconcile(self.base, r)
        r = deepcopy(self.revision)
        r["changes"][0]["expected_sha256"] = "0" * 64
        with self.assertRaisesRegex(UnsupportedRule, "base value"):
            reconcile(self.base, r)
        self.assertEqual(checksum(self.base), self.revision["base_bindings_sha256"])

    def test_omitting_gaps_or_renaming_patch_does_not_establish_parity(self):
        from training.simulator_lab.dependency_audit import audit

        for field in ("pending_reconciliation", "reconciliation_status"):
            revision = deepcopy(self.revision)
            del revision[field]
            with self.assertRaisesRegex(UnsupportedRule, "explicit reconciliation"):
                reconcile(self.base, revision)
        revision = deepcopy(self.revision)
        revision["reconciliation_status"] = "complete"
        with self.assertRaisesRegex(UnsupportedRule, "explicit reconciliation"):
            reconcile(self.base, revision)
        report = audit(
            {"patch": self.compiled["patch"], "strategies": []},
            {"cores": {}},
            self.compiled,
        )
        self.assertTrue(report["patch_label_match"])
        self.assertFalse(report["exact_patch_match"])
        self.assertFalse(report["runtime_promoted"])

    def ability_battle(self, key, *, stage=3):
        # Isolate the ability contract on synthetic opponents. The champion's
        # full trait roster is covered separately by dependency probes.
        c = content()
        spec = self.compiled["champions"][key]
        program = spec["ability_program"]
        c["champions"]["fixture"].update(deepcopy(program))
        if "stage_modifiers" in spec:
            c["champions"]["fixture"]["stage_modifiers"] = spec["stage_modifiers"]
        p = players()
        for player in p:
            player.stage = stage
        b = Battle(p, c, trace=True)
        for u in b.units:
            u.values.base["crit_chance"] = 0
        return b

    def test_fighter_requires_stage_and_changes_attack_speed(self):
        for stage, expected in ((2, 1.05), (3, 1.1), (4, 1.2), (5, 1.3), (6, 1.3)):
            b = self.ability_battle("DA_18_Camille", stage=stage)
            self.assertAlmostEqual(b.get(b.units[0], "attack_speed"), expected)
        with self.assertRaisesRegex(UnsupportedRule, "observed stage"):
            self.ability_battle("DA_18_Camille", stage=None)

    def test_caitlyn_third_attack_replaces_normal_and_preserves_critical(self):
        b = self.ability_battle("DA_18_Caitlyn")
        a, z = b.units
        a.values.base.update(ad=20, ap=100, crit_chance=1, crit_multiplier=2)
        z.values.base.update(hp=10000, ad=0, armor=0)
        z.hp = 10000
        z.hooks = []
        b.duration = 6
        result = b.run()
        damage = [
            e["amount"]
            for e in result["events"]
            if e["kind"] == "damage" and e["source"] == "a"
        ]
        self.assertEqual(damage[:6], [40, 40, 116, 40, 40, 116])
        self.assertEqual(a.casts, 0)

    def test_xayah_five_feathers_expire_and_reduce_armor_per_hit(self):
        b = self.ability_battle("DA_18_Xayah")
        a, z = b.units
        a.values.base.update(ad=20, ap=100, crit_chance=0)
        z.values.base.update(hp=10000, ad=0, armor=10)
        z.hp = 10000
        z.hooks = []
        z.spell = {"kind": "none", "effects": []}
        b.effects(a, z, a.spell["effects"])
        a.spell = {"kind": "none", "effects": []}
        b.duration = 4
        result = b.run()
        hits = [
            e["amount"]
            for e in result["events"]
            if e["kind"] == "damage" and e["source"] == "a"
        ]
        self.assertGreaterEqual(len(hits), 5)
        self.assertAlmostEqual(hits[0], 13.6 / 1.1)
        self.assertAlmostEqual(hits[4], 13.6 / 1.02)
        self.assertEqual(b.get(z, "armor"), 0)
        self.assertEqual(b.get(a, "attack_speed"), 1)
        self.assertEqual(a.empowers, {})

    def test_vi_heal_immunity_and_buffs_expire(self):
        b = self.ability_battle("DA_Vi18")
        a, z = b.units
        a.values.base["hp"] = 1000
        a.hp = 100
        b.hook("attack", a, z)
        self.assertEqual(a.hp, 120)
        b.effects(a, z, a.spell["effects"])
        self.assertEqual(a.hp, 320)
        self.assertAlmostEqual(b.get(a, "attack_speed"), 1.85)
        b.effects(z, a, [dict(op="status", name="stun", duration=1)])
        self.assertFalse(b.status(a, "stun"))
        b.now = 3
        self.assertEqual(b.get(a, "attack_speed"), 1)
        self.assertEqual(b.get(a, "cc_immune"), 0)

    def test_varus_line_must_include_current_target(self):
        b = self.ability_battle("DA_18_Varus")
        a, z = b.units
        a.position = (1, 1)
        z.position = (1, 5)
        for index, position in enumerate(((2, 1), (3, 1), (4, 1))):
            b.create("extra" + str(index), "fixture", 1, 1, position)
        unconstrained = b.select(a, z, {"kind": "best_line", "width": 0.8})
        self.assertNotIn(z, unconstrained)
        selected = b.select(a, z, a.spell["effects"][0]["target"])
        self.assertIn(z, selected)

    def test_stage_is_encoded_and_team_mirroring_preserves_context(self):
        encoder = BoardEncoder(["fixture"], [])
        p = players()
        unknown = encoder.encode(p)
        for player in p:
            player.stage = 3
        stage3 = encoder.encode(p)
        self.assertFalse(np.array_equal(unknown, stage3))
        self.assertEqual(stage3.shape, (encoder.size,))
        np.testing.assert_allclose(stage3.reshape(2, -1)[:, -2:], [[1, 0.3], [1, 0.3]])
        reversed_features = encoder.encode(p[::-1])
        np.testing.assert_array_equal(
            reversed_features,
            np.concatenate((stage3[encoder.side_size :], stage3[: encoder.side_size])),
        )

    def test_camille_flat_shield_and_hotfix_ad_ap_split(self):
        b = self.ability_battle("DA_18_Camille")
        a, z = b.units
        z.values.base["hp"] = 2000
        z.hp = 2000
        a.values.base["ap"] = 200
        b.effects(a, z, a.spell["effects"])
        self.assertAlmostEqual(z.hp, 1950)  # 20 AD * 1.5 + 200 AP * .1
        self.assertEqual(a.shields[0].amount, 60)  # shield has no AP scaling
        self.assertEqual(a.shields[0].expires, 2)

    def test_akali_samples_burn_before_strike_not_from_its_own_proc(self):
        b = self.ability_battle("DA_18_Akali_AD")
        a, z = b.units
        a.hooks = [
            dict(
                event="damage_dealt",
                _key="burn",
                effects=[dict(op="status", name="burn", duration=3)],
            )
        ]
        b.effects(a, z, a.spell["effects"])
        self.assertAlmostEqual(z.hp, 61)  # 20 * 1.45 + 100 * .1
        b.effects(a, z, a.spell["effects"])
        self.assertAlmostEqual(z.hp, 15)  # now 20 * 1.8 + 100 * .1

    def test_warwick_heals_from_actual_damage_and_ap_and_keeps_as(self):
        b = self.ability_battle("DA_18_Warwick")
        a, z = b.units
        a.hp = 10
        a.values.base["ap"] = 200
        z.values.base["armor"] = 100
        b.effects(a, z, a.spell["effects"])
        self.assertAlmostEqual(z.hp, 77)  # 46 raw, halved by armor
        self.assertAlmostEqual(a.hp, 21.5)  # .25 * 2 * 23
        self.assertAlmostEqual(b.get(a, "attack_speed"), 1.3)  # stage3 + skill

    def test_reksai_regeneration_window_refreshes_and_expires(self):
        b = self.ability_battle("DA_18_RekSai")
        a, z = b.units
        a.values.base["hp"] = 1000
        a.hp = 100
        b.hook("periodic", a, a)
        self.assertEqual(a.hp, 110)
        b.effects(a, z, a.spell["effects"])
        b.hook("periodic", a, a)
        self.assertEqual(a.hp, 140)
        b.now = 2
        b.effects(a, z, a.spell["effects"])
        b.now = 3
        b.hook("periodic", a, a)
        self.assertEqual(a.hp, 170)
        b.now = 5
        b.hook("periodic", a, a)
        self.assertEqual(a.hp, 180)

    def test_kobuko_next_attack_replacement_contains_hp_and_ap(self):
        b = self.ability_battle("DA_18_Kobuko")
        a, z = b.units
        b.effects(a, z, a.spell["effects"])
        effect = next(iter(a.empowers.values()))["rule"]
        self.assertTrue(effect["replace_attack"])
        self.assertEqual(effect["charges"], 1)
        b.effects(a, z, effect["effects"])
        self.assertAlmostEqual(z.hp, 20)  # 10% *100 HP + .7*100 AP


if __name__ == "__main__":
    unittest.main()
