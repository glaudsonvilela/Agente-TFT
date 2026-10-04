"""Conditional offer checks, without inventing a partial Wisp distribution."""

from .economy import positive_integer
from .state import IllegalAction, UnsupportedRule


def round_key(value):
    if not isinstance(value, str):
        raise UnsupportedRule("invalid Wisp round bound")
    parts = value.split("-")
    if len(parts) != 2 or any(not p.isdigit() or int(p) < 1 for p in parts):
        raise UnsupportedRule("invalid Wisp round bound")
    return tuple(map(int, parts))


def wisp_cost(spec, empowered):
    key = "blossom_cost" if empowered else "cost"
    if key not in spec:
        raise UnsupportedRule("missing variant-specific Wisp price")
    return positive_integer(spec[key], "Wisp cost", zero=True)


def require_eligible(player, name, spec, rules, *, empowered, coven_active):
    """Validate the offered snapshot, after a refresh has been paid for.

    This cannot prove that Beggar was the only eligible offer, select a Wisp,
    or infer offer history that predates an observed replay snapshot.
    """
    s = player.seasonal
    if s["round_kind"] != "pvp":
        raise IllegalAction("Wisps require PvP planning")
    e = spec.get("eligibility")
    fields = {
        "first_round",
        "last_round",
        "missing_hp_min",
        "hp_min",
        "streak_min",
        "streak_max",
        "one_star_min",
        "coven_inactive",
        "cooldown_rounds",
        "gold_min",
    }
    if (
        not isinstance(e, dict)
        or set(e) - fields
        or not {"first_round", "last_round"} <= set(e)
    ):
        raise UnsupportedRule("unbound Wisp eligibility condition")
    for key in (
        "missing_hp_min",
        "hp_min",
        "one_star_min",
        "cooldown_rounds",
        "gold_min",
    ):
        if key in e:
            positive_integer(e[key], key, zero=True)
    for key in ("streak_min", "streak_max"):
        if key in e and type(e[key]) is not int:
            raise UnsupportedRule("invalid Wisp streak bound")
    if "coven_inactive" in e and type(e["coven_inactive"]) is not bool:
        raise UnsupportedRule("invalid Wisp Coven condition")
    current = round_key(s["round"])
    if current < round_key(e.get("first_round")) or (
        e.get("last_round") is not None and current > round_key(e["last_round"])
    ):
        raise IllegalAction("Wisp outside its round window")
    if player.gold < wisp_cost(spec, empowered):
        raise IllegalAction("insufficient gold for offered Wisp")
    if player.gold < e.get("gold_min", 0):
        raise IllegalAction("Wisp requires more gold before purchase")
    if rules["hp_cap"] - player.hp < e.get("missing_hp_min", 0):
        raise IllegalAction("Wisp requires more missing health")
    if player.hp < e.get("hp_min", 0):
        raise IllegalAction("Wisp requires more remaining health")
    if ("streak_min" in e and player.streak < e["streak_min"]) or (
        "streak_max" in e and player.streak > e["streak_max"]
    ):
        raise IllegalAction("Wisp incompatible with current streak")
    if e.get("coven_inactive") and coven_active:
        raise IllegalAction("Wisp unavailable with active Coven")
    if sum(u.stars == 1 for u in player.units) < e.get("one_star_min", 0):
        raise IllegalAction("Wisp requires more one-star champions")
    if e.get("cooldown_rounds"):
        history = s["offer_history"]
        if history is None:
            raise UnsupportedRule("Wisp cooldown requires observed offer history")
        if name in history and s["round_index"] - history[name] < e["cooldown_rounds"]:
            raise IllegalAction("Wisp still on round cooldown")
