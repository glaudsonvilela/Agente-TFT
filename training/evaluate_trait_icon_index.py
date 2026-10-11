"""Real 1080p replay checks and CPU timing for the Set 18 portrait index."""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path

from PIL import Image

from prepare_trait_icon_catalog import DEFAULT_OUTPUT

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/hud_mapper"))
from hm.trait_portrait_reader import TraitPortraitReader  # noqa: E402


ROOT = DEFAULT_OUTPUT.parent
MODEL = ROOT / "model"
REPORT = ROOT / "evaluation.json"
CASES = [
    {
        "trait": "Fera do Rift", "image": Path(
            "/mnt/sherlock-ssd/AgenteTFT/diagnostics/gameplay-20261011/frame-260-trait.png"),
        "boxes": [(262 + 58 * i, 630, 310 + 58 * i, 682) for i in range(5)]
                 + [(262 + 58 * i, 690, 310 + 58 * i, 742) for i in range(5)],
        "expected_count": 3,
        "expected_slots": {0: "Cascalho", 1: "Rubrivirim", 3: "Grompe"},
    },
    {
        "trait": "Devastador", "image": Path(
            "/mnt/sherlock-ssd/tmp/codex-clipboard-f417ed78-6ca9-4b15-835f-5eb74cf17bcd.png"),
        "boxes": [(298 + 52 * i, 439, 340 + 52 * i, 481) for i in range(5)]
                 + [(298 + 52 * i, 488, 340 + 52 * i, 530) for i in range(2)],
        "expected_count": 1,
        "expected_slots": {1: "Camille"},
    },
    {
        "trait": "Vanguarda", "image": Path(
            "/mnt/sherlock-ssd/AgenteTFT/diagnostics/gameplay-20261011/frame-267-full.png"),
        "boxes": [(243 + 58 * i, 772, 292 + 58 * i, 822) for i in range(5)]
                 + [(243, 830, 292, 880)],
        "expected_count": 1,
        "expected_slots": {3: "Hecarim"},
    },
]


def main() -> None:
    reader = TraitPortraitReader(MODEL)
    checks = []
    runs = []
    for case in CASES:
        raw = case["image"].read_bytes()
        image = Image.open(case["image"]).convert("RGB")
        result = reader.read_slots(image, case["trait"], case["boxes"], case["expected_count"])
        expected = case["expected_slots"]
        predicted = {i: row["name"] for i, row in enumerate(result["slots"])
                     if row["status"] == "portrait_candidate"}
        active_positions = {i for i, row in enumerate(result["slots"])
                            if row["status"] != "inactive_portrait"}
        passed = (predicted == expected and active_positions == set(expected)
                  and result["count_consistent"])
        checks.append({
            "trait": case["trait"], "image": str(case["image"]),
            "image_sha256": hashlib.sha256(raw).hexdigest(),
            "expected_slots": expected, "predicted_slots": predicted,
            "active_positions": sorted(active_positions), "count_consistent": result["count_consistent"],
            "passed": passed,
        })
        for _ in range(300):
            t0 = time.perf_counter_ns()
            reader.read_slots(image, case["trait"], case["boxes"], case["expected_count"])
            runs.append((time.perf_counter_ns() - t0) / 1_000_000)
    ordered = sorted(runs)
    report = {
        "patch": "18.4B", "real_frames": len(checks),
        "active_icons": sum(len(case["expected_slots"]) for case in CASES),
        "inactive_icons": sum(len(case["boxes"]) - len(case["expected_slots"]) for case in CASES),
        "all_checks_passed": all(row["passed"] for row in checks),
        "timing_ms": {"median": round(statistics.median(runs), 3),
                      "p95": round(ordered[int(len(ordered) * .95)], 3),
                      "max": round(max(runs), 3)},
        "scope": "Reviewed, open trait tooltips only; no automatic tooltip localization or full-video validation",
        "cases": checks,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"},
                     ensure_ascii=False, indent=2))
    if not report["all_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
