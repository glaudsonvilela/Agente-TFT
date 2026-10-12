"""Create a versioned OCR lookup from Riot TFT Data Dragon (non-hero augments).

This archive is intentionally not an offer pool: Data Dragon also includes
historical IDs and does not encode live server-side availability.
"""
from __future__ import annotations

from html import unescape
from pathlib import Path
import argparse
import json
import re
import urllib.request


def plain_text(value: str) -> str:
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


def fetch(version: str, locale: str) -> tuple[str, dict]:
    url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/tft-augments.json'
    with urllib.request.urlopen(url, timeout=20) as response:
        return url, json.load(response)['data']


def build(version: str) -> dict:
    pt_url, pt = fetch(version, 'pt_BR')
    en_url, en = fetch(version, 'en_US')
    if set(pt) != set(en):
        raise ValueError('Data Dragon locales have different augment IDs')
    entries = []
    for key in sorted(pt):
        row = pt[key]
        entries.append({
            'id': key,
            'name': row['name'],
            'name_en': en[key]['name'],
            'description': plain_text(row['description']),
            'image': row['image']['full'],
            'set18_candidate_by_id_prefix': key.startswith('DA_'),
            'live_offer_eligibility_verified': False,
        })
    return {
        'schema_version': 1,
        'data_dragon_version': version,
        'locale': 'pt_BR',
        'entry_count': len(entries),
        'source_urls': [pt_url, en_url],
        'scope': 'All non-hero augment IDs in this Data Dragon release, across active sets',
        'live_offer_pool_complete': False,
        'hero_augments_included': False,
        'entries': entries,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='16.20.1')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] /
                        'configs/catalog/augments-ddragon-16.20.1-pt_BR.json')
    args = parser.parse_args()
    archive = build(args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    print(f'{len(archive["entries"])} augment IDs -> {args.output}')
