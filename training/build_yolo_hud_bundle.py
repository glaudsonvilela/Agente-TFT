"""Assemble a patch-bound YOLO runtime overlay without committing large weights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('detector', 'enemy_detector', 'champions', 'items', 'item_audit', 'output'):
        parser.add_argument('--' + name.replace('_', '-'), required=True, type=Path)
    parser.add_argument('--set-key', required=True)
    parser.add_argument('--patch', required=True)
    args = parser.parse_args()
    model_dir = args.output / 'models/yolo-hud'
    model_dir.mkdir(parents=True, exist_ok=True)
    sources = {'detector.onnx': args.detector, 'enemy_detector.onnx': args.enemy_detector,
               'champions.onnx': args.champions,
               'items.onnx': args.items}
    for name, source in sources.items():
        if not source.is_file() or source.stat().st_size > 32 * 1024**2:
            raise ValueError(f'Invalid YOLO model: {source}')
        shutil.copyfile(source, model_dir / name)
    audit = json.loads(args.item_audit.read_text(encoding='utf-8'))
    if len(audit.get('classes', [])) != 193:
        raise ValueError('Expected 193 item classes')
    (model_dir / 'items.json').write_text(json.dumps({'classes': audit['classes']},
                                        ensure_ascii=False, indent=2), encoding='utf-8')
    plan = {'schema_version': 1, 'id': 'active-yolo-hud-v1',
            'mode': 'diagnostic_candidates', 'set_key': args.set_key,
            'tft_patch': args.patch,
            'files': {name: digest(model_dir / name)
                      for name in (*sources, 'items.json')}}
    config_dir = args.output / 'configs/catalog'
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'active-yolo-hud-v1.json').write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'bundle': str(args.output), 'files': plan['files']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
