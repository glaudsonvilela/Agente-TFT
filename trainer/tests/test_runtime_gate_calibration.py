from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "calibrate_unit_head_runtime_gates.py"


def _run(tmp_path: Path, predictions: list[dict]):
    report = tmp_path / "report.json"
    output = tmp_path / "gates.json"
    report.write_text(json.dumps({
        "variants": {
            "dino": {
                "evaluation": {
                    "validation": {
                        "predictions": predictions,
                    }
                }
            }
        }
    }))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--report", str(report), "--output", str(output)],
        text=True,
        capture_output=True,
    )
    return result, (json.loads(output.read_text()) if output.is_file() else None)


def test_legacy_validation_without_margin_calibrates_zero_error_gate(tmp_path):
    result, gates = _run(tmp_path, [
        {"label":"a","predicted":"a","softmax_score_uncalibrated":0.90},
        {"label":"b","predicted":"b","softmax_score_uncalibrated":0.80},
        {"label":"c","predicted":"x","softmax_score_uncalibrated":0.40},
        {"label":"__unknown__","predicted":"a","softmax_score_uncalibrated":0.30},
    ])
    assert result.returncode == 0, result.stderr
    assert gates["legacy_probability_only"] is True
    assert gates["margin_available"] is False
    assert gates["wrong_accepted"] == 0
    assert gates["accepted_unknown"] == 0
    assert gates["accepted_named_correct"] == 2
    assert gates["runtime_gate_eligible"] is True
    assert gates["min_margin"] == 0.0
    assert gates["min_probability"] > 0.40


def test_margin_aware_validation_keeps_margin_gate(tmp_path):
    result, gates = _run(tmp_path, [
        {"label":"a","predicted":"a","softmax_score_uncalibrated":0.90,
         "softmax_margin_uncalibrated":0.30},
        {"label":"b","predicted":"b","softmax_score_uncalibrated":0.80,
         "softmax_margin_uncalibrated":0.20},
        {"label":"c","predicted":"x","softmax_score_uncalibrated":0.85,
         "softmax_margin_uncalibrated":0.05},
    ])
    assert result.returncode == 0, result.stderr
    assert gates["legacy_probability_only"] is False
    assert gates["margin_available"] is True
    assert gates["wrong_accepted"] == 0
    assert gates["accepted_named_correct"] == 2
    assert gates["min_margin"] > 0.05


def test_mixed_legacy_and_margin_rows_fail_closed(tmp_path):
    result, gates = _run(tmp_path, [
        {"label":"a","predicted":"a","softmax_score_uncalibrated":0.90},
        {"label":"b","predicted":"b","softmax_score_uncalibrated":0.80,
         "softmax_margin_uncalibrated":0.20},
    ])
    assert result.returncode != 0
    assert gates is None
    assert "mixes legacy and margin-aware" in result.stderr
