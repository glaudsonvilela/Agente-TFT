"""Versioned seasonal data, independent of screen geometry and model weights.

Reuses the existing unit/item/trait normalizers. A release never edits a layout,
selects latest for a replay, clears quarantine, or activates a runtime profile.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit, unquote

from ingestion.build_unit_catalog import build_catalog as units_catalog, find_set, iter_sets
from ingestion.build_item_catalog import build_catalog as items_catalog
from ingestion.build_trait_catalog import build_catalog as traits_catalog

MAX_BYTES = 64 * 1024 * 1024
LEGACY_ASSETS = 'https://raw.communitydragon.org/latest/game/'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'duplicate JSON key')
            out[k] = v
        return out
    with Path(path).open('rb') as f:
        data = f.read(MAX_BYTES+1)
    require(len(data) <= MAX_BYTES, 'source byte budget exceeded')
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    require(isinstance(value, dict), 'expected JSON object')
    return value, digest(data)


def pin_assets(obj, build):
    """Pin only URLs emitted by the shared legacy normalizer; no downloading."""
    if isinstance(obj, list):
        return [pin_assets(v, build) for v in obj]
    if isinstance(obj, dict):
        return {k: pin_assets(v, build) for k, v in obj.items()}
    if isinstance(obj, str) and obj.startswith(LEGACY_ASSETS):
        tail = obj[len(LEGACY_ASSETS):]
        url = urlsplit(obj)
        require(not url.query and not url.fragment and '..' not in unquote(tail).split('/'), 'unsafe asset path')
        return f'https://raw.communitydragon.org/{build}/game/{tail}'
    return obj


def read_release(folder):
    folder = Path(folder).resolve(strict=True)
    m, _ = load(folder/'release.json')
    require(m.get('schema_version') == 1 and m.get('policy') == 'seasonal_release_v1', 'unsupported knowledge release')
    body = {k:v for k,v in m.items() if k != 'release_sha256'}
    require(digest(canonical(body)) == m.get('release_sha256'), 'release identity mismatch')
    require(set(m['components']) == {'units', 'items', 'traits'}, 'unexpected release components')
    catalogs = {}
    for key, entry in m['components'].items():
        require(entry['path'] == key+'.json', 'unsafe catalog path')
        p = folder/entry['path']
        require(not p.is_symlink() and p.is_file(), 'missing/symlink catalog')
        obj, checksum = load(p)
        require(checksum == entry['sha256'], 'catalog content changed')
        catalogs[key] = obj
    require(catalogs['units'].get('set') == m['set'], 'catalog set mismatch')
    return m, catalogs


def changes(previous, current):
    result = {}
    for key, collection in [('units', 'champions'), ('items', 'items'), ('traits', 'traits')]:
        old = {v['api_name']:v for v in previous[key][collection]}
        new = {v['api_name']:v for v in current[key][collection]}
        result[key] = dict(added=sorted(new.keys()-old.keys()), removed=sorted(old.keys()-new.keys()),
                           changed=sorted(k for k in old.keys() & new.keys() if old[k] != new[k]))
    return dict(components=result, geometry_changed=False, model_weights_changed=False,
                note='URL changes are data changes, not proof artwork pixels changed; no training or activation')


def build(source_path, *, selector, tft_patch, source_build, locale, output_root):
    for value in (selector, tft_patch):
        require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value) is not None, 'invalid set/patch token')
    require(re.fullmatch(r'\d+\.\d+(?:\.\d+)?', source_build or '') is not None, 'require pinned provider build; latest/pbe forbidden')
    require(re.fullmatch(r'[a-z]{2}_[a-z]{2}', locale or '') is not None, 'explicit locale required')
    source, checksum = load(source_path)
    selected = find_set(iter_sets(source), selector)
    catalogs = dict(units=units_catalog(source, selected), items=items_catalog(source),
                    traits=traits_catalog(source, selected.key))
    require(catalogs['units']['champion_count'] > 0, 'empty unit catalog')
    catalogs = pin_assets(catalogs, source_build)
    parts = {k:canonical(v) for k,v in catalogs.items()}
    identity = dict(schema_version=1, policy='seasonal_release_v1', set=catalogs['units']['set'],
        tft_patch=tft_patch, provider_build=source_build, locale=locale, source_sha256=checksum,
        source_identity='local snapshot bytes; provider build and game patch explicitly declared, not inferred',
        components={k:dict(path=k+'.json', sha256=digest(v), size_bytes=len(v)) for k,v in parts.items()},
        items_scope='provider snapshot; per-set membership not inferred',
        unit_scope='existing normalizer: playable costs 1..5; special offers/other costs may be excluded',
        geometry_included=False, active_profile_written=False, model_trained=False)
    m = dict(**identity, release_sha256=digest(canonical(identity)))
    root = Path(output_root).absolute()
    require(not root.is_symlink(), 'symlink output root')
    parent = root/selector/tft_patch
    parent.mkdir(parents=True, exist_ok=True)
    require(parent.resolve().is_relative_to(root.resolve()), 'output path escapes release root')
    destination = parent/m['release_sha256']
    if destination.exists():
        existing, _ = read_release(destination)
        require(existing == m, 'existing release differs; no overwrite')
        return destination, m, False
    staging = Path(tempfile.mkdtemp(prefix='.building-', dir=parent))
    try:
        for k, data in parts.items(): (staging/(k+'.json')).write_bytes(data)
        (staging/'release.json').write_bytes(canonical(m))
        read_release(staging)
        try:
            staging.rename(destination)
        except OSError:
            if not destination.is_dir(): raise
            existing, _ = read_release(destination)
            require(existing == m, 'concurrent release mismatch')
            return destination, m, False
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return destination, m, True


def bind_names(report, context, release_dir):
    """Exact unique catalog lookup, never fuzzy correction or inference from cost."""
    m, catalogs = read_release(release_dir)
    s = report['summary']
    require(context.get('schema_version') == 1, 'unsupported recording context')
    require(context.get('set_key') == m['set']['key'] and context.get('tft_patch') == m['tft_patch'],
            'recording set/patch must be known and exactly match release')
    require(context.get('locale') == s.get('locale') == m['locale'] and context.get('layout_id') == s.get('layout_id'),
            'UI language/layout context mismatch')
    by_name = {}
    for u in catalogs['units']['champions']:
        by_name.setdefault(' '.join(u['name'].casefold().split()), []).append(u)
    for row in report['records']:
        if 'read' not in row: continue
        for slot in row['read']['slots']:
            name = slot['observed_name']
            if name is None: continue
            matches = by_name.get(' '.join(name.casefold().split()), [])
            slot['catalog_status'] = 'exact_unique_name' if len(matches)==1 else 'ambiguous_name' if matches else 'offer_not_in_unit_catalog'
            if len(matches)==1:
                slot['unit_id'] = matches[0]['api_name']
                slot['catalog_base_cost'] = matches[0]['cost']
    s.update(set_key=m['set']['key'], tft_patch=m['tft_patch'], knowledge_release=m['release_sha256'],
             catalog_status='explicitly_bound', provider_build=m['provider_build'])
    s['capabilities']['unit_id_binding'] = True
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--set', dest='selector', required=True)
    p.add_argument('--tft-patch', required=True)
    p.add_argument('--source-build', required=True)
    p.add_argument('--locale', required=True)
    p.add_argument('--output-root', type=Path, default=Path('knowledge/releases'))
    p.add_argument('--previous', type=Path)
    a = p.parse_args()
    try:
        path, manifest, changed = build(a.source, selector=a.selector, tft_patch=a.tft_patch,
            source_build=a.source_build, locale=a.locale, output_root=a.output_root)
        result = dict(path=str(path), changed=changed, release=manifest)
        if a.previous:
            _, old = read_release(a.previous)
            _, new = read_release(path)
            result['delta'] = changes(old, new)
        print('KNOWLEDGE_RELEASE='+json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (ValueError, KeyError, OSError, TypeError) as e:
        p.exit(2, f'KNOWLEDGE_RELEASE_ERROR={e}\n')

if __name__ == '__main__': main()
