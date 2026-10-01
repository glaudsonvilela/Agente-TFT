from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECOVERY = "configs/hud/tft-1920x1080-match001-v4-stage-recovery.json"
RUNNER = "scripts/probe_match001_hud_v4.sh"


def f32(v):
    return struct.unpack("f", struct.pack("f", v))[0]


class StageRecoveryConfigTests(unittest.TestCase):
    def test_measured_boxes_and_no_label_table(self):
        v = json.loads((ROOT / RECOVERY).read_text(encoding="utf-8"))
        self.assertEqual(v["schema_version"], 1)
        self.assertEqual((v["reference_width"], v["reference_height"]), (1920, 1080))
        self.assertEqual([c["name"] for c in v["candidates"]], ["standard", "initial"])
        for c, expected_x in zip(v["candidates"], (766, 826), strict=True):
            self.assertEqual(set(c), {"name", "rect"})
            r = {k: f32(x) for k, x in c["rect"].items()}
            x, y = math.floor(f32(r["x"] * 1920)), math.floor(f32(r["y"] * 1080))
            right = math.ceil(f32(f32(r["x"] + r["width"]) * 1920))
            bottom = math.ceil(f32(f32(r["y"] + r["height"]) * 1080))
            self.assertEqual((x, y, right-x, bottom-y), (expected_x, 5, 36, 25))

    def test_old_layout_and_explicit_opt_in(self):
        script = (ROOT / RUNNER).read_text(encoding="utf-8")
        self.assertIn('LAYOUT="configs/hud/tft-1920x1080-match001-v3-gray.json"', script)
        self.assertIn('--numeric-gray --stage-recovery "$RECOVERY"', script)
        self.assertNotIn('sed -i', script)
        self.assertNotIn('git reset', script)
        self.assertIn('mktemp -d', script)
        self.assertIn('HUD_PENDING_TRACE=', script)


@unittest.skipUnless(shutil.which("bash"), "runner requires bash")
class StageRecoveryRunnerTests(unittest.TestCase):
    def fixture(self, root: Path):
        (root / "scripts").mkdir()
        shutil.copy2(ROOT / RUNNER, root / RUNNER)
        (root / "configs/hud").mkdir(parents=True)
        (root / "configs/hud/tft-1920x1080-match001-v3-gray.json").write_text("{}")
        shutil.copy2(ROOT / RECOVERY, root / RECOVERY)
        ann = root / "training/annotations/match-001"
        (ann / "frames").mkdir(parents=True)
        (ann / "prelabels.json").write_text('{"unchanged":true}')
        bin_dir = root / "bin"; bin_dir.mkdir()
        for name in ("git", "tesseract", "ffmpeg"):
            p = bin_dir / name
            p.write_text("#!/bin/sh\necho fixture_backend\n"); p.chmod(0o755)
        cargo = bin_dir / "cargo"
        cargo.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
code = int(os.environ.get("FIXTURE_EXIT", "0"))
row = {"field":"gold", "timestamp_ms":850000, "expected":44,
       "recognized":None, "correct":False,
       "attempt_trace":[{"text":"44", "confidence":0.6, "reason":"below_min_confidence"}]}
report = {"summary":{"execution_complete":code==0, "frames_selected":1,
          "frames_in_labels":1, "ocr_profile":"fixture", "metric_kind":"prelabel_agreement",
          "promotion_gate":"not_evaluated_diagnostic_only", "stage_recovered":0,
          "fields":{"gold":{"annotated":1,"unknown":1}}}, "records":[row]}
Path(sys.argv[sys.argv.index("--output")+1]).write_text(json.dumps(report))
print(json.dumps(row))
sys.exit(code)
''')
        cargo.chmod(0o755)
        return {**os.environ, "PATH":str(bin_dir)+os.pathsep+os.environ["PATH"]}

    def test_runner_prints_pending_trace_and_does_not_overwrite_inputs_or_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); env = self.fixture(root)
            for _ in range(2):
                r = subprocess.run(["bash", str(root / RUNNER)], env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("HUD_PENDING_TRACE=", r.stdout)
                self.assertIn('"below_min_confidence"', r.stdout)
            self.assertEqual(len(list((root / "telemetry/data").glob("match-001-hud-v4.*"))), 2)
            self.assertEqual((root / "training/annotations/match-001/prelabels.json").read_text(), '{"unchanged":true}')

    def test_operational_exit_is_preserved_with_report_available(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); env = self.fixture(root); env["FIXTURE_EXIT"] = "2"
            r = subprocess.run(["bash", str(root / RUNNER)], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("HUD_PROBE_EXIT=2", r.stdout)
            self.assertIn("HUD_PROBE_COMPLETE= False", r.stdout)


if __name__ == "__main__":
    unittest.main()
