"""Supervision is synthetic placement of seed crops, not labels inferred from OCR/B1."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from .common import WIDTH, HEIGHT, PANELS, require, contained, sha, load, box_from_rect


def source_manifest(root: Path, plan: dict, manifest_path: Path) -> tuple[list[dict], dict]:
    require(plan['source_size'] == [1920, 1080] and plan['input_size'] == [WIDTH, HEIGHT], 'unsupported image geometry')
    require(set(plan['panels']) == set(PANELS), 'unexpected panels')
    rows = load(manifest_path)['frames']
    require(len(rows) == 40, 'L1 requires the complete 40-frame Match001 batch')
    require(len({r['image'] for r in rows}) == len(rows), 'duplicate paths')
    require(len({r['timestamp_ms'] for r in rows}) == len(rows), 'duplicate timestamps')
    result, hashes = [], {}
    for r in sorted(rows, key=lambda x: x['timestamp_ms']):
        require(type(r['timestamp_ms']) is int and r['timestamp_ms'] >= 0, 'invalid timestamp')
        path = contained(root, r['image'])
        require(0 < path.stat().st_size <= 16*1024**2, 'image size budget')
        digest = sha(path)
        with Image.open(path) as im:
            require(im.size == tuple(plan['source_size']), 'resolution mismatch')
            im.verify()
        result.append(dict(image=r['image'], timestamp_ms=r['timestamp_ms'], sha256=digest))
        hashes[str(path)] = digest
    split_sets = [set(plan[k+'_images']) for k in ('train','validation','test')]
    require(all(split_sets) and not any(split_sets[i] & split_sets[j]
                                      for i in range(3) for j in range(i)), 'source split leakage')
    index = {r['image']: r['sha256'] for r in result}
    for name, expected in plan['seed_sha256'].items():
        require(index.get(name) == expected, 'seed bytes changed: '+name)
    require(all(s <= set(index) for s in split_sets), 'missing split seed')
    split_hashes = [{index[x] for x in s} for s in split_sets]
    require(not any(split_hashes[i]&split_hashes[j] for i in range(3) for j in range(i)), 'duplicate seed bytes across splits')
    # Never read suggestions, scene labels, gold, HP or champion annotations.
    return result, hashes


class Compositor:
    """Independent panel translation/scaling, removal and cutouts.

    Pasted boundaries may be shortcuts: this is a seed-conditioned development
    task, NOT a validation on naturally changed TFT interfaces.
    """
    def __init__(self, root: Path, plan: dict, split: str):
        self.plan, self.split = plan, split
        self.images = []
        for name in plan[split+'_images']:
            with Image.open(contained(root, name)) as im:
                self.images.append(im.convert('RGB').copy())
        self.templates = {p: [] for p in PANELS}
        for im in self.images:
            for p in PANELS:
                x,y,w,h = plan['panels'][p]['rect']
                require(x >= 0 and y >= 0 and x+w <= im.width and y+h <= im.height, 'invalid seed ROI')
                self.templates[p].append(im.crop((x,y,x+w,y+h)))
        self.backgrounds = []
        for im in self.images:
            # Only the upper scene is used as background: original bottom panels
            # are not secretly present in samples labelled as absent.
            self.backgrounds.append(im.crop((0,0,im.width,600)).resize((WIDTH,HEIGHT)))

    def sample(self, seed: int):
        rng = np.random.default_rng(seed)
        if rng.random() < .70:
            background = self.backgrounds[int(rng.integers(len(self.backgrounds)))].copy()
            background = background.filter(ImageFilter.GaussianBlur(float(rng.uniform(0,2))))
        else:
            noise = rng.integers(0,150,(12,20,3),dtype=np.uint8)
            background = Image.fromarray(noise).resize((WIDTH,HEIGHT), Image.Resampling.BILINEAR)
        boxes = np.zeros((2,4), dtype=np.float32)
        visible = np.zeros(2, dtype=np.float32)
        metadata = []
        for i, panel in enumerate(PANELS):
            # Absence is generated deliberately, not inferred from failure to read.
            present = rng.random() >= .18
            if not present:
                metadata.append(dict(panel=panel, kind='not_inserted'))
                continue
            template = self.templates[panel][int(rng.integers(len(self.images)))].copy()
            w = int(rng.integers(130, 271))
            aspect = template.height / template.width
            h = max(16, int(w * aspect * rng.uniform(.75,1.35)))
            h = min(h,50 if i == 0 else 38)
            x = int(rng.integers(0, WIDTH-w+1))
            # Separate independent rows, deliberately broader than the real layout.
            lo, hi = ((30,min(130,150-h)) if i == 0 else (153,HEIGHT-h))
            y = int(rng.integers(lo,max(lo+1,hi+1)))
            resized = template.resize((w,h), Image.Resampling.BILINEAR)
            resized = ImageEnhance.Brightness(resized).enhance(float(rng.uniform(.6,1.35)))
            resized = ImageEnhance.Color(resized).enhance(float(rng.uniform(.3,1.3)))
            background.paste(resized,(x,y))
            boxes[i] = box_from_rect([x,y,w,h],(WIDTH,HEIGHT))
            visible[i] = 1
            kind = 'inserted'
            if rng.random() < .20:
                # Exact known obstruction: do not train the hidden coordinates.
                occ_w = int(rng.integers(max(1,w//4),w+1))
                ox = x + int(rng.integers(0,w-occ_w+1))
                color = tuple(int(v) for v in rng.integers(0,200,3))
                background.paste(color,(ox,y,ox+occ_w,y+h))
                visible[i] = 0
                kind = 'synthetically_occluded'
            metadata.append(dict(panel=panel, kind=kind, inserted_rect=[x,y,w,h]))
        image = np.asarray(background,dtype=np.float32).transpose(2,0,1)/255.
        return np.ascontiguousarray(image), boxes, visible, metadata

    def batch(self, seeds):
        rows = [self.sample(int(s)) for s in seeds]
        return tuple(np.stack([r[i] for r in rows]) for i in range(3))


def input_image(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert('RGB').resize((WIDTH,HEIGHT), Image.Resampling.BILINEAR)
        return np.ascontiguousarray(np.asarray(image,dtype=np.float32).transpose(2,0,1)/255.)
