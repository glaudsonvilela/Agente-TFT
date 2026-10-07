"""Seasonal trait constraints on raw native OCR; hypotheses never become labels."""
from __future__ import annotations

from itertools import combinations_with_replacement
import unicodedata


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if char.isalnum()
                   and not unicodedata.combining(char))


def _distance(a: str, b: str, limit: int = 2) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    row = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        next_row = [i]
        for j, other in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1,
                                row[j - 1] + (char != other)))
        row = next_row
        if min(row) > limit:
            return limit + 1
    return row[-1]


def bind_observed_traits(raw: dict | None, names: set[str]) -> dict:
    if not isinstance(raw, dict) or raw.get("status") not in ("raw_ocr", "cached_ocr"):
        return {"status": "unavailable", "traits": [], "unmatched": []}
    if raw.get("status") == "cached_ocr" and raw.get("age_ms", 99999) > 2000:
        return {"status": "stale", "traits": [], "unmatched": []}
    # The text baseline repeats every 53 px. A short OCR fragment such as
    # "FI" still proves that a row exists, even when its name cannot be bound.
    text_rows: set[int] = set()
    for word in raw.get("words") or []:
        box = word.get("box")
        value = word.get("text")
        if not isinstance(box, list) or len(box) != 4 or not isinstance(value, str):
            continue
        center = (box[1] + box[3]) / 2
        slot = round((center - 275) / 53)
        if (0 <= slot <= 3 and abs(center - (275 + slot * 53)) <= 11 and
                len(_fold(value)) >= 2 and word.get("confidence", 0) >= .25):
            text_rows.add(slot)
    rows: list[list[dict]] = []
    for word in sorted(raw.get("words") or [], key=lambda item: item.get("box", [0, 0])[1]):
        text = word.get("text")
        box = word.get("box")
        confidence = word.get("confidence")
        if not isinstance(text, str) or not isinstance(box, list) or len(box) != 4:
            continue
        # Tesseract often assigns low confidence to the Portuguese cedilla
        # with the English model, even when the full trait name is legible.
        # Catalog matching below still requires a unique full-word match.
        if type(confidence) not in (int, float) or confidence < .30 or len(_fold(text)) < 4:
            continue
        center = (box[1] + box[3]) / 2
        if rows and abs(center - sum((w["box"][1] + w["box"][3]) / 2
                                  for w in rows[-1]) / len(rows[-1])) <= 8:
            rows[-1].append(word)
        else:
            rows.append([word])
    canonical = {_fold(name): name for name in names}
    matched, unmatched = [], []
    for row in rows:
        observed = " ".join(w["text"] for w in sorted(row, key=lambda w: w["box"][0]))
        key = _fold(observed)
        if key in canonical:
            choice, method = canonical[key], "exact_text"
        else:
            distances = sorted((_distance(key, folded), name)
                               for folded, name in canonical.items())
            best, second = distances[0], distances[1] if len(distances) > 1 else (99, "")
            if best[0] > 2 or best[0] * 4 > len(key) or second[0] <= best[0]:
                unmatched.append(observed)
                continue
            choice, method = best[1], "unique_near_text"
        if choice not in {item["name"] for item in matched}:
            matched.append({"name": choice, "observed_text": observed,
                            "method": method,
                            "confidence": min(w["confidence"] for w in row)})
    return {"status": "candidates" if matched and len(matched) == len(text_rows)
            else "partial_panel" if matched else "no_catalog_match",
            "traits": matched, "unmatched": unmatched,
            "detected_text_rows": len(text_rows),
            "complete_panel_verified": False, "identity_verified": False}


def roster_hypotheses(binding: dict, markers: list[dict], champion_traits: dict[str, set[str]]) -> dict:
    observed = {row["name"] for row in binding.get("traits", [])}
    if binding.get("status") != "candidates" or binding.get("unmatched") or not observed:
        return {"status": "insufficient_traits", "rosters": []}
    board_count = sum(marker.get("color") == "green" and
                      type((marker.get("rect") or {}).get("y")) is int and
                      200 <= marker["rect"]["y"] < 665 for marker in markers)
    if not 1 <= board_count <= 4 or len(observed) > 10:
        return {"status": "board_count_unavailable", "rosters": []}
    eligible = sorted(unit for unit, traits in champion_traits.items()
                      if traits and traits <= observed)
    if len(eligible) > 20:
        return {"status": "too_many_eligible_units", "rosters": []}
    rosters = []
    for combination in combinations_with_replacement(eligible, board_count):
        if set.union(*(champion_traits[unit] for unit in combination)) == observed:
            rosters.append(list(combination))
            if len(rosters) > 12:
                return {"status": "ambiguous", "rosters": [], "hypotheses_over_limit": True}
    return {"status": "hypotheses" if rosters else "no_exact_trait_cover",
            "rosters": rosters, "board_bar_count": board_count,
            "identity_verified": False, "perspective_verified": False,
            "panel_completeness_verified": False}
