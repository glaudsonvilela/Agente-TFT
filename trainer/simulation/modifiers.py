"""Typed stat layers and independent timed effects, without patch constants."""
from dataclasses import dataclass
import math

from .state import UnsupportedRule


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


class Stats:
    """flat, base_pct, bonus_pct and multiplier are deliberately different units."""
    def __init__(self, base):
        self.base=dict(base)
        self.modifiers=[]

    def add(self, key, stat, value, mode='flat', *, expires=math.inf, group=None, strongest=False, when=None):
        if stat not in self.base or mode not in ('flat','base_pct','bonus_pct','multiplier'):
            raise UnsupportedRule('unknown stat or modifier unit')
        if not math.isfinite(value) or math.isnan(expires): raise UnsupportedRule('invalid modifier')
        if mode=='multiplier' and value<0: raise UnsupportedRule('negative multiplier')
        if when is not None:
            if set(when)!={'shielded'} or type(when['shielded']) is not bool:
                raise UnsupportedRule('unknown modifier condition')
            if stat in ('hp','mana','initial_mana','mana_per_second'):
                raise UnsupportedRule('conditional resource integration not implemented')
        self.modifiers.append(Modifier(key,stat,mode,float(value),expires,group,strongest,when))

    def get(self, stat, now=0, context=None):
        if stat not in self.base: raise UnsupportedRule(f'unknown stat: {stat}')
        mods=[m for m in self.modifiers if m.stat==stat and m.expires>now and
              (m.when is None or context is not None and all(context.get(k)==v for k,v in m.when.items()))]
        groups={}
        selected=[]
        for m in mods:
            if not m.strongest: selected.append(m); continue
            if m.group is None: raise UnsupportedRule('strongest effect needs stacking group')
            key=(m.group,m.mode)
            if key not in groups or abs(m.value)>abs(groups[key].value): groups[key]=m
        selected.extend(groups.values())
        flat=sum(m.value for m in selected if m.mode=='flat')
        base_pct=sum(m.value for m in selected if m.mode=='base_pct')
        bonus_pct=sum(m.value for m in selected if m.mode=='bonus_pct')
        multiplier=math.prod(m.value for m in selected if m.mode=='multiplier')
        return (self.base[stat]*(1+base_pct)+flat)*(1+bonus_pct)*multiplier

    def expire(self, now):
        self.modifiers[:]=[m for m in self.modifiers if m.expires>now]

    def remove(self,key):
        self.modifiers[:]=[m for m in self.modifiers if m.key!=key]


def formula(spec, source, target, now, context=None):
    """Sum explicit terms; never eval source text or infer AD/AP from HTML labels."""
    if not isinstance(spec,list): raise UnsupportedRule('formula must be a list of terms')
    total=0.
    for term in spec:
        if set(term)-{'coefficient','stat','owner','base','context'}: raise UnsupportedRule('unknown formula term')
        coefficient=term['coefficient']
        if isinstance(coefficient,list):
            if len(coefficient)<source.stars: raise UnsupportedRule('formula missing star level')
            coefficient=coefficient[source.stars-1]
        if type(coefficient) not in (int,float) or not math.isfinite(coefficient):
            raise UnsupportedRule('formula coefficient must be finite')
        stat=term.get('stat')
        if 'context' in term:
            if stat is not None or term['context'] not in ('damage','total_damage') or term['context'] not in (context or {}):
                raise UnsupportedRule('formula context unavailable')
            value=context[term['context']]
        elif stat is None: value=1.
        else:
            owner=term.get('owner','source')
            if owner not in ('source','target'): raise UnsupportedRule('unknown formula owner')
            unit=source if owner=='source' else target
            if unit is None: raise UnsupportedRule('formula target unavailable')
            if stat=='current_hp': value=unit.hp
            elif stat=='missing_hp': value=max(0,unit.values.get('hp',now)-unit.hp)
            else:
                context={'shielded':any(s.amount>0 and s.expires>now for s in getattr(unit,'shields',[]))}
                value=unit.values.base[stat] if term.get('base',False) else unit.values.get(stat,now,context)
        total+=coefficient*value
    return total
