"""Extract native-resolution TFT frames for whole-HUD annotation review.

All inherited HUD boxes are explicitly unverified proposals. This command
does not create trainable labels or assign champion identities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont


BASE = Path('/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009')
RAW = Path('/mnt/sherlock-ssd/AgenteTFT/diagnostics/fresh-champion-corpus-20261008/raw')
UNSEEN_TEST = {'wr5_dV3QajM', '8W7Wfnf36M8', '-YQHDFlMRRs'}
VALIDATION = {'QUiyk-mfoBs'}


def second_from_name(path: str) -> int:
    name = Path(path).stem
    match = re.search(r'(?:^|-)(\d+)-full$', name)
    if not match:
        raise ValueError(f'Cannot find second in frame name: {path}')
    return int(match.group(1))


def source_video(stem: str) -> Path:
    for subdir in ('targeted-4k', 'targeted'):
        matches = sorted((RAW / subdir).glob(stem + '.*'))
        if matches:
            return matches[0]
    raise FileNotFoundError(stem)


def extract(video: Path, second: int, target: Path) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    task = subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(second),
        '-i', str(video), '-frames:v', '1', '-pix_fmt', 'rgb24', '-y', str(target),
    ], capture_output=True, text=True, timeout=90)
    if task.returncode or not target.is_file():
        raise RuntimeError(f'Frame extraction failed: {video} {second}: {task.stderr[-500:]}')


def thumbnail(path: Path, title: str, size=(520, 320)) -> Image.Image:
    image = Image.open(path).convert('RGB')
    image.thumbnail((size[0], size[1] - 28), Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', size, '#111318')
    canvas.paste(image, ((size[0] - image.width) // 2, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 7), title, fill='#f5f5f5')
    return canvas


def proposal_overlay(path: Path, proposals: list[dict], target: Path) -> None:
    with Image.open(path) as original:
        canvas = original.convert('RGB').resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    colors = {
        'stage_display': '#f8c537', 'gold_display': '#f8c537',
        'level_display': '#f8c537', 'xp_display': '#f8c537',
        'player_hp_display': '#4dd7ff', 'shop_card': '#d77aff',
    }
    for item in proposals:
        box = item['box_source_1920x1080']
        color = colors.get(item['class'], '#7cf59b')
        draw.rectangle(box, outline=color, width=4)
        draw.text((box[0] + 3, max(0, box[1] - 16)), item['class'], fill=color)
    draw.rectangle((0, 0, 1090, 30), fill='#16191e')
    draw.text((10, 8), 'PROPOSTAS ANTIGAS | SEM REVISAO VISUAL | NAO USAR NO TREINO', fill='#ffffff')
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, quality=91)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    old = json.loads((args.base / 'experiments/joint-hud-unit-20261010/provenance.json').read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    seen = set()
    for entry in old['sources']:
        video_id = Path(entry['source_video']).stem
        second = second_from_name(entry['source_frame'])
        key = (video_id, second)
        if key in seen:
            raise ValueError(f'Duplicate source frame: {key}')
        seen.add(key)
        video = source_video(video_id)
        frame = args.output / 'native-frames' / f'{video_id}-{second:05d}.png'
        extract(video, second, frame)
        with Image.open(frame) as image:
            width, height = image.size
        split = 'test' if video_id in UNSEEN_TEST else 'val' if video_id in VALIDATION else 'train'
        proposals = [{
            'class': annotation['class'],
            'box_source_1920x1080': annotation['box_1920'],
            'review_status': 'unverified_layout_or_pixel_proposal',
        } for region in entry['region_labels'].values() for annotation in region]
        overlay = args.output / 'proposal-overlays' / f'{video_id}-{second:05d}.jpg'
        proposal_overlay(frame, proposals, overlay)
        rows.append({
            'source_video': str(video),
            'source_second': second,
            'source_frame': str(frame),
            'source_frame_sha256': hashlib.sha256(frame.read_bytes()).hexdigest(),
            'proposal_overlay': str(overlay),
            'resolution': [width, height],
            'global_split_by_video': split,
            'old_split_discarded': entry['split'],
            'inherited_box_proposals': proposals,
            'needs_review': [
                'board and 28 hexes per side', 'own and enemy champion bodies and identities',
                'own and enemy benches', 'shop card names and costs',
                'inventory and equipped items with carrier', 'own and enemy traits',
                'stage gold level XP and health values', 'player names and avatars',
                'carousel or combat state',
            ],
            'training_eligible': False,
        })
        print(f"FONTE {video_id} {second}s {width}x{height} {split} | {len(proposals)} propostas", flush=True)

    if len(rows) != len(old['sources']):
        raise ValueError('A source frame was lost')
    manifest = {
        'schema_version': 1,
        'purpose': 'review complete HUD before training',
        'prediction_labels_used': False,
        'trainable_labels': 0,
        'source_frames': rows,
    }
    (args.output / 'review-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    cell_w, cell_h = 520, 320
    cols = 3
    sheet = Image.new('RGB', (cols * cell_w, ((len(rows) + cols - 1) // cols) * cell_h), '#0b0d11')
    for i, row in enumerate(rows):
        path = Path(row['source_frame'])
        title = f"{path.stem} | {row['global_split_by_video']} | {row['resolution'][0]}x{row['resolution'][1]}"
        sheet.paste(thumbnail(path, title), ((i % cols) * cell_w, (i // cols) * cell_h))
    sheet.save(args.output / 'contact-sheet.jpg', quality=90)
    proposal_sheet = Image.new('RGB', sheet.size, '#0b0d11')
    for i, row in enumerate(rows):
        path = Path(row['proposal_overlay'])
        title = f"{path.stem} | {row['global_split_by_video']} | propostas"
        proposal_sheet.paste(thumbnail(path, title), ((i % cols) * cell_w, (i // cols) * cell_h))
    proposal_sheet.save(args.output / 'contact-proposals.jpg', quality=90)
    print(f"REVISÃO {args.output / 'contact-sheet.jpg'}", flush=True)
    print(f"PROPOSTAS {args.output / 'contact-proposals.jpg'}", flush=True)


if __name__ == '__main__':
    main()
