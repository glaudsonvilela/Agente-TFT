"""Eight-player synthetic integration loop. Not the TFT seasonal round schedule.

The rules bundle declares income, XP, damage and the intentionally simplified
pairing/loot/streak policies. Unknown policies raise instead of being skipped.
"""
from copy import deepcopy
import math
import random

from .combat import simulate
from .state import Action, World, Player, IllegalAction, UnsupportedRule, apply, validate_world, _reroll
from .economy import grant_xp, pool_identity, return_copies, positive_integer


def match_rules(content, *, initializing=False):
    rules = content.get('match_rules')
    if not isinstance(rules, dict) or content.get('planning_requirements'):
        raise UnsupportedRule('complete match progression dependencies unavailable')
    model=rules.get('income_model','fixed_round')
    if model not in ('fixed_round','ordinary_pvp_economy'):
        raise UnsupportedRule('unknown income model')
    if model=='ordinary_pvp_economy':
        from .round_economy import validate_rules
        validate_rules(rules.get('round_economy',{}))
        if initializing:
            raise UnsupportedRule('ordinary PvP settlement requires an observed stage; full calendar unavailable')
    else:
        positive_integer(rules.get('interest_step'), 'interest_step')
        for field in ('base_income', 'interest_cap', 'natural_xp', 'loss_damage', 'tie_damage'):
            positive_integer(rules.get(field), field, zero=True)
    if initializing:
        for field in ('starting_level', 'starting_hp', 'pool_per_champion'):
            positive_integer(rules.get(field), field)
        positive_integer(rules.get('starting_gold'), 'starting_gold', zero=True)
    streak_policy='outcome_signed' if model=='ordinary_pvp_economy' else 'none'
    if tuple(rules.get(k) for k in ('pairing', 'loot', 'streaks')) != ('seeded_shuffle_with_bye', 'none', streak_policy):
        raise UnsupportedRule('seasonal round policies not implemented')
    return rules


def new_match(content, seed):
    rules=match_rules(content, initializing=True)
    if content.get('scope') != 'experimental_hex_lab': raise UnsupportedRule('experimental match only')
    pool = {pool_identity(c, content): rules['pool_per_champion'] for c in content['champions']}
    world = World([Player(rules['starting_gold'],rules['starting_level'],0,hp=rules['starting_hp'])
                  for _ in range(8)], pool, seed=seed,
                  round_phase='between_rounds', pool_totals=dict(pool))
    validate_world(world, content)
    return world


def begin_round(world, content):
    rules = match_rules(content)
    if rules.get('income_model') == 'ordinary_pvp_economy':
        raise UnsupportedRule('next observed stage and round type required; full calendar unavailable')
    if world.rules_scope != 'complete_rules':
        raise UnsupportedRule('planning probe cannot advance a full match')
    validate_world(world, content)
    if world.round_phase != 'between_rounds':
        raise IllegalAction('round already started')
    state=deepcopy(world); rng=random.Random(world.seed)
    state.round_phase='planning'; state.round_number+=1
    if world.rng_state: rng.setstate(world.rng_state)
    for p in state.players:
        if p.hp <= 0: continue
        p.phase='planning'
        if not p.shop_locked: _reroll(state,p,content,rng)
    state.rng_state=rng.getstate(); validate_world(state,content)
    return state


