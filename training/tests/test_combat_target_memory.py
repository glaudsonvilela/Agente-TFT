"""Regression for the Set 18 rule that CC does not erase a valid target."""

import unittest

from trainer.simulation.event_combat import Battle
from trainer.simulation.state import Unit, UnsupportedRule
from training.tests.test_event_combat import content, players


class TargetMemoryTests(unittest.TestCase):
    def battle(self, policy="retain_until_invalid"):
        rules = content()
        rules["combat_rules"].update(
            targeting_policy=policy, duration=1, first_action_seconds=0
        )
        rules["champions"]["fixture"]["combat"].update(
            hp=[10000] * 3, ad=[1] * 3, range=10
        )
        teams = players()
        teams[1].units.append(Unit("c", "fixture", zone="board", position=(1, 3)))
        battle = Battle(teams, rules, seed=7, trace=True)
        attacker, original, closer = battle.units
        attacker.position, original.position, closer.position = (3, 3), (4, 3), (6, 3)
        return battle, attacker, original, closer

    def test_cc_then_nearer_enemy_does_not_reset_original_target(self):
        battle, attacker, original, closer = self.battle()
        self.assertIs(battle.acquire_target(attacker, [original, closer]), original)
        battle.effects(
            original, attacker, [dict(op="status", name="stun", duration=0.5)]
        )
        original.position, closer.position = (6, 3), (3, 4)
        battle.run()
        attacks = [
            event
            for event in battle.history
            if event["kind"] == "damage"
            and event["source"] == attacker.uid
            and event["tag"] == "attack"
        ]
        self.assertTrue(attacks)
        self.assertTrue(all(event["target"] == original.uid for event in attacks))

    def test_dead_or_untargetable_enemy_is_replaced(self):
        for invalid in ("dead", "untargetable"):
            with self.subTest(invalid=invalid):
                battle, attacker, original, replacement = self.battle()
                battle.acquire_target(attacker, [original, replacement])
                if invalid == "dead":
                    original.hp = 0
                else:
                    original.statuses["untargetable"] = [10]
                eligible = [
                    unit for unit in (original, replacement) if battle.targetable(unit)
                ]
                self.assertIs(battle.acquire_target(attacker, eligible), replacement)

    def test_legacy_profile_remains_explicitly_reproducible(self):
        battle, attacker, original, closer = self.battle("nearest_each_action")
        battle.acquire_target(attacker, [original, closer])
        original.position, closer.position = (6, 3), (3, 4)
        self.assertIs(battle.acquire_target(attacker, [original, closer]), closer)

    def test_unknown_policy_cannot_silently_fall_back(self):
        with self.assertRaisesRegex(UnsupportedRule, "target retention"):
            self.battle("unknown")


if __name__ == "__main__":
    unittest.main()
