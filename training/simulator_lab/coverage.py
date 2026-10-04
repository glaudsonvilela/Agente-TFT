"""Audit seasonal data independently of screen layout and executable game rules."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ingestion.knowledge_release import read_release

REQUIRED_STATS = ('hp', 'damage', 'attackSpeed', 'armor', 'magicResist',
                  'range', 'mana', 'initialMana', 'critChance', 'critMultiplier')


def audit(project: Path) -> dict:
    selection = json.loads((project / 'configs/catalog/active-knowledge-release-v1.json').read_text())
    manifest, catalogs = read_release(project / selection['reference'])
    units = []
    for champion in catalogs['units']['champions']:
        stats = champion.get('stats') or {}
        missing = [key for key in REQUIRED_STATS if not isinstance(stats.get(key), (float, int))
                   or isinstance(stats.get(key), bool) or not math.isfinite(stats[key])]
        ability = champion.get('ability') or {}
        units.append(dict(id=champion['api_name'], missing_stats=missing,
                          numeric_ability_variables=bool(ability.get('variables')),
                          unresolved_description='@' in str(ability.get('desc', ability.get('description', ''))),
                          executable_ability=False))
    # Coverage means an implemented and tested semantic handler, not merely text/IDs.
    # There is deliberately no user-editable 'ready: true' switch here.
    return dict(schema_version=1, kind='simulation_coverage', set_key=selection['set_key'],
                patch=selection['tft_patch'], release_sha256=manifest['release_sha256'],
                units=units, champions=len(units),
                champions_with_complete_stats=sum(not u['missing_stats'] for u in units),
                champions_with_numeric_ability_variables=sum(u['numeric_ability_variables'] for u in units),
                executable_abilities=0, current_patch_training_ready=False,
                runtime_promoted=False,
                blockers=['Set18 ability handlers and numerical formulas missing',
                          'Set18 item and trait effects not implemented and verified',
                          'Set18 economy, loot, augments and seasonal mechanic not validated',
                          'Owned units, stars, equipped items and hex positions lack replay ground truth',
                          'No independent match validation for combat or policy'],
                laboratory=dict(adapter='tft_goat_synthetic_tick_v1', set_key='synthetic',
                                official_rules=False, replay_compatible=False,
                                explicit_position_actions=False,
                                item_choice_actions=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.project)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'units'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
