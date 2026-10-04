"""Load explicit seasonal files and substitute numeric catalog fields safely.

This module contains no champion/item/trait IDs, patch values or executable text
evaluation. File checksums bind a run to one complete set of seasonal rules.
"""
from copy import deepcopy
import math
from pathlib import Path

from ingestion.knowledge_release import load
from trainer.simulation.state import UnsupportedRule


def load_bindings(path):
    path=Path(path).resolve(strict=True);manifest,_=load(path)
    if manifest.get('schema_version')!=2 or set(manifest.get('components',{}))!={'items','traits','champions','profile'}:
        raise UnsupportedRule('explicit four-part seasonal manifest required')
    result=deepcopy(manifest)
    for name,entry in manifest['components'].items():
        relative=Path(entry['path'])
        component=path.parent/relative
        if relative.is_absolute() or '..' in relative.parts or component.is_symlink():
            raise UnsupportedRule('unsafe seasonal component path')
        if not component.resolve(strict=True).is_relative_to(path.parent):raise UnsupportedRule('component escapes pack')
        value,checksum=load(component)
        if checksum!=entry['sha256']:raise UnsupportedRule(f'seasonal component changed: {name}')
        if 'patch' in value and value['patch']!=manifest['patch']:
            raise UnsupportedRule(f'seasonal component patch mismatch: {name}')
        result[name]=value
    return result


def substitute(value,fields,tiers=()):
    if isinstance(value,list):return [substitute(v,fields,tiers) for v in value]
    if not isinstance(value,dict):return value
    if '$field' not in value:return {k:substitute(v,fields,tiers) for k,v in value.items()}
    if set(value)-{'$field','scale','tier','integer'}:raise UnsupportedRule('unknown field substitution')
    source=fields
    if 'tier' in value:
        index=value['tier']
        if type(index) is not int or not 0<=index<len(tiers):raise UnsupportedRule('invalid inherited tier')
        source=tiers[index]['variables']
    key=value['$field']
    if key not in source:raise UnsupportedRule(f'required seasonal numeric field missing: {key}')
    number=source[key];scale=value.get('scale',1)
    if any(type(n) not in (int,float) or not math.isfinite(n) for n in (number,scale)):
        raise UnsupportedRule('invalid seasonal numeric field')
    result=number*scale
    if not math.isfinite(result):raise UnsupportedRule('numeric substitution overflow')
    if value.get('integer'):
        if abs(result-round(result))>1e-6:raise UnsupportedRule('counter requires integral value')
        return int(round(result))
    return result


def referenced_fields(value):
    """Current-tier fields only; inherited values are checked on substitution."""
    if isinstance(value,list):return set().union(*(referenced_fields(v) for v in value))
    if not isinstance(value,dict):return set()
    if '$field' in value:return {value['$field']} if 'tier' not in value else set()
    return set().union(*(referenced_fields(v) for v in value.values()))
