"""Typed stat layers and independent timed effects, without patch constants."""

from dataclasses import dataclass
import math
import operator

from .state import UnsupportedRule


HEALTH_CONDITIONS = {
    "hp_above": operator.gt,
    "hp_below": operator.lt,
    "hp_at_least": operator.ge,
    "hp_at_most": operator.le,
}
TARGET_HEALTH_CONDITIONS = {
    "target_" + key: value for key, value in HEALTH_CONDITIONS.items()
}


def matches_condition(condition, context):
    if condition is None:
        return True
    if context is None:
        return False
    for key, value in condition.items():
        if key in HEALTH_CONDITIONS:
            if "health_fraction" not in context or not HEALTH_CONDITIONS[key](
                context["health_fraction"], value
            ):
                return False
        elif key in TARGET_HEALTH_CONDITIONS:
            if "target_health_fraction" not in context or not TARGET_HEALTH_CONDITIONS[
                key
            ](context["target_health_fraction"], value):
                return False
        elif key == "target_held_seconds_at_least":
            if context.get("target_held_seconds", -1) < value:
                return False
        elif context.get(key) != value:
            return False
    return True


def actor_context(unit, now):
    # Conditional maximum health is prohibited, so this lookup cannot recurse.
    maximum = unit.values.get("hp", now)
    return {
        "shielded": any(
            s.amount > 0 and s.expires > now for s in getattr(unit, "shields", [])
        ),
        "health_fraction": unit.hp / maximum if maximum > 0 else 0.0,
    }


@dataclass
class Modifier:
    key: str
    stat: str
    mode: str
    value: float
    expires: float = math.inf
    group: str | None = None
    strongest: bool = False
    when: dict | None = None
    per_context: str | None = None


class Stats:
    """flat, base_pct, bonus_pct and multiplier are deliberately different units."""

    def __init__(self, base):
        self.base = dict(base)
        self.modifiers = []

    def add(
        self,
        key,
        stat,
        value,
        mode="flat",
        *,
        expires=math.inf,
        group=None,
        strongest=False,
        when=None,
        per_context=None,
    ):
        if stat not in self.base or mode not in (
            "flat",
            "base_pct",
            "bonus_pct",
            "multiplier",
        ):
            raise UnsupportedRule("unknown stat or modifier unit")
        if not math.isfinite(value) or math.isnan(expires):
            raise UnsupportedRule("invalid modifier")
        if mode == "multiplier" and value < 0:
            raise UnsupportedRule("negative multiplier")
        if when is not None:
            if (
                not isinstance(when, dict)
                or not when
                or set(when)
                - (
                    {"shielded", "target_held_seconds_at_least"}
                    | set(HEALTH_CONDITIONS)
                    | set(TARGET_HEALTH_CONDITIONS)
                )
            ):
                raise UnsupportedRule("unknown modifier condition")
            for name, threshold in when.items():
                if name == "shielded":
                    if type(threshold) is not bool:
                        raise UnsupportedRule("shield condition must be boolean")
                elif (
                    type(threshold) not in (int, float)
                    or not math.isfinite(threshold)
                    or threshold < 0
                    or (name != "target_held_seconds_at_least" and threshold > 1)
                ):
                    raise UnsupportedRule("health threshold must be a finite fraction")
            if stat in ("hp", "mana", "initial_mana", "mana_per_second"):
                raise UnsupportedRule(
                    "conditional resource integration not implemented"
                )
        if per_context is not None and (
            per_context != "enemies_targeting"
            or stat not in ("armor", "mr")
            or mode != "flat"
        ):
            raise UnsupportedRule("unsupported contextual stat multiplier")
        self.modifiers.append(
            Modifier(
                key,
                stat,
                mode,
                float(value),
                expires,
                group,
                strongest,
                when,
                per_context,
            )
        )

    def get(self, stat, now=0, context=None):
        if stat not in self.base:
            raise UnsupportedRule(f"unknown stat: {stat}")
        mods = [
            m
            for m in self.modifiers
            if m.stat == stat and m.expires > now and matches_condition(m.when, context)
        ]
        groups = {}
        selected = []
        for m in mods:
            if not m.strongest:
                selected.append(m)
                continue
            if m.group is None:
                raise UnsupportedRule("strongest effect needs stacking group")
            key = (m.group, m.mode)
            if key not in groups or abs(m.value) > abs(groups[key].value):
                groups[key] = m
        selected.extend(groups.values())

        def value(m):
            if m.per_context is None:
                return m.value
            scale = (context or {}).get(m.per_context, 0)
            if type(scale) is not int or scale < 0:
                raise UnsupportedRule("invalid contextual stat count")
            return m.value * scale

        flat = sum(value(m) for m in selected if m.mode == "flat")
        base_pct = sum(m.value for m in selected if m.mode == "base_pct")
        bonus_pct = sum(m.value for m in selected if m.mode == "bonus_pct")
        multiplier = math.prod(m.value for m in selected if m.mode == "multiplier")
        return (self.base[stat] * (1 + base_pct) + flat) * (1 + bonus_pct) * multiplier

    def expire(self, now):
        self.modifiers[:] = [m for m in self.modifiers if m.expires > now]

    def remove(self, key):
        self.modifiers[:] = [m for m in self.modifiers if m.key != key]


def formula(spec, source, target, now, context=None, stat_getter=None):
    """Sum explicit terms; never eval source text or infer AD/AP from HTML labels."""
    if not isinstance(spec, list):
        raise UnsupportedRule("formula must be a list of terms")
    total = 0.0
    for term in spec:
        if set(term) - {"coefficient", "stat", "owner", "base", "context", "factor"}:
            raise UnsupportedRule("unknown formula term")
        coefficient = term["coefficient"]
        if isinstance(coefficient, list):
            if len(coefficient) < source.stars:
                raise UnsupportedRule("formula missing star level")
            coefficient = coefficient[source.stars - 1]
        if type(coefficient) not in (int, float) or not math.isfinite(coefficient):
            raise UnsupportedRule("formula coefficient must be finite")
        stat = term.get("stat")
        if "context" in term:
            if (
                stat is not None
                or term["context"] not in ("damage", "total_damage")
                or term["context"] not in (context or {})
            ):
                raise UnsupportedRule("formula context unavailable")
            value = context[term["context"]]
        elif stat is None:
            value = 1.0
        else:
            owner = term.get("owner", "source")
            if owner not in ("source", "target"):
                raise UnsupportedRule("unknown formula owner")
            unit = source if owner == "source" else target
            if unit is None:
                raise UnsupportedRule("formula target unavailable")
            if stat == "current_hp":
                value = unit.hp
            elif stat == "missing_hp":
                value = max(0, unit.values.get("hp", now) - unit.hp)
            else:
                value = (
                    unit.values.base[stat]
                    if term.get("base", False)
                    else (
                        stat_getter(unit, stat)
                        if stat_getter is not None
                        else unit.values.get(stat, now, actor_context(unit, now))
                    )
                )
        if "factor" in term:
            factor = term["factor"]
            if not isinstance(factor, dict) or set(factor) != {"stat", "divisor"}:
                raise UnsupportedRule("invalid formula factor")
            divisor = factor["divisor"]
            if (
                type(divisor) not in (int, float)
                or not math.isfinite(divisor)
                or divisor <= 0
                or factor["stat"] not in source.values.base
            ):
                raise UnsupportedRule("invalid formula factor stat/divisor")
            factor_value = (
                stat_getter(source, factor["stat"])
                if stat_getter is not None
                else source.values.get(factor["stat"], now, actor_context(source, now))
            )
            value *= factor_value / divisor
        total += coefficient * value
    return total
