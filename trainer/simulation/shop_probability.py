"""Exact next ordinary shop probabilities, conditional on a supplied shared pool.

The dynamic program uses the same cost-tier renormalization and copy-weighted
sampling as the planning shop. No independent-slot approximation and no claim
that the hidden reservations in other players' shops are observable.
"""

from functools import lru_cache

from .economy import pool_identity, return_copies, shop_weights
from .state import IllegalAction, UnsupportedRule, validate_world


def next_shop_probability(world, seat, champion, content, *, at_least=1, slots=5):
    validate_world(world, content)
    if type(seat) is not int or not 0 <= seat < len(world.players):
        raise IllegalAction("invalid shop seat")
    if (
        type(slots) is not int
        or not 1 <= slots <= 5
        or type(at_least) is not int
        or not 1 <= at_least <= slots
    ):
        raise IllegalAction("invalid next-shop target count")
    p = world.players[seat]
    if world.round_phase != "planning" or p.phase != "planning" or p.hp <= 0:
        raise IllegalAction("player cannot refresh shop")
    identity = pool_identity(champion, content)
    if identity != champion or content["champions"][champion].get("purchase_blocker"):
        raise UnsupportedRule("form-specific shop probability unavailable")
    cost = content["champions"][identity]["cost"]
    if type(cost) is not int or not 1 <= cost <= 5:
        raise UnsupportedRule("ordinary shop requires a declared 1..5 cost")
    weights = shop_weights(content, p.level)
    pool = dict(world.pool)
    # Refresh returns this player's unbought offers before drawing a new shop.
    for offer in p.shop:
        if offer is None:
            continue
        if offer.kind != "champion":
            raise UnsupportedRule("special shop probability unavailable")
        return_copies(pool, offer.entity, 1, content)
    counts = tuple(
        sum(n for key, n in pool.items() if content["champions"][key]["cost"] == cost)
        for cost in range(1, 6)
    )
    target_cost = cost - 1
    target = pool.get(identity, 0)

    @lru_cache(maxsize=None)
    def probability(remaining, target_remaining, draws, needed):
        if needed <= 0:
            return 1.0
        if draws < needed or target_remaining < needed:
            return 0.0
        denominator = sum(w for n, w in zip(remaining, weights) if n > 0)
        if denominator == 0:
            return 0.0
        total = 0.0
        for cost, (n, weight) in enumerate(zip(remaining, weights)):
            if n <= 0 or weight == 0:
                continue
            after = list(remaining)
            after[cost] -= 1
            after = tuple(after)
            if cost == target_cost:
                hit = target_remaining / n
                branch = hit * probability(
                    after, target_remaining - 1, draws - 1, needed - 1
                )
                if hit < 1:
                    branch += (1 - hit) * probability(
                        after, target_remaining, draws - 1, needed
                    )
            else:
                branch = probability(after, target_remaining, draws - 1, needed)
            total += weight / denominator * branch
        return total

    value = probability(counts, target, slots, at_least)
    return dict(
        champion=champion,
        level=p.level,
        slots=slots,
        at_least=at_least,
        target_copies_available_after_refresh=target,
        cost_pool_after_refresh=list(counts),
        probability=min(1.0, max(0.0, value)),
        dynamic_program_states=probability.cache_info().currsize,
        scope="ordinary_shop_given_supplied_pool",
        hidden_pool_observed=False,
        purchase_affordability_evaluated=False,
        seasonal_effects_evaluated=False,
    )
