"""Complete core item recipes from the pinned seasonal item release.

This is an identity lookup. A recipe being known does not validate its combat
effect or authorize the strategic coach to recommend crafting it.
"""
from __future__ import annotations

from itertools import combinations_with_replacement


CORE_COMPONENTS = (
    'TFT_Item_BFSword',
    'TFT_Item_ChainVest',
    'TFT_Item_GiantsBelt',
    'TFT_Item_NeedlesslyLargeRod',
    'TFT_Item_NegatronCloak',
    'TFT_Item_RecurveBow',
    'TFT_Item_SparringGloves',
    'TFT_Item_TearOfTheGoddess',
)


def core_recipes(items: list[dict]) -> dict[tuple[str, str], dict]:
    """Return exactly one ordinary completed item for every core pair."""
    components = set(CORE_COMPONENTS)
    by_pair: dict[tuple[str, str], dict] = {}
    for row in items:
        item_id = row.get('api_name', '')
        pair = row.get('composition') or []
        if (not item_id.startswith('TFT_Item_') or
                item_id.startswith('TFT_Item_Corrupted') or
                len(pair) != 2 or not set(pair) <= components):
            continue
        key = tuple(sorted(pair))
        if key in by_pair:
            raise ValueError(f'Ambiguous core item recipe: {key}')
        if not row.get('name'):
            raise ValueError(f'Unnamed core item recipe: {item_id}')
        by_pair[key] = {'item_id': item_id, 'name': row['name']}
    expected = set(combinations_with_replacement(CORE_COMPONENTS, 2))
    if set(by_pair) != expected:
        missing = sorted(expected - set(by_pair))
        extra = sorted(set(by_pair) - expected)
        raise ValueError(f'Incomplete core item recipes: missing={missing}, extra={extra}')
    return by_pair


def crafted_item(recipes: dict[tuple[str, str], dict], first: str, second: str) -> dict | None:
    return recipes.get(tuple(sorted((first, second))))