def resolve_round(world, content, seed):
    """All fights see the same round-start boards; settlement follows combat."""
    rules = match_rules(content)
    if world.rules_scope != 'complete_rules':
        raise UnsupportedRule('planning probe cannot settle a full match')
    validate_world(world, content)
    if world.round_phase != 'planning':
        raise IllegalAction('round has already settled or has not started')
    if any(p.phase != 'planning' for p in world.players if p.hp > 0):
        raise IllegalAction('round players are not in planning')
    state=deepcopy(world); rng=random.Random(seed)
    active=[i for i,p in enumerate(state.players) if p.hp>0]; rng.shuffle(active)
    if rules.get('income_model')=='ordinary_pvp_economy' and len(active)%2:
        raise UnsupportedRule('ordinary economy requires a resolved opponent; ghost pairing unavailable')
    if rules.get('income_model')=='ordinary_pvp_economy' and len({state.players[i].stage for i in active})!=1:
        raise UnsupportedRule('ordinary economy requires one shared observed stage')
    fights=[]
    for a,b in zip(active[::2],active[1::2]):
        result=simulate([world.players[a],world.players[b]],content,seed=rng.randrange(2**31))
        settle_combat(state,(a,b),result)
        winner=result['winner']
        if winner is not None and (type(winner) is not int or winner not in (0,1)):
            raise UnsupportedRule('invalid combat winner')
        receipts=[]
        if rules.get('income_model')=='ordinary_pvp_economy':
            from .round_economy import project_pvp
            if winner is None: raise UnsupportedRule('draw economy unavailable')
            for local,seat in enumerate((a,b)):
                enemy=(b,a)[local]
                original_enemy_ids={u.uid for u in world.players[enemy].units if u.zone=='board'}
                survivors=sum(row['health']>0 and row['uid'] in original_enemy_ids for row in result['units'])
                state.players[seat],receipt=project_pvp(state.players[seat],content,rules['round_economy'],
                    outcome='win' if local==winner else 'loss',surviving_enemy_champions=survivors)
                receipts.append(dict(seat=seat,**receipt))
        elif winner is None:
            state.players[a].hp=max(0,state.players[a].hp-rules['tie_damage'])
            state.players[b].hp=max(0,state.players[b].hp-rules['tie_damage'])
        else:
            loser=(a,b)[1-winner]
            state.players[loser].hp=max(0,state.players[loser].hp-rules['loss_damage'])
        fights.append(dict(seats=[a,b],winner=None if winner is None else (a,b)[winner],
                           duration_seconds=result['duration_seconds'],economy_receipts=receipts))
    eliminated=[]
    for i in active:
        p=state.players[i]
        p.round_free_rerolls=0
        if p.hp<=0:
            eliminated.append(i)
            for u in p.units:
                if u.stars > 3: raise UnsupportedRule('four-star elimination provenance not implemented')
                return_copies(state.pool, u.champion, 3**(u.stars-1), content)
            for offer in p.shop:
                if offer is not None:
                    if offer.kind!='champion': raise UnsupportedRule('eliminated seasonal offer')
                    return_copies(state.pool, offer.entity, 1, content)
            p.units=[];p.shop=[None]*5;p.phase='eliminated'
        else:
            p.phase='between_rounds'
            if rules.get('income_model')!='ordinary_pvp_economy':
                p.gold+=rules['base_income']+min(rules['interest_cap'],p.gold//rules['interest_step'])
                grant_xp(p, rules['natural_xp'], content)
    state.round_phase='between_rounds'
    validate_world(state,content)
    return state,dict(round_number=state.round_number,fights=fights,eliminated=eliminated,bye=active[-1] if len(active)%2 else None)


def settle_combat(state, seats, result):
    """Apply earned deltas once to the cloned round state, including dead owners.

    Temporary stats, health and summoned units never become owned pieces.
    Summon rewards belong to the summon team; summon stats are not persisted.
    The caller owns the atomic transaction (resolve_round uses a deep copy).
    """
    seen=set()
    for row in result.get('units',[]):
        uid=row['uid'];team=row['team']
        if uid in seen or type(team) is not int or team not in (0,1):
            raise UnsupportedRule('invalid combat settlement identity')
        seen.add(uid);player=state.players[seats[team]]
        owned=next((u for u in player.units if u.uid==uid),None)
        for stat,delta in row.get('permanent_delta',{}).items():
            if type(delta) not in (int,float) or not math.isfinite(delta):
                raise UnsupportedRule('invalid permanent reward')
            if owned is not None:owned.permanent[stat]=owned.permanent.get(stat,0)+delta
        for resource,amount in row.get('resources',{}).items():
            if resource!='gold' or type(amount) not in (int,float) or not math.isfinite(amount) or amount<0 or int(amount)!=amount:
                raise UnsupportedRule('invalid combat resource reward')
            player.gold+=int(amount)


def scripted_action(world,seat,content):
    p=world.players[seat]
    board=[u for u in p.units if u.zone=='board']
    bench=[u for u in p.units if u.zone=='bench']
    if bench and len(board)<p.level:
        u=bench[0]; ranged=content['champions'][u.champion]['combat']['range']>1
        occupied={v.position for v in board}
        rows=(3,2,1,0) if ranged else (0,1,2,3)
        pos=next((r,c) for r in rows for c in (3,2,4,1,5,0,6) if (r,c) not in occupied)
        return Action('move',(u.uid,'board',pos))
    if len(board)<p.level:
        for i,offer in enumerate(p.shop):
            if offer and offer.cost<=p.gold: return Action('buy',(i,))
    if p.gold>=20 and str(p.level) in content['economy']['xp_to_next']:
        return Action('xp')
    return Action('hold')


def play(content,seed=0,policy=scripted_action):
    world=new_match(content,seed); history=[]; placements={}
    for round_id in range(content['match_rules']['max_rounds']):
        world=begin_round(world,content)
        active=[i for i,p in enumerate(world.players) if p.hp>0]
        for seat in active:
            for _ in range(content['match_rules']['planning_actions']):
                action=policy(world,seat,content)
                if action.kind=='hold': break
                world=apply(world,seat,action,content)
        world,record=resolve_round(world,content,seed*1000+round_id)
        # Simultaneous eliminations share their mean place; no invented tie-break rule.
        place=len(active)-(len(record['eliminated'])-1)/2
        for seat in record['eliminated']: placements[str(seat)]=place
        history.append(record)
        survivors=[i for i,p in enumerate(world.players) if p.hp>0]
        if len(survivors)<=1:
            if survivors: placements[str(survivors[0])]=1.
            break
    completed=len([p for p in world.players if p.hp>0])<=1
    return dict(scope='experimental_hex_lab',seed=seed,rounds=len(history),completed=completed,
                truncated=not completed,placements=placements,history=history,
                combat_calls=sum(len(r['fights']) for r in history),runtime_promoted=False)
