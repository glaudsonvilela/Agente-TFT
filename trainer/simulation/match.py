"""Eight-player synthetic integration loop. Not the TFT seasonal round schedule.

The rules bundle declares income, XP, damage and the intentionally simplified
pairing/loot/streak policies. Unknown policies raise instead of being skipped.
"""
from copy import deepcopy
import random

from .combat import simulate
from .state import Action, World, Player, UnsupportedRule, apply, validate_world, _reroll


def new_match(content, seed):
    rules=content['match_rules']
    if content.get('scope') != 'experimental_hex_lab': raise UnsupportedRule('experimental match only')
    if (rules['pairing'],rules['loot'],rules['streaks']) != ('seeded_shuffle_with_bye','none','none'):
        raise UnsupportedRule('seasonal round policies not implemented')
    return World([Player(rules['starting_gold'],rules['starting_level'],0,hp=rules['starting_hp'])
                  for _ in range(8)], {c:rules['pool_per_champion'] for c in content['champions']},seed=seed)


def begin_round(world, content):
    state=deepcopy(world); rng=random.Random(world.seed)
    if world.rng_state: rng.setstate(world.rng_state)
    for p in state.players:
        if p.hp <= 0: continue
        p.phase='planning'
        if not p.shop_locked: _reroll(state,p,content,rng)
    state.rng_state=rng.getstate(); validate_world(state,content)
    return state


def resolve_round(world, content, seed):
    """All fights see the same round-start boards; settlement follows combat."""
    state=deepcopy(world); rng=random.Random(seed); rules=content['match_rules']
    active=[i for i,p in enumerate(state.players) if p.hp>0]; rng.shuffle(active)
    fights=[]
    for a,b in zip(active[::2],active[1::2]):
        result=simulate([world.players[a],world.players[b]],content,seed=rng.randrange(2**31))
        winner=result['winner']
        if winner is None:
            state.players[a].hp=max(0,state.players[a].hp-rules['tie_damage'])
            state.players[b].hp=max(0,state.players[b].hp-rules['tie_damage'])
        else:
            loser=(a,b)[1-winner]
            state.players[loser].hp=max(0,state.players[loser].hp-rules['loss_damage'])
        fights.append(dict(seats=[a,b],winner=None if winner is None else (a,b)[winner],
                           duration_seconds=result['duration_seconds']))
    eliminated=[]
    for i in active:
        p=state.players[i]
        if p.hp<=0:
            eliminated.append(i)
            for u in p.units: state.pool[u.champion]+=3**(u.stars-1)
            for offer in p.shop:
                if offer is not None:
                    if offer.kind!='champion': raise UnsupportedRule('eliminated seasonal offer')
                    state.pool[offer.entity]+=1
            p.units=[];p.shop=[None]*5;p.phase='eliminated'
        else:
            p.gold+=rules['base_income']+min(rules['interest_cap'],p.gold//rules['interest_step'])
            p.xp+=rules['natural_xp']
            curve=content['economy']['xp_to_next']
            while str(p.level) in curve and p.xp>=curve[str(p.level)]:
                p.xp-=curve[str(p.level)];p.level+=1
    validate_world(state,content)
    return state,dict(fights=fights,eliminated=eliminated,bye=active[-1] if len(active)%2 else None)


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
