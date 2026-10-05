import copy
from pathlib import Path
import json
from types import SimpleNamespace
import unittest
import threading

import numpy as np

from hm.unit_identity import decode_scores, unit_box
from hm.runtime_session import HM4RuntimeSession, hub_due
from hm.dataset import Latest
from collections import Counter
from training.train_unit_identity import samples
from hm45_core_server import AnalysisCore

ROOT = Path(__file__).resolve().parents[3]


class UnitIdentityContracts(unittest.TestCase):
    def test_ambiguous_nonfinite_and_unknown_scores_cannot_confirm_identity(self):
        classes = ["a", "b", "__unknown__"]
        rows = decode_scores([[10, 0, 0], [2, 2, 0], [0, 0, 12]], classes)
        self.assertEqual([r["candidate_id"] for r in rows], ["a", None, None])
        self.assertTrue(all(r["identity_verified"] is False for r in rows))
        for bad in ([[float("nan"), 0, 0]], [[0, 0]], [1, 2, 3]):
            with self.assertRaises(ValueError):
                decode_scores(bad, classes)

    def test_partial_crops_and_malformed_markers_are_rejected(self):
        self.assertEqual(
            unit_box(dict(x=873, y=346, width=64, height=5), (1920, 1080)),
            [841, 354, 969, 498],
        )
        for rect in (
            None,
            {},
            dict(x=0, y=346, width=64, height=5),
            dict(x=100, y=1000, width=64, height=5),
            dict(x=True, y=200, width=64, height=5),
        ):
            self.assertIsNone(unit_box(rect, (1920, 1080)))

    def test_capture_submits_board_without_any_ocr_result_and_bounds_queue(self):
        # No reader or OCR worker exists on this object; submission depends on
        # capture time only. Stale pending input is replaced, not accumulated.
        session = HM4RuntimeSession.__new__(HM4RuntimeSession)
        session.hub_pending = Latest()
        session.counts = Counter()
        session.hub_interval_ms = 1000
        for i in range(50):
            session.submit_hub_frame(SimpleNamespace(epoch=1, pts_ms=i * 1000, id=i))
        self.assertEqual(session.hub_pending.get().id, 49)
        self.assertEqual(session.hub_pending.replaced, 49)
        self.assertEqual(session.counts["hub_submitted"], 50)

    def test_seek_and_new_capture_epoch_reset_sampling_deadline(self):
        previous = dict(epoch=1, source_ms=50000)
        self.assertTrue(hub_due(previous, SimpleNamespace(epoch=1, pts_ms=100), 1000))
        self.assertTrue(hub_due(previous, SimpleNamespace(epoch=2, pts_ms=50001), 1000))
        self.assertFalse(
            hub_due(previous, SimpleNamespace(epoch=1, pts_ms=50500), 1000)
        )
        self.assertTrue(hub_due(previous, SimpleNamespace(epoch=1, pts_ms=51000), 1000))

    def test_ip_hub_derives_geometry_from_same_frame_without_touching_ocr(self):
        core = AnalysisCore.__new__(AnalysisCore)
        core.hub_lock = threading.Lock()
        # Deliberately omit reader, hp, and their locks. Any OCR dependency fails.
        calls = []

        def geometry(frame, calibrate):
            calls.append((frame.id, frame.pts_ms, len(frame.rgb), calibrate))
            return {"timestamp_ms": frame.pts_ms, "markers": []}

        core.board_worker = SimpleNamespace(observe=geometry)
        core.board = SimpleNamespace(
            observe=lambda frame, read: {"snapshot": read, "regions": []}
        )
        result = core.dispatch(
            dict(
                op="hub",
                frame_id=7,
                source_ms=500,
                width=1920,
                height=1080,
                codec="rgb8",
                calibrate_board=True,
                board_read={"timestamp_ms": -100, "markers": ["stale"]},
            ),
            bytes(1920 * 1080 * 3),
        )
        self.assertEqual(calls, [(7, 500, 1920 * 1080 * 3, True)])
        self.assertEqual(result["snapshot"], {"timestamp_ms": 500, "markers": []})

    def test_reviewed_matches_may_not_leak_across_splits(self):
        document = json.loads(
            (ROOT / "configs/training/unit-identity-review-20261004.json").read_text(
                encoding="utf-8"
            )
        )
        reference = json.loads(
            (ROOT / "configs/catalog/active-visual-reference-v1.json").read_text(
                encoding="utf-8"
            )
        )
        catalog = json.loads(
            (ROOT / reference["reference"] / "champions.json").read_text(
                encoding="utf-8"
            )
        )
        rows = samples(document, None, catalog, "reference")
        self.assertEqual(len(rows["test"]), 12)
        changed = copy.deepcopy(document)
        changed["frames"][0]["identity_split"] = "test"
        with self.assertRaisesRegex(ValueError, "leakage"):
            samples(changed, None, catalog, "reference")
        changed = copy.deepcopy(document)
        changed["frames"][0]["entities"][0]["identity"]["id"] = "a_guessed_unit"
        with self.assertRaisesRegex(ValueError, "absent from catalog"):
            samples(changed, None, catalog, "reference")


if __name__ == "__main__":
    unittest.main()
