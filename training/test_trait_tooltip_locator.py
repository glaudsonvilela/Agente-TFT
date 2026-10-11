"""Regression checks for exact full-frame trait portrait placement."""
from __future__ import annotations

from pathlib import Path
from collections import Counter
import sys
import threading
from types import SimpleNamespace
import unittest

from PIL import Image

from prepare_trait_icon_catalog import DEFAULT_OUTPUT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/hud_mapper"))
from hm.trait_portrait_reader import TraitPortraitReader  # noqa: E402
from hm.trait_tooltip_locator import locate_trait_tooltip  # noqa: E402
from hm.trait_tooltip_session import TraitTooltipSession  # noqa: E402
from hm.dataset import Latest  # noqa: E402
from hm.runtime_session import HM4RuntimeSession  # noqa: E402


FRAMES = Path("/tmp/tft-full-1fps")


class TraitTooltipLocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reader = TraitPortraitReader(DEFAULT_OUTPUT.parent / "model")

    def test_all_portraits_fit_bright_and_dark_arenas(self) -> None:
        cases = (
            ("0261.jpg", "Fera do Rift", (244, 262, 573, 759), 10,
             ["Cascalho", "Rubrivirim", "Grompe"]),
            ("0262.jpg", "Congregação das Bruxas", (252, 262, 581, 866), 6,
             ["Camille", "Cassiopeia"]),
            ("0267.jpg", "Vanguarda", (225, 421, 554, 899), 6, ["Hecarim"]),
            ("0271.jpg", "Vivaz", (262, 474, 591, 1056), 6, ["Veigar"]),
            ("0275.jpg", "Fera do Rift", (262, 262, 591, 758), 10,
             ["Cascalho", "Grompe"]),
        )
        for filename, title, bounds, count, names in cases:
            with self.subTest(frame=filename):
                with Image.open(FRAMES / filename) as source:
                    frame = source.convert("RGB")
                tooltip = locate_trait_tooltip(frame, self.reader.members)
                self.assertIsNotNone(tooltip)
                self.assertEqual((tooltip.title, tooltip.bounds, len(tooltip.boxes)),
                                 (title, bounds, count))
                self.assertTrue(all(bounds[0] <= box[0] < box[2] <= bounds[2] and
                                    bounds[1] <= box[1] < box[3] <= bounds[3]
                                    for box in tooltip.boxes))
                reading = self.reader.read_slots(frame, title, list(tooltip.boxes))
                self.assertEqual(reading["candidate_names"], names)

    def test_rejects_cropped_input(self) -> None:
        with Image.open(FRAMES / "0261.jpg") as source:
            clipped = source.crop((0, 0, 1920, 900))
        self.assertIsNone(locate_trait_tooltip(clipped, self.reader.members))

    def test_realigns_covered_portraits_without_guessing_from_arena(self) -> None:
        cases = (
            ("0260.jpg", "Inferno", ["Akali", "Varus"], 100),
            ("0304.jpg", "Florescer", ["Karma"], 111),
            ("0319.jpg", "Solar", ["Kayle"], -79),
        )
        for filename, trait, names, shift in cases:
            with self.subTest(frame=filename):
                with Image.open(FRAMES / filename) as source:
                    frame = source.convert("RGB")
                tooltip = locate_trait_tooltip(frame, self.reader.members, allow_alignment=True)
                self.assertIsNotNone(tooltip)
                self.assertEqual(tooltip.title, trait)
                boxes, actual_shift, result = self.reader.realign_if_ambiguous(
                    frame, trait, list(tooltip.boxes), tooltip.bounds[1])
                self.assertEqual(actual_shift, shift)
                self.assertEqual(result["candidate_names"], names)
                self.assertEqual(result["active_portraits"], len(names))
                self.assertTrue(all(0 <= y0 < y1 <= frame.height for _, y0, _, y1 in boxes))

    def test_session_reuses_unchanged_title_and_respects_frame_cadence(self) -> None:
        session = TraitTooltipSession(DEFAULT_OUTPUT.parent / "model", min_interval_ms=150)
        with Image.open(FRAMES / "0262.jpg") as source:
            first = source.convert("RGB")
        with Image.open(FRAMES / "0263.jpg") as source:
            second = source.convert("RGB")
        a = session.observe(first, 262000)
        skipped = session.observe(first, 262050)
        b = session.observe(second, 263000)
        self.assertEqual((a["status"], b["status"]),
                         ("active_portraits_named", "active_portraits_named"))
        self.assertEqual(a["candidate_names"], ["Camille", "Cassiopeia"])
        self.assertEqual(b["candidate_names"], a["candidate_names"])
        self.assertEqual(skipped["status"], "cadence_skip")
        self.assertLess(b["processing_ms"], a["processing_ms"])

    def test_runtime_worker_emits_named_portraits_from_uncut_frame(self) -> None:
        session = object.__new__(HM4RuntimeSession)
        session.trait_model_dir = DEFAULT_OUTPUT.parent / "model"
        session.trait_pending = Latest()
        session.cancel = threading.Event()
        session.producer_done = threading.Event()
        session.producer_done.set()
        session.lock = threading.RLock()
        session.counts = Counter()
        session.versions = {}
        emitted = []
        session.store = SimpleNamespace(emit=lambda stream, row: emitted.append((stream, row)))
        with Image.open(FRAMES / "0262.jpg") as source:
            frame = source.convert("RGB")
        session.trait_pending.put(SimpleNamespace(
            id=262, epoch=1, pts_ms=262000, width=1920, height=1080,
            rgb=frame.tobytes()))
        session._trait_tooltip_loop()
        self.assertEqual(session.counts["trait_tooltip_results"], 1)
        self.assertEqual(emitted[0][0], "trait-tooltip-observations")
        self.assertEqual(emitted[0][1]["candidate_names"], ["Camille", "Cassiopeia"])
        self.assertEqual(emitted[0][1]["source_size"], [1920, 1080])


if __name__ == "__main__":
    unittest.main()
