"""Package the approved mascot PNG into desktop icon formats.
Dev-only requirement: Pillow. Artwork and original alpha remain unchanged.
"""
from pathlib import Path
from PIL import Image
root = Path(__file__).resolve().parent
source = Image.open(root / 'assets/agente-pengu.png').convert('RGBA')
out = root / 'icons'
out.mkdir(exist_ok=True)
for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
    icon = source.copy()
    icon.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (size, size))
    canvas.alpha_composite(icon, ((size-icon.width)//2, (size-icon.height)//2))
    canvas.save(out / f'icon-{size}.png')
image = Image.open(out / 'icon-1024.png')
image.save(out / 'icon.ico', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
image.save(out / 'icon.icns')
print('Approved Pengu: PNG, Windows ICO and macOS ICNS exported.')
