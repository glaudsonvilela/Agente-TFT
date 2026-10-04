"""Declarative combat effects with explicit targets, stacking and provenance.

The engine executes only supplied rules. Kernel support is distinct from a
champion's replay-validated accuracy. This module never enables HUD promotion.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import heapq
import math
import random

from .combat import STATS, finite, star_value, mitigation
from .hexgrid import distance, global_hex, next_step
from .modifiers import Stats, formula
from .state import UnsupportedRule
from .traits import contributions

NEUTRAL=dict(damage_amp=0.,durability=0.,omnivamp=0.,wound=0.,healing_amp=0.,shield_amp=0.,
             armor_pen=0.,magic_pen=0.,sunder=0.,shred=0.,slow=0.,precision=0.,cc_immune=0.,invulnerable=0.,
             mana_per_pre_damage=0.,mana_damage_cap=1e12,vulnerable=0.)
EVENTS={'combat_start','attack','cast','ally_cast','damage_dealt','damage_taken',
        'kill','takedown','death','health_below','periodic','shield_end'}
OPS={'damage','heal','shield','mana','stat','status','over_time','execute',
     'permanent_stat','resource','summon','transform','displace',
     'sequence','branch','mark','volley','empower','cleanse'}
TARGETS={'self','target','allies','enemies','lowest_hp_allies','nearest_enemies',
         'farthest_enemies','target_and_nearest','area','best_area','line',
         'best_line','area_allies','lowest_hp_enemies','most_damage_allies','least_items_farthest'}


@dataclass
class Shield:
    key: str
    amount: float
    expires: float


@dataclass
class Actor:
    uid: str
    champion: str
    team: int
    stars: int
    position: tuple
    values: Stats
    spell: dict
    hooks: list
    tags: set
    hp: float
    mana: float
    shields: list=field(default_factory=list)
    statuses: dict=field(default_factory=dict)
    counters: dict=field(default_factory=dict)
    cooldowns: dict=field(default_factory=dict)
    permanent_delta: dict=field(default_factory=dict)
    resources: dict=field(default_factory=dict)
    damage_dealt: float=0.
    attacks: int=0
    casts: int=0
    version: int=0
    dot_groups: dict=field(default_factory=dict)
    contributors: set=field(default_factory=set)
    mana_lock_until: float=0.
    marks: set=field(default_factory=set)
    empowers: dict=field(default_factory=dict)
    item_count: int=0


def validate_effects(effects):
    if not isinstance(effects,list): raise UnsupportedRule('effects must be a list')
    for e in effects:
        if e.get('op') not in OPS: raise UnsupportedRule(f"unsupported effect: {e.get('op')}")
        selector=e.get('target',{'kind':'target'})
        if selector.get('kind') not in TARGETS: raise UnsupportedRule('unsupported selector')
        if set(selector)-{'kind','center','cast_range','radius','width','exclude_self','exclude_status','max_range','count','shares_trait','damaged_only'}:
            raise UnsupportedRule('unknown targeting field')
        fields={
            'damage':{'amount','damage_type','falloff_min','falloff_per_hex','falloff_per_target','execute_threshold','low_health_multiplier','can_crit','first_target_multiplier','per_unique_three_star'},
            'heal':{'amount'},'shield':{'amount','duration','can_crit'},'mana':{'amount'},
            'stat':{'amount','stat','mode','duration','group','strongest','health_change'},
            'permanent_stat':{'amount','stat','mode','health_change'},
            'status':{'name','duration'},
            'over_time':{'duration','ticks','effects','then','mark','scaling_time','stacking','group'},
            'execute':set(),'resource':{'resource','amount'},
            'summon':{'champion','count','stars'},'transform':{'base_stats','spell'},
            'displace':{'max_hexes','direction'},
            'sequence':{'effects'},'branch':{'condition','effects','otherwise'},
            'mark':{'name'},'cleanse':{'statuses'},
            'volley':{'count','effects'},
            'empower':{'charges','replace_attack','attack_speed','effects','last_effects'}}
        if set(e)-({'op','target','key'}|fields[e['op']]):raise UnsupportedRule('unknown effect field')
        if 'duration' in e and any(finite(v,'duration')<=0 for v in (e['duration'] if isinstance(e['duration'],list) else [e['duration']])):raise UnsupportedRule('invalid effect duration')
        if e['op'] in ('sequence','branch','volley','empower'):
            validate_effects(e['effects'])
        if e['op']=='branch':
            c=e['condition']
            if not isinstance(c,dict) or len(c)!=1 or next(iter(c)) not in ('marked','casts_at_least'):
                raise UnsupportedRule('unknown ability condition')
            validate_effects(e.get('otherwise',[]))
        if e['op'] in ('volley','empower'):
            value=e['count' if e['op']=='volley' else 'charges']
            for n in value if isinstance(value,list) else [value]:
                if type(n) is not int or not 1<=n<=100:raise UnsupportedRule('invalid ability counter')
        if e['op']=='empower':
            validate_effects(e.get('last_effects',[]))
            if type(e.get('replace_attack')) is not bool or 'key' not in e:
                raise UnsupportedRule('empowered attack replacement and key required')
            finite(e.get('attack_speed',0),'empowered attack speed')
        if e['op']=='cleanse' and set(e['statuses'])-{'stun','disarm','silence','root'}:
            raise UnsupportedRule('unknown cleanse status')
        if e['op']=='over_time':
            if type(e.get('ticks')) is not int or not 1<=e['ticks']<=1000 or finite(e.get('duration'),'duration')<=0:
                raise UnsupportedRule('invalid periodic effect')
            if e.get('scaling_time') not in ('snapshot','dynamic'):
                raise UnsupportedRule('periodic scaling time must be explicit')
            if e.get('stacking') not in ('stack','refresh_strongest'):
                raise UnsupportedRule('periodic stacking policy must be explicit')
            validate_effects(e['effects']);validate_effects(e.get('then',[]))
        if e['op'] in ('damage','heal','shield','mana','stat','permanent_stat','resource'):
            if not isinstance(e.get('amount'),list): raise UnsupportedRule('explicit formula required')
        if e['op']=='damage' and e.get('damage_type') not in ('magic','physical','true'):
            raise UnsupportedRule('damage type unavailable')


class Battle:
    def __init__(self,players,content,seed=0,trace=False):
        if len(players)!=2 or content.get('scope')!='experimental_hex_lab':
            raise UnsupportedRule('event combat remains experimental; two teams required')
        self.content=content;self.rng=random.Random(seed);self.seed=seed
        self.now=0.;self.queue=[];self.sequence=0;self.units=[];self.by_id={};self.history=[]
        self.trace=trace;self.active_traits=[];self.max_events=content['combat_rules'].get('max_events',100000)
        self.effect_depth=0
        cfg=content['combat_rules']
        self.duration=finite(cfg['duration'],'duration')
        self.move_seconds=finite(cfg['move_seconds'],'move_seconds')
        self.cap=finite(cfg['attack_speed_cap'],'attack_speed_cap')
        self.windup=finite(cfg['attack_windup_fraction'],'attack_windup_fraction')
        self.projectile_speed=finite(cfg['projectile_hexes_per_second'],'projectile speed')
        if min(self.duration,self.move_seconds,self.cap)<=0 or not 0<=self.windup<=1 or self.projectile_speed<0:
            raise UnsupportedRule('invalid event clock')
        for team,player in enumerate(players):
            effects,traits=contributions(player,content);self.active_traits.append(traits)
            occupied=set()
            for unit in player.units:
                if unit.zone!='board': continue
                actor=self.create(unit.uid,unit.champion,team,unit.stars,global_hex(team,unit.position),
                                  unit.items,unit.permanent,effects[unit.uid])
                if actor.position in occupied: raise UnsupportedRule('occupied starting hex')
                occupied.add(actor.position)

    def create(self,uid,champion,team,stars,position,items=(),permanent=None,team_effects=None):
        if uid in self.by_id: raise UnsupportedRule('duplicate actor')
        spec=self.content['champions'].get(champion)
        if not spec or spec.get('unsupported') or spec.get('special_rules'):
            raise UnsupportedRule(f'champion handler unavailable: {champion}')
        base={k:star_value(spec['combat'].get(k),stars,k) for k in STATS}
        base.update({k:star_value(spec['combat'].get(k,v),stars,k) for k,v in NEUTRAL.items()})
        values=Stats(base);hooks=deepcopy(spec.get('hooks',[]));tags=set(spec.get('traits',[]))
        mods=deepcopy(spec.get('modifiers',[]))
        for item_index,item in enumerate(items):
            rule=self.content['items'].get(item)
            if not rule or rule.get('combat_handler')!='effects':
                raise UnsupportedRule(f'item handler unavailable: {item}')
            mods.extend(deepcopy(rule.get('modifiers',[])))
            item_hooks=deepcopy(rule.get('hooks',[]))
            def namespace(value):
                if isinstance(value,list):
                    for entry in value:namespace(entry)
                elif isinstance(value,dict):
                    for key,entry in value.items():
                        if key in ('key','shield_key','counter'):value[key]=f'item:{item_index}:{entry}'
                        else:namespace(entry)
            namespace(item_hooks)
            hooks.extend(item_hooks)
            tags.update(rule.get('grants_traits',[]))
        if team_effects:
            mods.extend(team_effects['modifiers']);hooks.extend(team_effects['hooks'])
        for key,value in (permanent or {}).items():
            values.add('permanent:'+key,key,finite(value,key))
        for i,m in enumerate(mods):
            values.add(f'initial:{i}',m['stat'],finite(m['value'],m['stat']),m['mode'],when=m.get('when'))
        spell=deepcopy(spec.get('spell'))
        if not spell or spell.get('kind') not in ('none','effects'): raise UnsupportedRule('event spell missing')
        if spell['kind']=='effects':
            if values.get('mana')<=0 or finite(spell.get('cast_seconds'),'cast time')<0:
                raise UnsupportedRule('active spell mana/timing missing')
            validate_effects(spell['effects'])
        for i,h in enumerate(hooks):
            if h.get('event') not in EVENTS: raise UnsupportedRule('unknown trigger')
            h['_key']=f'hook:{i}'
            validate_effects(h['effects'])
            validate_effects(h.get('at_limit_effects',[]))
            if 'counter' in h and (not isinstance(h['counter'],str) or not h['counter']):
                raise UnsupportedRule('invalid shared trigger counter')
            if 'limit' in h and (type(h['limit']) is not int or h['limit']<1):
                raise UnsupportedRule('invalid trigger limit')
            if h.get('at_limit_effects') and 'limit' not in h:raise UnsupportedRule('capstone requires a limit')
            if h['event']=='periodic' and finite(h.get('interval'),'interval')<=0:
                raise UnsupportedRule('invalid interval')
        if values.get('hp')<=0 or values.get('attack_speed')<=0 or values.get('range')<1:
            raise UnsupportedRule('invalid health/speed/range')
        if any(values.get(k)<0 for k in ('ad','ap','mana','initial_mana','mana_per_attack','mana_per_second')):
            raise UnsupportedRule('negative combat resource')
        if not 0<=values.get('crit_chance')<=1:
            raise UnsupportedRule('critical chance overflow conversion is not implemented')
        actor=Actor(uid,champion,team,stars,position,values,spell,hooks,tags,
                    values.get('hp'),values.get('initial_mana'))
        actor.item_count=len(items)
        self.units.append(actor);self.by_id[uid]=actor
        return actor

    def emit(self,kind,**data):
        if self.trace:self.history.append(dict(time=round(self.now,6),kind=kind,**data))

    def schedule(self,when,kind,uid,payload=None):
        if not math.isfinite(when) or when<self.now: raise UnsupportedRule('invalid event time')
        self.sequence+=1;heapq.heappush(self.queue,(when,self.sequence,kind,uid,payload))

    def get(self,u,key):
        return u.values.get(key,self.now,context={'shielded':any(s.amount>0 and s.expires>self.now for s in u.shields)})

    def status(self,u,name):return max((end for end in u.statuses.get(name,[]) if end>self.now),default=0.)

    def targetable(self,u):return u.hp>0 and not self.status(u,'untargetable')

    def select(self,source,target,selector):
        kind=selector['kind']; enemies=[u for u in self.units if u.team!=source.team and self.targetable(u)]
        allies=[u for u in self.units if u.team==source.team and self.targetable(u)]
        self.last_center=target.position if target else source.position
        if kind=='self':return [source]
        if kind=='target':return [target] if target and self.targetable(target) else []
        if kind=='allies': candidates=allies
        elif kind in ('enemies','nearest_enemies','farthest_enemies','target_and_nearest'):candidates=enemies
        elif kind in ('lowest_hp_allies','lowest_hp_enemies'):
            candidates=sorted(allies if kind=='lowest_hp_allies' else enemies,key=lambda u:(u.hp/self.get(u,'hp'),u.uid))
        elif kind=='most_damage_allies':candidates=sorted(allies,key=lambda u:(-u.damage_dealt,u.uid))
        elif kind=='least_items_farthest':candidates=sorted(enemies,key=lambda u:(u.item_count,-distance(source.position,u.position),u.uid))
        elif kind in ('area','area_allies','best_area','line','best_line'):
            center=source.position if selector.get('center','target')=='source' else target.position if target else source.position
            if kind=='best_area':
                cells=[(r,c) for r in range(8) for c in range(7) if distance(source.position,(r,c))<=selector['cast_range']]
                center=max(cells,key=lambda p:(sum(distance(p,u.position)<=selector['radius'] for u in enemies),
                                                -distance(p,center),-p[0],-p[1]))
            if kind=='best_line':
                lines=[(u,self.select(source,u,dict(kind='line',width=selector['width']))) for u in enemies]
                if not lines:return []
                target,candidates=min(lines,key=lambda p:(-len(p[1]),distance(source.position,p[0].position),p[0].uid))
                center=target.position
            elif kind=='line':
                if target is None:return []
                # Exact center-line intersections; widths must be explicitly provided.
                from .hexgrid import cube
                import math as geometry
                def xy(pos):
                    q,_,r=cube(pos);return geometry.sqrt(3)*(q+r/2),1.5*r
                sx,sy=xy(source.position);tx,ty=xy(target.position);vx,vy=tx-sx,ty-sy
                length=math.hypot(vx,vy)
                if length==0:return []
                candidates=[]
                for u in enemies:
                    ux,uy=xy(u.position);projection=((ux-sx)*vx+(uy-sy)*vy)/length
                    perpendicular=abs((ux-sx)*vy-(uy-sy)*vx)/length
                    if projection>0 and perpendicular<=selector['width']:
                        candidates.append(u)
                candidates.sort(key=lambda u:(distance(source.position,u.position),u.uid))
            else:
                candidates=[u for u in (allies if kind=='area_allies' else enemies) if distance(center,u.position)<=selector['radius']]
            self.last_center=center
        else:raise UnsupportedRule('selector not implemented')
        if kind in ('nearest_enemies','farthest_enemies','target_and_nearest'):
            reverse=-1 if kind=='farthest_enemies' else 1
            candidates.sort(key=lambda u:(reverse*distance(source.position,u.position),u.uid))
        if selector.get('shares_trait'):candidates=[u for u in candidates if u.tags & source.tags]
        if selector.get('damaged_only'):candidates=[u for u in candidates if u.hp<self.get(u,'hp')]
        if selector.get('exclude_self'):candidates=[u for u in candidates if u.uid!=source.uid]
        if 'exclude_status' in selector:candidates=[u for u in candidates if not self.status(u,selector['exclude_status'])]
        if 'max_range' in selector:candidates=[u for u in candidates if distance(source.position,u.position)<=selector['max_range']]
        if kind=='target_and_nearest' and target and self.targetable(target):
            candidates=[target]+[u for u in candidates if u.uid!=target.uid]
        return candidates[:int(star_value(selector.get('count',len(candidates)),source.stars,'target count'))]

    def change_stat(self,u,key,value,mode,identifier,duration=None,group=None,strongest=False,health_change=None):
        old_hp=self.get(u,'hp')
        u.values.add(identifier,key,value,mode,expires=self.now+duration if duration is not None else math.inf,
                     group=group,strongest=strongest)
        if key=='hp':
            if health_change=='add_delta':u.hp+=self.get(u,'hp')-old_hp
            elif health_change=='preserve_fraction':u.hp=u.hp/old_hp*self.get(u,'hp')
            elif health_change!='preserve_current':raise UnsupportedRule('maximum health change semantics required')
            u.hp=min(u.hp,self.get(u,'hp'))
        if duration is not None:self.schedule(self.now+duration,'expiry',u.uid)

    def gain_mana(self,u,value):
        if self.now>=u.mana_lock_until and u.hp>0:u.mana=max(0,u.mana+value)

    def hook(self,event,u,target=None,context=None):
        context=context or {}
        for h in u.hooks:
            if h['event']!=event:continue
            if context.get('only_hook') is not None and h['_key']!=context['only_hook']:continue
            key=h['_key'];seen=u.counters.get(key+':seen',0)+1;u.counters[key+':seen']=seen
            if seen%h.get('every',1):continue
            counter=h.get('counter',key)
            if u.counters.get(counter,0)>=h.get('limit',math.inf) or u.cooldowns.get(key,0)>self.now:continue
            if 'damage_tag' in h and context.get('tag')!=h['damage_tag']:continue
            if 'damage_tags' in h and context.get('tag') not in h['damage_tags']:continue
            if 'shield_key' in h and context.get('key')!=h['shield_key']:continue
            if 'caster_trait' in h and (target is None or h['caster_trait'] not in target.tags):continue
            if event=='health_below' and (u.hp<=0 or u.hp/self.get(u,'hp')>=h['threshold']):continue
            if self.rng.random()>h.get('chance',1.):continue
            u.counters[counter]=u.counters.get(counter,0)+1;u.cooldowns[key]=self.now+h.get('cooldown',0)
            reached_limit=u.counters[counter]==h.get('limit')
            self.effects(u,target,h['effects'],context,tag='proc')
            if reached_limit:
                self.effects(u,target,h.get('at_limit_effects',[]),context,tag='proc')

    def heal(self,source,target,raw):
        if target.hp<=0:return 0.
        value=max(0,raw)*(1+self.get(source,'healing_amp'))*(1-min(1,max(0,self.get(target,'wound'))))
        actual=min(self.get(target,'hp')-target.hp,value);target.hp+=actual
        self.emit('heal',source=source.uid,target=target.uid,amount=actual)
        return actual

    def hit(self,source,target,raw,dtype,tag,critical=False,trigger_procs=True):
        if target.hp<=0 or self.get(target,'invulnerable')>0:return 0.
        if dtype=='physical':resist=self.get(target,'armor')*(1-self.get(target,'sunder'))*(1-self.get(source,'armor_pen'))
        elif dtype=='magic':resist=self.get(target,'mr')*(1-self.get(target,'shred'))*(1-self.get(source,'magic_pen'))
        elif dtype=='true':resist=0
        else:raise UnsupportedRule('unknown damage type')
        damage=max(0,raw)*(self.get(source,'crit_multiplier') if critical else 1)
        if dtype!='true':damage*=mitigation(resist)*(1+self.get(source,'damage_amp'))*(1-min(1,max(0,self.get(target,'durability'))))
        if dtype!='true':damage*=1+max(0,self.get(target,'vulnerable'))
        pre_shield=damage
        for shield in sorted(target.shields,key=lambda s:s.expires):
            if shield.expires<=self.now or shield.amount<=0:continue
            absorbed=min(damage,shield.amount);damage-=absorbed;shield.amount-=absorbed
            if shield.amount<=0:self.hook('shield_end',target,source,dict(key=shield.key))
        lost=min(target.hp,damage);target.hp-=lost;source.damage_dealt+=lost
        if lost>0:target.contributors.add(source.uid)
        if tag!='proc':self.heal(source,source,lost*self.get(source,'omnivamp'))
        self.gain_mana(target,min(self.get(target,'mana_damage_cap'),
                                 max(0,raw)*self.get(target,'mana_per_pre_damage')+
                                 pre_shield*self.get(target,'mana_per_damage')))
        context=dict(tag=tag,damage=lost,critical=critical)
        self.emit('damage',source=source.uid,target=target.uid,amount=lost,damage_type=dtype,tag=tag,critical=critical)
        if target.hp<=0:
            target.version+=1;self.emit('death',target=target.uid)
            self.hook('kill',source,target,context);self.hook('death',target,source,context)
            for contributor in sorted(target.contributors):self.hook('takedown',self.by_id[contributor],target,context)
        else:
            self.hook('health_below',target,source,context)
            if trigger_procs:self.hook('damage_taken',target,source,context)
        if trigger_procs:self.hook('damage_dealt',source,target,context)
        return lost

    def effects(self,source,target,effects,context=None,tag='spell'):
        if self.effect_depth>=32:raise UnsupportedRule('recursive combat effect loop')
        self.effect_depth+=1
        try:self._effects(source,target,effects,context,tag)
        finally:self.effect_depth-=1

    def _effects(self,source,target,effects,context=None,tag='spell'):
        context=dict(context or {})
        for effect in effects:
            selector=effect.get('target',{'kind':'target'})
            selected=self.select(source,target,selector)
            center=getattr(self,'last_center',target.position if target else source.position)
            if effect['op']=='volley':
                for shot in range(int(star_value(effect['count'],source.stars,'volley count'))):
                    living=[u for u in selected if self.targetable(u)]
                    if not living:break
                    self.effects(source,living[shot%len(living)],effect['effects'],context,tag)
                continue
            for index,unit in enumerate(selected):
                op=effect['op'];raw=formula(effect['amount'],source,unit,self.now,context) if 'amount' in effect else None
                identifier=effect.get('key',f'effect:{source.uid}:{self.sequence}:{index}')
                if op=='damage':
                    raw*=max(effect.get('falloff_min',0),1-effect.get('falloff_per_hex',0)*distance(center,unit.position))
                    raw*=max(effect.get('falloff_min',0),1-star_value(effect.get('falloff_per_target',0),source.stars,'falloff')*context.get('target_index',index))
                    if 'execute_threshold' in effect and unit.hp/self.get(unit,'hp')<effect['execute_threshold']:
                        raw*=effect['low_health_multiplier']
                    if context.get('target_index',index)==0:raw*=effect.get('first_target_multiplier',1)
                    if 'per_unique_three_star' in effect:
                        identities={self.content['champions'][u.champion].get('identity',u.champion)
                                    for u in self.units if u.team==source.team and u.stars==3 and ':summon:' not in u.uid}
                        raw*=1+effect['per_unique_three_star']*len(identities)
                    crit=effect.get('can_crit',True) and self.get(source,'precision')>0 and self.rng.random()<self.get(source,'crit_chance')
                    dealt=self.hit(source,unit,raw,effect['damage_type'],tag,crit,tag!='proc')
                    context['damage']=dealt;context['total_damage']=context.get('total_damage',0)+dealt
                elif op=='heal':self.heal(source,unit,raw)
                elif op=='shield':
                    amount=max(0,raw)*(1+self.get(source,'shield_amp'))
                    if effect.get('can_crit') and self.get(source,'precision')>0 and self.rng.random()<self.get(source,'crit_chance'):
                        amount*=self.get(source,'crit_multiplier')
                    duration=star_value(effect['duration'],source.stars,'shield duration')
                    unit.shields.append(Shield(identifier,amount,self.now+duration))
                    self.schedule(self.now+duration,'expiry',unit.uid)
                    self.emit('shield',unit=unit.uid,amount=amount)
                elif op=='mana':self.gain_mana(unit,raw)
                elif op in ('stat','permanent_stat'):
                    self.change_stat(unit,effect['stat'],raw,effect.get('mode','flat'),identifier,
                                     star_value(effect['duration'],source.stars,'stat duration') if 'duration' in effect else None,
                                     effect.get('group'),effect.get('strongest',False),effect.get('health_change'))
                    if op=='permanent_stat':
                        if effect.get('mode','flat')!='flat':raise UnsupportedRule('permanent layer must be explicit flat value')
                        unit.permanent_delta[effect['stat']]=unit.permanent_delta.get(effect['stat'],0)+raw
                elif op=='status':
                    name=effect['name'];duration=star_value(effect['duration'],source.stars,'status duration')
                    if name not in ('stun','disarm','silence','root','untargetable','poison','burn'):
                        raise UnsupportedRule('unknown status')
                    if name in ('stun','disarm','silence','root') and self.get(unit,'cc_immune')>0:continue
                    unit.statuses.setdefault(name,[]).append(self.now+duration)
                    if name=='stun':
                        unit.version+=1;self.schedule(self.now+duration,'act',unit.uid,unit.version)
                    self.emit('status',unit=unit.uid,status=name,duration=duration)
                elif op=='sequence':self.effects(source,unit,effect['effects'],dict(context,target_index=index),tag)
                elif op=='mark':unit.marks.add((source.uid,effect['name']))
                elif op=='branch':
                    condition=effect['condition']
                    passed=((source.uid,condition['marked']) in unit.marks if 'marked' in condition
                            else source.casts>=condition['casts_at_least'])
                    self.effects(source,unit,effect['effects'] if passed else effect.get('otherwise',[]),context,tag)
                elif op=='cleanse':
                    stunned=bool(self.status(unit,'stun'))
                    for name in effect['statuses']:unit.statuses.pop(name,None)
                    if stunned and not self.status(unit,'stun'):
                        unit.version+=1;self.schedule(self.now,'act',unit.uid,unit.version)
                elif op=='empower':
                    key=f'empower:{source.uid}:{identifier}'
                    unit.values.remove(key)
                    unit.values.add(key,'attack_speed',effect.get('attack_speed',0),'base_pct')
                    unit.empowers[key]=dict(source=source.uid,remaining=int(star_value(effect['charges'],source.stars,'charges')),
                                             rule=deepcopy(effect))
                elif op=='over_time':
                    if effect.get('mark'):unit.statuses.setdefault(effect['mark'],[]).append(self.now+effect['duration'])
                    ticks=effect['ticks']
                    tick_effects=deepcopy(effect['effects'])
                    if effect['scaling_time']=='snapshot':
                        for child in tick_effects:
                            if 'amount' in child:child['amount']=[{'coefficient':formula(child['amount'],source,unit,self.now)}]
                    gate=None
                    tick_times=[self.now+effect['duration']*tick/ticks for tick in range(1,ticks+1)]
                    if effect.get('stacking')=='refresh_strongest':
                        group=effect['group'];dot_key=(group,source.uid,identifier)
                        power=sum(formula(e['amount'],source,unit,self.now) for e in tick_effects if e['op']=='damage')
                        token=self.sequence+1
                        interval=effect['duration']/ticks;old=unit.dot_groups.get(dot_key)
                        anchor=old[3] if old and old[1]>self.now else self.now
                        if old and old[1]>self.now and abs(old[4]-interval)>1e-9:
                            raise UnsupportedRule('refresh cannot silently change periodic cadence')
                        first=math.floor((self.now-anchor)/interval)+1
                        tick_times=[anchor+interval*k for k in range(first,first+ticks+1)
                                    if anchor+interval*k<=self.now+effect['duration']+1e-9]
                        unit.dot_groups[dot_key]=(token,self.now+effect['duration'],power,anchor,interval)
                        gate=dict(key=dot_key,token=token)
                    for when in tick_times:
                        payload=dict(target=unit.uid,effects=tick_effects,tag=tag,gate=gate)
                        self.schedule(when,'effects',source.uid,payload)
                    if effect.get('then'):
                        self.schedule(self.now+effect['duration'],'effects',source.uid,dict(target=unit.uid,effects=effect['then'],tag=tag))
                elif op=='execute':self.hit(source,unit,unit.hp+sum(s.amount for s in unit.shields), 'true',tag,trigger_procs=False)
                elif op=='resource':
                    if effect['resource']!='gold':raise UnsupportedRule('unknown combat reward')
                    unit.resources['gold']=unit.resources.get('gold',0)+raw
                elif op=='summon':
                    occupied={u.position for u in self.units if u.hp>0}
                    cells=sorted(((r,c) for r in range(8) for c in range(7) if (r,c) not in occupied),
                                 key=lambda p:(distance(unit.position,p),p))
                    for i in range(min(effect['count'],len(cells))):
                        uid=f'{source.uid}:summon:{len(self.units)}'
                        child=self.create(uid,effect['champion'],source.team,effect.get('stars',source.stars),cells[i])
                        self.start_actor(child,self.now)
                        self.emit('summon',source=source.uid,unit=uid,position=cells[i])
                elif op=='transform':
                    old_max=self.get(unit,'hp')
                    for key,value in effect['base_stats'].items():
                        if key not in unit.values.base:raise UnsupportedRule('transform stat unknown')
                        unit.values.base[key]=star_value(value,unit.stars,key)
                    unit.hp=unit.hp/old_max*self.get(unit,'hp')
                    if 'spell' in effect:validate_effects(effect['spell']['effects']);unit.spell=deepcopy(effect['spell'])
                elif op=='displace':
                    occupied={u.position for u in self.units if u.hp>0 and u.uid!=unit.uid}
                    cells=[(r,c) for r in range(8) for c in range(7) if (r,c) not in occupied and distance(unit.position,(r,c))<=effect['max_hexes']]
                    if cells:
                        reverse=-1 if effect['direction']=='away_from_source' else 1
                        unit.position=min(cells,key=lambda p:(reverse*distance(source.position,p),p))
                else:raise UnsupportedRule('effect not implemented')

    def start_actor(self,unit,when):
        self.hook('combat_start',unit,unit)
        for i,h in enumerate(unit.hooks):
            if h['event']=='periodic':self.schedule(self.now+h.get('start',h['interval']),'periodic',unit.uid,i)
        self.schedule(when,'act',unit.uid,unit.version)

    def run(self):
        initial=list(self.units);self.rng.shuffle(initial)
        start=finite(self.content['combat_rules']['first_action_seconds'],'first action')
        for unit in initial:self.start_actor(unit,start)
        previous=0.;processed=0
        while self.queue:
            if len({u.team for u in self.units if u.hp>0})<2 and self.queue[0][0]>self.now:break
            self.now,_,kind,uid,payload=heapq.heappop(self.queue)
            if self.now>self.duration:self.now=self.duration;break
            processed+=1
            if processed>self.max_events:raise UnsupportedRule('event budget exceeded; possible recursive rule')
            for u in list(self.units):
                if u.hp>0:
                    unlocked=max(0,self.now-max(previous,u.mana_lock_until))
                    u.mana+=unlocked*u.values.get('mana_per_second',previous)
                    u.values.expire(self.now);u.hp=min(u.hp,self.get(u,'hp'))
                    expired=[s for s in u.shields if s.expires<=self.now and s.amount>0]
                    u.shields[:]=[s for s in u.shields if s.expires>self.now and s.amount>0]
                    for shield in expired:self.hook('shield_end',u,None,dict(key=shield.key))
            previous=self.now;unit=self.by_id[uid]
            if kind=='expiry':continue
            if kind=='effects':
                gate=payload.get('gate')
                if gate:
                    target_unit=self.by_id[payload['target']];key=gate['key'];entry=target_unit.dot_groups.get(key)
                    if not entry or entry[0]!=gate['token']:continue
                    peers=[(k,v) for k,v in target_unit.dot_groups.items() if k[0]==key[0] and v[1]>=self.now]
                    if not peers or max(peers,key=lambda p:(p[1][2],p[0]))[0]!=key:continue
                self.effects(unit,self.by_id[payload['target']],payload['effects'],tag=payload['tag']);continue
            if kind=='impact':
                victim=self.by_id[payload['target']]
                if not payload.get('replace_attack'):
                    self.hit(unit,victim,payload['damage'],'physical','attack',payload['critical'])
                for enhanced in payload.get('enhanced',[]):
                    self.effects(self.by_id[enhanced['source']],victim,enhanced['effects'],tag='spell')
                continue
            if unit.hp<=0:continue
            if kind=='periodic':
                h=unit.hooks[payload];self.hook('periodic',unit,unit,dict(only_hook=h['_key']))
                if unit.counters.get(h.get('counter',h['_key']),0)<h.get('limit',math.inf):
                    self.schedule(self.now+h['interval'],'periodic',uid,payload)
                continue
            version=payload if kind=='act' else payload['version']
            if version!=unit.version:continue
            blocked=self.status(unit,'stun')
            if blocked:
                self.schedule(blocked,'act',uid,unit.version);continue
            enemies=[u for u in self.units if u.team!=unit.team and self.targetable(u)]
            if not enemies:
                self.schedule(self.now+self.move_seconds,'act',uid,unit.version);continue
            target=min(enemies,key=lambda u:(distance(unit.position,u.position),u.uid))
            speed=min(self.cap,max(.01,self.get(unit,'attack_speed')*(1-min(.99,max(0,self.get(unit,'slow'))))))
            if kind=='cast':
                original=self.by_id[payload['target']]
                if self.targetable(original):target=original
                self.effects(unit,target,payload['effects'])
                self.hook('cast',unit,target)
                for ally in list(self.units):
                    if ally.team==unit.team and ally.hp>0:self.hook('ally_cast',ally,unit)
                self.schedule(max(self.now,unit.mana_lock_until),'act',uid,unit.version);continue
            if kind=='attack':
                original=self.by_id[payload['target']]
                if self.targetable(original) and not self.status(unit,'disarm'):
                    unit.attacks+=1;crit=self.rng.random()<self.get(unit,'crit_chance')
                    delay=distance(unit.position,original.position)/self.projectile_speed if self.projectile_speed and self.get(unit,'range')>1 else 0.
                    enhanced=[];replace=False
                    for key,buff in list(unit.empowers.items()):
                        rule=buff['rule'];buff['remaining']-=1
                        enhanced.append(dict(source=buff['source'],effects=deepcopy(
                            rule.get('last_effects',rule['effects']) if buff['remaining']==0 else rule['effects'])))
                        replace=replace or rule['replace_attack']
                        if buff['remaining']==0:
                            unit.values.remove(key);del unit.empowers[key]
                    self.schedule(self.now+delay,'impact',uid,dict(target=original.uid,damage=self.get(unit,'ad'),critical=crit,
                                                                  replace_attack=replace,enhanced=enhanced))
                    self.gain_mana(unit,self.get(unit,'mana_per_attack'))
                    self.hook('attack',unit,original,dict(critical=crit))
                continue
            if distance(unit.position,target.position)>self.get(unit,'range'):
                if not self.status(unit,'root'):
                    occupied={u.position for u in self.units if u.hp>0 and u.uid!=uid}
                    unit.position=next_step(unit.position,target.position,self.get(unit,'range'),occupied)
                    self.emit('move',unit=uid,position=unit.position)
                self.schedule(self.now+self.move_seconds,'act',uid,unit.version)
            elif unit.spell['kind']!='none' and unit.mana>=self.get(unit,'mana') and not self.status(unit,'silence'):
                unit.mana-=self.get(unit,'mana');unit.casts+=1;self.emit('cast',unit=uid,target=target.uid)
                unit.mana_lock_until=self.now+unit.spell.get('mana_lock_seconds',unit.spell['cast_seconds'])
                self.schedule(self.now+unit.spell['cast_seconds'],'cast',uid,dict(version=unit.version,target=target.uid,effects=deepcopy(unit.spell['effects'])))
            else:
                if not self.status(unit,'disarm'):
                    self.schedule(self.now+self.windup/speed,'attack',uid,dict(version=unit.version,target=target.uid))
                self.schedule(self.now+1/speed,'act',uid,unit.version)
        alive={u.team for u in self.units if u.hp>0}
        return dict(schema_version=2,scope='experimental_hex_lab',seed=self.seed,
                    winner=next(iter(alive)) if len(alive)==1 else None,duration_seconds=self.now,
                    processed_events=processed,active_traits=self.active_traits,runtime_promoted=False,
                    units=[dict(uid=u.uid,team=u.team,health=u.hp,position=u.position,attacks=u.attacks,
                                casts=u.casts,damage_dealt=u.damage_dealt,permanent_delta=u.permanent_delta,
                                resources=u.resources) for u in self.units],events=self.history)


def simulate(players,content,*,seed=0,trace=False):
    return Battle(players,content,seed,trace).run()
