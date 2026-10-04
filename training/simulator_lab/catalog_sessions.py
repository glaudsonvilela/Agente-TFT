"""Verify and deduplicate replay frames without converting model predictions to labels."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

from .selfplay import atomic_json

MAX_FILE = 32 * 1024 * 1024


def safe_relative(name):
    path = PurePosixPath(name.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts or ':' in name or not path.parts:
        raise ValueError('Unsafe session member path')
    return path.as_posix()


class SessionSource:
    def __init__(self, path):
        self.path = path.resolve(strict=True)
        self.archive = None
        self.prefix = ''
        self.entries = {}
        if self.path.is_file():
            self.archive = zipfile.ZipFile(self.path)
            for entry in self.archive.infolist():
                if not entry.is_dir():
                    name = safe_relative(entry.filename)
                    self.entries.setdefault(name, []).append(entry)
            manifests = [n for n in self.entries if PurePosixPath(n).name == 'training-manifest.json']
            if len(manifests) != 1:
                self.close()
                raise ValueError('Expected exactly one training manifest')
            self.prefix = manifests[0][:-len('training-manifest.json')]

    def read(self, name):
        name = safe_relative(name)
        if self.archive:
            entries = self.entries[self.prefix + name]
            if any(entry.file_size > MAX_FILE for entry in entries):
                raise ValueError('Session file exceeds size budget')
            data = self.archive.read(entries[0])
            checksum = hashlib.sha256(data).digest()
            for entry in entries[1:]:
                if hashlib.sha256(self.archive.read(entry)).digest() != checksum:
                    raise ValueError('Conflicting duplicate ZIP member')
            return data
        path = (self.path / name).resolve(strict=True)
        if not path.is_relative_to(self.path) or path.stat().st_size > MAX_FILE:
            raise ValueError('Session file outside root or too large')
        return path.read_bytes()

    def close(self):
        if self.archive:
            self.archive.close()


def catalog(sources, output):
    from PIL import Image
    records, sessions = {}, []
    observations = 0
    for path in sources:
        source = SessionSource(path)
        try:
            raw = source.read('training-manifest.json')
            manifest = json.loads(raw)
            session_id = manifest['session_id']
            samples = manifest['samples']
            if len(samples) > 10000:
                raise ValueError('Session sample budget exceeded')
            for sample in samples:
                data = source.read(sample['image'])
                checksum = hashlib.sha256(data).hexdigest()
                if checksum != sample['image_sha256']:
                    raise ValueError(f'Frame hash mismatch: {session_id}/{sample["image"]}')
                with Image.open(io.BytesIO(data)) as image:
                    if image.size != (sample['width'], sample['height']) or image.width * image.height > 16_000_000:
                        raise ValueError('Frame dimensions mismatch or oversized')
                    pixels = image.convert('RGB').tobytes()
                rgb_sha = hashlib.sha256(pixels).hexdigest()
                if sample.get('decoded_rgb_sha256') and rgb_sha != sample['decoded_rgb_sha256']:
                    raise ValueError('Decoded pixel hash mismatch')
                row = records.setdefault(rgb_sha, dict(decoded_rgb_sha256=rgb_sha, observations=[],
                    geometry_scope='screen_layout', seasonal_binding=None, match_group=None,
                    split='unassigned', supervision='unlabelled', labels={}, predictions_are_labels=False))
                reference = dict(session_id=session_id, source=str(source.path),
                                 image=sample['image'], image_sha256=checksum,
                                 frame_id=sample.get('frame_id'), source_ms=sample.get('source_ms'))
                if reference not in row['observations']:
                    row['observations'].append(reference)
                observations += 1
            sessions.append(dict(session_id=session_id, samples=len(samples),
                                 manifest_sha256=hashlib.sha256(raw).hexdigest()))
        finally:
            source.close()
    result = dict(schema_version=1, kind='verified_replay_frame_catalog', sessions=sessions,
                  source_samples=observations, unique_frames=len(records),
                  duplicate_frames=observations-len(records), reviewed_labels=0,
                  strategic_training_ready=False, independent_match_split=False,
                  split_policy='Require reviewed match identity before any train/validation split',
                  frames=sorted(records.values(), key=lambda row: row['decoded_rgb_sha256']))
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, result)
    return {k: v for k, v in result.items() if k != 'frames'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(catalog(args.source, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
