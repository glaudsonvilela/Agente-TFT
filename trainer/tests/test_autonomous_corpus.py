from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "trainer/scripts/ingest_autonomous_corpus.py"


def crop(path: Path, value: tuple[int, int, int]) -> str:
    image = Image.new("RGB", (128, 144), value)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return hashlib.sha256(image.tobytes()).hexdigest()


def gold(source: str, pixel: str, relative: str, unit: str = "DA_18_Ahri"):
    return {
        "source_id": source,
        "source_seconds_nominal": 10,
        "crop": relative,
        "pixel_sha256": pixel,
        "unit_id": unit,
        "decision": "supported",
        "label_source": "autonomous_shop_purchase_bench_consensus_v1",
        "training_eligible": True,
        "human_review_required": False,
        "model_prediction_used_as_label": False,
    }


def silver(source: str, pixel: str, relative: str, unit: str = "DA_18_Ahri", weight: float = 0.2):
    return {
        "source_id": source,
        "source_seconds_nominal": 12,
        "crop": relative,
        "pixel_sha256": pixel,
        "unit_id": unit,
        "supervision_tier": "silver_auto",
        "label_source": "silver_auto_shop_multiteacher_temporal_v1",
        "recommended_training_weight": weight,
        "training_eligible": True,
        "human_review_required": False,
    }


def run(manifest: Path, collection: Path, gold_path: Path, silver_path: Path, source: str):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest", str(manifest),
            "--collection", str(collection),
            "--gold", str(gold_path),
            "--silver", str(silver_path),
            "--source-id", source,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def write_labels(root: Path, source: str, color: tuple[int, int, int], *, weight: float = 0.2):
    collection = root / source.replace(":", "_")
    g_rel = "crops/gold.png"
    s_rel = "crops/silver.png"
    g_pixel = crop(collection / g_rel, color)
    s_color = tuple((v + 17) % 255 for v in color)
    s_pixel = crop(collection / s_rel, s_color)
    gold_path = root / f"{source.replace(':', '_')}-gold.json"
    silver_path = root / f"{source.replace(':', '_')}-silver.json"
    gold_path.write_text(json.dumps([gold(source, g_pixel, g_rel)]))
    silver_path.write_text(json.dumps([silver(source, s_pixel, s_rel, weight=weight)]))
    return collection, gold_path, silver_path, g_pixel


def test_central_corpus_accumulates_sources_and_is_idempotent(tmp_path):
    manifest = tmp_path / "corpus" / "manifest.json"
    a = write_labels(tmp_path, "hm45-session:a", (20, 40, 60), weight=0.2)
    first = run(manifest, *a[:3], "hm45-session:a")
    assert first.returncode == 0, first.stderr
    doc = json.loads(manifest.read_text())
    assert doc["counts"] == {"sources": 1, "gold": 1, "silver": 1, "unique_pixels": 2}
    assert doc["sources"][0]["use_declared_silver_weights"] is True

    again = run(manifest, *a[:3], "hm45-session:a")
    assert again.returncode == 0
    assert "already_ingested" in again.stdout
    assert json.loads(manifest.read_text())["counts"]["sources"] == 1

    b = write_labels(tmp_path, "hm45-session:b", (80, 100, 120), weight=0.35)
    second = run(manifest, *b[:3], "hm45-session:b")
    assert second.returncode == 0, second.stderr
    doc = json.loads(manifest.read_text())
    assert doc["counts"] == {"sources": 2, "gold": 2, "silver": 2, "unique_pixels": 4}
    assert {row["source_id"] for row in doc["sources"]} == {
        "hm45-session:a",
        "hm45-session:b",
    }


def test_central_corpus_rejects_pixel_identity_conflict(tmp_path):
    manifest = tmp_path / "corpus" / "manifest.json"
    a = write_labels(tmp_path, "hm45-session:a", (3, 7, 11))
    assert run(manifest, *a[:3], "hm45-session:a").returncode == 0

    # Reuse exactly the same decoded pixels from source A but claim another ID.
    source = "hm45-session:conflict"
    collection = tmp_path / "conflict"
    rel = "crops/gold.png"
    target = collection / rel
    target.parent.mkdir(parents=True)
    target.write_bytes((a[0] / "crops/gold.png").read_bytes())
    pixel = a[3]
    gold_path = tmp_path / "conflict-gold.json"
    silver_path = tmp_path / "conflict-silver.json"
    gold_path.write_text(json.dumps([gold(source, pixel, rel, unit="DA_18_Akali_AD")]))
    silver_path.write_text("[]")

    result = run(manifest, collection, gold_path, silver_path, source)
    assert result.returncode != 0
    assert "pixel identity conflict" in (result.stderr + result.stdout)
    doc = json.loads(manifest.read_text())
    assert doc["counts"]["sources"] == 1
