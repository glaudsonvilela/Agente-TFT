#!/usr/bin/env python3
"""Show temporal unit crops for human review without promoting track labels."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(tracks_file: Path, output: Path, per_seed: int = 4) -> dict:
    source = json.loads(tracks_file.read_text())
    if source.get('all_transfers_require_visual_review') is not True:
        raise ValueError('Temporal candidates must remain unverified')
    grouped = defaultdict(list)
    for row in source['tracks']:
        if row.get('may_train') is not False:
            raise ValueError('A track is already marked trainable')
        grouped[row['seed_id']].append(row)
    chosen = []
    for seed, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row['frame'])
        indices = list(dict.fromkeys(round(i * (len(rows) - 1) / max(1, per_seed - 1))
                                     for i in range(min(per_seed, len(rows)))))
        chosen.append((seed, [rows[index] for index in indices]))
    tile_w, tile_h = 260, 250
    sheet = Image.new('RGB', (per_seed * tile_w, max(1, len(chosen)) * tile_h), (23, 24, 27))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for row_index, (seed, rows) in enumerate(chosen):
        for column, record in enumerate(rows):
            frame = Path(record['frame'])
            with Image.open(frame) as opened:
                if opened.size != (3840, 2160):
                    raise ValueError(f'Expected original 4K frame: {frame}')
                box = record['box_preview_2048']
                crop = opened.crop(tuple(round(value * 3840 / 2048) for value in box)).convert('RGB')
            crop.thumbnail((tile_w - 14, tile_h - 57), Image.Resampling.LANCZOS)
            x, y = column * tile_w, row_index * tile_h
            sheet.paste(crop, (x + (tile_w - crop.width) // 2,
                               y + 20 + (tile_h - 57 - crop.height) // 2))
            name = record['identity_suggestion']
            draw.text((x + 6, y + 4), f'{seed}  {name} (?)', fill=(244, 244, 244), font=font)
            draw.text((x + 6, y + tile_h - 25), frame.stem[-16:], fill=(164, 185, 193), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=90)
    return {'candidate_tracks': len(source['tracks']), 'seeds': len(chosen),
            'shown': sum(len(rows) for _, rows in chosen), 'review_only': True,
            'sheet': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--per-seed', type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(render(args.tracks, args.output, args.per_seed), ensure_ascii=False))
