"""Interaction regressions for health branches, critical mana and stacking."""

import unittest

import pytest

from ingestion.simulation_bindings import load_bindings
from trainer.simulation.event_combat import Battle
from trainer.simulation.modifiers import Stats, formula
from trainer.simulation.state import UnsupportedRule
from training.compile_effects import compile_item
from training.tests.test_event_combat import content, players
from training.tests.test_seasonal_rules import PACK


def battle_with(name, fields, copies=1):
    c, p = content(), players()
    c["items"][name] = compile_item(
        dict(api_name="TFT_Item_" + name, name=name, effects=fields, unique=False),
        load_bindings(PACK)["items"],
    )
    p[0].units[0].items = [name] * copies
    return Battle(p, c, seed=2, trace=True)


class ItemConditionals(unittest.TestCase):
    def test_health_durability_changes_on_damage_and_healing(self):
        b = battle_with(
            "NightHarvester",
            dict(
                Armor=0,
                Health=0,
                CritChance=0,
                BaseDurability=0.05,
                EmpoweredDurability=0.15,
                ThresholdForEmpower=0.5,
            ),
        )
        a, z = b.units
        assert b.hit(z, a, 20, "physical", "attack") == 17
        a.hp = 50
        assert b.get(a, "durability") == 0.05
        b.heal(a, a, 1)
        assert b.get(a, "durability") == 0.15
        a.hp = 49
        assert b.get(a, "durability") == 0.05

    def test_hand_of_justice_branches_apply_to_actual_damage_and_healing(self):
        b = battle_with(
            "UnstableConcoction",
            dict(
                AD_NotStatBar=0.15,
                AP_NotStatBar=15,
                StatOmnivamp_NotStatBar=0.12,
                HealthThreshold=0.5,
                CritChance=0,
                ManaRegen=0,
                **{"{f23e83fc}": 2}
            ),
        )
        a, z = b.units
        assert b.get(a, "ad") == pytest.approx(27.2)
        assert b.get(a, "ap") == 136
        assert b.get(a, "omnivamp") == 0.15
        a.hp = 50
        assert b.get(a, "ad") == pytest.approx(23.6)
        assert b.get(a, "omnivamp") == 0.15
        a.hp = 40
        assert b.get(a, "omnivamp") == 0.3
        assert formula([{"stat": "ap", "coefficient": 1}], a, z, b.now) == 118
        b.hit(a, z, 20, "physical", "attack")
        assert a.hp == pytest.approx(46)
        b.heal(a, a, 10)
        assert b.get(a, "ad") == pytest.approx(27.2)
        assert b.get(a, "omnivamp") == 0.15

    def test_nashor_critical_bonus_replaces_normal_bonus_and_duplicates_are_independent(
        self,
    ):
        b = battle_with(
            "Leviathan",
            dict(AP=0, AS=0, CritChance=0, Health=0, BaseManaOnHit=2, ManaOnCrit=4),
            copies=2,
        )
        a, z = b.units
        b.hook("attack", a, z, {"critical": False})
        assert a.mana == 4
        b.hook("attack", a, z, {"critical": True})
        assert a.mana == 12
        # An unknown critical outcome must not silently choose either branch.
        b.hook("attack", a, z)
        assert a.mana == 12
        a.mana_lock_until = 1
        b.hook("attack", a, z, {"critical": True})
        assert a.mana == 12

    def test_kraken_stacks_stop_at_cap_with_one_capstone_per_copy(self):
        b = battle_with(
            "RunaansHurricane",
            dict(
                AD=0.1,
                AS=0.1,
                MagicResist=20,
                ADOnAttack=0.035,
                MaxStacks=15,
                ASCapstone=0.15,
            ),
            copies=2,
        )
        a, z = b.units
        for _ in range(100):
            b.hook("attack", a, z)
        assert b.get(a, "ad") == pytest.approx(20 * (1 + 0.2 + 2 * 15 * 0.035))
        assert b.get(a, "attack_speed") == pytest.approx(1 + 0.002 + 0.3)

    def test_blue_buff_amplifies_later_bonuses_and_void_staff_refreshes_without_stacking(
        self,
    ):
        b = battle_with("BlueBuff", dict(AD=0.15, AP=15, ManaRegen=5, ModifiedADAP=0.1))
        a, z = b.units
        b.change_stat(a, "ap", 10, "flat", "later")
        assert b.get(a, "ap") == pytest.approx(137.5)
        assert b.get(a, "ad") == pytest.approx(25.3)
        b = battle_with(
            "StatikkShiv",
            dict(AP=35, AS=15, ManaRegen=1, MRShred=30, MRShredDuration=5),
        )
        a, z = b.units
        z.values.base["mr"] = 100
        b.hook("damage_dealt", a, z, {"tag": "proc"})
        assert b.get(z, "shred") == 0
        b.hook("damage_dealt", a, z, {"tag": "attack"})
        b.now = 4
        b.hook("damage_dealt", a, z, {"tag": "spell"})
        b.now = 5
        assert b.get(z, "shred") == 0.3
        assert b.hit(a, z, 17, "magic", "proc") == pytest.approx(10)
        b.now = 9
        assert b.get(z, "shred") == 0

    def test_filtered_hits_do_not_advance_trigger_cadence(self):
        c = content()
        c["champions"]["fixture"]["hooks"] = [
            dict(
                event="damage_dealt",
                damage_tag="spell",
                critical=True,
                every=2,
                effects=[
                    dict(
                        op="mana", target={"kind": "self"}, amount=[{"coefficient": 3}]
                    )
                ],
            )
        ]
        b = Battle(players(), c)
        a, z = b.units
        b.hook("damage_dealt", a, z, {"tag": "spell", "critical": True})
        b.hook("damage_dealt", a, z, {"tag": "attack", "critical": True})
        b.hook("damage_dealt", a, z, {"tag": "spell", "critical": False})
        assert a.mana == 0
        b.hook("damage_dealt", a, z, {"tag": "spell", "critical": True})
        assert a.mana == 3

    def test_invalid_health_condition_is_rejected(self):
        for condition in (
            {"hp_above": float("nan")},
            {"hp_above": True},
            {"hp_below": 1.1},
            {"typo": 0.5},
            {},
        ):
            with self.subTest(condition=condition), pytest.raises(UnsupportedRule):
                Stats({"ad": 20}).add("bad", "ad", 2, when=condition)

    def test_conditional_health_cannot_create_recursive_resource_lookup(self):
        with pytest.raises(UnsupportedRule):
            Stats({"hp": 100}).add("bad", "hp", 20, when={"hp_above": 0.5})

    def test_formula_preserves_damage_context_across_stat_terms(self):
        b = Battle(players(), content())
        a, z = b.units
        terms = [
            {"stat": "ap", "coefficient": 0.1},
            {"context": "damage", "coefficient": 0.2},
        ]
        assert formula(terms, a, z, 0, {"damage": 50}) == 20
