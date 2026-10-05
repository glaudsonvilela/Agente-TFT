"""Extract the separate, ability-free coaching catalog from sealed source data.

This does not upgrade incomplete combat bindings to validated combat programs.
The raw attributes fallback is named explicitly and excludes missing stats.
"""

import argparse
import hashlib
import json
from pathlib import Path


def build(content_path, release, profile_path):
    raw = Path(content_path).read_bytes()
    content = json.loads(raw)
    profile = json.loads(Path(profile_path).read_text())
    units = json.loads((Path(release) / "units.json").read_text())["champions"]
    out = dict(
        schema_version=1,
        set_key="TFTSet18",
        patch=content["catalog_patch"],
        revision=content["patch"],
        scope="attribute_planning_without_abilities",
        source_content_sha256=hashlib.sha256(raw).hexdigest(),
        release_sha256=content["release_sha256"],
        economy=content["economy"],
        champions={},
        items={},
        recipes=content["recipes"],
        excluded_champions={},
        shop_champions={},
        limitations=[
            "Attribute utility is a designed objective, not a combat win probability.",
            "No champion abilities, augment interactions, seasonal rewards or hidden opponent state.",
            "Only bound item handlers and recipes are considered.",
        ],
    )
    for unit in units:
        key = unit["api_name"]
        entry = content["champions"][key]
        if entry.get("combat"):
            out["champions"][key] = {
                k: entry.get(k)
                for k in ("name", "cost", "combat", "traits", "purchase_blocker")
            }
        else:
            s = unit["stats"]
            if any(
                type(s.get(k)) not in (int, float)
                for k in (
                    "hp",
                    "damage",
                    "armor",
                    "magicResist",
                    "attackSpeed",
                    "range",
                )
            ):
                out["excluded_champions"][key] = "missing numerical base attribute"
                continue
            out["champions"][key] = dict(
                name=unit["name"],
                cost=unit["cost"],
                traits=entry.get("traits", []),
                purchase_blocker=entry.get("purchase_blocker"),
                attribute_source="sealed_base_catalog_18.3",
                combat=dict(
                    hp=[s["hp"] * v for v in profile["star_multipliers"]["hp"]],
                    ad=[s["damage"] * v for v in profile["star_multipliers"]["ad"]],
                    armor=s["armor"],
                    mr=s["magicResist"],
                    attack_speed=s["attackSpeed"],
                    range=s["range"],
                    ap=profile["base_ap"],
                    crit_chance=s.get("critChance", 0.25),
                    crit_multiplier=s.get("critMultiplier", 1.4),
                ),
            )
        out["champions"][key]["pool_identity"] = entry.get("pool_identity", key)
    for key, entry in content["champions"].items():
        if (
            key == entry.get("pool_identity", key)
            and not entry.get("purchase_blocker")
            and entry["cost"] in (1, 2, 3, 4, 5)
        ):
            out["shop_champions"][key] = dict(cost=entry["cost"])
    for key, entry in content["items"].items():
        if not entry.get("unsupported"):
            out["items"][key] = {
                k: entry.get(k) for k in ("name", "component", "modifiers", "unique")
            }
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    for name in ("content", "release", "profile", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.content, args.release, args.profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
