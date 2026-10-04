"""Supervised and DPO objectives for a small, masked action policy.

The objectives are used in language-model training, but here an output is an
explicit game action. This module does not invent demonstrations or reward
labels, read private game state, or authorize an incomplete simulator for use.
"""

from copy import deepcopy
import math

import torch
from torch import nn
from torch.nn import functional as F


class ActionPolicy(nn.Module):
    """Score each candidate's supplied observable state/action features."""

    def __init__(self, features, hidden=64):
        super().__init__()
        if (
            type(features) is not int
            or features < 1
            or type(hidden) is not int
            or not 1 <= hidden <= 512
        ):
            raise ValueError("invalid action policy dimensions")
        self.layers = nn.Sequential(
            nn.Linear(features, hidden), nn.Tanh(), nn.Linear(hidden, 1)
        )

    def forward(self, features):
        if (
            features.ndim != 3
            or features.shape[2] != self.layers[0].in_features
            or not torch.isfinite(features).all()
        ):
            raise ValueError("expected finite [states, candidates, features]")
        return self.layers(features).squeeze(-1)


def masked_log_probabilities(logits, legal):
    if (
        logits.ndim != 2
        or legal.shape != logits.shape
        or legal.dtype != torch.bool
        or logits.device != legal.device
        or logits.shape[0] == 0
        or not torch.isfinite(logits).all()
        or not legal.any(dim=1).all()
    ):
        raise ValueError(
            "every state requires finite scores and at least one legal candidate"
        )
    return F.log_softmax(logits.masked_fill(~legal, -torch.inf), dim=-1)


def validate_targets(targets, legal):
    if (
        targets.shape != (legal.shape[0],)
        or targets.dtype != torch.long
        or targets.device != legal.device
        or (targets < 0).any()
        or (targets >= legal.shape[1]).any()
    ):
        raise ValueError("invalid action label")
    rows = torch.arange(legal.shape[0], device=legal.device)
    if not legal[rows, targets].all():
        raise ValueError("labeled action is illegal or padded")
    return rows


def supervised_action_loss(logits, demonstrated, legal):
    logp = masked_log_probabilities(logits, legal)
    rows = validate_targets(demonstrated, legal)
    return -logp[rows, demonstrated].mean()


def preference_loss(logits, reference_logits, preferred, rejected, legal, *, beta=0.1):
    """DPO Eq. 7: -log sigmoid(beta * (policy log-ratio - reference log-ratio)).

    Both actions belong to the same observed decision and legal candidate set.
    The reference is fixed; no gradient can enter it through this objective.
    """
    if type(beta) not in (float, int) or not math.isfinite(beta) or beta <= 0:
        raise ValueError("beta must be finite and positive")
    if reference_logits.shape != logits.shape:
        raise ValueError("policy/reference candidate sets differ")
    policy = masked_log_probabilities(logits, legal)
    reference = masked_log_probabilities(reference_logits.detach(), legal)
    rows = validate_targets(preferred, legal)
    validate_targets(rejected, legal)
    if (preferred == rejected).any():
        raise ValueError("ties cannot be preference labels")
    margin = beta * (
        (policy[rows, preferred] - policy[rows, rejected])
        - (reference[rows, preferred] - reference[rows, rejected])
    )
    return -F.logsigmoid(margin).mean(), margin.detach()


def frozen_reference(policy):
    reference = deepcopy(policy).eval()
    for parameter in reference.parameters():
        parameter.requires_grad_(False)
    return reference


def validate_partition(records, *, patch, content_sha256, engine_sha256):
    """Audit declared training rows before tensorization, preserving provenance.

    Complete examples must be independently reviewed; narration alone, model
    suggestions and partial screen readings cannot become action preferences.
    Split membership is checked by source, match and observation fingerprint.
    """
    groups = {}
    if not records:
        raise ValueError("no reviewed decision examples")
    for row in records:
        if any(
            row.get(k) != v
            for k, v in (
                ("patch", patch),
                ("content_sha256", content_sha256),
                ("engine_sha256", engine_sha256),
            )
        ):
            raise ValueError("decision data patch/content/engine identity mismatch")
        if (
            row.get("split") not in ("train", "validation", "test")
            or row.get("state_coverage") != "complete_observable_state"
        ):
            raise ValueError(
                "decision needs an explicit split and complete observable state"
            )
        provenance = row.get("label_provenance", {})
        if provenance.get("kind") not in (
            "reviewed_demonstration",
            "reviewed_preference",
            "paired_validated_rollouts",
        ) or not provenance.get("evidence_id"):
            raise ValueError("unsupported or unreviewed decision label")
        if provenance["kind"] == "paired_validated_rollouts" and (
            not provenance.get("validation_report_sha256")
            or not provenance.get("paired_seeds")
        ):
            raise ValueError(
                "simulated preferences require validation and paired seeds"
            )
        if provenance["kind"] == "paired_validated_rollouts" and provenance.get(
            "tie", False
        ):
            raise ValueError("tied rollouts do not establish preference")
        for key in ("source_sha256", "match_id", "observation_sha256"):
            value = row.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError("decision identity missing")
            group = (key, value)
            if group in groups and groups[group] != row["split"]:
                raise ValueError(
                    "decision source/match/observation leaks across splits"
                )
            groups[group] = row["split"]
    if not {"train", "validation"} <= {row["split"] for row in records}:
        raise ValueError("independent train and validation partitions required")
    return {
        "rows": len(records),
        "splits": {
            split: sum(row["split"] == split for row in records)
            for split in ("train", "validation", "test")
        },
        "runtime_promoted": False,
        "real_tft_improvement_proven": False,
    }
