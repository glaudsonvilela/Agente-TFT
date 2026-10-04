from copy import deepcopy
import math
import unittest

import torch

from training.decision_objectives import (
    ActionPolicy,
    frozen_reference,
    masked_log_probabilities,
    supervised_action_loss,
    preference_loss,
    validate_partition,
)


class DecisionObjectives(unittest.TestCase):
    def test_masked_actions_have_zero_probability_and_no_gradient(self):
        logits = torch.tensor([[0.0, 1000.0, 1.0]], requires_grad=True)
        legal = torch.tensor([[True, False, True]])
        loss = supervised_action_loss(logits, torch.tensor([2]), legal)
        loss.backward()
        self.assertEqual(logits.grad[0, 1], 0)
        self.assertEqual(masked_log_probabilities(logits, legal).exp()[0, 1], 0)
        with self.assertRaisesRegex(ValueError, "illegal"):
            supervised_action_loss(logits, torch.tensor([1]), legal)
        with self.assertRaises(ValueError):
            masked_log_probabilities(logits, torch.zeros_like(legal))

    def test_dpo_matches_closed_form_and_keeps_reference_fixed(self):
        policy = torch.tensor([[1.0, 0.0]], requires_grad=True)
        reference = torch.tensor([[0.5, 0.0]], requires_grad=True)
        legal = torch.ones_like(policy, dtype=torch.bool)
        loss, margin = preference_loss(
            policy, reference, torch.tensor([0]), torch.tensor([1]), legal, beta=2.0
        )
        self.assertAlmostEqual(margin.item(), 1, places=6)
        self.assertAlmostEqual(loss.item(), math.log1p(math.exp(-1)), places=6)
        loss.backward()
        self.assertIsNone(reference.grad)
        self.assertLess(policy.grad[0, 0], 0)
        self.assertGreater(policy.grad[0, 1], 0)

    def test_preference_training_changes_weights_and_improves_held_out_pairs(self):
        torch.manual_seed(19)
        policy = ActionPolicy(2, 16)
        ref = frozen_reference(policy)
        train = torch.tensor([[[1.0, v], [0.0, v]] for v in (0.0, 0.2, 0.4, 0.6)])
        validation = torch.tensor([[[1.0, v], [0.0, v]] for v in (0.1, 0.3, 0.5)])
        legal = torch.ones((4, 2), dtype=torch.bool)
        chosen = torch.zeros(4, dtype=torch.long)
        rejected = torch.ones(4, dtype=torch.long)
        original = {k: v.clone() for k, v in policy.state_dict().items()}
        ref_before = {k: v.clone() for k, v in ref.state_dict().items()}
        with torch.no_grad():
            initial = (
                (policy(validation)[:, 0] - policy(validation)[:, 1]).mean().item()
            )
        optimizer = torch.optim.Adam(policy.parameters(), lr=0.01)
        for _ in range(30):
            optimizer.zero_grad()
            loss, _ = preference_loss(
                policy(train), ref(train), chosen, rejected, legal, beta=0.5
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 1)
            optimizer.step()
        with torch.no_grad():
            final = (policy(validation)[:, 0] - policy(validation)[:, 1]).mean().item()
        self.assertGreater(final, initial + 1)
        self.assertTrue(
            any(not torch.equal(original[k], v) for k, v in policy.state_dict().items())
        )
        self.assertTrue(
            all(torch.equal(ref_before[k], v) for k, v in ref.state_dict().items())
        )

    def rows(self):
        return [
            dict(
                patch="candidate",
                content_sha256="content",
                engine_sha256="engine",
                split=split,
                state_coverage="complete_observable_state",
                source_sha256="source-" + split,
                match_id="match-" + split,
                observation_sha256="pixels-" + split,
                label_provenance=dict(
                    kind="reviewed_preference", evidence_id="review-" + split
                ),
            )
            for split in ("train", "validation")
        ]

    def audit(self, rows):
        return validate_partition(
            rows, patch="candidate", content_sha256="content", engine_sha256="engine"
        )

    def test_provenance_rejects_narration_partial_state_and_split_leakage(self):
        self.assertEqual(self.audit(self.rows())["rows"], 2)
        for key in ("source_sha256", "match_id", "observation_sha256"):
            rows = self.rows()
            rows[1][key] = rows[0][key]
            with self.assertRaisesRegex(ValueError, "leaks"):
                self.audit(rows)
        rows = self.rows()
        rows[0]["state_coverage"] = "partial_screen"
        with self.assertRaisesRegex(ValueError, "observable"):
            self.audit(rows)
        rows = self.rows()
        rows[0]["label_provenance"]["kind"] = "model_suggestion"
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            self.audit(rows)
        rows = self.rows()
        rows[0]["engine_sha256"] = "older-simulator"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.audit(rows)

    def test_ties_and_unvalidated_simulations_are_not_preferences(self):
        logits = torch.zeros((1, 2))
        legal = torch.ones_like(logits, dtype=torch.bool)
        with self.assertRaisesRegex(ValueError, "ties"):
            preference_loss(logits, logits, torch.tensor([0]), torch.tensor([0]), legal)
        rows = self.rows()
        rows[0]["label_provenance"] = {
            "kind": "paired_validated_rollouts",
            "evidence_id": "batch",
        }
        with self.assertRaisesRegex(ValueError, "paired seeds"):
            self.audit(rows)


if __name__ == "__main__":
    unittest.main()
