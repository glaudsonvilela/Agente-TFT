"""The trainer must preserve independent game evidence and the weight cap."""

import importlib.util
import sys
from pathlib import Path

import pytest


def load_module():
    source = Path(__file__).resolve().parents[1] / "train_weighted_autonomous_challenger.py"
    spec = importlib.util.spec_from_file_location("weighted_challenger", source)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(source.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_mixed_teacher_gold_requires_strict_direct_evidence():
    module = load_module()
    row = {
        "decision": "direct_gold_teacher_mixed",
        "label_source": "autonomous_tooltip_temporal_consensus_v1",
        "training_eligible": True,
        "partition": "training_pool_unlabeled",
        "human_review_required": False,
        "model_prediction_used_as_label": False,
        "recommended_training_weight": 0.5,
        "teachers": {
            "frozen_classifier": {"agrees_with_gold": False},
            "supervised_retrieval": {"agrees_with_gold": True},
        },
        "evidence": {
            "exact_catalog_name_ocr": True,
            "ocr_name_confidence": 96.0,
            "temporal_confirmations": 2,
            "selected_unit_association": {
                "association_pass": True,
                "selected_ring": {"shape_pass": True},
            },
        },
    }
    module.assert_gold([row])
    row["evidence"]["temporal_confirmations"] = 1
    with pytest.raises(SystemExit):
        module.assert_gold([row])
    row["evidence"]["temporal_confirmations"] = 2
    row["teachers"]["supervised_retrieval"]["agrees_with_gold"] = False
    with pytest.raises(SystemExit):
        module.assert_gold([row])
    row["teachers"]["supervised_retrieval"]["agrees_with_gold"] = True
    row["partition"] = "evaluation_unlabeled"
    with pytest.raises(SystemExit):
        module.assert_gold([row])
