"""Explicit planning state and atomic offline actions.

No screen coordinates, mouse control, or patch constants live in this module.
Economy, recipes, sale values and shop probabilities come from a rules bundle.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import random


class UnsupportedRule(ValueError):
    pass


class IllegalAction(ValueError):
    pass


@dataclass
class Unit:
    uid: str
    champion: str
    stars: int = 1
    # board=(front-to-back row, left-to-right column); bench=(slot,).
    zone: str = 'bench'
    position: tuple[int, ...] = (0,)
    items: list[str] = field(default_factory=list)
    permanent: dict[str, float] = field(default_factory=dict)


@dataclass
class Offer:
    kind: str
    entity: str
    cost: int


@dataclass
class Player:
    gold: int
    level: int
    xp: int
    hp: int = 100
    units: list[Unit] = field(default_factory=list)
    inventory: list[str] = field(default_factory=list)
    shop: list[Offer | None] = field(default_factory=lambda: [None] * 5)
    shop_locked: bool = False
    phase: str = 'planning'
    augments: list[str] = field(default_factory=list)


@dataclass
class World:
    players: list[Player]
    # Copies reserved by all players' shops have already left this pool.
    pool: dict[str, int]
    seed: int = 0
    next_uid: int = 0
    rng_state: tuple | None = None


@dataclass(frozen=True)
class Action:
    kind: str
    args: tuple = ()


def validate_world(world: World, content: dict):
    if not 1 <= len(world.players) <= 8:
        raise IllegalAction('expected 1..8 players')
    seen = set()
    for p in world.players:
        if any(type(v) is not int or v < 0 for v in (p.gold, p.level, p.xp, p.hp)) or p.level < 1:
            raise IllegalAction('invalid player resources')
        if len(p.shop) != 5:
            raise IllegalAction('shop requires five explicit slots')
        locations = set()
        board_slots = 0
        for u in p.units:
            if u.uid in seen or u.champion not in content['champions'] or type(u.stars) is not int or not 1 <= u.stars <= 4:
                raise IllegalAction('invalid/duplicate unit')
            if any(type(x) is not int for x in u.position):
                raise IllegalAction('positions require integers')
            seen.add(u.uid)
            if u.zone == 'board':
                if len(u.position) != 2 or not (0 <= u.position[0] < 4 and 0 <= u.position[1] < 7):
                    raise IllegalAction('invalid hex')
                board_slots += content['champions'][u.champion].get('team_slots', 1)
            elif u.zone == 'bench':
                if len(u.position) != 1 or not 0 <= u.position[0] < 9:
                    raise IllegalAction('invalid bench slot')
            else:
                raise IllegalAction('unknown unit zone')
            key = (u.zone, u.position)
            if key in locations or len(u.items) > 3:
                raise IllegalAction('occupied position or too many equipped items')
            locations.add(key)
            if any(i not in content['items'] for i in u.items):
                raise UnsupportedRule('unknown equipped item')
        if board_slots > p.level or len(p.inventory) > content['economy']['inventory_slots']:
            raise IllegalAction('board/inventory capacity exceeded')
        if any(i not in content['items'] for i in p.inventory):
            raise UnsupportedRule('unknown inventory item')
        for offer in p.shop:
            if offer is not None and (type(offer.cost) is not int or offer.cost < 0):
                raise IllegalAction('invalid offer cost')
    if any(c not in content['champions'] for c in world.pool):
        raise UnsupportedRule('unknown pool champion')
    if any(type(n) is not int or n < 0 for n in world.pool.values()):
        raise IllegalAction('negative pool')


def _bench(p):
    occupied = {u.position[0] for u in p.units if u.zone == 'bench'}
    return next((i for i in range(9) if i not in occupied), None)


def _find(p, uid):
    for u in p.units:
        if u.uid == uid:
            return u
    raise IllegalAction('unit is not owned')


def _pay(p, amount):
    if p.gold < amount:
        raise IllegalAction('insufficient gold')
    p.gold -= amount


def _merge(p, champion):
    for star in (1, 2):
        candidates = sorted((u for u in p.units if u.champion == champion and u.stars == star),
                            key=lambda u: (u.zone != 'board', u.position, u.uid))
        while len(candidates) >= 3:
            selected = candidates[:3]
            # Item priority/overflow on real merges needs its own verified rule.
            if any(u.items for u in selected):
                raise UnsupportedRule('equipped-item merge ordering not implemented')
            if any(u.permanent for u in selected):
                raise UnsupportedRule('permanent stack merge ordering not implemented')
            keep = selected[0]; keep.stars += 1
            p.units = [u for u in p.units if u not in selected[1:]]
            candidates = candidates[3:]


def _reroll(world, p, content, rng):
    for offer in p.shop:
        if offer is not None:
            if offer.kind != 'champion':
                raise UnsupportedRule('seasonal shop refresh not implemented for this offer')
            world.pool[offer.entity] = world.pool.get(offer.entity, 0) + 1
    weights = content['economy']['shop_odds'].get(str(p.level))
    if weights is None or len(weights) != 5 or abs(sum(weights) - 1) > 1e-6:
        raise UnsupportedRule('verified shop odds unavailable for level')
    p.shop = []
    for _ in range(5):
        available = {cost: [c for c, n in world.pool.items() if n > 0 and
                           content['champions'][c]['cost'] == cost] for cost in range(1, 6)}
        costs = [c for c in available if available[c] and weights[c-1] > 0]
        if not costs:
            p.shop.append(None); continue
        cost = rng.choices(costs, [weights[c-1] for c in costs])[0]
        champion = rng.choices(available[cost], [world.pool[c] for c in available[cost]])[0]
        world.pool[champion] -= 1
        p.shop.append(Offer('champion', champion, cost))


def apply(world: World, seat: int, action: Action, content: dict) -> World:
    """Return a new state, or raise without changing the original state or RNG."""
    validate_world(world, content)
    if type(seat) is not int or not 0 <= seat < len(world.players):
        raise IllegalAction('invalid seat')
    result = deepcopy(world); p = result.players[seat]
    if p.phase != 'planning' or p.hp <= 0:
        raise IllegalAction('player cannot act')
    rng = random.Random(world.seed)
    if world.rng_state is not None:
        rng.setstate(world.rng_state)
    args, kind = action.args, action.kind
    if kind == 'hold':
        if args: raise IllegalAction('hold takes no arguments')
    elif kind == 'lock':
        if len(args) != 1 or type(args[0]) is not bool: raise IllegalAction('lock needs a boolean')
        p.shop_locked = args[0]
    elif kind == 'buy':
        if len(args) != 1 or type(args[0]) is not int or not 0 <= args[0] < 5:
            raise IllegalAction('invalid shop slot')
        offer = p.shop[args[0]]
        if offer is None: raise IllegalAction('empty shop slot')
        if offer.kind != 'champion': raise UnsupportedRule('shop consumable needs explicit handler')
        if offer.entity not in content['champions']: raise UnsupportedRule('unknown champion')
        _pay(p, offer.cost)
        empty = _bench(p)
        if empty is None:
            # A full bench can still buy the third copy when the purchase merges.
            copies = [u for u in p.units if u.champion == offer.entity and u.stars == 1]
            if len(copies) < 2: raise IllegalAction('bench full')
            empty = 9  # temporary only; post-merge validation enforces the real limit.
        occupied_ids = {u.uid for player in result.players for u in player.units}
        while f'unit-{result.next_uid}' in occupied_ids: result.next_uid += 1
        p.units.append(Unit(f'unit-{result.next_uid}', offer.entity, position=(empty,)))
        result.next_uid += 1; p.shop[args[0]] = None
        _merge(p, offer.entity)
    elif kind == 'sell':
        if len(args) != 1: raise IllegalAction('sell needs unit')
        u = _find(p, args[0])
        if len(p.inventory) + len(u.items) > content['economy']['inventory_slots']:
            raise UnsupportedRule('item overflow on sale requires drop handling')
        price = content['champions'][u.champion].get('sale_prices', {}).get(str(u.stars))
        if price is None: raise UnsupportedRule('sale value unavailable at star level')
        p.gold += price; p.inventory.extend(u.items); p.units.remove(u)
        result.pool[u.champion] = result.pool.get(u.champion, 0) + 3 ** (u.stars - 1)
    elif kind == 'move':
        if len(args) != 3: raise IllegalAction('move needs unit, zone, position')
        u = _find(p, args[0]); zone, pos = args[1], tuple(args[2])
        other = next((v for v in p.units if v.zone == zone and v.position == pos and v.uid != u.uid), None)
        if other is not None: other.zone, other.position = u.zone, u.position
        u.zone, u.position = zone, pos
    elif kind == 'equip':
        if len(args) != 2: raise IllegalAction('equip needs inventory slot and unit')
        slot, uid = args
        if type(slot) is not int or not 0 <= slot < len(p.inventory): raise IllegalAction('invalid inventory slot')
        u = _find(p, uid); item = p.inventory[slot]
        components=[j for j,i in enumerate(u.items) if content['items'][i].get('component')]
        if content['items'][item].get('component') and components:
            if len(components)!=1: raise UnsupportedRule('ambiguous equipped-component priority')
            index=components[0]
            product=content['recipes'].get('+'.join(sorted((item,u.items[index]))))
            if product is None: raise UnsupportedRule('equipped recipe unavailable')
            if content['items'][product].get('unique') and product in u.items:
                raise IllegalAction('unique recipe product already equipped')
            u.items[index]=product;p.inventory.pop(slot)
        else:
            if len(u.items) >= 3: raise IllegalAction('unit item slots full')
            if content['items'][item].get('unique') and item in u.items: raise IllegalAction('unique item already equipped')
            u.items.append(p.inventory.pop(slot))
    elif kind == 'combine':
        if not content['economy'].get('allow_inventory_combine',False):
            raise UnsupportedRule('inventory crafting is not enabled; equip components onto a unit')
        if len(args) != 2 or any(type(v) is not int or not 0 <= v < len(p.inventory) for v in args) or args[0] == args[1]:
            raise IllegalAction('combine needs two different inventory slots')
        ingredients = sorted(p.inventory[v] for v in args)
        product = content['recipes'].get('+'.join(ingredients))
        if product is None: raise UnsupportedRule('recipe unavailable')
        for i in sorted(args, reverse=True): p.inventory.pop(i)
        p.inventory.append(product)
    elif kind == 'xp':
        if args: raise IllegalAction('xp takes no arguments')
        e = content['economy']
        if str(p.level) not in e['xp_to_next']: raise IllegalAction('level cap or unknown XP curve')
        _pay(p, e['xp_cost']); p.xp += e['xp_amount']
        while str(p.level) in e['xp_to_next'] and p.xp >= e['xp_to_next'][str(p.level)]:
            p.xp -= e['xp_to_next'][str(p.level)]; p.level += 1
    elif kind == 'reroll':
        if args: raise IllegalAction('reroll takes no arguments')
        _pay(p, content['economy']['reroll_cost']); _reroll(result, p, content, rng)
    else:
        raise IllegalAction('unknown action')
    result.rng_state = rng.getstate()
    validate_world(result, content)
    return result


def legal_actions(world, seat, content, *, positions=False):
    p = world.players[seat]
    proposals = [Action('hold'), Action('xp'), Action('reroll'), Action('lock', (not p.shop_locked,))]
    proposals += [Action('buy', (i,)) for i in range(5)]
    for u in p.units:
        proposals.append(Action('sell', (u.uid,)))
        proposals += [Action('equip', (i, u.uid)) for i in range(len(p.inventory))]
        if positions:
            proposals += [Action('move', (u.uid, 'board', (r, c))) for r in range(4) for c in range(7)
                          if u.zone != 'board' or u.position != (r, c)]
            proposals += [Action('move', (u.uid, 'bench', (i,))) for i in range(9)
                          if u.zone != 'bench' or u.position != (i,)]
    proposals += [Action('combine', (i, j)) for i in range(len(p.inventory)) for j in range(i+1, len(p.inventory))]
    result = []
    for action in proposals:
        try: apply(world, seat, action, content)
        except (IllegalAction, UnsupportedRule): continue
        result.append(action)
    return result
