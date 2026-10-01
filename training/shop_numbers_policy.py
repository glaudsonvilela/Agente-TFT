"""S5 UI-only numeric geometry. An appearance selects a box, never a value."""
from __future__ import annotations

FIELDS = (
    ('buy_xp_price', 'buy_xp', ('active_appearance', 'dimmed_appearance')),
    ('refresh_price', 'refresh', ('active_appearance', 'dimmed_appearance', 'free_refresh_appearance')),
    ('refresh_free_count', 'refresh', ('free_refresh_appearance',)),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def contains(outer: dict, inner: dict) -> bool:
    return (outer['x'] <= inner['x'] and outer['y'] <= inner['y']
            and inner['x'] + inner['width'] <= outer['x'] + outer['width']
            and inner['y'] + inner['height'] <= outer['y'] + outer['height'])


def overlaps(a: dict, b: dict) -> bool:
    return (a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width']
            and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height'])


def validate_policy(policy: dict, controls: dict, layout: dict) -> None:
    require(set(policy) == {'schema_version', 'id', 'controls_profile_id', 'fields'},
            'numeric policy keys invalid; values/thresholds are not UI geometry')
    require(type(policy['schema_version']) is int and policy['schema_version'] == 1
            and isinstance(policy['id'], str) and 0 < len(policy['id'].encode()) <= 100
            and policy['id'].strip() and policy['controls_profile_id'] == controls['id'],
            'numeric policy identity mismatch')
    rows = policy['fields']
    require(isinstance(rows, list) and len(rows) == len(FIELDS), 'numeric field count mismatch')
    screen = dict(x=0, y=0, width=layout['reference_width'], height=layout['reference_height'])
    obstacles = [s['card'] for s in layout['slots']] + [s['rect'] for s in controls['controls']]
    previous = []
    for row, (field_id, control_id, states) in zip(rows, FIELDS):
        require(set(row) == {'id', 'control_id', 'regions'} and row['id'] == field_id
                and row['control_id'] == control_id, 'numeric field identity/order mismatch')
        regions = row['regions']
        require(isinstance(regions, list) and len(regions) == len(states), 'numeric state coverage mismatch')
        require([r.get('appearance') for r in regions] == list(states), 'numeric states/order mismatch')
        for region in regions:
            require(set(region) == {'appearance', 'rect'}, 'numeric region has unknown keys')
            rect = region['rect']
            require(isinstance(rect, dict) and set(rect) == {'x', 'y', 'width', 'height'}
                    and all(type(v) is int and v >= 0 for v in rect.values())
                    and 1 <= rect['width'] <= 256 and 1 <= rect['height'] <= 96
                    and contains(screen, rect) and not any(overlaps(rect, o) for o in obstacles),
                    'numeric rectangle out of bounds or overlaps a visual/card')
            for other_id, other_control, other_state, other_rect in previous:
                simultaneous = control_id != other_control or region['appearance'] == other_state
                require(other_id == field_id or not simultaneous or not overlaps(rect, other_rect),
                        'simultaneous numeric fields overlap')
            previous.append((field_id, control_id, region['appearance'], rect))


def selected_rect(policy: dict, field_id: str, appearance: str) -> dict:
    row = next((r for r in policy['fields'] if r['id'] == field_id), None)
    require(row is not None, 'unknown numeric field')
    region = next((r for r in row['regions'] if r['appearance'] == appearance), None)
    require(region is not None, 'no numeric geometry for observed appearance')
    return region['rect']
