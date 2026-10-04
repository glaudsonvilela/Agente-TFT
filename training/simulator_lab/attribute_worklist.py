"""Compile a traceable attribute/dependency inventory from a sealed release.

Numbers in a provider variable array are preserved as evidence, not interpreted
as damage or star scaling until their semantics have been verified.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re

from ingestion.knowledge_release import read_release
from .coverage import REQUIRED_STATS
from .selfplay import atomic_json

PLACEHOLDER = re.compile(r'@([^@]+)@')


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def variables_audit(ability):
    numeric, rejected = {}, []
    rows = ability.get('variables') or []
    if not isinstance(rows, list):
        return {}, ['variables_not_array']
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejected.append(f'row_{index}_not_object'); continue
        name, values = row.get('name'), row.get('values')
        if (not isinstance(name, str) or not name or name in numeric
                or not isinstance(values, list) or not values
                or not all(finite_number(v) for v in values)):
            rejected.append(f'row_{index}_invalid_or_duplicate'); continue
        numeric[name] = values
    return numeric, rejected


def compile_release(folder):
    manifest, catalogs = read_release(folder)
    rows = []
    for unit in catalogs['units']['champions']:
        stats = unit.get('stats') or {}
        ability = unit.get('ability') or {}
        variables, rejected = variables_audit(ability)
        tokens = sorted(set(PLACEHOLDER.findall(ability.get('description', ''))))
        missing = [name for name in REQUIRED_STATS if not finite_number(stats.get(name))]
        rows.append(dict(id=unit['api_name'], name=unit['name'], cost=unit['cost'],
                         role=unit.get('role'), traits=unit.get('traits', []),
                         base_stats={k: stats[k] for k in REQUIRED_STATS if k not in missing},
                         missing_base_stats=missing, ability_name=ability.get('name'),
                         placeholder_dependencies=tokens, raw_numeric_variables=variables,
                         rejected_variable_rows=rejected,
                         direct_name_matches=[t for t in tokens if t in variables],
                         unresolved_dependencies=[t for t in tokens if t not in variables],
                         star_index_semantics_verified=False, ability_handler=None,
                         source_component_sha256=manifest['components']['units']['sha256'],
                         executable=False))
    item_rows = []
    for item in catalogs['items']['items']:
        effects = item.get('effects') or {}
        item_rows.append(dict(id=item['api_name'],
                              numeric_effects={k: v for k, v in effects.items() if finite_number(v)},
                              unresolved_effects=sorted(k for k, v in effects.items() if not finite_number(v)),
                              set_membership_verified=False, effect_handler=None))
    return dict(schema_version=1, kind='seasonal_attribute_worklist',
                set_key=manifest['set']['key'], patch=manifest['tft_patch'],
                provider_build=manifest['provider_build'], source_url=manifest['source_url'],
                source_sha256=manifest['source_sha256'], release_sha256=manifest['release_sha256'],
                geometry_included=False, models_included=False,
                champions=rows, items=item_rows,
                summary=dict(champions=len(rows),
                             complete_base_stats=sum(not r['missing_base_stats'] for r in rows),
                             missing_base_stat_fields=sum(len(r['missing_base_stats']) for r in rows),
                             numeric_variable_arrays=sum(len(r['raw_numeric_variables']) for r in rows),
                             placeholder_dependencies=sum(len(r['placeholder_dependencies']) for r in rows),
                             dependencies_without_direct_variable=sum(len(r['unresolved_dependencies']) for r in rows),
                             executable_abilities=0),
                current_patch_training_ready=False,
                blockers=['Missing base attributes must be sourced, never filled with zero',
                          'Direct variable names alone do not define formulas, targeting or timing',
                          'Items snapshot is global; numeric effects do not prove set membership',
                          'Combat handlers require source-backed semantics and replay validation'])


def assert_patch_compatible(worklist, *, set_key, patch, release_sha256):
    """Consumers must request the exact immutable release; PBE/latest cannot substitute."""
    if worklist.get('kind') != 'seasonal_attribute_worklist' or any(
        worklist.get(key) != expected for key, expected in
        [('set_key', set_key), ('patch', patch), ('release_sha256', release_sha256)]
    ):
        raise ValueError('Seasonal worklist does not match requested release')


def attach_official_observations(worklist, observations):
    """Attach partial patch facts; never treat them as executable ability handlers."""
    if (observations.get('kind') != 'official_patch_observations'
            or observations.get('set_key') != worklist['set_key']
            or observations.get('base_release_sha256') != worklist['release_sha256']):
        raise ValueError('Official observations reference a different base release')
    units = {u['id']: u for u in worklist['champions']}
    seen = set()
    for fact in observations['facts']:
        key = (fact['entity_id'], fact['field'], fact['patch'])
        if key in seen or fact['entity_id'] not in units:
            raise ValueError('Unknown/duplicate patch observation')
        seen.add(key)
        values, stars = fact.get('values'), fact.get('star_levels')
        if not isinstance(values, list) or not values or not all(finite_number(v) for v in values):
            raise ValueError('Invalid observed values')
        if stars is not None and (stars != list(range(1, len(values)+1)) or len(stars) > 4):
            raise ValueError('Invalid explicit star coverage')
        if fact.get('semantics_verified_for_execution') is not False or fact.get('formula_binding') is not None:
            raise ValueError('Observations cannot assert an executable formula')
    # Validate every row before modifying the worklist.
    for fact in observations['facts']:
        units[fact['entity_id']].setdefault('official_observations', []).append(dict(
            **fact, source_url=observations['source_url']))
    worklist['summary']['official_observations'] = len(observations['facts'])
    worklist['summary']['champions_with_official_observations'] = len({f['entity_id'] for f in observations['facts']})
    return worklist


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--official-observations', type=Path)
    args = parser.parse_args()
    result = compile_release(args.release)
    if args.official_observations:
        attach_official_observations(result, json.loads(args.official_observations.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(json.dumps(result['summary'], indent=2))
