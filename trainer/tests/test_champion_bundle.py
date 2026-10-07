from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_runtime_champion_bundle_contains_l3_and_unit_head(tmp_path):
    trainer = Path(__file__).resolve().parents[1]
    script = trainer / "scripts" / "build_champion_bundle.py"

    l3_onnx = tmp_path / "candidate-model.onnx"
    l3_bytes = b"fake-l3"
    l3_onnx.write_bytes(l3_bytes)
    l3_meta = tmp_path / "deployment-candidate.json"
    l3_meta.write_text(json.dumps({
        "schema_version": 2,
        "coordinate_format": "normalized_tlbr",
        "sha256": _sha(l3_bytes),
        "validated": True,
        "activation_allowed": False,
    }))

    encoder = tmp_path / "encoder.onnx"
    encoder_bytes = b"fake-dino"
    encoder.write_bytes(encoder_bytes)
    head = tmp_path / "dino-head.json"
    head.write_text(json.dumps({
        "schema_version": 1,
        "feature_mode": "dino",
        "crop_transform": "upper_88x80_v1",
        "encoder_sha256": _sha(encoder_bytes),
    }))

    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({
        "set_key": "TFTSet18",
        "reference_sha256": "a" * 64,
    }))

    output = tmp_path / "g1.zip"
    publish = tmp_path / "g1.publish.json"
    subprocess.run([
        sys.executable,
        str(script),
        "--version", "g000001-bootstrap",
        "--generation", "1",
        "--runtime-min-version", "0.7.0",
        "--l3-metadata", str(l3_meta),
        "--l3-onnx", str(l3_onnx),
        "--unit-head", str(head),
        "--unit-encoder", str(encoder),
        "--unit-reference", str(reference),
        "--unit-set-key", "TFTSet18",
        "--unit-min-probability", "0.5",
        "--unit-min-margin", "0.1",
        "--output", str(output),
        "--publish-request", str(publish),
        "--channel", "stable",
    ], check=True)

    with zipfile.ZipFile(output) as archive:
        package = json.loads(archive.read("model-package.json"))
        roles = {row["role"] for row in package["files"]}
        assert {
            "l3_metadata",
            "l3_onnx",
            "unit_head_json",
            "unit_encoder_onnx",
            "unit_head_plan",
        } <= roles
        plan = json.loads(archive.read("configs/catalog/active-unit-head-v1.json"))
        assert plan["set_key"] == "TFTSet18"
        assert plan["min_probability"] == 0.5
        assert plan["min_margin"] == 0.1

    request = json.loads(publish.read_text())
    assert request["generation"] == 1
    assert request["channel"] == "stable"
    assert request["model_identity_sha256"] == _sha(l3_bytes)
