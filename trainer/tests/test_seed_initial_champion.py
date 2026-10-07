from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_seed_initial_champion_publishes_stable_g1_with_unit_head(tmp_path):
    trainer = Path(__file__).resolve().parents[1]
    repo = trainer.parent
    script = trainer / "scripts" / "seed_initial_champion.py"

    seed = tmp_path / "runtime-seed"
    learner = tmp_path / "learner"
    data = tmp_path / "data"

    l3_bytes = b"seed-l3"
    (seed / "models").mkdir(parents=True)
    (seed / "models" / "candidate-model.onnx").write_bytes(l3_bytes)
    (seed / "models" / "deployment-candidate.json").write_text(json.dumps({
        "schema_version": 2,
        "coordinate_format": "normalized_tlbr",
        "sha256": _sha(l3_bytes),
        "validated": True,
        "activation_allowed": False,
    }))

    encoder_bytes = b"seed-dino"
    (learner / "model").mkdir(parents=True)
    (learner / "encoder").mkdir(parents=True)
    (learner / "reference").mkdir(parents=True)
    (learner / "encoder" / "dino.onnx").write_bytes(encoder_bytes)
    (learner / "model" / "dino-head.json").write_text(json.dumps({
        "schema_version": 1,
        "feature_mode": "dino",
        "crop_transform": "upper_88x80_v1",
        "encoder_sha256": _sha(encoder_bytes),
    }))
    (learner / "model" / "runtime-gates.json").write_text(json.dumps({
        "schema_version": 1,
        "policy": "validation_zero_error_max_coverage_v1",
        "runtime_gate_eligible": True,
        "min_probability": 0.55,
        "min_margin": 0.08,
    }))
    (learner / "reference" / "reference.json").write_text(json.dumps({
        "set_key": "TFTSet18",
        "reference_sha256": "b" * 64,
    }))

    subprocess.run([
        sys.executable,
        str(script),
        "--data-root", str(data),
        "--repo", str(repo),
        "--seed-root", str(seed),
        "--learner-root", str(learner),
    ], check=True)

    manifest = json.loads(
        (data / "champions" / "stable" / "manifest.json").read_text()
    )
    assert manifest["generation"] == 1
    assert manifest["approved"] is True
    assert manifest["version"] == "g000001-bootstrap"

    package = (
        data / "champions" / "stable" / "versions"
        / "000000000001-g000001-bootstrap.zip"
    )
    assert package.is_file()
    with zipfile.ZipFile(package) as archive:
        internal = json.loads(archive.read("model-package.json"))
        roles = {row["role"] for row in internal["files"]}
        assert {
            "l3_metadata",
            "l3_onnx",
            "unit_head_json",
            "unit_encoder_onnx",
            "unit_head_plan",
        } <= roles
        plan = json.loads(archive.read("configs/catalog/active-unit-head-v1.json"))
        assert plan["min_probability"] == 0.55
        assert plan["min_margin"] == 0.08
