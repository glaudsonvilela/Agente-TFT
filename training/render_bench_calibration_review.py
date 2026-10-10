"""Show separate upper/lower reserve proposals on a 1080p enemy arena."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def render(image_path: Path, candidate_path: Path, output: Path) -> None:
    image = Image.open(image_path).convert('RGB')
    if image.size != (1920, 1080):
        raise ValueError('Expected the exact 1920×1080 analysis image')
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    draw = ImageDraw.Draw(image, 'RGBA')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 12)
    for key, color, prefix in (('enemy_board_rows', (255, 122, 98, 230), 'E'),
                               ('own_board_rows', (83, 218, 255, 230), 'P')):
        for row, (left, right, y) in enumerate(candidate.get(key) or []):
            for col in range(7):
                x = left + (right-left)*col/6
                draw.ellipse((x-8, y-8, x+8, y+8), outline=color, width=2)
                draw.text((x+9, y-8), f'{prefix}{chr(65+row)}{col+1}',
                          font=small, fill=color, stroke_width=2,
                          stroke_fill=(0, 0, 0, 240))
    for key, color, prefix in (('upper_reserve', (255, 122, 98, 255), 'RIVAL?'),
                               ('lower_reserve', (255, 216, 93, 255), 'JOGADOR?')):
        centers = candidate.get(key) or []
        if centers and len(centers) != 9:
            raise ValueError(f'{key} requires nine slots')
        for index, (x, y) in enumerate(centers):
            draw.ellipse((x-12, y-12, x+12, y+12), outline=color, width=3)
            draw.text((x-24, y+15), f'{prefix} R{index+1}', font=font, fill=color,
                      stroke_width=2, stroke_fill=(0, 0, 0, 240))
    draw.rectangle((8, 8, 860, 72), fill=(0, 0, 0, 200))
    opposite = bool(candidate.get('enemy_board_visible'))
    draw.text((18, 17), f'{56 if opposite else 28} CASAS + {2 if opposite else 1} BANCOS · calibração candidata 1080p',
              font=font, fill=(255, 255, 255, 255))
    draw.text((18, 43), 'Nomes dos donos e posições precisam ser validados nesta arena',
              font=font, fill=(255, 255, 255, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(args.image, args.candidate, args.output)


if __name__ == '__main__':
    main()
