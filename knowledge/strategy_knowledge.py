"""Patch-bound reference retrieval for the strategic brain.

No visual guess is promoted to a verified unit and no catalog description is
treated as an executable combat rule. The caller supplies exact catalog IDs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class StrategyKnowledge:
    def __init__(self, directory: Path, *, set_key: str, patch: str):
        directory = Path(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("knowledge_file") != "knowledge.json":
            raise ValueError("unknown strategy knowledge file")
        raw = (directory / "knowledge.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.get("knowledge_sha256"):
            raise ValueError("strategy knowledge hash mismatch")
        data = json.loads(raw)
        if (manifest.get("schema_version"), data.get("schema_version")) != (1, 1):
            raise ValueError("unsupported strategy knowledge schema")
        if any((document.get("set_key"), document.get("patch")) != (set_key, patch)
               for document in (manifest, data)):
            raise ValueError("strategy knowledge patch mismatch")
        if manifest.get("runtime_promoted") is not False or data.get("runtime_combat_rules_verified") is not False:
            raise ValueError("unreviewed strategy knowledge status")
        self.data = data
        self.digest = manifest["knowledge_sha256"]
        self.set_key = set_key
        self.patch = patch

    @classmethod
    def for_patch(cls, root: Path, *, set_key: str, patch: str):
        # A missing pack means there is no new reference context for this
        # session. A present but invalid pack fails closed at construction.
        directory = Path(root) / "configs" / "strategy" / set_key / patch
        if not directory.is_dir():
            return None
        return cls(directory, set_key=set_key, patch=patch)

    def champion(self, unit_id: str):
        if not isinstance(unit_id, str):
            return None
        row = self.data["champions"].get(unit_id)
        if row is None:
            return None
        linked_traits = {}
        for identity in row["traits"]:
            trait = self.data["traits"][identity]
            trait_names = {trait["name"], trait["name_en"]}
            base_trait_changes = [change for change in self.data["official_base_patch_changes"]
                                  if change["section"] == "TRAITS" and
                                  any(change["subject"] == name or
                                      str(change["subject"]).startswith(name + " (")
                                      for name in trait_names)]
            linked_traits[identity] = dict(
                name=trait["name"], description=trait["description"],
                breakpoints=[tier["minimum"] for tier in trait["tiers"]],
                mechanic_status=trait["mechanic_status"],
                official_base_patch_changes=base_trait_changes)
        names = {row["name_en"], row["name"]}
        base_changes = [change for change in self.data["official_base_patch_changes"]
                        if change["section"].startswith("UNITS:") and
                        change["subject"] in names]
        changes = [change for change in self.data["official_mid_patch_changes"]
                   if change["kind"] == "champion" and change["subject"] in names]
        return dict(unit_id=unit_id, name=row["name"], name_en=row["name_en"],
                    cost=row["cost"], role=row["role"],
                    catalog_class=row["catalog_class"],
                    stats=row["stats"], stats_status=row["stats_status"],
                    ability=row["ability"], traits=linked_traits,
                    official_base_patch_changes=base_changes,
                    official_mid_patch_changes=changes,
                    mechanic_status=row["mechanic_status"])

    def effect(self, effect_id: str):
        if not isinstance(effect_id, str):
            return None
        row = self.data["effects"].get(effect_id)
        if row is None:
            return None
        names = {row["name"], row["name_en"]}
        base_changes = [change for change in self.data["official_base_patch_changes"]
                        if change["section"] in {"ITEMS", "EMBLEMS", "AUGMENTS", "WISPS"}
                        and change["subject"] in names]
        changes = [change for change in self.data["official_mid_patch_changes"]
                   if change["kind"] in {"item", "augment", "wisp"}
                   and change["subject"] in names]
        return dict(effect_id=effect_id, **row,
                    official_base_patch_changes=base_changes,
                    official_mid_patch_changes=changes)

    def verified_owned_context(self, state):
        """Attach exact owned identities only for a fresh, patch-bound state."""
        if (not isinstance(state, dict) or state.get("verified") is not True or
                state.get("perspective") != "self" or
                (state.get("set_key"), state.get("patch")) !=
                (self.set_key, self.patch) or
                type(state.get("age_ms")) not in (int, float) or
                not 0 <= state["age_ms"] <= 2000):
            return []
        result = []
        units = state.get("units")
        if not isinstance(units, list):
            return result
        for unit in units[:19]:
            if not isinstance(unit, dict) or unit.get("identity_verified") is not True:
                continue
            champion = self.champion(unit.get("unit_id"))
            if champion is None:
                continue
            raw_items = unit.get("items")
            if not isinstance(raw_items, list):
                raw_items = []
            items = [self.effect(identity) for identity in raw_items[:3]
                     if isinstance(identity, str)]
            result.append(dict(uid=unit.get("uid"), stars=unit.get("stars"),
                               zone=unit.get("zone"), champion=champion,
                               items=[item for item in items if item is not None]))
        return result

    def observed_shop_context(self, offers, owned_state=None):
        """Return a bounded reference for exact, readable shop identities."""
        result = []
        for offer in (offers if isinstance(offers, list) else [])[:5]:
            if not isinstance(offer, dict):
                continue
            if (offer.get("catalog_status") != "unique_name_bound" or
                    offer.get("status") != "offer_text_readable"):
                continue
            unit_id = offer.get("unit_id")
            if not isinstance(unit_id, str):
                continue
            row = self.champion(unit_id)
            if row is None or row["catalog_class"] != "shop":
                continue
            result.append(dict(slot=offer.get("slot"), **row))
        return dict(set_key=self.set_key, patch=self.patch,
                    knowledge_sha256=self.digest,
                    fact_type="patch_reference_not_observed_ownership",
                    combat_rules_verified=False,
                    offers=result,
                    verified_owned=self.verified_owned_context(owned_state),
                    economy_status=self.data["economy"]["status"])
