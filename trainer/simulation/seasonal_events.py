"""Atomic seasonal resource events driven by explicit observations.

Offer selection, combat outcomes and non-PvP payouts are inputs, never invented
labels. This layer is usable in replay probes and deliberately cannot satisfy
full-match readiness while seasonal distributions and combat remain incomplete.
"""

from copy import deepcopy
import hashlib
import json
import random

from .economy import grant_xp, positive_integer, return_copies
from .round_calendar import describe, require_next
from .round_economy import project_pvp
from .seasonal_offers import require_eligible, wisp_cost
from .state import IllegalAction, UnsupportedRule, validate_world, _pay, _reroll


def identity(rules):
    return hashlib.sha256(
        json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_state(s):
    required = {
        "round",
        "phase",
        "rules_sha256",
        "offer",
        "purchased",
        "blossom_tier",
        "coven_essence",
        "coven_choice_pending",
        "pending",
        "shops_seen",
        "round_kind",
        "round_index",
        "offer_history",
        "calendar_sha256",
    }
    if not isinstance(s, dict) or set(s) != required:
        raise IllegalAction("invalid seasonal state fields")
    if s["phase"] not in ("planning", "combat", "settled") or not isinstance(
        s["round"], str
    ):
        raise IllegalAction("invalid seasonal phase/round")
    if not isinstance(s["rules_sha256"], str) or len(s["rules_sha256"]) != 64:
        raise IllegalAction("missing seasonal rule identity")
    if not isinstance(s["calendar_sha256"], str) or len(s["calendar_sha256"]) != 64:
        raise IllegalAction("missing calendar identity")
    for key in ("purchased", "blossom_tier", "coven_essence", "shops_seen"):
        positive_integer(s[key], key, zero=True)
    positive_integer(s["round_index"], "round index", zero=True)
    if s["round_kind"] not in ("pvp", "pve", "carousel"):
        raise IllegalAction("invalid seasonal round kind")
    if s["offer_history"] is not None:
        if not isinstance(s["offer_history"], dict):
            raise IllegalAction("invalid offer history")
        for name, index in s["offer_history"].items():
            if not isinstance(name, str):
                raise IllegalAction("invalid historical Wisp identity")
            positive_integer(index, "historical round index", zero=True)
            if index > s["round_index"]:
                raise IllegalAction("offer history cannot contain future rounds")
    if type(s["coven_choice_pending"]) is not bool or not isinstance(
        s["pending"], list
    ):
        raise IllegalAction("invalid seasonal pending state")
    if s["offer"] is not None and not isinstance(s["offer"], str):
        raise IllegalAction("invalid Wisp identity")
    for effect in s["pending"]:
        _validate_effect(effect, pending=True)


def _validate_effect(e, *, pending=False):
    if not isinstance(e, dict):
        raise UnsupportedRule("effect must be a record")
    kind = e.get("kind")
    fields = {
        "grant": {"resource", "amount"},
        "combat_reward": {"resource", "amount", "trigger", "combats", "min_kills"},
        "dice_gold": {"dice", "sides", "offset"},
        "delayed_wins": {"combats", "gold_per_win", "bonus"}
        | ({"wins"} if pending else set()),
        "health_cost": {"amount"},
        "missing_health_gold": {"divisor"},
        "extend_streak": {"outcome", "amount"},
        "shop_tier": {"cost"},
    }
    if kind not in fields or set(e) - ({"kind"} | fields[kind]):
        raise UnsupportedRule("unknown seasonal effect field or handler")
    if kind in ("grant", "combat_reward"):
        if e.get("resource") not in (
            "gold",
            "xp",
            "hp",
            "free_rerolls",
            "round_free_rerolls",
        ):
            raise UnsupportedRule("unknown reward resource")
        positive_integer(e.get("amount"), "reward amount", zero=True)
        if kind == "combat_reward":
            if e.get("trigger") not in (
                "champion_kills",
                "win",
                "loss",
                "allied_survivors",
                "one_star_deaths",
            ):
                raise UnsupportedRule("unknown combat reward trigger")
            positive_integer(e.get("combats"), "reward combats")
            positive_integer(e.get("min_kills", 0), "minimum kills", zero=True)
    elif kind == "dice_gold":
        positive_integer(e.get("dice"), "dice count")
        positive_integer(e.get("sides"), "die sides")
        if type(e.get("offset")) is not int or e["offset"] < -1:
            raise UnsupportedRule("invalid die offset")
    elif kind == "delayed_wins":
        for k in ("gold_per_win", "bonus"):
            positive_integer(e.get(k), k, zero=True)
        positive_integer(e.get("combats"), "delayed combats")
        if pending:
            positive_integer(e.get("wins"), "accumulated wins", zero=True)
    elif kind == "health_cost":
        positive_integer(e.get("amount"), "health cost")
    elif kind == "missing_health_gold":
        positive_integer(e.get("divisor"), "missing health divisor")
    elif kind == "extend_streak":
        positive_integer(e.get("amount"), "streak extension")
        if e.get("outcome") not in ("win", "loss"):
            raise UnsupportedRule("unknown streak extension outcome")
    elif kind == "shop_tier":
        if type(e.get("cost")) is not int or not 1 <= e["cost"] <= 5:
            raise UnsupportedRule("invalid forced shop tier")
    else:
        raise UnsupportedRule("seasonal resource effect not implemented")
    if pending and kind not in ("combat_reward", "delayed_wins"):
        raise UnsupportedRule("invalid pending effect")


def _check(world, seat, content, rules, phase=None):
    validate_world(world, content)
    if type(seat) is not int or not 0 <= seat < len(world.players):
        raise IllegalAction("invalid seasonal seat")
    if (
        rules.get("schema_version") != 1
        or rules.get("kind") != "observed_seasonal_events_candidate"
    ):
        raise UnsupportedRule("seasonal resource binding missing")
    if content.get("patch") != rules.get("patch"):
        raise UnsupportedRule("seasonal resource patch mismatch")
    p = world.players[seat]
    if p.hp <= 0 or p.augments:
        raise UnsupportedRule("eliminated player or unbound augment economy")
    if p.seasonal:
        if p.seasonal["rules_sha256"] != identity(rules):
            raise UnsupportedRule("seasonal rules changed during the probe")
        if phase is not None and p.seasonal["phase"] != phase:
            raise IllegalAction("seasonal event out of order or already settled")
    elif phase is not None:
        raise IllegalAction("seasonal round not initialized")
    return p


def _policy(s, rules):
    tier = s["blossom_tier"]
    if tier >= rules["blossom"]["unsupported_from"]:
        raise UnsupportedRule("prismatic Blossom resource effects unavailable")
    policy = rules["blossom"]["tiers"].get(str(tier))
    if policy is None:
        raise UnsupportedRule("unknown latched Blossom tier")
    return policy


def begin_observed_round(
    world,
    seat,
    key,
    content,
    rules,
    calendar,
    *,
    initial_blossom_tier=0,
    initial_offer_history=None,
):
    """Attach an observed round. No free shop, loot or income is manufactured."""
    p = _check(world, seat, content, rules)
    row = describe(key, calendar)
    if row.get("augment"):
        raise UnsupportedRule(
            "augment choice and economic effects require their binding"
        )
    if p.seasonal:
        _check_calendar(p, calendar)
        if p.seasonal["phase"] != "settled":
            raise IllegalAction("previous round not settled")
        if p.seasonal["coven_choice_pending"]:
            raise IllegalAction("Coven reward/continue choice required")
        require_next(p.seasonal["round"], key, calendar)
        if initial_blossom_tier != 0:
            raise IllegalAction("cannot override persistent Blossom state")
        if initial_offer_history is not None:
            raise IllegalAction("cannot override persistent offer history")
    elif p.phase != "planning":
        raise IllegalAction("initial observed snapshot must be in planning")
    result = deepcopy(world)
    result.rules_scope = "observed_seasonal_probe"
    result.round_phase = "planning"
    target = result.players[seat]
    if not target.seasonal:
        target.seasonal = dict(
            round=key,
            phase="planning",
            rules_sha256=identity(rules),
            calendar_sha256=identity(calendar),
            offer=None,
            purchased=0,
            blossom_tier=initial_blossom_tier,
            coven_essence=0,
            coven_choice_pending=False,
            pending=[],
            shops_seen=0,
            round_kind=row["kind"],
            round_index=list(calendar["rounds"]).index(key),
            offer_history=deepcopy(initial_offer_history),
        )
    else:
        target.seasonal.update(
            round=key,
            phase="planning",
            offer=None,
            purchased=0,
            round_kind=row["kind"],
            round_index=list(calendar["rounds"]).index(key),
        )
    target.stage = row["stage"]
    target.phase = "planning"
    _policy(target.seasonal, rules)
    validate_world(result, content)
    return result


def _check_calendar(player, calendar):
    if player.seasonal["calendar_sha256"] != identity(calendar):
        raise UnsupportedRule("calendar changed during seasonal probe")


def observe_offer(world, seat, wisp, content, rules, *, refresh=False):
    """Install an observed overlay; optional paid refresh conserves all five units.

    Distribution and cadence cannot be inferred from only a Wisp name. Caller
    must supply None for a shop observed without an offer, including locked shops.
    """
    p = _check(world, seat, content, rules, "planning")
    if p.phase != "planning":
        raise IllegalAction("player cannot receive Wisp offers")
    policy = _policy(p.seasonal, rules)
    if wisp is not None:
        if wisp not in rules["wisps"]:
            raise UnsupportedRule("unbound Wisp; no placeholder effect")
        if p.seasonal["purchased"] >= policy["limit"]:
            raise IllegalAction("round Wisp purchase limit reached")
        spec = rules["wisps"][wisp]
        wisp_cost(spec, policy["empowered"])
        for e in spec["blossom" if policy["empowered"] else "normal"]:
            _validate_effect(e)
    if p.seasonal["offer"] is not None and not refresh:
        raise IllegalAction("existing observed offer must be bought or refreshed")
    result = deepcopy(world)
    target = result.players[seat]
    rng = random.Random(world.seed)
    if world.rng_state is not None:
        rng.setstate(world.rng_state)
    if refresh:
        if target.round_free_rerolls:
            target.round_free_rerolls -= 1
        elif target.free_rerolls:
            target.free_rerolls -= 1
        else:
            _pay(target, content["economy"]["reroll_cost"])
        _reroll(result, target, content, rng)
    if wisp is not None:
        require_eligible(
            target,
            wisp,
            spec,
            rules,
            empowered=policy["empowered"],
            coven_active=_trait_count(target, content, rules["coven"]["trait"]) >= 3,
        )
        if target.seasonal["offer_history"] is not None:
            target.seasonal["offer_history"][wisp] = target.seasonal["round_index"]
    target.seasonal["offer"] = wisp
    target.seasonal["shops_seen"] += 1
    result.rng_state = rng.getstate()
    validate_world(result, content)
    return result


def _grant(p, resource, amount, content, rules):
    positive_integer(amount, "reward amount", zero=True)
    if resource == "xp":
        grant_xp(p, amount, content)
    elif resource == "hp":
        p.hp = min(rules["hp_cap"], p.hp + amount)
    elif resource in ("gold", "free_rerolls", "round_free_rerolls"):
        setattr(p, resource, getattr(p, resource) + amount)
    else:
        raise UnsupportedRule("unknown resource")


def _eliminate(world, p, content):
    for u in p.units:
        if u.stars > 3:
            raise UnsupportedRule("four-star elimination provenance unavailable")
        return_copies(world.pool, u.champion, 3 ** (u.stars - 1), content)
    for offer in p.shop:
        if offer is not None:
            if offer.kind != "champion":
                raise UnsupportedRule("special offer elimination unavailable")
            return_copies(world.pool, offer.entity, 1, content)
    p.units = []
    p.shop = [None] * 5
    p.phase = "eliminated"
    p.round_free_rerolls = 0
    p.seasonal.update(offer=None, phase="settled", pending=[])


def buy_wisp(world, seat, content, rules):
    p = _check(world, seat, content, rules, "planning")
    s = p.seasonal
    policy = _policy(s, rules)
    if s["offer"] is None:
        raise IllegalAction("no Wisp offered")
    if s["purchased"] >= policy["limit"]:
        raise IllegalAction("round Wisp purchase limit reached")
    spec = rules["wisps"].get(s["offer"])
    if spec is None:
        raise UnsupportedRule("unbound Wisp")
    effects = spec["blossom" if policy["empowered"] else "normal"]
    for e in effects:
        _validate_effect(e)
    result = deepcopy(world)
    target = result.players[seat]
    state = target.seasonal
    cost = wisp_cost(spec, policy["empowered"])
    _pay(target, cost)  # rebate and reward cannot finance the purchase
    rng = random.Random(world.seed)
    if world.rng_state is not None:
        rng.setstate(world.rng_state)
    applied = []
    for raw in effects:
        e = deepcopy(raw)
        kind = e["kind"]
        if kind == "grant":
            _grant(target, e["resource"], e["amount"], content, rules)
        elif kind == "dice_gold":
            e["results"] = [
                rng.randint(1, e["sides"]) + e["offset"] for _ in range(e["dice"])
            ]
            target.gold += sum(e["results"])
        elif kind in ("combat_reward", "delayed_wins"):
            if kind == "delayed_wins":
                e["wins"] = 0
            state["pending"].append(deepcopy(e))
        elif kind == "health_cost":
            target.hp = max(0, target.hp - e["amount"])
        elif kind == "missing_health_gold":
            e["gold"] = max(0, rules["hp_cap"] - target.hp) // e["divisor"]
            target.gold += e["gold"]
        elif kind == "extend_streak":
            sign = 1 if e["outcome"] == "win" else -1
            if target.streak * sign < 0:
                raise IllegalAction("cannot extend opposite streak")
            target.streak += sign * e["amount"]
        elif kind == "shop_tier":
            _reroll(result, target, content, rng, forced_cost=e["cost"])
            state["shops_seen"] += 1
        applied.append(e)
    target.gold += policy["rebate"]
    state["purchased"] += 1
    state["offer"] = None
    if target.hp == 0:
        _eliminate(result, target, content)
    result.rng_state = rng.getstate()
    validate_world(result, content)
    return result, dict(
        wisp=s["offer"],
        empowered=policy["empowered"],
        cost=cost,
        rebate=policy["rebate"],
        effects=applied,
        gold_after=target.gold,
        hp_after=target.hp,
        scope="observed_seasonal_probe",
    )


def end_planning(world, seat, content, rules):
    _check(world, seat, content, rules, "planning")
    result = deepcopy(world)
    # Overlay disappears; the reserved champion underneath stays in the pool ledger.
    result.players[seat].seasonal.update(offer=None, phase="combat")
    validate_world(result, content)
    return result


def _trait_count(player, content, trait):
    identities = {}
    for u in player.units:
        if u.zone != "board":
            continue
        c = content["champions"][u.champion]
        tags = set(c.get("traits", []))
        for item in u.items:
            tags.update(content["items"][item].get("grants_traits", []))
        if trait not in tags:
            continue
        count = positive_integer(
            c.get("trait_contributions", {}).get(trait, 1), "trait contribution"
        )
        key = c.get("identity", u.champion)
        identities[key] = max(count, identities.get(key, 0))
    return sum(identities.values())


def _tier(count, spec):
    if count >= spec["unsupported_from"]:
        raise UnsupportedRule("unbound highest seasonal trait tier")
    return max((int(k) for k in spec["tiers"] if int(k) <= count), default=0)


def settle_observed_pvp(
    world,
    seat,
    content,
    rules,
    calendar,
    economy,
    *,
    outcome,
    enemy_champion_kills,
    surviving_enemy_champions,
    allied_survivors,
    one_star_deaths=0,
):
    """Observed resource consequences, not a replacement for missing combat logic.

    The declared counts exclude summons. This initial contract counts each owned
    champion once; revival and duplication event histories require another binding.
    """
    p = _check(world, seat, content, rules, "combat")
    _check_calendar(p, calendar)
    if describe(p.seasonal["round"], calendar)["kind"] != "pvp":
        raise UnsupportedRule("PvE/carousel settlement requires observed resources")
    if outcome not in ("win", "loss"):
        raise UnsupportedRule("draw rewards unavailable")
    for n in (
        enemy_champion_kills,
        surviving_enemy_champions,
        allied_survivors,
        one_star_deaths,
    ):
        positive_integer(n, "observed champion count", zero=True)
    owned = [u for u in p.units if u.zone == "board"]
    if (
        allied_survivors > len(owned)
        or one_star_deaths > sum(u.stars == 1 for u in owned)
        or allied_survivors + one_star_deaths > len(owned)
    ):
        raise IllegalAction("impossible allied survivor/death observations")
    result = deepcopy(world)
    target = result.players[seat]
    s = target.seasonal
    coven = rules["coven"]
    count = _trait_count(p, content, coven["trait"])
    tier = _tier(count, coven)
    essence = 0
    if tier:
        values = coven["tiers"][str(tier)]
        essence = enemy_champion_kills * values["per_kill"] + (
            values["per_loss"] if outcome == "loss" else 0
        )
        s["coven_essence"] += essence
        s["coven_choice_pending"] = s["coven_essence"] >= coven["first_cashout"]
    events = []
    remaining = []
    for raw in s["pending"]:
        e = deepcopy(raw)
        _validate_effect(e, pending=True)
        if e["kind"] == "delayed_wins":
            e["wins"] += int(outcome == "win")
            e["combats"] -= 1
            if e["combats"] == 0:
                amount = e["wins"] * e["gold_per_win"] + e["bonus"]
                _grant(target, "gold", amount, content, rules)
                events.append(
                    dict(resource="gold", amount=amount, source="delayed_wins")
                )
        else:
            trigger = e["trigger"]
            multiplier = {
                "champion_kills": enemy_champion_kills,
                "allied_survivors": allied_survivors,
                "one_star_deaths": one_star_deaths,
                "win": int(outcome == "win"),
                "loss": int(outcome == "loss"),
            }[trigger]
            if enemy_champion_kills < e.get("min_kills", 0):
                multiplier = 0
            amount = e["amount"] * multiplier
            _grant(target, e["resource"], amount, content, rules)
            events.append(dict(resource=e["resource"], amount=amount, source=trigger))
            e["combats"] -= 1
        if e["combats"]:
            remaining.append(e)
    s["pending"] = remaining
    # Resource effects earned in combat precede the candidate next-income projection.
    target.seasonal = {}
    settled, receipt = project_pvp(
        target,
        content,
        economy,
        outcome=outcome,
        surviving_enemy_champions=surviving_enemy_champions,
    )
    settled.seasonal = s
    result.players[seat] = settled
    s["phase"] = "settled"
    s["blossom_tier"] = _tier(
        _trait_count(p, content, rules["blossom"]["trait"]), rules["blossom"]
    )
    if settled.hp == 0:
        _eliminate(result, settled, content)
    validate_world(result, content)
    return result, dict(
        round=s["round"],
        resource_events=events,
        coven_essence_gained=essence,
        coven_choice_pending=s["coven_choice_pending"],
        economy=receipt,
        scope="observed_seasonal_probe",
        full_match=False,
    )


def continue_coven(world, seat, content, rules):
    p = _check(world, seat, content, rules, "settled")
    if not p.seasonal["coven_choice_pending"]:
        raise IllegalAction("no Coven choice pending")
    result = deepcopy(world)
    result.players[seat].seasonal["coven_choice_pending"] = False
    return result


def settle_observed_non_pvp(world, seat, content, rules, calendar, *, resources):
    """Record measured totals at a special boundary, explicitly not simulated loot.

    Persistent effects count player combats only, so PvE/carousel do not consume
    their counters. Item/unit loot, augments and carousel drafts remain unsupported.
    """
    p = _check(world, seat, content, rules, "combat")
    _check_calendar(p, calendar)
    round_kind = describe(p.seasonal["round"], calendar)["kind"]
    if round_kind == "pvp":
        raise IllegalAction("PvP requires its outcome-dependent settlement")
    fields = {
        "gold",
        "xp",
        "level",
        "hp",
        "streak",
        "free_rerolls",
        "round_free_rerolls",
    }
    if not isinstance(resources, dict) or set(resources) != fields:
        raise IllegalAction("complete measured resource snapshot required")
    if type(resources["streak"]) is not int or resources["streak"] != p.streak:
        raise IllegalAction("non-PvP boundary must preserve the streak")
    result = deepcopy(world)
    target = result.players[seat]
    for key, value in resources.items():
        if key != "streak":
            positive_integer(value, key, zero=key != "level")
        setattr(target, key, value)
    target.phase = "between_rounds"
    target.seasonal["phase"] = "settled"
    if round_kind == "pve":
        target.seasonal["blossom_tier"] = _tier(
            _trait_count(p, content, rules["blossom"]["trait"]), rules["blossom"]
        )
    if target.hp == 0:
        _eliminate(result, target, content)
    validate_world(result, content)
    return result, dict(
        round=p.seasonal["round"],
        measured_resources=resources,
        source="external_observation",
        rewards_simulated=False,
        full_match=False,
    )
