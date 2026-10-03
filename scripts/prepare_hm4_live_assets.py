"""Prepare pinned L3 and Riot artwork for the Windows replay-screen installer."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from training.board_hub_item_candidates import fetch_icon, load_reference, select_entries


def prepare() -> dict:
    plan = json.loads((root / 'configs/catalog/active-visual-reference-v1.json').read_text(encoding='utf-8'))
    asset_root = root / 'build/hm4-live-assets'
    model_dir = asset_root / 'models'
    metadata_path = model_dir / 'deployment-candidate.json'
    onnx_path = model_dir / 'candidate-model.onnx'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    model_bytes = onnx_path.read_bytes()
    model_hash = hashlib.sha256(model_bytes).hexdigest()
    if (metadata.get('schema_version') != 2 or metadata.get('panels') != ['bench', 'shop']
            or metadata.get('sha256') != model_hash or metadata.get('activation_allowed') is not False
            or len(model_bytes) > 8 * 1024**2):
        raise ValueError('L3 shadow model metadata/hash mismatch')
    manifest, entries = load_reference(root / plan['reference'])
    selected = select_entries(entries, manifest['set_key'], plan['match_scope'])
    if manifest['set_key'] != plan['set_key'] or len(selected) < 100:
        raise ValueError('Invalid or incomplete set-specific item reference')
    icons = asset_root / plan['icon_dir']
    icons.mkdir(parents=True, exist_ok=True)
    def attempt(entry):
        for _ in range(2):
            try:
                fetch_icon(entry, icons)
                return None
            except (OSError, TimeoutError) as exc:
                failure = str(exc)
        return {'icon': entry['icon'], 'error': failure}
    with ThreadPoolExecutor(max_workers=8) as pool:
        failures = [error for error in pool.map(attempt, selected) if error]
    if failures:
        raise ValueError(f'Riot item icon download incomplete: {failures[:3]}')
    if any(not (icons / entry['icon']).is_file() for entry in selected):
        raise ValueError('Item icon bank incomplete after download')
    report = {'schema_version': 1, 'policy': 'hm4_replay_screen_assets_v1',
              'model_sha256': model_hash, 'model_bytes': len(model_bytes),
              'model_mode': 'shadow_diagnostic',
              'reference_sha256': manifest['reference_sha256'],
              'data_dragon_version': manifest['version'], 'set_key': manifest['set_key'],
              'matching_item_entries': len(selected),
              'icon_hashes': {entry['icon']: hashlib.sha256((icons / entry['icon']).read_bytes()).hexdigest()
                              for entry in selected}}
    (asset_root / 'ASSET_REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    report = prepare()
    print('HM4_LIVE_ASSETS=' + json.dumps({key: value for key, value in report.items()
                                           if key != 'icon_hashes'}, ensure_ascii=False))
