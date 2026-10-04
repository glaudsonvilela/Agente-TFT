"""Numerical pipeline checks on synthetic labels, not evidence of TFT skill."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import torch

from training.decision_lab import prepare, fit


class DecisionLab(unittest.TestCase):
    def document(self, root):
        evidence = root / "synthetic-review.json"
        evidence.write_text('{"test_fixture":true}')
        records = []
        for split in ("train", "validation", "test"):
            for mode in ("sft", "dpo"):
                for index in range(4):
                    identity = f"{split}-{mode}-{index}"
                    records.append(
                        dict(
                            patch="fixture",
                            content_sha256="content",
                            engine_sha256="engine",
                            split=split,
                            mode=mode,
                            state_coverage="complete_observable_state",
                            source_sha256=identity,
                            match_id=identity,
                            observation_sha256=identity,
                            label_provenance=dict(
                                kind=(
                                    "reviewed_demonstration"
                                    if mode == "sft"
                                    else "reviewed_preference"
                                ),
                                evidence_id="test-fixture",
                            ),
                            candidates=[
                                dict(
                                    id="good", features=[1.0, index * 0.01], legal=True
                                ),
                                dict(
                                    id="bad", features=[0.0, index * 0.01], legal=True
                                ),
                                dict(id="invalid", features=[100.0, 0.0], legal=False),
                            ],
                            chosen=0,
                            rejected=1,
                        )
                    )
        return dict(
            schema_version=1,
            kind="reviewed_action_features",
            feature_names=["fixture-signal", "fixture-context"],
            records=records,
            evidence_registry={
                "test-fixture": dict(
                    path=evidence.name,
                    sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
                )
            },
        )

    def prepare(self, d, root):
        return prepare(
            d,
            patch="fixture",
            content_sha256="content",
            engine_sha256="engine",
            evidence_root=root,
        )

    def test_sft_then_dpo_updates_policy_without_changing_reference_or_rng(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tensors, audit = self.prepare(self.document(root), root)
            state = torch.random.get_rng_state().clone()
            model, report = fit(
                tensors,
                2,
                seed=11,
                sft_epochs=12,
                dpo_epochs=12,
                learning_rate=0.01,
                beta=0.5,
            )
            self.assertTrue(torch.equal(state, torch.random.get_rng_state()))
            self.assertTrue(report["reference_unchanged"])
            self.assertLess(
                report["after_sft"]["validation/sft"]["chosen_nll"],
                report["initial"]["validation/sft"]["chosen_nll"],
            )
            self.assertGreater(
                report["after_dpo"]["validation/dpo"]["mean_preference_margin"],
                report["after_sft"]["validation/dpo"]["mean_preference_margin"],
            )
            self.assertFalse(audit["real_tft_improvement_proven"])
            self.assertEqual(report["objectives"]["sft"]["optimizer_steps"], 12)
            self.assertEqual(report["objectives"]["dpo"]["optimizer_steps"], 12)

    def test_evidence_changes_and_illegal_labels_cannot_enter_training(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            doc = self.document(root)
            bad = deepcopy(doc)
            bad["evidence_registry"]["test-fixture"]["sha256"] = "changed"
            with self.assertRaisesRegex(ValueError, "checksum"):
                self.prepare(bad, root)
            bad = deepcopy(doc)
            bad["records"][0]["chosen"] = 2
            with self.assertRaisesRegex(ValueError, "legal"):
                self.prepare(bad, root)
            bad = deepcopy(doc)
            bad["records"][0]["mode"] = "other"
            with self.assertRaisesRegex(ValueError, "objective"):
                self.prepare(bad, root)
            bad = deepcopy(doc)
            bad["records"][0]["label_provenance"]["kind"] = "reviewed_preference"
            with self.assertRaisesRegex(ValueError, "demonstration"):
                self.prepare(bad, root)
            bad = deepcopy(doc)
            bad["records"] = [
                r
                for r in bad["records"]
                if (r["split"], r["mode"]) != ("validation", "dpo")
            ]
            with self.assertRaisesRegex(ValueError, "validation"):
                self.prepare(bad, root)


if __name__ == "__main__":
    unittest.main()
