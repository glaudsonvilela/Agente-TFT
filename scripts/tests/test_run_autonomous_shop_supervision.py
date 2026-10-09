import json
import subprocess
import sys
from pathlib import Path

from run_autonomous_shop_supervision import valid_dense


def test_dense_source_url_must_match(tmp_path: Path):
    report = {
        "status": "complete",
        "collection_mode": "annotation_only",
        "review_interval_seconds": 2,
        "sample_interval_seconds": 2,
        "training_performed": False,
        "inference_performed": False,
        "source_id": "youtube:other",
        "source_url": "https://www.youtube.com/watch?v=old",
    }
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    assert valid_dense(tmp_path, "youtube:other", report["source_url"]) == report
    assert valid_dense(tmp_path, "youtube:other", "https://www.youtube.com/watch?v=other") is None


def test_custom_source_requires_matching_url():
    script = Path(__file__).resolve().parents[1] / "run_autonomous_shop_supervision.py"
    result = subprocess.run(
        [sys.executable, str(script), "--source-id", "youtube:other"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "custom source ID requires its matching --source-url" in result.stderr
