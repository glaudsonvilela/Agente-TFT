"""Seasonal trait constraints on raw native OCR; hypotheses never become labels."""
from __future__ import annotations

from itertools import combinations_with_replacement
import unicodedata


class TraitCountConsensus:
    """Confirm a visible trait count twice before using it for live advice."""

    def __init__(self):
        self.previous = {}
        self.epoch = None
        self.source_ms = None

    def update(self, raw: dict | None, binding: dict, *, epoch, source_ms):
        if (type(source_ms) not in (int, float) or epoch != self.epoch or self.source_ms is None or
                source_ms <= self.source_ms or source_ms - self.source_ms > 3500):
            self.previous = {}
        if type(source_ms) not in (int, float):
            self.source_ms = None
            return {}
        self.epoch, self.source_ms = epoch, source_ms
        words = ((raw or {}).get('words') or []) if (raw or {}).get('status') == 'raw_ocr' else []
        current, confirmed = {}, {}
        for trait in binding.get('traits') or []:
            box = trait.get('row_box')
            if (trait.get('method') != 'exact_text' or trait.get('confidence', 0) < .85
                    or not isinstance(box, list) or len(box) != 4):
                continue
            center = (box[1] + box[3]) / 2
            matches = [word for word in words
                       if isinstance(word.get('box'), list) and len(word['box']) == 4
                       and word['box'][0] <= 130 and word.get('confidence', 0) >= .9
                       and str(word.get('text', '')).isdigit()
                       and 1 <= int(word['text']) <= 9
                       and abs((word['box'][1] + word['box'][3]) / 2 - center) <= 12]
            if len(matches) != 1:
                continue
            name, count = trait['name'], int(matches[0]['text'])
            current[name] = count
            if self.previous.get(name) == count:
                confirmed[name] = count
        self.previous = current
        return confirmed


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


def bind_observed_traits(raw: dict | None, names: set[str] | dict[str, str]) -> dict:
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
        if (0 <= slot <= 9 and abs(center - (275 + slot * 53)) <= 11 and
                sum(char.isalpha() for char in value) >= 2 and
                word.get("confidence", 0) >= .25):
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
        if (type(confidence) not in (int, float) or confidence < .30 or
                sum(char.isalpha() for char in text) < 3):
            continue
        center = (box[1] + box[3]) / 2
        if rows and abs(center - sum((w["box"][1] + w["box"][3]) / 2
                                  for w in rows[-1]) / len(rows[-1])) <= 8:
            rows[-1].append(word)
        else:
            rows.append([word])
    canonical: dict[str, str] = {}
    for alias, name in (names.items() if isinstance(names, dict)
                        else ((name, name) for name in names)):
        key = _fold(alias)
        if key in canonical and canonical[key] != name:
            raise ValueError('Ambiguous folded trait alias')
        canonical[key] = name
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
                            "confidence": min(w["confidence"] for w in row),
                            "row_box": [min(w['box'][0] for w in row),
                                        min(w['box'][1] for w in row),
                                        max(w['box'][2] for w in row),
                                        max(w['box'][3] for w in row)]})
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
    # Only a very small early roster can be discussed from visible bars.
    # A late-game trait list may contain many unseen champions behind effects.
    if len(observed) > 4:
        return {"status": "large_roster_not_exhaustive", "rosters": []}
    if not 1 <= board_count <= 4:
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
