"""Tentative win/loss streak icon observation in the 1920x1080 TFT HUD.

The icon color is useful evidence, but this reader does not yet read the
number beside it or establish a round result for strategy.
"""

ICON_BOX = [1105, 877, 1135, 905]
REGION_BOX = [1098, 867, 1184, 920]


def observe_streak(rgb: bytes, width: int, height: int) -> dict:
    if (width, height) != (1920, 1080) or len(rgb) != width * height * 3:
        return dict(status='unsupported_resolution', kind=None, count=None, box=None)
    blue = orange = 0
    stride = width * 3
    for y in range(ICON_BOX[1], ICON_BOX[3]):
        for x in range(ICON_BOX[0], ICON_BOX[2]):
            offset = y * stride + x * 3
            red, green, navy = rgb[offset:offset + 3]
            blue += navy > 90 and navy > red * 1.25 and navy > green * 1.05
            orange += red > 100 and red > green * 1.3 and red > navy * 1.6
    kind = ('loss' if blue >= 45 and blue > orange * 2 else
            'win' if orange >= 45 and orange > blue * 2 else None)
    return dict(status='icon_color_candidate' if kind else 'icon_unread',
                kind=kind, count=None, box=REGION_BOX,
                evidence=dict(blue_pixels=blue, orange_pixels=orange),
                verified=False)
