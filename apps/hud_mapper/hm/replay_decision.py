"""Patch-bound replay state and conservative first purchase decision.

Geometry, OCR and patch metadata are independent. A readable shop name is
bound to the catalog only when it has one exact match. An upgrade instruction
also requires verified owned unit identities from the board/bench observer.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import unicodedata


def _key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.strip()).casefold()
    return "".join(char for char in folded if not unicodedata.combining(char))


def _gold(answer: dict) -> int | None:
    rows = [row for row in answer.get("hud") or []
            if row.get("field") == "gold" and
            row.get("status") == "single_frame_observation" and
            type(row.get("value")) is int and
            float(row.get("confidence") or 0) >= .85]
    return rows[0]["value"] if len(rows) == 1 and 0 <= rows[0]["value"] <= 300 else None


class ReplayDecisionEngine:
    def __init__(self, configs: str):
        root = Path(configs).resolve().parent
        catalog = json.loads((root / "configs/catalog/active-visual-reference-v1.json").read_text(encoding="utf-8"))
        context = json.loads((root / "configs/contexts/match001-interface.json").read_text(encoding="utf-8"))
        if catalog["set_key"] != context["set_key"]:
            raise ValueError("Patch and visual catalog refer to different sets")
        reference = root / catalog["reference"]
        manifest = json.loads((reference / "reference.json").read_text(encoding="utf-8"))
        champions = json.loads((reference / "champions.json").read_text(encoding="utf-8"))
        if (manifest["set_key"] != catalog["set_key"] or
                champions["set_key"] != catalog["set_key"] or
                champions["version"] != manifest["version"]):
            raise ValueError("Champion catalog and patch reference differ")
        self.patch = context["tft_patch"]
        self.set_key = catalog["set_key"]
        self.catalog_version = manifest["version"]
        knowledge = json.loads((root / "configs/catalog/active-knowledge-release-v1.json").read_text(encoding="utf-8"))
        release = root / knowledge["reference"]
        release_manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
        units_bytes = (release / "units.json").read_bytes()
        if (knowledge["set_key"] != self.set_key or knowledge["tft_patch"] != self.patch or
                release_manifest["set"]["key"] != self.set_key or
                release_manifest["tft_patch"] != self.patch or
                release_manifest["components"]["units"]["sha256"] != hashlib.sha256(units_bytes).hexdigest()):
            raise ValueError("Champion attributes and selected patch differ")
        units = json.loads(units_bytes)["champions"]
        self.champion_attributes = {unit["api_name"]: unit for unit in units}
        if set(self.champion_attributes) != {entry["id"] for entry in champions["entries"]}:
            raise ValueError("Champion attributes and visual identities differ")
        self.knowledge_release = release_manifest["release_sha256"]
        names = {}
        for entry in champions["entries"]:
            names.setdefault(_key(entry["name"]), set()).add(entry["id"])
        self.names = names

    def evaluate(self, answer: dict, owned: dict | None = None) -> dict:
        """Return a new answer; never turn a candidate icon into a owned unit."""
        output = copy.deepcopy(answer)
        shop = output.get("shop") or {}
        bound = 0
        for slot in shop.get("slots") or []:
            name = slot.get("observed_name")
            if (slot.get("status") != "offer_text_readable" or
                    not isinstance(name, str) or
                    float(slot.get("name_confidence") or 0) < .9 or
                    type(slot.get("observed_cost")) is not int or
                    not 1 <= slot["observed_cost"] <= 5):
                continue
            matches = self.names.get(_key(name), set())
            if len(matches) == 1:
                slot["unit_id"] = next(iter(matches))
                slot["catalog_status"] = "unique_name_bound"
                slot["catalog_set"] = self.set_key
                slot["catalog_version"] = self.catalog_version
                bound += 1
            elif matches:
                slot["catalog_status"] = "ambiguous_name"
            else:
                slot["catalog_status"] = "name_not_in_patch"
        output["catalog_binding"] = {
            "patch": self.patch, "set_key": self.set_key,
            "data_dragon_version": self.catalog_version,
            "knowledge_release": self.knowledge_release,
            "basis": "reported_replay_patch_and_unique_ocr_name",
            "bound_offers": bound}
        # The present B4 observer is candidate-only. Its rows cannot establish
        # a roster; a future validated observer must pass this explicit shape.
        verified = ((owned or {}).get("verified") is True and
                    (owned or {}).get("perspective") == "self")
        units = (owned or {}).get("units") or []
        if not verified or not units:
            output["decision"] = self._wait("OWNED_UNITS_UNVERIFIED")
            return output
        age_ms = owned.get("age_ms")
        if type(age_ms) not in (int, float) or not 0 <= age_ms <= 2000:
            output["decision"] = self._wait("OWNED_UNITS_STALE")
            return output
        copies = Counter()
        for unit in units:
            if (unit.get("identity_verified") is True and
                    isinstance(unit.get("unit_id"), str) and
                    unit.get("stars") == 1):
                copies[unit["unit_id"]] += 1
        gold = _gold(output)
        if gold is None:
            output["decision"] = self._wait("GOLD_UNVERIFIED")
            return output
        if (shop.get("cadence_delivery") or {}).get("fresh") is not True:
            output["decision"] = self._wait("SHOP_STALE")
            return output
        candidates = [slot for slot in shop.get("slots") or []
                      if slot.get("catalog_status") == "unique_name_bound" and
                      float(slot.get("cost_confidence") or 0) >= .9 and
                      copies[slot["unit_id"]] >= 2 and
                      gold >= slot["observed_cost"]]
        if not candidates:
            output["decision"] = self._wait("NO_VERIFIED_UPGRADE")
            return output
        slot = min(candidates, key=lambda row: (row["observed_cost"], row["slot"]))
        output["decision"] = {
            "schema_version": "0.1.0",
            "action": {"type": "buy", "shop_slot": slot["slot"], "unit_id": slot["unit_id"]},
            "confidence": min(.95, float(slot["name_confidence"])),
            "evidence": [{"code": "THIRD_COPY_UPGRADE",
                          "detail": "Two verified one-star copies and a fresh, affordable catalog-bound offer."}],
            "policy": "verified_third_copy_v1",
            "patch": self.patch}
        return output

    @staticmethod
    def _wait(reason: str) -> dict:
        return {"schema_version": "0.1.0", "action": {"type": "wait"},
                "confidence": 0.0, "evidence": [{"code": reason}],
                "policy": "verified_third_copy_v1"}
