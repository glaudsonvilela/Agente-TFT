import unittest

from training.audit_full_simulator_18_4b import audit


class FullSimulatorAuditTest(unittest.TestCase):
    def test_real_patch_is_blocked_with_individual_missing_bindings(self):
        report = audit()
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["training_allowed"])
        self.assertEqual(report["known_catalog_entries"]["champions"], 91)
        self.assertEqual(report["known_catalog_entries"]["traits"], 36)
        self.assertEqual(report["known_catalog_entries"]["effects"], 1444)
        self.assertEqual(report["known_official_patch_changes"]["official_mid_patch_changes"], 32)
        blockers = {(item["kind"], item["id"]) for item in report["blockers"]}
        self.assertIn(("executor", "18.4B"), blockers)
        self.assertIn(("lineage", "18.1→18.4B"), blockers)
        self.assertIn(("match_system", "wisp_offers_eligibility_and_effects"), blockers)
        self.assertIn(("champions", "DA_18_Ahri"), blockers)
        self.assertIn(("readiness", "wisps"), blockers)
        self.assertIn(("ability_text", "DA_18_Ahri"), blockers)


if __name__ == "__main__":
    unittest.main()
