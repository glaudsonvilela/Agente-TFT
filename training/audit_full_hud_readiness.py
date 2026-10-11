"""Audit whether a fresh TFT corpus can train and test the complete HUD.

This is a data gate, not a model score. Candidate boxes and model predictions
never become verified training labels merely because a detector found them.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


BASE = Path('/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009')
REPO = Path(__file__).resolve().parents[1]
REQUIRED_HUD = (
    'own_board_units', 'own_bench_units', 'enemy_board_units',
    'enemy_bench_units', 'shop_cards', 'shop_names', 'equipped_items',
    'item_bench', 'own_traits', 'enemy_traits', 'stage_value', 'gold_value',
    'level_value', 'xp_value', 'player_health', 'opponent_health',
    'player_names', 'own_avatar', 'enemy_avatars', 'board_hexes',
    'combat_or_planning', 'carousel',
)
BOX_PROPOSALS = {
    'champion_body': ('own_board_units', 'own_bench_units',
                      'enemy_board_units', 'enemy_bench_units'),
    'shop_card': ('shop_cards',),
    'stage_display': ('stage_value',),
    'gold_display': ('gold_value',),
    'level_display': ('level_value',),
    'xp_display': ('xp_value',),
    'player_hp_display': ('player_health', 'opponent_health'),
}


def source_id(path: str) -> str:
    return Path(path).stem


def audit_item_reference(repo: Path) -> dict:
    active = json.loads((repo / 'configs/catalog/active-visual-reference-v1.json').read_text())
    reference_dir = repo / active['reference']
    manifest = json.loads((reference_dir / 'reference.json').read_text())
    item_bytes = (reference_dir / 'items.json').read_bytes()
    expected_hash = manifest['components']['items']['sha256']
    if hashlib.sha256(item_bytes).hexdigest() != expected_hash:
        raise ValueError('Item reference hash mismatch')
    entries = json.loads(item_bytes)['entries']
    set_key = manifest['set_key']
    if set_key != active['set_key']:
        raise ValueError('Active item set mismatch')
    selected = [row for row in entries if row.get('key', '').startswith(set_key + '/')
                or row.get('id', '').startswith('TFT_Item_')
                or row.get('key', '').startswith('Set5_RadiantItems/')]
    icon_dir = repo / 'build/hm4-live-assets/board-hub-icons'
    model_dir = repo / 'build/hm4-live-assets/models/item-icons'
    metadata = json.loads((model_dir / 'metadata.json').read_text())
    model_bytes = (model_dir / 'item-icons.onnx').read_bytes()
    if hashlib.sha256(model_bytes).hexdigest() != metadata['model_sha256']:
        raise ValueError('Item model hash mismatch')
    present = sum((icon_dir / row['icon']).is_file() for row in selected)
    return {
        'catalog_records': len(entries),
        'selected_set_and_core_items': len(selected),
        'selected_item_icons_present': present,
        'neural_icon_classes': len(metadata['classes']),
        'catalog_and_assets_ready': present == len(selected),
        'live_identity_status': metadata['mode'],
        'independent_live_match_validation': False,
        'reference': str(reference_dir),
        'icon_dir': str(icon_dir),
        'neural_model': str(model_dir / 'item-icons.onnx'),
    }


def audit_spatial_and_telemetry(repo: Path) -> dict:
    topology = json.loads((repo / 'configs/topology/board-standard-4x7-v1.json').read_text())
    bench = json.loads((repo / 'configs/topology/bench-nine-v1.json').read_text())
    profiles = {}
    for arena in ('cyber', 'red', 'pond'):
        path = repo / f'configs/ui/{arena}-arena-reserves-v1.json'
        profile = json.loads(path.read_text())
        profiles[arena] = {
            'status': profile['status'],
            'own_board_rows': len(profile.get('own_board_rows', [])),
            'enemy_board_rows': len(profile.get('enemy_board_rows', [])),
            'own_bench_slots': len(profile.get('lower_reserve', [])),
            'enemy_bench_slots': len(profile.get('upper_reserve', [])),
            'training_label': profile.get('training_label') is True,
        }
    modules = (
        'arena_registration', 'spatial_map', 'match_identity',
        'opponent_tracking', 'combat_events', 'process_memory',
    )
    present = {name: (repo / f'apps/hud_mapper/hm/{name}.py').is_file()
               for name in modules}
    return {
        'topology_cells_per_side': topology['rows_per_side'] * topology['columns'],
        'topology_cells_total': 2 * topology['rows_per_side'] * topology['columns'],
        'bench_slots_per_side': len(bench['slots']),
        'profiles': profiles,
        'pixel_projection_independently_validated': False,
        'telemetry_modules_present': present,
        'end_to_end_tracking_independently_validated': False,
    }


def audit_traits(repo: Path) -> dict:
    aliases = repo / 'configs/catalog/trait-aliases-set18-en-us-16.20.json'
    reader = repo / 'tools/e1-native/src/main.rs'
    return {
        'alias_catalog_present': aliases.is_file(),
        'rust_ocr_reader_present': reader.is_file(),
        'visual_icon_and_count_model_validated': False,
        'independent_full_match_validation': False,
    }


def audit(base: Path) -> dict:
    roster = json.loads((base / 'roster/set18-shop-roster-20261010.json').read_text())['rows']
    records = json.loads((base / 'roster/unified-reviewed-candidates-20261010.json').read_text())['records']
    coverage = json.loads((base / 'source-review-20261010/coverage-report.json').read_text())
    joint = json.loads((base / 'experiments/joint-hud-unit-20261010/provenance.json').read_text())
    if len(roster) != 65 or len({r['name_pt_br'] for r in roster}) != 65:
        raise ValueError('The 65-champion roster is incomplete or duplicated')

    by_name = defaultdict(list)
    for row in records:
        by_name[row['champion']].append(row)
    identity_evidence = Counter(row['review_status'] for row in records)
    provisional = {r['champion']: r['provisional_pose_families'] for r in coverage['classes']}
    champions = []
    for row in roster:
        name = row['name_pt_br']
        samples = by_name[name]
        # Approved poses require an explicit family ID; neighboring frames are
        # not counted as distinct angles or movements.
        approved = {s['pose_family_id'] for s in samples
                    if s.get('training_eligible') is True
                    and s.get('quality_approved') is True
                    and s.get('pose_family_id')}
        champions.append({
            'champion': name,
            'cost': row['cost'],
            'reviewed_crop_candidates': len(samples),
            'provisional_pose_families': provisional.get(name, 0),
            'approved_distinct_poses': len(approved),
            'remaining_approved_poses': max(0, 5 - len(approved)),
            'zones_covered_by_approved': sorted({s['zone'] for s in samples
                                                  if s.get('training_eligible') is True
                                                  and s.get('quality_approved') is True}),
        })

    proposals = Counter()
    for source in joint['sources']:
        for labels in source['region_labels'].values():
            proposals.update(label['class'] for label in labels)
    hud = []
    for category in REQUIRED_HUD:
        matching = [old for old, mapped in BOX_PROPOSALS.items() if category in mapped]
        hud.append({
            'category': category,
            'box_proposals': sum(proposals[name] for name in matching),
            'verified_boxes': 0 if joint['hud_labels'] == 'layout_and_pixel_proposals_pending_visual_audit' else None,
            'verified_values': 0,
            'ready': False,
        })

    # Every observation task must use the same split by match, otherwise a
    # supposedly unseen identity test may contain HUD frames from training.
    identity_split = {}
    for row in records:
        video = source_id(row['source_video_local'])
        split = 'test' if video == 'wr5_dV3QajM' else 'val' if video == 'QUiyk-mfoBs' else 'train'
        identity_split[video] = split
    hud_splits = defaultdict(set)
    for source in joint['sources']:
        hud_splits[source_id(source['source_video'])].add(source['split'])
    conflicts = [
        {'video': video, 'identity_split': split, 'hud_splits': sorted(hud_splits[video])}
        for video, split in sorted(identity_split.items())
        if video in hud_splits and hud_splits[video] != {split}
    ]
    global_splits = {
        video: ('test' if video in {'wr5_dV3QajM', '8W7Wfnf36M8', '-YQHDFlMRRs'}
                else 'val' if video == 'QUiyk-mfoBs' else 'train')
        for video in sorted(set(identity_split) | set(hud_splits))
    }
    return {
        'schema_version': 1,
        'scope': 'fresh-reset complete TFT HUD, 65 shop champions',
        'training_ready': False,
        'roster_size': len(roster),
        'approved_champions_at_five_poses': sum(r['approved_distinct_poses'] >= 5 for r in champions),
        'approved_pose_total': sum(r['approved_distinct_poses'] for r in champions),
        'reviewed_candidate_crops': len(records),
        'identity_evidence': dict(identity_evidence),
        'candidate_source_videos': len({source_id(row['source_video_local']) for row in records}),
        'candidate_zones_unverified': sum(row.get('zone') == 'unverified_board_or_bench'
                                          for row in records),
        'provisional_pose_families': sum(r['provisional_pose_families'] for r in champions),
        'provisional_zero_champions': sum(r['provisional_pose_families'] == 0 for r in champions),
        'hud_categories_required': len(REQUIRED_HUD),
        'hud_categories_ready': sum(r['ready'] for r in hud),
        'hud_source_frames': len(joint['sources']),
        'hud_label_status': joint['hud_labels'],
        'item_reference': audit_item_reference(REPO),
        'spatial_and_telemetry': audit_spatial_and_telemetry(REPO),
        'traits': audit_traits(REPO),
        'cross_task_split_conflicts': conflicts,
        'global_split_by_video_for_new_corpus': global_splits,
        'global_split_status': 'proposal_only_not_applied_to_existing_training_sets',
        'champions': champions,
        'hud': hud,
        'requirements': [
            'Five quality-approved distinct poses per shop champion, including board and bench views.',
            'Board, bench, shop, item, trait, economy, players and avatar annotations reviewed on full frames.',
            'Actual text and number values, not only boxes around displays.',
            'One train/validation/test split per match across every perception task.',
            'A held-out full-match evaluation with identity, location and value metrics reported separately.',
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f"CAMPEÕES  {report['approved_champions_at_five_poses']}/{report['roster_size']} prontos; "
          f"{report['approved_pose_total']} poses aprovadas; "
          f"{report['provisional_zero_champions']} sem pose candidata")
    print(f"HUD       {report['hud_categories_ready']}/{report['hud_categories_required']} categorias prontas; "
          f"{report['hud_source_frames']} quadros com propostas ainda não revisadas")
    items = report['item_reference']
    print(f"ITENS     catálogo e arte prontos: {items['selected_item_icons_present']}/"
          f"{items['selected_set_and_core_items']} ícones; "
          f"rede com {items['neural_icon_classes']} classes")
    print(f"PARTIDAS  {len(report['cross_task_split_conflicts'])} conflitos de separação entre tarefas")
    print(f"ROTULOS   {report['identity_evidence']} ; "
          f"{report['candidate_zones_unverified']} zonas por revisar")
    spatial = report['spatial_and_telemetry']
    print(f"MAPA      {spatial['topology_cells_total']} casas e "
          f"{spatial['bench_slots_per_side']} bancos por lado na topologia; "
          'projeções ainda não validadas')
    print('SINERGIAS catálogo e OCR presentes; leitura visual integral sem validação')
    for conflict in report['cross_task_split_conflicts']:
        print(f"          {conflict['video']}: campeões={conflict['identity_split']} "
              f"HUD={','.join(conflict['hud_splits'])}")
    print(f'RELATÓRIO {args.output}')


if __name__ == '__main__':
    main()
