from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_legacy_validation_report_calibrates_probability_only(tmp_path):
    trainer = Path(__file__).resolve().parents[1]
    script = trainer / "scripts" / "calibrate_unit_head_runtime_gates.py"

    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "variants": {
            "dino": {
                "evaluation": {
                    "validation": {
                        "predictions": [
                            {
                                "label": "A",
                                "predicted": "A",
                                "softmax_score_uncalibrated": 0.90,
                            },
                            {
                                "label": "B",
                                "predicted": "B",
                                "softmax_score_uncalibrated": 0.80,
                            },
                            {
                                "label": "A",
                                "predicted": "B",
                                "softmax_score_uncalibrated": 0.70,
                            },
                        ]
                    }
                }
            }
        }
    }))

    output = tmp_path / "gates.json"
    subprocess.run([
        sys.executable,
        str(script),
        "--report", str(report),
        "--output", str(output),
    ], check=True)

    gates = json.loads(output.read_text())
    assert gates["runtime_gate_eligible"] is True
    assert gates["legacy_probability_only"] is True
    assert gates["margin_available"] is False
    assert gates["min_margin"] == 0.0
    assert gates["wrong_accepted"] == 0
    assert gates["accepted_named_correct"] == 2
    assert gates["min_probability"] == 0.8
