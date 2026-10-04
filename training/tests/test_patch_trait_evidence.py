"""Patch deltas must change real combat without mutating sealed evidence."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import pytest

from ingestion.field_names import field_hash, resolve_fields
from ingestion.numeric_overrides import apply_overrides
from ingestion.simulation_bindings import load_bindings
from trainer.simulation.event_combat import Battle
from trainer.simulation.state import Unit, UnsupportedRule
from training.compile_effects import compile_item, compile_trait
from training.tests.test_event_combat import content, players
from training.tests.test_seasonal_rules import PACK


def trait_battle(name, effects, count):
    c, p = content(), players()
    c["traits"][name] = compile_trait(
        dict(api_name=name, name=name, effects=effects), load_bindings(PACK)["traits"]
    )
    p[0].units = []
    for i in range(count + 1):
        ident = f"fixture-{i}"
        c["champions"][ident] = deepcopy(c["champions"]["fixture"])
        c["champions"][ident]["traits"] = [name] if i < count else []
        p[0].units.append(Unit(str(i), ident, zone="board", position=(i // 7, i % 7)))
    p[0].level = count + 1
    return Battle(p, c, trace=True)


class PatchTraitEvidence(unittest.TestCase):
    def test_hash_resolution_preserves_unknowns_and_rejects_collisions(self):
        assert field_hash("DefenderDefenseGain") == "{8c16b281}"
        assert field_hash("BonusBleedPercent") == "{2c61751d}"
        assert resolve_fields(
            "@DefenderDefenseGain@ @CritChance*100@ @Unknown@",
            {"{8c16b281}": 120, "CritChance": 0.15, "{12345678}": 1},
        ) == {"{8c16b281}": "DefenderDefenseGain", "CritChance": "CritChance"}
        with patch("ingestion.field_names.field_hash", return_value="{12345678}"):
            with pytest.raises(UnsupportedRule, match="ambiguous"):
                resolve_fields("@One@ @Two@", {"{12345678}": 1})

    def test_stale_or_unattributed_patch_deltas_are_rejected(self):
        rule = load_bindings(PACK)["traits"]["entities"]["DA_18_Defender"]["tiers"]["6"]
        changes = rule["numeric_overrides"]
        fields = {"{8c16b281}": 120}
        assert apply_overrides(fields, changes, "18.3") == {"{8c16b281}": 115}
        assert fields == {"{8c16b281}": 120}
        for values, deltas, version in [
            ({"{8c16b281}": 115}, changes, "18.3"),
            (fields, changes, "18.4"),
            (fields, changes * 2, "18.3"),
            (fields, [dict(changes[0], source_url="file:///tmp/data")], "18.3"),
            (fields, [dict(changes[0], value=float("nan"))], "18.3"),
        ]:
            with pytest.raises(UnsupportedRule):
                apply_overrides(values, deltas, version)

    def test_defender_replaces_team_bonus_and_applies_official_six_piece_nerf(self):
        b = trait_battle(
            "DA_18_Defender",
            [
                dict(
                    min_units=6,
                    max_units=99,
                    variables={"{0eb6405e}": 12, "{8c16b281}": 120},
                )
            ],
            6,
        )
        for stat in ("armor", "mr"):
            assert b.get(b.units[0], stat) == 115
            assert b.get(b.units[6], stat) == 12
            assert b.get(b.units[-1], stat) == 0
        # The team member bonus is replaced, never 115 + 12.
        assert b.hit(
            b.units[-1], b.units[0], 21.5, "physical", "attack"
        ) == pytest.approx(10)

    def test_caustic_refreshes_both_resists_and_preserves_stronger_debuff(self):
        b = trait_battle(
            "DA_18_Caustic",
            [
                dict(
                    min_units=1,
                    max_units=99,
                    variables={"ShredDuration": 4, "ShredPercent": 30},
                )
            ],
            1,
        )
        a, outsider, z = b.units
        z.values.base.update(armor=100, mr=100)
        assert b.hit(a, z, 10, "physical", "attack") == 5
        assert b.get(z, "sunder") == b.get(z, "shred") == 0.3
        z.values.add("stronger", "shred", 0.5, expires=2, group="shred", strongest=True)
        assert b.get(z, "shred") == 0.5
        b.now = 3
        b.hit(a, z, 1, "magic", "spell")
        b.now = 4
        assert b.get(z, "shred") == b.get(z, "sunder") == 0.3
        assert not outsider.hooks
        b.now = 7
        assert b.get(z, "shred") == b.get(z, "sunder") == 0

    def test_executioner_two_available_but_unknown_bleed_tiers_stay_blocked(self):
        effects = [
            dict(min_units=2, max_units=2, variables={"CritChance": 0.15}),
            dict(
                min_units=3,
                max_units=99,
                variables={"BleedDuration": 3, "{2c61751d}": 0.3},
            ),
        ]
        b = trait_battle("DA_18_Executioner", effects, 2)
        assert b.get(b.units[0], "precision") == 1
        assert b.get(b.units[0], "crit_chance") == 0.15
        assert b.get(b.units[2], "precision") == 0
        with pytest.raises(UnsupportedRule, match="not implemented"):
            trait_battle("DA_18_Executioner", effects, 3)

    def test_bloodthirster_uses_video_corroborated_patch_threshold_and_shield(self):
        row = dict(
            api_name="TFT_Item_Bloodthirster",
            name="BT",
            unique=False,
            effects=dict(
                AD=0.15,
                AP=15,
                MagicResist=20,
                HealthThreshold=40,
                ShieldHealthPercent=25,
                ShieldDuration=5,
                LifeSteal=20,
                StatOmnivamp=0.2,
            ),
        )
        original = deepcopy(row)
        c, p = content(), players()
        c["items"]["BT"] = compile_item(row, load_bindings(PACK)["items"])
        p[0].units[0].items = ["BT"]
        b = Battle(p, c)
        a, z = b.units
        assert b.get(a, "ad") == pytest.approx(23.6)
        assert b.get(a, "ap") == 118
        a.hp = 49
        b.hook("health_below", a, z)
        assert len(a.shields) == 1 and a.shields[0].amount == 30
        b.hook("health_below", a, z)
        assert len(a.shields) == 1
        assert row == original
