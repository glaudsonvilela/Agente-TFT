"""A1.6 verified pixel/observation handoff for an existing A15 reservation.

Internal local control-plane contract, not an authenticated inference service.
Only the producer knows how status observations were obtained. Hash verification
binds files and observations; it does not prove OCR correctness or account identity.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile
from training.perception_registry import canonical, digest, hash_value, require
from training.perception_coordinator import validate_samples

MAX_JSON = 16 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def load(path: Path) -> dict:
    require(not path.is_symlink() and path.is_file(), 'missing/symlink JSON')
    with path.open('rb') as f: raw = f.read(MAX_JSON+1)
    require(len(raw) <= MAX_JSON, 'JSON byte budget exceeded')
    def pairs(items):
        obj = {}
        for k,v in items:
            require(k not in obj, 'duplicate JSON key'); obj[k] = v
        return obj
    obj = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    require(isinstance(obj,dict), 'expected JSON object')
    return obj


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def publish(path: Path, obj: dict) -> None:
    """Publish a complete file without replacing an existing name (local POSIX)."""
    require(not path.exists() and not path.is_symlink(), 'destination already exists')
    raw = canonical(obj).encode()+b'\n'
    require(len(raw) <= MAX_JSON, 'output JSON byte budget exceeded')
    fd, name = tempfile.mkstemp(prefix='.a16-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        os.link(name,path,follow_symlinks=False)
        sync_dir(path.parent)
    finally:
        os.unlink(name)


def contained(root: Path, relative: str) -> Path:
    require(isinstance(relative,str) and relative and not Path(relative).is_absolute()
            and '..' not in Path(relative).parts, 'unsafe source path')
    path = root/relative
    require(not path.is_symlink(), 'source symlink not supported')
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(root.resolve(strict=True)), 'source escaped evidence root')
    return resolved


def verify_source(root: Path, bundle: dict, decision: dict) -> tuple[dict, dict[str,str]]:
    require(set(bundle) == {'schema_version','request_id','image_root','frames','samples'}
            and bundle['schema_version'] == 1 and bundle['request_id'] == decision['request_id'],
            'invalid work source contract')
    validate_samples(bundle['samples'])
    samples, frames = bundle['samples'], bundle['frames']
    require(isinstance(frames,list) and len(frames)==len(samples), 'frame/observation mismatch')
    require(digest(samples)==decision['input_hash'], 'source observations differ from reserved evidence')
    require([[s['timestamp_ms'],s['image_sha256']] for s in samples]==decision['source_frames'],
            'source identities differ from reservation')
    base = contained(root,bundle['image_root'])
    require(base.is_dir(), 'image root must be a directory')
    seen, hashes, stripped, total = set(), {}, [], 0
    for frame,sample in zip(frames,samples):
        require(set(frame)=={'timestamp_ms','image','sha256'}, 'labels/extra fields not allowed in worker manifest')
        require(frame['timestamp_ms']==sample['timestamp_ms'] and frame['sha256']==sample['image_sha256'],
                'frame/status identity mismatch')
        path=contained(base,frame['image'])
        require(path.is_file() and path not in seen, 'missing/duplicate image path')
        size=path.stat().st_size; total+=size
        require(0<size<=MAX_IMAGE and total<=MAX_TOTAL, 'image byte budget exceeded')
        require(sha256(path)==frame['sha256'], 'source image hash mismatch')
        hashes[str(path)]=frame['sha256'];seen.add(path);stripped.append(dict(frame))
    return dict(frames=stripped,image_root=str(base)),hashes


def submit_observations(coordinator, evidence_root: Path, inbox: Path, context: dict,
                        baseline: dict, candidate: dict, frames: list[dict], samples: list[dict],
                        image_root: Path, now_ms: int, completed_evidence_id: str | None=None) -> dict:
    """Internal producer API. Caller supplies actual observations, never labels.

    Validate pixels before assessing. No CLI imports arbitrary status JSON as a
    trusted sensor. Failed publication leaves a reservation without a source;
    the worker fails it rather than manufacturing a source or retrying forever.
    """
    from training.perception_registry import context_key, profile_key
    root=evidence_root.resolve(strict=True);base=image_root.resolve(strict=True)
    require(base.is_relative_to(root), 'images outside evidence root')
    pair=digest(dict(context=context_key(context),baseline=profile_key(baseline),candidate=profile_key(candidate)))
    ids=[[s['timestamp_ms'],s['image_sha256']] for s in samples]
    key=digest(dict(pair=pair,frames=ids))
    bundle=dict(schema_version=1,request_id=key,image_root=str(base.relative_to(root)),frames=frames,samples=samples)
    pseudo=dict(request_id=key,input_hash=digest(samples),source_frames=ids)
    verify_source(root,bundle,pseudo)
    receipt=coordinator.assess(context,baseline,candidate,samples,now_ms,completed_evidence_id)
    if receipt['intent_created']:
        require(inbox.resolve().is_relative_to(root) and not inbox.is_symlink(), 'unsafe worker inbox')
        inbox.mkdir(exist_ok=True)
        publish(inbox/(key+'.json'),bundle)
    return receipt
