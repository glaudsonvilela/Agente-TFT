"""Fast, read-only matching of highlighted Set 18 trait tooltip portraits.

Input slot boxes must come from a tooltip locator or a reviewed replay frame.
The reader never treats an inactive/grayscale portrait as a owned champion and
does not turn visual similarity into an inspect-panel confirmation.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image


class TraitPortraitReader:
    def __init__(self, model_dir: Path):
        model_dir = Path(model_dir)
        meta = json.loads((model_dir / "index.json").read_text(encoding="utf-8"))
        with np.load(model_dir / "portraits.npz", allow_pickle=False) as bank:
            self.features = bank["features"].astype(np.float32, copy=False)
            self.labels = bank["labels"].tolist()
            self.kinds = bank["kinds"].tolist()
        expected_rows = len(meta["id_to_name"]) * 2
        if (self.features.shape != (expected_rows, 256) or len(self.labels) != expected_rows
                or expected_rows != 148):
            raise ValueError("invalid Set 18 portrait index")
        self.names = meta["id_to_name"]
        self.members = meta["trait_members_by_name"]
        self.patch = meta["patch"]
        self._trait_rows = {
            trait: np.asarray([i for i, identity in enumerate(self.labels)
                               if identity in set(members)], dtype=np.int32)
            for trait, members in self.members.items()
        }

    @staticmethod
    def _inner(full: Image.Image) -> Image.Image:
        # The full square source is never cropped.  Only the UI frame/border is
        # excluded from the observed screen slot, proportional to its size.
        w, h = full.size
        border = max(2, round(min(w, h) * 0.12))
        if w <= border * 2 or h <= border * 2:
            raise ValueError("portrait slot too small")
        return full.crop((border, border, w - border, h - border))

    @staticmethod
    def _active(inner: Image.Image) -> tuple[bool, float]:
        rgb = np.asarray(inner.convert("RGB"), dtype=np.float32)
        chroma = float((rgb.max(axis=2) - rgb.min(axis=2)).mean())
        return chroma >= 15.0, chroma

    @staticmethod
    def _feature(inner: Image.Image) -> np.ndarray:
        gray = inner.convert("L").resize((16, 16), Image.Resampling.BILINEAR)
        values = np.asarray(gray, dtype=np.float32).reshape(-1).copy()
        values -= values.mean()
        return values / max(float(np.linalg.norm(values)), 1.0)

    def match(self, image: Image.Image, trait_name: str, box: tuple[int, int, int, int]) -> dict:
        if trait_name not in self._trait_rows:
            return {"status": "trait_not_in_patch", "trait": trait_name}
        if (box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height
                or box[2] <= box[0] or box[3] <= box[1]):
            raise ValueError("slot outside frame")
        inner = self._inner(image.crop(box))
        active, chroma = self._active(inner)
        if not active:
            return {"status": "inactive_portrait", "chroma": round(chroma, 2)}
        rows = self._trait_rows[trait_name]
        if not len(rows):
            return {"status": "trait_has_no_roster", "trait": trait_name}
        scores = self.features[rows] @ self._feature(inner)
        best_by_id: dict[str, tuple[float, str]] = {}
        for idx, score in zip(rows, scores):
            identity = self.labels[int(idx)]
            if identity not in best_by_id or score > best_by_id[identity][0]:
                best_by_id[identity] = (float(score), self.kinds[int(idx)])
        ranked = sorted(best_by_id.items(), key=lambda pair: pair[1][0], reverse=True)
        winner, (score, kind) = ranked[0]
        runner = ranked[1][1][0] if len(ranked) > 1 else -1.0
        margin = score - runner
        status = "portrait_candidate" if score >= 0.44 and margin >= 0.15 else "ambiguous_portrait"
        return {"status": status, "id": winner if status == "portrait_candidate" else None,
                "name": self.names[winner] if status == "portrait_candidate" else None,
                "similarity": round(score, 4), "margin": round(margin, 4),
                "source_icon": kind, "chroma": round(chroma, 2),
                "alternatives": [(self.names[identity], round(value[0], 4))
                                 for identity, value in ranked[:3]]}

    def read_slots(self, image: Image.Image, trait_name: str,
                   boxes: list[tuple[int, int, int, int]],
                   displayed_count: int | None = None) -> dict:
        rows = [self.match(image, trait_name, box) for box in boxes]
        candidates = [row for row in rows if row["status"] == "portrait_candidate"]
        active = sum(row["status"] != "inactive_portrait" for row in rows)
        return {"trait": trait_name, "patch": self.patch,
                "active_portraits": active, "displayed_count": displayed_count,
                "count_consistent": displayed_count == active if displayed_count is not None else None,
                "candidate_names": [row["name"] for row in candidates], "slots": rows}

    def resolve_with_trait_assignment(self, image: Image.Image, trait_name: str,
                                      boxes: list[tuple[int, int, int, int]], result: dict) -> dict:
        """Use the trait's one-to-one icon inventory to break close matches."""
        if not any(row["status"] == "ambiguous_portrait" for row in result["slots"]):
            return result
        members = sorted(self.members[trait_name])
        if len(members) != len(boxes) or len(members) > 10:
            return result
        scores = np.empty((len(boxes), len(members)), dtype=np.float32)
        for i, box in enumerate(boxes):
            patch = self._inner(image.crop(box))
            feature = self._feature(patch)
            for j, identity in enumerate(members):
                rows = [k for k in self._trait_rows[trait_name] if self.labels[int(k)] == identity]
                scores[i, j] = float((self.features[rows] @ feature).max())

        @lru_cache(None)
        def best(mask: int) -> tuple[float, tuple[int, ...]]:
            i = mask.bit_count()
            if i == len(members):
                return 0.0, ()
            options = []
            for j in range(len(members)):
                if not mask & (1 << j):
                    tail_score, tail = best(mask | (1 << j))
                    options.append((float(scores[i, j]) + tail_score, (j,) + tail))
            return max(options, key=lambda item: item[0])

        total, assignment = best(0)
        revised = [dict(row) for row in result["slots"]]
        for i, row in enumerate(revised):
            if row["status"] != "ambiguous_portrait":
                continue
            chosen = assignment[i]
            own = float(scores[i, chosen])
            runner_total = max(
                (float(scores[i, alt]) + self._best_without_slot(scores, i, alt)
                 for alt in range(len(members)) if alt != chosen), default=-1.0)
            global_margin = total - runner_total
            if own >= .55 and global_margin >= .12:
                identity = members[chosen]
                row.update(status="portrait_candidate_by_trait_assignment", id=identity,
                           name=self.names[identity], similarity=round(own, 4),
                           global_margin=round(global_margin, 4))
        revised_names = [row["name"] for row in revised if row["status"].startswith("portrait_candidate")]
        return {**result, "candidate_names": revised_names, "slots": revised}

    @staticmethod
    def _best_without_slot(scores: np.ndarray, excluded_row: int, fixed_column: int) -> float:
        """Maximum one-to-one score with one slot fixed to one identity."""
        n = scores.shape[0]
        @lru_cache(None)
        def solve(row: int, mask: int) -> float:
            if row == n:
                return 0.0
            if row == excluded_row:
                return solve(row + 1, mask)
            return max(float(scores[row, j]) + solve(row + 1, mask | (1 << j))
                       for j in range(n) if j != fixed_column and not mask & (1 << j))
        return solve(0, 0)

    def _alignment_score(self, image: Image.Image, trait_name: str,
                         boxes: list[tuple[int, int, int, int]]) -> tuple[float, float]:
        rows = self._trait_rows[trait_name]
        scores = []
        for box in boxes:
            if box[1] < 0 or box[3] > image.height:
                return -1.0, -1.0
            patch = image.crop(box)
            pixels = np.asarray(patch, dtype=np.uint8)
            if pixels.mean() < 25 or pixels.std() < 18:
                return -1.0, -1.0
            scores.append(float((self.features[rows] @ self._feature(self._inner(patch))).max()))
        return float(np.mean(scores)), min(scores)

    def realign_if_ambiguous(self, image: Image.Image, trait_name: str,
                             boxes: list[tuple[int, int, int, int]],
                             panel_top: int) -> tuple[list[tuple[int, int, int, int]], int, dict]:
        """Use every native portrait to repair a vertical offset on dark skins.

        Expensive search runs only when the initial read has an unresolved
        colored portrait.  A better alignment must improve the whole row,
        not merely match one colorful board patch by chance.
        """
        initial = self.read_slots(image, trait_name, boxes)
        if initial["active_portraits"] == len(initial["candidate_names"]) and initial["active_portraits"]:
            return boxes, 0, initial
        baseline, _ = self._alignment_score(image, trait_name, boxes)
        best = (baseline, 0, -1.0)

        def shifted(dy: int) -> list[tuple[int, int, int, int]]:
            return [(x0, y0 + dy, x1, y1 + dy) for x0, y0, x1, y1 in boxes]

        for dy in range(-140, 141, 4):
            test = shifted(dy)
            if test[0][1] < panel_top + 80 or test[-1][3] > image.height - 5:
                continue
            mean, minimum = self._alignment_score(image, trait_name, test)
            if mean > best[0]:
                best = mean, dy, minimum
        coarse_dy = best[1]
        for dy in range(coarse_dy - 4, coarse_dy + 5):
            test = shifted(dy)
            if test[0][1] < panel_top + 80 or test[-1][3] > image.height - 5:
                continue
            mean, minimum = self._alignment_score(image, trait_name, test)
            if mean > best[0]:
                best = mean, dy, minimum
        if best[0] < .60 or best[2] < .35 or best[0] - baseline < .06:
            return boxes, 0, self.resolve_with_trait_assignment(image, trait_name, boxes, initial)
        aligned = shifted(best[1])
        result = self.read_slots(image, trait_name, aligned)
        result = self.resolve_with_trait_assignment(image, trait_name, aligned, result)
        if (not result["candidate_names"] or
                result["active_portraits"] != len(result["candidate_names"])):
            return boxes, 0, initial
        return aligned, best[1], result
