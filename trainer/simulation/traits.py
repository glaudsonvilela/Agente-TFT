"""Count distinct identities, emblems and explicit extra trait contributions."""
from collections import defaultdict
from copy import deepcopy
from .state import UnsupportedRule


def active_traits(player, content):
    identities=defaultdict(dict)
    membership={}
    for u in player.units:
        if u.zone!='board': continue
        champion=content['champions'][u.champion]
        identity=champion.get('identity',u.champion)
        tags=set(champion.get('traits',[]))
        for item in u.items: tags.update(content['items'][item].get('grants_traits',[]))
        membership[u.uid]=tags
        for trait in tags:
            contribution=champion.get('trait_contributions',{}).get(trait,1)
            if type(contribution) is not int or contribution<1:
                raise UnsupportedRule('invalid trait contribution')
            identities[trait][identity]=max(identities[trait].get(identity,0),contribution)
    active=[]
    for trait,units in sorted(identities.items()):
        spec=content.get('traits',{}).get(trait)
        if spec is None: raise UnsupportedRule(f'trait definition missing: {trait}')
        count=sum(units.values())
        tiers=[t for t in spec['tiers'] if t['min']<=count and count<=t.get('max',1000)]
        if not tiers: continue
        tier=max(tiers,key=lambda t:t['min'])
        if tier.get('unsupported') or spec.get('unsupported'):
            raise UnsupportedRule(f'active trait effect not implemented: {trait}')
        active.append(dict(id=trait,count=count,members=[uid for uid,tags in membership.items() if trait in tags],
                           tier=deepcopy(tier)))
    return active


def contributions(player,content):
    """Per-unit effects/procs. Member bonuses may replace or add to team bonuses."""
    rows={u.uid:dict(modifiers=[],hooks=[]) for u in player.units if u.zone=='board'}
    active=active_traits(player,content)
    for trait in active:
        tier=trait['tier']
        for uid,row in rows.items():
            member=uid in trait['members']
            scopes=['team']
            if member:
                scopes=['members'] if tier.get('members_replace_team',False) else ['team','members']
            for scope in scopes:
                effect=tier.get(scope,{})
                row['modifiers'].extend(deepcopy(effect.get('modifiers',[])))
                row['hooks'].extend(deepcopy(effect.get('hooks',[])))
    for augment in player.augments:
        spec=content.get('augments',{}).get(augment)
        if spec is None or spec.get('unsupported'): raise UnsupportedRule(f'augment handler missing: {augment}')
        if spec.get('planning_effects'): raise UnsupportedRule('planning augment settlement not implemented')
        for row in rows.values():
            row['modifiers'].extend(deepcopy(spec.get('modifiers',[])))
            row['hooks'].extend(deepcopy(spec.get('hooks',[])))
    return rows,active
