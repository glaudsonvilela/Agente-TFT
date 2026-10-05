"""Bounded, observable-state coaching. No spells or fabricated win rates.

Candidate legality is independent of the learned ranker. The numerical
objective measures attributes/economy; it is deliberately not a combat model.
Geometry and state validation live here; seasonal numbers live in the catalog.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path


FEATURES = (
    "roll",
    "composition",
    "position",
    "equip",
    "hp_pressure",
    "gold_fraction",
    "dps_gain",
    "ehp_gain",
    "formation_gain",
    "synergy_gain",
    "hit_estimate",
    "gold_spent_fraction",
    "interest_lost",
    "component_commitment",
    "urgency_gain",
)
SCOPE = "attribute_planning_without_abilities"


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def state_error(state, catalog):
    if not isinstance(state, dict):
        return "BOARD_STATE_MISSING"
    if (
        state.get("verified") is not True
        or state.get("perspective") != "self"
        or state.get("phase") != "planning"
        or state.get("complete") is not True
    ):
        return "BOARD_STATE_UNVERIFIED"
    if (state.get("patch"), state.get("set_key")) != (
        catalog["patch"],
        catalog["set_key"],
    ):
        return "BOARD_PATCH_MISMATCH"
    if not number(state.get("age_ms"), 0, 2000):
        return "BOARD_STATE_STALE"
    if not state.get("evidence_id"):
        return "BOARD_EVIDENCE_MISSING"
    for key, low, high in (("gold", 0, 300), ("hp", 1, 100), ("level", 1, 10)):
        if not integer(state.get(key), low, high):
            return "RESOURCE_UNVERIFIED"
    if state.get("augments") or state.get("seasonal"):
        return "SPECIAL_EFFECTS_UNSUPPORTED"
    units, inventory = state.get("units"), state.get("inventory")
    if (
        not isinstance(units, list)
        or not 1 <= len(units) <= 19
        or not isinstance(inventory, list)
        or len(inventory) > 10
    ):
        return "ROSTER_OR_INVENTORY_INVALID"
    ids, places = set(), set()
    for unit in units:
        if (
            not isinstance(unit, dict)
            or unit.get("identity_verified") is not True
            or not isinstance(unit.get("unit_id"), str)
            or unit["unit_id"] not in catalog["champions"]
            or not isinstance(unit.get("uid"), str)
            or unit["uid"] in ids
            or not integer(unit.get("stars"), 1, 3)
            or unit.get("permanent")
        ):
            return "UNIT_UNVERIFIED_OR_UNSUPPORTED"
        ids.add(unit["uid"])
        pos, zone = unit.get("position"), unit.get("zone")
        if zone == "board":
            if (
                not isinstance(pos, list)
                or len(pos) != 2
                or not integer(pos[0], 0, 3)
                or not integer(pos[1], 0, 6)
            ):
                return "POSITION_UNVERIFIED"
        elif zone == "bench":
            if not integer(pos, 0, 8):
                return "POSITION_UNVERIFIED"
        else:
            return "POSITION_UNVERIFIED"
        place = (zone, tuple(pos) if isinstance(pos, list) else pos)
        if place in places:
            return "DUPLICATE_POSITION"
        places.add(place)
        items = unit.get("items")
        if not isinstance(items, list) or len(items) > 3:
            return "ITEMS_UNVERIFIED"
        for item in items:
            if item not in catalog["items"]:
                return "ITEM_EFFECT_UNSUPPORTED"
            if catalog["items"][item].get("unique") and items.count(item) > 1:
                return "UNIQUE_ITEM_CONFLICT"
    if sum(u["zone"] == "board" for u in units) > state["level"]:
        return "BOARD_CAPACITY_INVALID"
    if any(not isinstance(i, str) or i not in catalog["items"] for i in inventory):
        return "ITEM_EFFECT_UNSUPPORTED"
    copies = Counter()
    for unit in units:
        copies[catalog["champions"][unit["unit_id"]]["pool_identity"]] += 3 ** (
            unit["stars"] - 1
        )
    for champion, count in copies.items():
        cost = catalog["shop_champions"].get(champion, {}).get("cost")
        if cost and count > catalog["economy"]["pool_by_cost"][str(cost)]:
            return "COPY_COUNT_REQUIRES_SPECIAL_EFFECT"
    return None


def attributes(unit, catalog):
    base = catalog["champions"][unit["unit_id"]]["combat"]
    stats = {
        k: (v[unit["stars"] - 1] if isinstance(v, list) else v)
        for k, v in base.items()
        if isinstance(v, (int, float, list))
    }
    original = dict(stats)
    # Static modifiers only. Dynamic hooks/spells are not silently approximated.
    for item in unit["items"]:
        for mod in catalog["items"][item]["modifiers"]:
            key, value = mod["stat"], mod["value"]
            if mod["mode"] == "flat":
                stats[key] = stats.get(key, 0) + value
            elif mod["mode"] == "base_pct":
                stats[key] = stats.get(key, 0) + original.get(key, 0) * value
    for item in unit["items"]:
        for mod in catalog["items"][item]["modifiers"]:
            if mod["mode"] == "bonus_pct":
                stats[mod["stat"]] = stats.get(mod["stat"], 0) * (1 + mod["value"])
    crit = min(1, stats.get("crit_chance", 0.25))
    dps = (
        stats["ad"]
        * stats["attack_speed"]
        * (1 + crit * (stats.get("crit_multiplier", 1.4) - 1))
    )
    dps *= 1 + stats.get("damage_amp", 0)
    ehp = stats["hp"] * (1 + (stats["armor"] + stats["mr"]) / 200)
    return dps, ehp, stats["range"]


def board_features(units, catalog):
    board = [u for u in units if u["zone"] == "board"]
    dps = ehp = placement = 0.0
    traits, seen = Counter(), set()
    tanks = [u for u in board if attributes(u, catalog)[2] <= 1]
    for unit in board:
        damage, health, reach = attributes(unit, catalog)
        row, col = unit["position"]  # row zero is the front row
        dps += damage
        ehp += health
        if reach > 1:
            cover = any(
                t["position"][0] < row and abs(t["position"][1] - col) <= 1
                for t in tanks
            )
            placement += damage * (row / 3 + 0.5 * cover)
        else:
            placement += damage * (1 - row / 3)
        if unit["unit_id"] not in seen:
            traits.update(catalog["champions"][unit["unit_id"]].get("traits", []))
            seen.add(unit["unit_id"])
    # Affinity only: this does not assert that a trait breakpoint is activated.
    affinity = sum(max(0, n - 1) for n in traits.values())
    return dps, ehp, placement, affinity


def objective(features):
    """Explicit project-designed teacher, not labels from human demonstrations."""
    f = dict(zip(FEATURES, features))
    gain = (
        2 * f["dps_gain"]
        + f["ehp_gain"]
        + 0.45 * f["formation_gain"]
        + 0.12 * f["synergy_gain"]
    )
    return (
        gain * (1 + 0.5 * f["hp_pressure"])
        + f["urgency_gain"]
        + f["hit_estimate"] * (0.4 + f["hp_pressure"])
        - 0.8 * f["gold_spent_fraction"]
        - 0.15 * f["interest_lost"]
        - 0.12 * f["component_commitment"]
    )


def candidate(kind, action, before, after, state, **extra):
    hp_pressure = max(0, (60 - state["hp"]) / 60)
    features = [float(kind == k) for k in ("roll", "composition", "position", "equip")]
    gains = [
        max(-10, min(10, (after[i] - before[i]) / max(1, before[i]))) for i in range(4)
    ]
    features += [
        hp_pressure,
        state["gold"] / 100,
        *gains,
        extra.get("hit", 0),
        extra.get("spent", 0) / max(10, state["gold"]),
        extra.get("interest", 0),
        extra.get("commitment", 0),
        extra.get("urgency", 0),
    ]
    return dict(
        family=kind,
        action=action,
        features=features,
        teacher_utility=objective(features),
    )


def alternatives(state, catalog):
    error = state_error(state, catalog)
    if error:
        raise ValueError(error)
    units, inventory = state["units"], state["inventory"]
    before = board_features(units, catalog)
    choices = [candidate("hold", {"type": "hold"}, before, before, state)]
    board = [u for u in units if u["zone"] == "board"]
    bench = [u for u in units if u["zone"] == "bench"]
    # Evaluate every legal single move/swap. No random-position advice.
    for unit in board:
        for row, col in itertools.product(range(4), range(7)):
            if unit["position"] == [row, col]:
                continue
            updated = deepcopy(units)
            moved = next(u for u in updated if u["uid"] == unit["uid"])
            other = next(
                (
                    u
                    for u in updated
                    if u["zone"] == "board" and u["position"] == [row, col]
                ),
                None,
            )
            if other:
                other["position"] = moved["position"]
            moved["position"] = [row, col]
            action = dict(
                type="position",
                uid=unit["uid"],
                unit_id=unit["unit_id"],
                destination=[row, col],
                swap_uid=other["uid"] if other else None,
            )
            choices.append(
                candidate(
                    "position", action, before, board_features(updated, catalog), state
                )
            )
    # Build the current composition from actually owned pieces; no imaginary purchases.
    for incoming in bench:
        outgoing = board if len(board) >= state["level"] else [None]
        for removed in outgoing:
            updated = deepcopy(units)
            add = next(u for u in updated if u["uid"] == incoming["uid"])
            occupied = {tuple(u["position"]) for u in board}
            reach = attributes(incoming, catalog)[2]
            destination = (
                removed["position"]
                if removed
                else next(
                    [r, c]
                    for r in ([3, 2, 1, 0] if reach > 1 else [0, 1, 2, 3])
                    for c in range(7)
                    if (r, c) not in occupied
                )
            )
            add["zone"], add["position"] = "board", destination
            if removed:
                old = next(u for u in updated if u["uid"] == removed["uid"])
                old["zone"], old["position"] = "bench", incoming["position"]
            choices.append(
                candidate(
                    "composition",
                    dict(
                        type="composition",
                        incoming=incoming["uid"],
                        unit_id=incoming["unit_id"],
                        outgoing=removed["uid"] if removed else None,
                        outgoing_id=removed["unit_id"] if removed else None,
                        destination=destination,
                    ),
                    before,
                    board_features(updated, catalog),
                    state,
                )
            )
    # Compare an item with keeping it; components are only committed as a known recipe.
    options = [
        (item, [i])
        for i, item in enumerate(inventory)
        if not catalog["items"][item]["component"]
    ]
    for i, j in itertools.combinations(range(len(inventory)), 2):
        recipe = "+".join(sorted((inventory[i], inventory[j])))
        result = catalog["recipes"].get(recipe)
        if result in catalog["items"]:
            options.append((result, [i, j]))
    for item, slots in options:
        for unit in board:
            if (
                len(unit["items"]) >= 3
                or any(catalog["items"][x]["component"] for x in unit["items"])
                or (catalog["items"][item]["unique"] and item in unit["items"])
            ):
                continue
            updated = deepcopy(units)
            next(u for u in updated if u["uid"] == unit["uid"])["items"].append(item)
            choices.append(
                candidate(
                    "equip",
                    dict(
                        type="equip",
                        uid=unit["uid"],
                        unit_id=unit["unit_id"],
                        item_id=item,
                        inventory_slots=slots,
                        components=[inventory[i] for i in slots],
                    ),
                    before,
                    board_features(updated, catalog),
                    state,
                    commitment=int(len(slots) == 2),
                )
            )
    choices += roll_alternatives(state, catalog, before)
    return choices


def roll_alternatives(state, catalog, before):
    """Bounded spending for one-copy upgrades. Pool estimates are named assumptions.

    Never assume unobserved opposing holdings are zero without marking uncertainty.
    Stop after each new shop: advice must be recomputed before another refresh.
    """
    copies = Counter()
    for u in state["units"]:
        identity = catalog["champions"][u["unit_id"]]["pool_identity"]
        copies[identity] += 3 ** (u["stars"] - 1)
    rules, gold = catalog["economy"], state["gold"]
    reserve = 50 if state["hp"] > 50 else 30 if state["hp"] > 25 else 10
    result = []
    for champion, n in copies.items():
        data = catalog["champions"].get(champion)
        if data is None:
            continue
        if (
            n not in (2, 8)
            or data.get("purchase_blocker")
            or data["cost"] not in (1, 2, 3, 4, 5)
        ):
            continue
        if not any(
            u["zone"] == "board"
            and catalog["champions"][u["unit_id"]]["pool_identity"] == champion
            for u in state["units"]
        ):
            continue
        cost = data["cost"]
        available = gold - reserve - cost
        rolls = min(5, available // rules["reroll_cost"])
        if rolls < 1:
            continue
        tier = [k for k, v in catalog["shop_champions"].items() if v["cost"] == cost]
        pool = rules["pool_by_cost"][str(cost)]
        remaining = max(0, pool - n)
        denominator = max(
            remaining, len(tier) * pool - sum(v for k, v in copies.items() if k in tier)
        )
        chance_slot = (
            rules["shop_odds"][str(state["level"])][cost - 1]
            * remaining
            / max(1, denominator)
        )
        if chance_slot <= 0:
            continue
        hit = 1 - (1 - chance_slot) ** (rolls * 5)
        spent = rolls * rules["reroll_cost"] + cost
        # Upgrade urgency rises with HP pressure, but does not invent fight results.
        action = dict(
            type="roll",
            unit_id=champion,
            rolls_max=rolls,
            reserve_gold=reserve,
            purchase_reserve=cost,
            gold_budget=spent,
            target_stars=2 if n == 2 else 3,
            stop="target_found_or_budget_or_board_change",
            probability_estimate=hit,
            probability_basis="independent_slots_full_pool_minus_own_copies",
            hidden_pool_observed=False,
        )
        result.append(
            candidate(
                "roll",
                action,
                before,
                before,
                state,
                hit=hit,
                spent=spent,
                interest=min(5, gold // 10) - min(5, (gold - spent) // 10),
                urgency=max(0, (50 - state["hp"]) / 100),
            )
        )
    return result


class StrategicCoach:
    def __init__(self, root):
        self.root = Path(root)
        manifest = json.loads((self.root / "configs/coaching/active.json").read_text())
        raw = self._read(manifest["catalog"])
        self.catalog = json.loads(raw)
        self.catalog_sha256 = hashlib.sha256(raw).hexdigest()
        self.model = None
        self.model_error = None
        if manifest.get("model"):
            try:
                from .strategy_ranker import StrategyRanker

                self.model = StrategyRanker(
                    json.loads(self._read(manifest["model"])), self.catalog_sha256
                )
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.model_error = str(exc)

    def _read(self, entry):
        path = (self.root / entry["path"]).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("coaching artifact escapes package")
        raw = path.read_bytes()
        if (
            len(raw) > 4 * 1024 * 1024
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
        ):
            raise ValueError("coaching artifact identity mismatch")
        return raw

    def evaluate(self, state):
        error = state_error(state, self.catalog)
        result = dict(
            scope=SCOPE,
            abilities_used=False,
            catalog_sha256=self.catalog_sha256,
            learned_ranker=self.model is not None,
            model_error=self.model_error,
            recommendations=[],
            blockers=[],
        )
        if error:
            result["blockers"] = [error]
            return result
        choices = alternatives(state, self.catalog)
        try:
            scores = (
                self.model.predict([c["features"] for c in choices])
                if self.model
                else [c["teacher_utility"] for c in choices]
            )
        except ValueError as exc:
            result["model_error"] = str(exc)
            result["learned_ranker"] = False
            scores = [c["teacher_utility"] for c in choices]
        for family in ("roll", "composition", "position", "equip"):
            options = [
                i
                for i, c in enumerate(choices)
                if c["family"] == family and c["teacher_utility"] >= 0.03
            ]
            if not options:
                result["blockers"].append(
                    family.upper() + "_NO_POSITIVE_SUPPORTED_ALTERNATIVE"
                )
                continue
            index = max(options, key=lambda i: scores[i])
            selected = deepcopy(choices[index])
            selected.update(
                rank_score=float(scores[index]),
                evidence_id=state["evidence_id"],
                confidence_basis="verified_inputs_not_action_success",
                scope=SCOPE,
            )
            selected["text"] = self.explain(selected["action"])
            result["recommendations"].append(selected)
        result["recommendations"].sort(key=lambda c: c["rank_score"], reverse=True)
        result["candidates_evaluated"] = len(choices)
        return result

    def explain(self, action):
        name = self.catalog["champions"][action["unit_id"]]["name"]
        if action["type"] == "roll":
            return (
                f'Role até {action["rolls_max"]} vezes procurando {name}. '
                f'Pare ao encontrar ou ao chegar a {action["reserve_gold"] + action["purchase_reserve"]} de ouro; '
                f'reserve {action["purchase_reserve"]} para comprar. Confira a disputa antes de gastar.'
            )
        if action["type"] == "composition":
            if action["outgoing_id"]:
                old = self.catalog["champions"][action["outgoing_id"]]["name"]
                return f"Coloque {name} no lugar de {old}; mantenha {old} no banco."
            return f"Coloque {name} no tabuleiro para preencher a vaga disponível."
        if action["type"] == "position":
            row, col = action["destination"]
            swap = (
                " Troque com a unidade que ocupa essa casa."
                if action["swap_uid"]
                else ""
            )
            return f"Mova {name} para a linha {row + 1}, coluna {col + 1}, contando da frente e da esquerda.{swap}"
        item = self.catalog["items"][action["item_id"]]["name"]
        if len(action["inventory_slots"]) == 2:
            parts = [self.catalog["items"][i]["name"] for i in action["components"]]
            return f"Combine {parts[0]} e {parts[1]} em {name} para formar {item}."
        return f"Equipe {item} em {name}."
