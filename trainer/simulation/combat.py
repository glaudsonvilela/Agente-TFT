"""Seeded hex combat kernel for explicit laboratory rules bundles.

This is not a complete TFT patch implementation. Unsupported traits, item procs
and spells fail before combat. Timing and targeting are declared approximations
until compared with independently annotated fights.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import heapq
import math
import random

from .hexgrid import distance, global_hex, next_step
from .state import UnsupportedRule


@dataclass
class Fighter:
    uid: str
    team: int
    champion: str
    stars: int
    position: tuple[int, int]
    stats: dict
    spell: dict
    hp: float
    mana: float
    shields: list = field(default_factory=list)
    damage_dealt: float = 0
    casts: int = 0
    attacks: int = 0
    permanent: dict = field(default_factory=dict)


STATS = ('hp', 'ad', 'ap', 'armor', 'mr', 'attack_speed', 'range', 'mana',
         'initial_mana', 'mana_per_attack', 'mana_per_second',
         'mana_per_damage', 'crit_chance', 'crit_multiplier')
BONUSES = {'hp', 'ad', 'ap', 'armor', 'mr', 'attack_speed', 'initial_mana'}


def finite(x, label):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise UnsupportedRule(f'nonfinite/missing {label}')
    return float(x)


def star_value(value, stars, label):
    if isinstance(value, list):
        if not 1 <= stars <= len(value): raise UnsupportedRule(f'unavailable star value: {label}')
        value = value[stars-1]
    return finite(value, label)


def materialize(players, content):
    result = []; seen = set()
    if len(players) != 2: raise ValueError('combat requires two players')
    if content.get('scope') != 'experimental_hex_lab':
        raise UnsupportedRule('only experimental_hex_lab is supported; current patch is not complete')
    for team, player in enumerate(players):
        if player.augments:
            raise UnsupportedRule('augment handlers require the event combat kernel')
        occupied = set()
        for unit in player.units:
            if unit.zone != 'board': continue
            spec = content['champions'][unit.champion]
            if spec.get('traits') or spec.get('special_rules'):
                raise UnsupportedRule('trait/seasonal handlers not implemented in hex kernel')
            if unit.uid in seen: raise ValueError('duplicate unit identifier')
            seen.add(unit.uid)
            position = global_hex(team, unit.position)
            if position in occupied: raise ValueError('occupied hex')
            occupied.add(position)
            stats = {k: star_value(spec['combat'].get(k), unit.stars, k) for k in STATS}
            for item in unit.items:
                item_spec = content['items'][item]
                if item_spec.get('combat_handler') != 'stats' or set(item_spec['bonuses']) - BONUSES:
                    raise UnsupportedRule(f'unsupported item effect: {item}')
                for k, value in item_spec['bonuses'].items(): stats[k] += finite(value, k)
            if set(unit.permanent) - {'ap'}: raise UnsupportedRule('unknown permanent stat')
            stats['ap'] += finite(unit.permanent.get('ap', 0), 'permanent AP')
            if stats['hp'] <= 0 or stats['attack_speed'] <= 0 or stats['range'] < 1 or stats['range'] % 1:
                raise UnsupportedRule('invalid health/speed/range')
            if any(stats[k] < 0 for k in ('ad','ap','mana','initial_mana','mana_per_attack',
                                         'mana_per_second','mana_per_damage')):
                raise UnsupportedRule('negative combat resource')
            if not 0 <= stats['crit_chance'] <= 1 or stats['crit_multiplier'] < 1:
                raise UnsupportedRule('invalid critical strike rules')
            spell = spec.get('spell')
            if spell is None or spell.get('kind') not in ('none','target_damage','target_dot','self_shield'):
                raise UnsupportedRule('spell handler unavailable')
            if spell['kind'] != 'none':
                if stats['mana'] <= 0: raise UnsupportedRule('active spell requires positive mana')
                if spell.get('scaling') not in ('flat', 'ap', 'ad'): raise UnsupportedRule('unknown scaling')
                star_value(spell.get('amount'), unit.stars, 'spell amount')
                if finite(spell.get('cast_seconds'), 'cast time') < 0: raise UnsupportedRule('negative cast time')
                if spell['kind'] in ('target_damage','target_dot') and spell.get('damage_type') not in ('physical','magic','true'):
                    raise UnsupportedRule('unknown damage type')
                if spell['kind'] in ('target_dot','self_shield') and finite(spell.get('duration'), 'duration') <= 0:
                    raise UnsupportedRule('invalid duration')
                if spell['kind'] == 'target_dot' and (type(spell.get('ticks')) is not int or spell['ticks'] < 1):
                    raise UnsupportedRule('invalid dot ticks')
            result.append(Fighter(unit.uid, team, unit.champion, unit.stars, position, stats, spell,
                                  stats['hp'], min(stats['mana'], stats['initial_mana']),
                                  permanent=dict(unit.permanent)))
    return result


def mitigation(resistance):
    return 100/(100+resistance) if resistance >= 0 else 2-100/(100-resistance)


def simulate(players, content, *, seed=0, trace=False):
    """No mutation of planning state. Independent shields and persistent DOT events."""
    if content.get('combat_version')==2:
        from .event_combat import simulate as event_simulate
        return event_simulate(players,content,seed=seed,trace=trace)
    units = materialize(players, content); by_id = {u.uid: u for u in units}
    cfg = content['combat_rules']
    required = ('duration', 'move_seconds', 'first_action_seconds', 'attack_speed_cap')
    rules = {k: finite(cfg.get(k), k) for k in required}
    if any(rules[k] <= 0 for k in ('duration','move_seconds','attack_speed_cap')) or rules['first_action_seconds'] < 0:
        raise UnsupportedRule('invalid combat clock')
    rng = random.Random(seed); queue = []; sequence = 0; now = 0.; history = []

    def emit(kind, **values):
        if trace: history.append(dict(time=round(now, 6), kind=kind, **values))

    def schedule(when, kind, uid, payload=None):
        nonlocal sequence
        sequence += 1
        heapq.heappush(queue, (when, sequence, kind, uid, payload))

    def hit(source, target, raw, dtype):
        if target.hp <= 0: return False
        raw = max(0, raw)
        reduced = raw * (mitigation(target.stats['armor']) if dtype == 'physical' else
                         mitigation(target.stats['mr']) if dtype == 'magic' else 1)
        target.shields = [s for s in target.shields if s[0] > now and s[1] > 0]
        damage = reduced
        for shield in sorted(target.shields, key=lambda s: s[0]):
            absorbed = min(shield[1], damage); shield[1] -= absorbed; damage -= absorbed
        lost = min(target.hp, damage); target.hp -= lost
        source.damage_dealt += lost
        target.mana = min(target.stats['mana'], target.mana + lost * target.stats['mana_per_damage'])
        emit('damage', source=source.uid, target=target.uid, raw=raw, mitigated=reduced,
             health_lost=lost, damage_type=dtype)
        if target.hp <= 0: emit('death', target=target.uid)
        return target.hp <= 0

    def amount(unit):
        spell = unit.spell
        base = star_value(spell['amount'], unit.stars, 'spell amount')
        return base * (unit.stats['ap']/100 if spell['scaling'] == 'ap' else
                       unit.stats['ad']/100 if spell['scaling'] == 'ad' else 1)

    ordered = list(units); rng.shuffle(ordered)
    for unit in ordered: schedule(rules['first_action_seconds'], 'act', unit.uid)
    previous = 0.
    while queue:
        teams = {u.team for u in units if u.hp > 0}
        if len(teams) < 2: break
        now, _, kind, uid, payload = heapq.heappop(queue)
        if now > rules['duration']:
            now = rules['duration']; break
        for unit in units:
            if unit.hp > 0:
                unit.mana = min(unit.stats['mana'], unit.mana + (now-previous)*unit.stats['mana_per_second'])
        previous = now
        unit = by_id[uid]
        if kind == 'dot':
            target, value, dtype = payload
            hit(unit, by_id[target], value, dtype)
            continue
        if unit.hp <= 0: continue
        enemies = [e for e in units if e.team != unit.team and e.hp > 0]
        if not enemies: break
        # This nearest-target rule is explicit laboratory behavior, not verified patch targeting.
        target = min(enemies, key=lambda e: (distance(unit.position, e.position), e.uid))
        spell = unit.spell
        if kind == 'cast':
            original = by_id[payload]
            if original.hp > 0: target = original
            value = amount(unit)
            if spell['kind'] == 'target_damage': hit(unit, target, value, spell['damage_type'])
            elif spell['kind'] == 'target_dot':
                for i in range(1, spell['ticks']+1):
                    schedule(now + spell['duration']*i/spell['ticks'], 'dot', uid,
                             (target.uid, value/spell['ticks'], spell['damage_type']))
            elif spell['kind'] == 'self_shield':
                unit.shields.append([now+spell['duration'], value]); emit('shield', unit=uid, amount=value)
            schedule(now + 1/min(rules['attack_speed_cap'], unit.stats['attack_speed']), 'act', uid)
            continue
        if distance(unit.position, target.position) > unit.stats['range']:
            occupied = {u.position for u in units if u.hp > 0 and u.uid != uid}
            step = next_step(unit.position, target.position, unit.stats['range'], occupied)
            emit('move', unit=uid, origin=unit.position, destination=step)
            unit.position = step
            schedule(now + rules['move_seconds'], 'act', uid)
        elif spell['kind'] != 'none' and unit.mana >= unit.stats['mana']:
            unit.mana = 0; unit.casts += 1
            emit('cast', unit=uid, target=target.uid)
            schedule(now + spell['cast_seconds'], 'cast', uid, target.uid)
        else:
            unit.attacks += 1
            critical = rng.random() < unit.stats['crit_chance']
            hit(unit, target, unit.stats['ad'] * (unit.stats['crit_multiplier'] if critical else 1), 'physical')
            unit.mana = min(unit.stats['mana'], unit.mana + unit.stats['mana_per_attack'])
            schedule(now + 1/min(rules['attack_speed_cap'], unit.stats['attack_speed']), 'act', uid)
    alive = {u.team for u in units if u.hp > 0}
    winner = next(iter(alive)) if len(alive) == 1 else None
    return dict(schema_version=1, scope='experimental_hex_lab', seed=seed, winner=winner,
                duration_seconds=now, runtime_promoted=False,
                units=[dict(uid=u.uid, team=u.team, health=u.hp, position=u.position,
                            damage_dealt=u.damage_dealt, casts=u.casts, attacks=u.attacks,
                            permanent=u.permanent) for u in units], events=history)
