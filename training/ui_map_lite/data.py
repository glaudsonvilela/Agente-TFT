"""Bounded, reproducible composites. Crop seeds are weak semantics, not annotated game truth."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageEnhance, ImageDraw, ImageFilter
from .core import WIDTH, HEIGHT, PANELS, require, sha, load_json, inside


def read_rgb(path: Path) -> Image.Image:
    with Image.open(path) as im:
        require(im.size == (1920,1080), 'U1 needs unscaled 1920x1080 source images')
        return im.convert('RGB')


def profile_regions(board: dict, shop: dict) -> list[list[int]]:
    require(board.get('id') == 'match001-board-bench-v1' and len(board['bench_centers'])==9,
            'unexpected bank profile')
    require(shop.get('id') == 'match001-desktop-1920x1080-ptbr-v1' and len(shop['slots'])==5,
            'unexpected shop profile')
    half = board['bench_crop_width']//2
    bank = [min(board['bench_centers'])-half,board['bench_crop_y'],
            max(board['bench_centers'])-half+board['bench_crop_width'],
            board['bench_crop_y']+board['bench_crop_height']]
    cards = [s['card'] for s in shop['slots']]
    store = [min(x['x'] for x in cards),min(x['y'] for x in cards),
             max(x['x']+x['width'] for x in cards),max(x['y']+x['height'] for x in cards)]
    for b in (bank,store):
        require(0<=b[0]<b[2]<=1920 and 0<=b[1]<b[3]<=1080, 'region outside image')
    return [bank,store]


def prepare(root: Path, spec_path: Path, image_root: Path, manifest_path: Path):
    spec = load_json(spec_path)
    require(spec.get('schema_version')==1 and spec.get('id')=='uimap-lite-u1-match001', 'bad U1 spec')
    require(len(spec['profiles'])==2 and 3<=len(spec['seeds'])<=32,'profile/seed budget')
    provenance = {str(spec_path.resolve()):sha(spec_path)}
    profiles = []
    for p in spec['profiles']:
        path = inside(root,p['path']);raw = path.read_bytes()
        blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        require(blob==p['git_blob'], 'profile changed; requires new U1 experiment: '+str(path))
        profiles.append(json.loads(raw));provenance[str(path.resolve())]=sha(path)
    boxes = profile_regions(*profiles)
    manifest = load_json(manifest_path)
    rows = []
    seen, timestamps = set(), set()
    require(1<=len(manifest['frames'])<=128, 'frame count budget')
    for row in manifest['frames']:
        image, ms = row['image'],row['timestamp_ms']
        require(type(ms) is int and ms>=0 and ms not in timestamps and image not in seen, 'duplicate/invalid frame')
        path = inside(image_root,image);digest=sha(path)
        rows.append(dict(image=image,timestamp_ms=ms,sha256=digest))
        provenance[str(path.resolve())]=digest;seen.add(image);timestamps.add(ms)
    require(rows==sorted(rows,key=lambda r:r['timestamp_ms']), 'frames out of time order')
    provenance[str(manifest_path.resolve())]=sha(manifest_path)
    by_image={r['image']:r for r in rows}
    seed_hashes=set();seeds=[]
    for row in spec['seeds']:
        require(row['split'] in ('train','validation','test') and row['image'] in by_image,'invalid seed')
        require(by_image[row['image']]['sha256']==row['sha256'] and row['sha256'] not in seed_hashes,
                'seed bytes mismatch or duplicate crossing splits')
        seed_hashes.add(row['sha256']);seeds.append(dict(row))
    require(all(any(s['split']==g for s in seeds) for g in ('train','validation','test')), 'missing split')
    crops = {}
    for s in seeds:
        image=read_rgb(inside(image_root,s['image']))
        crops[s['image']]=[image.crop(tuple(b)) for b in boxes]
    return dict(spec=spec,seeds=seeds,boxes=boxes,frames=rows,provenance=provenance,crops=crops)


def generated_sample(crops, rng):
    # A fully defined synthetic canvas. No target markers are drawn in the pixels.
    noise = rng.integers(10,130,(12,20,3),dtype=np.uint8)
    canvas=Image.fromarray(noise).resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR)
    canvas=canvas.filter(ImageFilter.GaussianBlur(1))
    target=np.zeros(10,np.float32)
    # Separated bands prevent one pasted panel from silently covering the other.
    # Positions vary independently, rather than estimating a global screenshot border.
    for i,crop in enumerate(crops):
        w=int(rng.integers(128,275));h=int(rng.integers(18,39))
        x=int(rng.integers(0,WIDTH-w+1))
        lo,hi=(64,154-h) if i==0 else (154,HEIGHT-h)
        y=int(rng.integers(lo,hi+1))
        visible = rng.random() >= .22
        patch=crop.resize((w,h),Image.Resampling.BILINEAR)
        patch=ImageEnhance.Brightness(patch).enhance(float(rng.uniform(.70,1.25)))
        patch=ImageEnhance.Contrast(patch).enhance(float(rng.uniform(.80,1.20)))
        if visible:
            canvas.paste(patch,(x,y))
            # Fully obscured panel is a known synthetic negative, not an inferred game state.
            if rng.random()<.14:
                ImageDraw.Draw(canvas).rectangle((x,y,x+w-1,y+h-1),fill=tuple(map(int,rng.integers(15,170,3))))
                visible=False
        target[i*5:i*5+4]=[x/WIDTH,y/HEIGHT,(x+w)/WIDTH,(y+h)/HEIGHT]
        target[i*5+4]=float(visible)
    array=np.asarray(canvas,dtype=np.float32).transpose(2,0,1)/255.
    return np.ascontiguousarray(array),target


def generate(prepared, split: str, count: int, seed: int):
    require(type(count) is int and 1<=count<=1024,'sample budget exceeded')
    candidates=[s for s in prepared['seeds'] if s['split']==split]
    require(bool(candidates),'no source in split')
    rng=np.random.default_rng(seed)
    xs,ys=[],[]
    for i in range(count):
        source=candidates[i%len(candidates)]
        x,y=generated_sample(prepared['crops'][source['image']],rng);xs.append(x);ys.append(y)
    return np.stack(xs),np.stack(ys)


def image_tensor(path: Path):
    image=read_rgb(path).resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR)
    return np.ascontiguousarray(np.asarray(image,dtype=np.float32).transpose(2,0,1)[None]/255.)


def fixed_boxes(boxes):
    return [[b[0]/1920,b[1]/1080,b[2]/1920,b[3]/1080] for b in boxes]
