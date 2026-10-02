"""One frozen L2 dependency, not another copy of U1/L1/L2."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
L2 = ROOT / 'experiments/ui-map-lite-l2'

def bind():
    manifest = json.loads((L2 / 'PACKAGE_MANIFEST.json').read_text())
    # Package manifests map relative names directly to SHA-256 hashes.
    entries = manifest.get('files', manifest.get('sha256', {}))
    if not entries:
        raise ValueError('frozen L2 manifest missing')
    if isinstance(entries, list):
        entries = {x['path']: x['sha256'] for x in entries}
    for name, value in entries.items():
        expected = value['sha256'] if isinstance(value, dict) else value
        p = L2 / name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('frozen L2 changed: ' + name)
    path = str(L2 / 'training')
    if path not in sys.path:
        sys.path.insert(0, path)
    return L2

bind()
