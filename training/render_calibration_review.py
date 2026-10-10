"""Render candidate 1080p anchors for human calibration review only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(source: Path, profile: Path, output: Path) -> None:
    board = json.loads(profile.read_text(encoding='utf-8'))
    image = Image.open(source).convert('RGB')
    if image.size != (1920, 1080):
        raise ValueError('A imagem de análise precisa ser 1920×1080')
    draw = ImageDraw.Draw(image, 'RGBA')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
    small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 12)

    def circle(x, y, label, color):
        draw.ellipse((x-10, y-10, x+10, y+10), outline=color, width=2)
        draw.text((x+12, y-12), label, font=small, fill=color,
                  stroke_width=2, stroke_fill=(0, 0, 0, 220))

    for row, (left, right, y) in enumerate(board['board_rows']):
        for col in range(7):
            circle(left + (right-left)*col/6, y,
                   f'{chr(65+row)}{col+1}', (75, 235, 255, 225))
    for slot, x in enumerate(board['bench_centers']):
        circle(x, board['bench_y'], f'R{slot+1}', (255, 215, 86, 240))

    # Opposite-side anchors are deliberately not rendered until measured from
    # an enemy-board frame. This review tests the own-side seed and HUD ROIs.
    guides = [
        ('estágio', (720, 0, 830, 42)),
        ('sinergias', (0, 245, 300, 820)),
        ('jogadores / HP', (1680, 165, 1918, 805)),
        ('nível / XP', (336, 870, 565, 928)),
        ('ouro', (966, 870, 1100, 930)),
        ('loja', (548, 925, 1560, 1078)),
    ]
    for label, rect in guides:
        draw.rectangle(rect, outline=(255, 155, 78, 200), width=2)
        x1, y1, _, _ = rect
        draw.text((x1+5, y1+4), label, font=font, fill=(255, 231, 194, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0, 240))
    draw.rectangle((8, 8, 560, 52), fill=(0, 0, 0, 190))
    draw.text((18, 18), 'CALIBRAÇÃO CANDIDATA 1080p · confirmar casas e banco',
              font=font, fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(args.image, args.profile, args.output)


if __name__ == '__main__':
    main()
