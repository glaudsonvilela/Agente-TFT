"""Planning contracts shared by seasons; all balance values come from content."""

from copy import deepcopy
import math

from .state import IllegalAction, UnsupportedRule


def positive_integer(value, label, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise UnsupportedRule(f"invalid {label}")
    return value


def shop_weights(content, level):
    weights = content["economy"]["shop_odds"].get(str(level))
    if (
        not isinstance(weights, (list, tuple))
        or len(weights) != 5
        or any(
            type(w) not in (int, float) or not math.isfinite(w) or not 0 <= w <= 1
            for w in weights
        )
        or abs(sum(weights) - 1) > 1e-6
    ):
        raise UnsupportedRule("verified shop odds unavailable for level")
    return weights


def validate_economy(content):
    rules = content.get("economy")
    if not isinstance(rules, dict):
        raise UnsupportedRule("economy binding unavailable")
    for key in ("inventory_slots", "xp_cost", "xp_amount"):
        positive_integer(rules.get(key), key)
    positive_integer(rules.get("reroll_cost"), "reroll cost", zero=True)
    curve = rules.get("xp_to_next")
    if not isinstance(curve, dict):
        raise UnsupportedRule("XP curve unavailable")
    for level, value in curve.items():
        if (
            not isinstance(level, str)
            or not level.isdigit()
            or int(level) < 1
            or str(int(level)) != level
        ):
            raise UnsupportedRule("invalid XP level")
        positive_integer(value, "XP threshold")
    if curve and sorted(map(int, curve)) != list(range(1, max(map(int, curve)) + 1)):
        raise UnsupportedRule("noncontiguous XP curve")
    if not isinstance(rules.get("shop_odds"), dict):
        raise UnsupportedRule("shop odds unavailable")
    for level in rules["shop_odds"]:
        if (
            not isinstance(level, str)
            or not level.isdigit()
            or int(level) < 1
            or str(int(level)) != level
        ):
            raise UnsupportedRule("invalid shop level")
        shop_weights(content, level)
    if "pool_by_cost" in rules:
        if (
            not isinstance(rules["pool_by_cost"], dict)
            or not rules["pool_by_cost"]
            or set(rules["pool_by_cost"]) - {"1", "2", "3", "4", "5"}
        ):
            raise UnsupportedRule("invalid pool size table")
        for size in rules["pool_by_cost"].values():
            positive_integer(size, "pool size")
    if "sale_prices_by_cost" in rules:
        if not isinstance(rules["sale_prices_by_cost"], dict):
            raise UnsupportedRule("sale price table required")
        for cost, prices in rules["sale_prices_by_cost"].items():
            if cost not in {"1", "2", "3", "4", "5"} or not isinstance(prices, dict):
                raise UnsupportedRule("invalid sale price cost")
            for stars, value in prices.items():
                if stars not in {"1", "2", "3"}:
                    raise UnsupportedRule("unimplemented sale star level")
                positive_integer(value, "sale price", zero=True)


def grant_xp(player, amount, content):
    """Consume each level's threshold exactly once, preserving overflow."""
    positive_integer(amount, "XP grant", zero=True)
    validate_economy(content)
    player.xp += amount
    curve = content["economy"]["xp_to_next"]
    while str(player.level) in curve and player.xp >= curve[str(player.level)]:
        player.xp -= curve[str(player.level)]
        player.level += 1


def pool_identity(champion, content):
    spec = content["champions"].get(champion)
    if spec is None:
        raise UnsupportedRule("unknown pool champion")
    identity = spec.get("pool_identity", champion)
    base = content["champions"].get(identity)
    if (
        base is None
        or base.get("pool_identity", identity) != identity
        or base["cost"] != spec["cost"]
    ):
        raise UnsupportedRule("invalid shared pool identity")
    return identity


def return_copies(pool, champion, copies, content):
    positive_integer(copies, "returned copies")
    identity = pool_identity(champion, content)
    if identity not in pool:
        raise UnsupportedRule("pool identity missing from world")
    pool[identity] += copies


def accounted_copies(world, content):
    """Remaining + every reserved shop offer + every owned star equivalent."""
    totals = dict(world.pool)
    for player in world.players:
        for unit in player.units:
            identity = pool_identity(unit.champion, content)
            if identity not in totals:
                raise UnsupportedRule("owned unit has no pool identity")
            if unit.stars > 3:
                raise UnsupportedRule(
                    "four-star copy provenance requires an explicit handler"
                )
            totals[identity] += 3 ** (unit.stars - 1)
        for offer in player.shop:
            if offer is None:
                continue
            if offer.kind != "champion":
                raise UnsupportedRule("seasonal offer reservation handler unavailable")
            identity = pool_identity(offer.entity, content)
            if identity not in totals:
                raise UnsupportedRule("offered unit has no pool identity")
            totals[identity] += 1
    return totals


def validate_pool(world, content):
    for identity in world.pool:
        if pool_identity(identity, content) != identity:
            raise UnsupportedRule("variant must share its canonical pool")
    if world.pool_totals is not None:
        if not isinstance(world.pool_totals, dict) or any(
            type(n) is not int or n < 0 for n in world.pool_totals.values()
        ):
            raise IllegalAction("invalid pool totals")
        if accounted_copies(world, content) != world.pool_totals:
            raise IllegalAction("champion copies are not conserved")


def new_planning_probe(players, content, seed=0):
    """Build an explicitly limited ordinary-shop snapshot, never a full match.

    Seasonal shop events and form selection are not inferred from a snapshot.
    This entry point permits isolated economy tests with an audited pool ledger.
    """
    from .state import World, validate_world

    validate_economy(content)
    sizes = content["economy"].get("pool_by_cost")
    if not sizes:
        raise UnsupportedRule("pool sizes unavailable")
    pool = {}
    for champion, spec in content["champions"].items():
        identity = pool_identity(champion, content)
        pool[identity] = positive_integer(sizes.get(str(spec["cost"])), "pool size")
    world = World(
        deepcopy(players),
        pool,
        seed=seed,
        rules_scope="ordinary_shop_probe",
        pool_totals=dict(pool),
    )
    accounted = accounted_copies(world, content)
    for identity, total in accounted.items():
        world.pool[identity] -= total - world.pool_totals[identity]
    validate_world(world, content)
    return world
