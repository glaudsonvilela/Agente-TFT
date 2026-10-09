"""Tentative tactician locations from the named health bars visible on the board."""
from __future__ import annotations


def _bars(pixels, kind):
    import numpy as np

    area = pixels[65:700, 350:1550]
    red, green, blue = (area[:, :, channel] for channel in range(3))
    if kind == 'own':
        mask = (red > 140) & (blue > 145) & (green < 90) & (red > green * 1.7)
    else:
        mask = (blue > 150) & (green > 115) & (red < 140) & (blue > red * 1.3)
    clusters = {}
    row_counts = mask.sum(axis=1)
    for row_index in np.flatnonzero((row_counts >= 55) & (row_counts <= 450)):
        row = mask[row_index]
        edges = np.flatnonzero(np.diff(np.r_[False, row, False].astype(np.int8)))
        for left, right in zip(edges[::2], edges[1::2]):
            width = right - left
            if not 55 <= width <= 150:
                continue
            x0, x1, y = int(left + 350), int(right + 350), int(row_index) + 65
            key = (round(x0 / 8), round(x1 / 8), round(y / 16))
            clusters.setdefault(key, []).append((x0, x1, y))
    return sorted((rows for rows in clusters.values() if len(rows) >= 4),
                  key=lambda rows: (len(rows), sum(x1-x0 for x0, x1, _ in rows)),
                  reverse=True)


def observe(image):
    """Return candidate boxes; no mascot identity or HP is inferred here."""
    import numpy as np

    if image.size != (1920, 1080):
        return []
    pixels = np.asarray(image.convert('RGB'))
    output = []
    for kind in ('own', 'enemy'):
        for rows in _bars(pixels, kind):
            x0, x1, y = rows[0]
            if kind == 'enemy':
                badge = pixels[max(0, y-10):y+16, x0-27:x0-3]
                if (badge.size == 0 or (badge.max(axis=2) < 70).mean() < .35
                        or (badge.min(axis=2) > 140).mean() < .02):
                    continue
            output.append(dict(class_name='own_tactician' if kind == 'own' else 'enemy_tactician',
                               box=[max(0, x0-28), y+12, min(1920, x1+28),
                                    min(1080, y+(145 if kind == 'own' else 175))],
                               source='visible_health_bar', identity_verified=False))
            break
    return output
