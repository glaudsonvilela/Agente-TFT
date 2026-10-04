"""Common economy at an explicit ordinary PvP income boundary.

All coefficients are supplied by a separate rules table. This projection joins
HP risk, streaks, victory gold, interest and XP; it is not a calendar or a claim
that seasonal rewards, hidden opponent state or PvE have been simulated.
"""

from copy import deepcopy

from .economy import grant_xp, positive_integer
from .state import IllegalAction, UnsupportedRule


def validate_rules(rules):
    if (
        rules.get("schema_version") != 1
        or rules.get("kind") != "ordinary_pvp_economy_candidate"
        or rules.get("interest_order") != "after_win_before_income"
    ):
        raise UnsupportedRule("ordinary PvP economy rules unavailable")
    for name in (
        "base_income",
        "win_gold",
        "interest_cap",
        "natural_xp",
        "damage_per_surviving_champion",
    ):
        positive_integer(rules.get(name), name, zero=True)
    positive_integer(rules.get("interest_step"), "interest step")
    tiers = rules.get("streak_tiers")
    if not isinstance(tiers, list) or not tiers:
        raise UnsupportedRule("streak tiers unavailable")
    previous = 0
    for tier in tiers:
        minimum = positive_integer(tier.get("min"), "streak threshold")
        positive_integer(tier.get("gold"), "streak gold", zero=True)
        if minimum <= previous:
            raise UnsupportedRule("streak thresholds must be increasing")
        previous = minimum
    stages = rules.get("stage_damage")
    if not isinstance(stages, dict) or not stages:
        raise UnsupportedRule("stage damage table unavailable")
    for stage, value in stages.items():
        if (
            not isinstance(stage, str)
            or not stage.isdigit()
            or str(int(stage)) != stage
        ):
            raise UnsupportedRule("invalid damage stage")
        positive_integer(value, "base stage damage", zero=True)


def interest(gold, rules):
    positive_integer(gold, "gold", zero=True)
    return min(rules["interest_cap"], gold // rules["interest_step"])


def streak_reward(length, rules):
    return max(
        (tier["gold"] for tier in rules["streak_tiers"] if abs(length) >= tier["min"]),
        default=0,
    )


def project_pvp(player, content, rules, *, outcome, surviving_enemy_champions):
    """Return a cloned next-boundary player and a fully itemized receipt.

    `outcome` and survivor count are conditions, not predictions. Existing
    combat earnings must already be present in gold. This function adds only
    the supplied ordinary economy. World lifecycle ownership stays with the
    caller; the returned player must pass through a new planning boundary.
    """
    validate_rules(rules)
    if outcome not in ("win", "loss"):
        raise UnsupportedRule("draw/PvE/special round economy not bound")
    if type(player.streak) is not int:
        raise IllegalAction("invalid signed streak")
    for field in ("gold", "xp", "hp", "free_rerolls", "round_free_rerolls"):
        positive_integer(getattr(player, field), field, zero=True)
    positive_integer(player.level, "level")
    if player.hp <= 0:
        raise IllegalAction("eliminated player cannot receive a new round")
    if player.phase != "planning":
        raise IllegalAction("player economy already settled or not in planning")
    if player.augments:
        raise UnsupportedRule("augment economy is outside the ordinary projection")
    positive_integer(surviving_enemy_champions, "surviving enemy count", zero=True)
    if outcome == "win" and surviving_enemy_champions:
        raise IllegalAction("winner cannot have surviving ordinary enemy champions")
    stage = player.stage
    if type(stage) is not int or str(stage) not in rules["stage_damage"]:
        raise UnsupportedRule("observed stage requires explicit damage rule")
    result = deepcopy(player)
    sign = 1 if outcome == "win" else -1
    result.streak = player.streak + sign if player.streak * sign > 0 else sign
    damage = (
        (
            rules["stage_damage"][str(stage)]
            + surviving_enemy_champions * rules["damage_per_surviving_champion"]
        )
        if outcome == "loss"
        else 0
    )
    result.hp = max(0, result.hp - damage)
    win = rules["win_gold"] if outcome == "win" else 0
    result.gold += win
    basis = result.gold
    alive = result.hp > 0
    reward = streak_reward(result.streak, rules) if alive else 0
    earned_interest = interest(basis, rules) if alive else 0
    base = rules["base_income"] if alive else 0
    xp = rules["natural_xp"] if alive else 0
    result.gold += base + earned_interest + reward
    if alive:
        grant_xp(result, xp, content)
    result.phase = "between_rounds" if alive else "eliminated"
    result.round_free_rerolls = 0
    receipt = dict(
        scope="ordinary_pvp_income_projection",
        outcome_condition=outcome,
        stage=stage,
        hp_before=player.hp,
        hp_after=result.hp,
        player_damage=damage,
        enemy_champions=surviving_enemy_champions,
        streak_before=player.streak,
        streak_after=result.streak,
        gold_before=player.gold,
        win_gold=win,
        interest_basis=basis,
        interest=earned_interest,
        base_income=base,
        streak_gold=reward,
        gold_after=result.gold,
        natural_xp=xp,
        level_before=player.level,
        level_after=result.level,
        xp_before=player.xp,
        xp_after=result.xp,
        eliminated=not alive,
        round_rerolls_expired=player.round_free_rerolls,
        seasonal_effects_evaluated=False,
        runtime_promoted=False,
    )
    return result, receipt
