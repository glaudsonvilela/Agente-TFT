"""Build a patch-bound, read-only TFT knowledge pack from pinned snapshots.

The pack is reference data for a strategy model, not an executable combat
simulator. In particular, ability placeholders are kept verbatim and official
mid-patch changes are annotations rather than guessed substitutions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SET_KEY = "TFTSet18"
PATCH = "18.4B"
PATCH_NOTES = "https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/"


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def read(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def unique(rows, key="apiName"):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result:
            raise ValueError(f"duplicate catalog identity: {identity}")
        result[identity] = row
    return result


def set_data(source):
    matches = [row for row in source["setData"] if row.get("number") == 18]
    if len(matches) != 1:
        raise ValueError("expected one Set 18 catalog")
    return matches[0]


def build(en_path, pt_path, roster_path, deltas_path, base_deltas_path,
          economy_path):
    en, en_hash = read(en_path)
    pt, pt_hash = read(pt_path)
    roster, roster_hash = read(roster_path)
    deltas, delta_hash = read(deltas_path)
    base_deltas, base_delta_hash = read(base_deltas_path)
    economy_catalog, economy_hash = read(economy_path)
    en_set, pt_set = set_data(en), set_data(pt)
    if en_set["mutator"] != "TFTSet18" or pt_set["mutator"] != "TFTSet18":
        raise ValueError("unexpected set mutator")
    if (roster.get("set"), len(roster.get("rows", []))) != (SET_KEY, 65):
        raise ValueError("reviewed 65-unit shop roster required")
    if (deltas.get("set_key"), deltas.get("patch"), deltas.get("source_url")) != (
            SET_KEY, PATCH, PATCH_NOTES):
        raise ValueError("official deltas belong to another patch")
    if (base_deltas.get("set_key"), base_deltas.get("patch"),
            base_deltas.get("source_url")) != (SET_KEY, "18.4", PATCH_NOTES):
        raise ValueError("official base deltas belong to another patch")
    if (economy_catalog.get("set_key"), economy_catalog.get("patch"),
            economy_catalog.get("revision")) != (
            SET_KEY, "18.3", "18.3B-20260928"):
        raise ValueError("working economy reference must be the 18.3B pack")
    shop = {row["game_id"]: row for row in roster["rows"]}
    if len(shop) != 65:
        raise ValueError("duplicate shop identity")
    en_units = unique(en_set["champions"])
    pt_units = unique(pt_set["champions"])
    en_traits = unique(en_set["traits"])
    pt_traits = unique(pt_set["traits"])
    en_trait_names = {row["name"]: identity for identity, row in en_traits.items()}
    pt_trait_names = {row["name"]: identity for identity, row in pt_traits.items()}
    if len(en_trait_names) != len(en_traits) or len(pt_trait_names) != len(pt_traits):
        raise ValueError("trait display names are not unique")
    en_items = unique(en["items"])
    pt_items = unique(pt["items"])
    if set(en_units) != set(pt_units) or set(en_traits) != set(pt_traits):
        raise ValueError("locale catalogs have different unit or trait IDs")
    if not set(shop) <= set(pt_units):
        raise ValueError("shop roster has unknown Set 18 IDs")

    champions = {}
    for identity, row in sorted(pt_units.items()):
        english = en_units[identity]
        trait_ids = [pt_trait_names[name] for name in row.get("traits") or []]
        en_trait_ids = [en_trait_names[name] for name in english.get("traits") or []]
        if row.get("cost") != english.get("cost") or trait_ids != en_trait_ids:
            raise ValueError(f"locale gameplay mismatch: {identity}")
        ability = row.get("ability") or {}
        champions[identity] = dict(
            name=row.get("name"), name_en=english.get("name"), cost=row.get("cost"),
            role=row.get("role"), traits=trait_ids,
            stats=row.get("stats") or {},
            stats_status="provider_snapshot_not_reconciled_with_official_18.4_changes",
            ability=dict(name=ability.get("name"), description=ability.get("desc"),
                         variables=ability.get("variables") or []),
            catalog_class="shop" if identity in shop else "set_variant_or_nonshop",
            mechanic_status="reference_only_not_executable",
        )
    incomplete_shop = [identity for identity in shop if not (
        champions[identity]["traits"] and champions[identity]["stats"] and
        champions[identity]["ability"]["name"] and
        champions[identity]["ability"]["description"])]
    if incomplete_shop:
        raise ValueError(f"incomplete shop champion records: {incomplete_shop}")
    traits = {}
    for identity, row in sorted(pt_traits.items()):
        english = en_traits[identity]
        tiers = [{"minimum": tier.get("minUnits"), "maximum": tier.get("maxUnits"),
                  "variables": tier.get("variables") or {}}
                 for tier in row.get("effects") or []]
        traits[identity] = dict(name=row.get("name"), name_en=english.get("name"),
                                description=row.get("desc"), tiers=tiers,
                                mechanic_status="reference_only_not_executable")
    if not all(set(row["traits"]) <= set(traits) for row in champions.values()):
        raise ValueError("champion refers to unknown trait")

    # Set-scoped effects include Wisps and set-specific items. Common TFT_Item
    # entries include the reusable core item catalog. Other historical items
    # are excluded, even if they happen to be present in the global export.
    set_items = set(pt_set["items"])
    core_items = {key for key in pt_items if key.startswith("TFT_Item_")}
    augment_ids = set(pt_set["augments"])
    selected = set_items | core_items | augment_ids
    if not selected <= set(pt_items) or not selected <= set(en_items):
        raise ValueError("set item or augment missing from a locale")
    effects = {}
    for identity in sorted(selected):
        row, english = pt_items[identity], en_items[identity]
        effects[identity] = dict(
            name=row.get("name"), name_en=english.get("name"),
            description=row.get("desc"), variables=row.get("effects") or {},
            composition=row.get("composition") or [],
            associated_traits=row.get("associatedTraits") or [],
            categories=sorted(filter(None, ["augment" if identity in augment_ids else None,
                                            "set_item_or_wisp" if identity in set_items else None,
                                            "core_item" if identity in core_items else None])),
            mechanic_status="reference_only_not_executable",
            availability="unknown_until_observed_in_match",
        )
    changes = deltas["changes"]
    if not isinstance(changes, list) or len(changes) < 10:
        raise ValueError("incomplete B-patch annotation")
    for row in changes:
        if row.get("kind") not in {"champion", "trait", "item", "augment", "wisp", "rule"}:
            raise ValueError("invalid delta kind")
        if not isinstance(row.get("subject"), str) or not isinstance(row.get("change"), str):
            raise ValueError("delta requires subject and change")
    if not isinstance(base_deltas.get("changes"), list) or len(base_deltas["changes"]) < 80:
        raise ValueError("incomplete official 18.4 numeric changes")

    body = dict(schema_version=1, set_key=SET_KEY, patch=PATCH,
        purpose="strategy_reference_and_future_training_features",
        runtime_combat_rules_verified=False,
        source=dict(
            community_dragon_build="16.20",
            en_us_sha256=en_hash, pt_br_sha256=pt_hash,
            community_dragon_url="https://raw.communitydragon.org/16.20/cdragon/tft/pt_br.json",
            riot_data_dragon_version=roster["source_riot_data_dragon"]["version"],
            riot_roster_url=roster["source_riot_data_dragon"]["url"],
            riot_roster_sha256=roster["source_riot_data_dragon"]["sha256_json"],
            reconciled_roster_sha256=roster_hash,
            official_patch_notes_url=PATCH_NOTES,
            official_delta_file_sha256=delta_hash,
            official_base_delta_file_sha256=base_delta_hash),
            economy=dict(status="working_parameters_unverified_for_18.4B",
                         source_patch="18.3B", source_sha256=economy_hash,
                         parameters=economy_catalog["economy"]),
        coverage=dict(shop_champions=len(shop), set_champion_entries=len(champions),
                      traits=len(traits), set_items=len(set_items),
                      core_items=len(core_items), augments=len(augment_ids),
                      unresolved_ability_placeholders=sum(
                          "@" in (row["ability"]["description"] or "")
                          for row in champions.values())),
        champions=champions, traits=traits, effects=effects,
        official_base_patch_changes=base_deltas["changes"],
        official_mid_patch_changes=changes,
        limitations=["Ability text and variables are reference data, not executable combat rules.",
                     "The provider snapshot may precede some 18.4B changes; official deltas are separate.",
                     "Catalog membership does not prove an augment or Wisp is enabled in a given lobby.",
                     "Economy odds and pool sizes require independent 18.4B client verification."])
    return body


def write_pack(body, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = canonical(body)
    manifest = dict(schema_version=1, set_key=SET_KEY, patch=PATCH,
                    knowledge_file="knowledge.json",
                    knowledge_sha256=hashlib.sha256(data).hexdigest(),
                    source=body["source"], coverage=body["coverage"],
                    runtime_promoted=False, model_trained=False)
    (output / "knowledge.json").write_bytes(data)
    (output / "manifest.json").write_bytes(canonical(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("en", "pt", "roster", "deltas", "base-deltas", "economy", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(write_pack(build(args.en, args.pt, args.roster, args.deltas,
                                     args.base_deltas, args.economy),
                                args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
