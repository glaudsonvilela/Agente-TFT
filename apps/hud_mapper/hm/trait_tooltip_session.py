"""Frame-bound Set 18 trait portrait observation for a 1080p HUD runtime.

The method is read-only and runs on a limited cadence.  Colored portraits
mean active trait members on the currently viewed board; they are visual
candidates, not inspect-panel confirmation or bench ownership.
"""
from __future__ import annotations

from pathlib import Path
import time

from PIL import Image

from .trait_portrait_reader import TraitPortraitReader
from .trait_tooltip_locator import TooltipTitleCache, locate_trait_tooltip


class TraitTooltipSession:
    def __init__(self, model_dir: Path, min_interval_ms: int = 150):
        self.reader = TraitPortraitReader(model_dir)
        self.title_cache = TooltipTitleCache()
        self.min_interval_ms = min_interval_ms
        self.last_source_ms: int | None = None
        self.last_alignment: tuple[str, tuple[int, int, int, int], int] | None = None

    def observe(self, frame: Image.Image, source_ms: int) -> dict:
        if frame.size != (1920, 1080):
            return {"status": "unsupported_frame_size", "source_ms": source_ms,
                    "required_size": [1920, 1080]}
        if self.last_source_ms is not None and 0 <= source_ms - self.last_source_ms < self.min_interval_ms:
            return {"status": "cadence_skip", "source_ms": source_ms}
        self.last_source_ms = source_ms
        start = time.perf_counter_ns()
        tooltip = locate_trait_tooltip(frame, self.reader.members, allow_alignment=True,
                                       title_cache=self.title_cache)
        if tooltip is None:
            self.last_alignment = None
            return {"status": "no_complete_trait_tooltip", "source_ms": source_ms,
                    "processing_ms": round((time.perf_counter_ns() - start) / 1e6, 2)}
        boxes = list(tooltip.boxes)
        signature = (tooltip.title, tooltip.bounds)
        shift = 0
        if self.last_alignment is not None and self.last_alignment[:2] == signature:
            remembered = self.last_alignment[2]
            proposed = [(x0, y0 + remembered, x1, y1 + remembered) for x0, y0, x1, y1 in boxes]
            if all(0 <= box[1] < box[3] <= frame.height for box in proposed):
                candidate = self.reader.read_slots(frame, tooltip.title, proposed)
                if candidate["active_portraits"] and candidate["active_portraits"] == len(candidate["candidate_names"]):
                    boxes, shift, reading = proposed, remembered, candidate
                else:
                    boxes, shift, reading = self.reader.realign_if_ambiguous(
                        frame, tooltip.title, boxes, tooltip.bounds[1])
            else:
                boxes, shift, reading = self.reader.realign_if_ambiguous(
                    frame, tooltip.title, boxes, tooltip.bounds[1])
        else:
            boxes, shift, reading = self.reader.realign_if_ambiguous(
                frame, tooltip.title, boxes, tooltip.bounds[1])
        self.last_alignment = (*signature, shift)
        fully_named = bool(reading["active_portraits"]) and len(reading["candidate_names"]) == reading["active_portraits"]
        active_slots = ([{"box": list(boxes[i]), "name": slot["name"],
                          "status": "visual_candidate"}
                         for i, slot in enumerate(reading["slots"])
                         if slot["status"].startswith("portrait_candidate")]
                        if fully_named else [])
        return {"status": "active_portraits_named" if fully_named else "insufficient_visual_evidence",
                "source_ms": source_ms, "trait": tooltip.title, "patch": self.reader.patch,
                "bounds": [tooltip.bounds[0], tooltip.bounds[1], tooltip.bounds[2], tooltip.bounds[3] + shift],
                "boxes": [list(box) for box in boxes],
                "candidate_names": reading["candidate_names"] if fully_named else [],
                "active_slots": active_slots,
                "active_portraits": reading["active_portraits"],
                "evidence": "colored_trait_tooltip_portraits", "confirmed_by_inspect_panel": False,
                "processing_ms": round((time.perf_counter_ns() - start) / 1e6, 2)}
