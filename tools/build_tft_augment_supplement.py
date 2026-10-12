"""Archive Set 18 augment IDs omitted by the current Riot Data Dragon file.

CommunityDragon mirrors client assets.  A prior Data Dragon version preserves
removed IDs.  Neither source proves that an augment can currently be offered.
"""
from __future__ import annotations

from html import unescape
from pathlib import Path
import json
import re
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CURRENT = 'https://raw.communitydragon.org/16.20/cdragon/tft'
PREVIOUS = 'https://ddragon.leagueoflegends.com/cdn/16.19.1/data'
OFFICIAL_NOTES = ('https://teamfighttactics.leagueoflegends.com/en-us/news/'
                  'game-updates/teamfight-tactics-patch-18-4/')
MISSING_CURRENT = ('DA_ChallengersGrace', 'TFT_Augment_BoosterPackPlusPlus')
REMOVED_PREVIOUS = ('DA_NestingDollsPlus', 'DA_NestingDollsPlusPlus')


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def plain(value: str) -> str:
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


def build(current_archive: dict) -> dict:
    existing = {row['id'] for row in current_archive['entries']}
    client_pt = fetch(f'{CURRENT}/pt_br.json')
    client_en = fetch(f'{CURRENT}/en_us.json')
    set18_ids = set(next(row['augments'] for row in client_en['setData']
                         if row.get('number') == 18))
    missing = set18_ids - existing
    if missing != set(MISSING_CURRENT):
        raise ValueError(f'Unexpected Set 18 client/Data Dragon difference: {sorted(missing)}')
    pt_items = {row.get('apiName'): row for row in client_pt['items']}
    en_items = {row.get('apiName'): row for row in client_en['items']}
    entries = []
    for key in MISSING_CURRENT:
        pt, en = pt_items[key], en_items[key]
        desc = plain(pt['desc'])
        if key == 'DA_ChallengersGrace':
            # The client mirror still says 3 s; Riot's 18.4B notes say 4 s.
            desc = desc.replace('@AttackSpeedMultiplier*100@', '25').replace(
                '@BuffDuration@', '4')
        elif key == 'TFT_Augment_BoosterPackPlusPlus':
            desc = desc.replace('@TotalValue@', '26').replace('@GuaranteedCost@', '5')
        entries.append(dict(id=key, name=pt['name'], name_en=en['name'],
                            description=desc, image=pt['icon'],
                            source=f'{CURRENT}/pt_br.json',
                            source_kind='client_asset_mirror',
                            present_in_current_set18_client_list=True,
                            live_offer_eligibility_verified=False,
                            description_patch_adjusted=(key == 'DA_ChallengersGrace')))
    old_pt = fetch(f'{PREVIOUS}/pt_BR/tft-augments.json')['data']
    old_en = fetch(f'{PREVIOUS}/en_US/tft-augments.json')['data']
    for key in REMOVED_PREVIOUS:
        if key in existing or key in set18_ids:
            raise ValueError(f'Expected archived-only augment: {key}')
        entries.append(dict(id=key, name=old_pt[key]['name'],
                            name_en=old_en[key]['name'],
                            description=plain(old_pt[key]['description']),
                            image=old_pt[key]['image']['full'],
                            source=f'{PREVIOUS}/pt_BR/tft-augments.json',
                            source_kind='previous_riot_data_dragon',
                            present_in_current_set18_client_list=False,
                            live_offer_eligibility_verified=False,
                            description_patch_adjusted=False))
    return dict(schema_version=1, locale='pt_BR', set_key='TFTSet18',
                current_client_version='16.20', previous_data_dragon_version='16.19.1',
                source_urls=[f'{CURRENT}/pt_br.json', f'{CURRENT}/en_us.json',
                             f'{PREVIOUS}/pt_BR/tft-augments.json',
                             f'{PREVIOUS}/en_US/tft-augments.json', OFFICIAL_NOTES],
                purpose='Identity lookup and historical preservation, not a live offer pool',
                live_offer_pool_complete=False, entry_count=len(entries), entries=entries)


if __name__ == '__main__':
    current = json.loads((ROOT / 'configs/catalog/augments-ddragon-16.20.1-pt_BR.json')
                         .read_text(encoding='utf-8'))
    result = build(current)
    output = ROOT / 'configs/catalog/augments-set18-supplement-18.4b-pt_BR.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                      encoding='utf-8')
    print(f'{len(result["entries"])} supplemental IDs -> {output}')
