import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from training.akash_policy_supervisor import (
    checkpoint_valid, ensure_persistent, preflight, run,
)

ROOT = Path(__file__).resolve().parents[2]


class AkashPolicySupervisorTests(unittest.TestCase):
    def test_plain_container_directory_is_not_accepted_as_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "persistent volume"):
                ensure_persistent(root / "job", root)

    def test_current_patch_preflight_blocks_unreviewed_data_and_simulator(self):
        gate = preflight(ROOT,
                         ROOT / "configs/training/challenger-strategy-18.4b.example.json",
                         ROOT / "datasets/player-policy-18.4b/reviewed-actions.json",
                         ROOT / "datasets/player-policy-18.4b/content.json")
        self.assertFalse(gate["training_ready"])
        self.assertFalse(gate["simulator_ready"])
        self.assertEqual(gate["selected_matches"], 0)

    def test_resume_after_child_failure_and_keep_original_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = root / "fake_trainer.py"
            child.write_text('''import hashlib, json, os, pathlib, sys
root = pathlib.Path(os.environ["TFT_CHECKPOINT_DIR"])
checkpoint = root / "weights.bin"
if "--resume" not in sys.argv:
    checkpoint.write_bytes(b"first checkpoint")
    (root / "checkpoint.json").write_text(json.dumps({
        "path": checkpoint.name,
        "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest()}))
    raise SystemExit(7)
assert checkpoint.read_bytes() == b"first checkpoint"
(root / "complete.flag").write_text("ok")
''')
            command = [sys.executable, str(child)]
            state = run(root, command, seconds=60,
                        sleep=lambda _: time.sleep(.02))
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["attempts"], 2)
            self.assertTrue(state["resumed_from_checkpoint"])
            deadline = state["deadline_utc"]
            again = run(root, command, seconds=60)
            self.assertEqual(again["attempts"], 2)
            self.assertEqual(again["deadline_utc"], deadline)
            self.assertTrue(checkpoint_valid(root))

    def test_tampered_checkpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "weights.bin").write_bytes(b"changed")
            (root / "checkpoint.json").write_text(json.dumps({
                "path": "weights.bin", "sha256": hashlib.sha256(b"original").hexdigest()}))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                checkpoint_valid(root)

    def test_expired_budget_does_not_launch_new_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = [sys.executable, "missing_trainer.py"]
            (root / "job.json").write_text(json.dumps({
                "schema_version": 1,
                "command_sha256": hashlib.sha256(json.dumps([command, ""]).encode()).hexdigest(),
                "budget_seconds": 60, "deadline_utc": 1,
                "attempts": 0, "status": "created"}))
            state = run(root, command, seconds=60)
            self.assertEqual(state["status"], "budget_exhausted")
            self.assertEqual(state["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
