"""Whole-scene warps plus context feathering; labels are synthetic, not natural truth."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
from .common import WIDTH,HEIGHT,PANELS,require,load,sha,contained,rect_corners,validate_policy


def source_manifest(root,plan,manifest):
    validate_policy(plan)
    rows=load(manifest)['frames']; require(len(rows)==40,'complete 40-frame batch required')
    require(len({r['image'] for r in rows})==40 and len({r['timestamp_ms'] for r in rows})==40,'duplicate frame identity')
    result=[];hashes={};index={}
    for r in sorted(rows,key=lambda x:x['timestamp_ms']):
        require(type(r['timestamp_ms']) is int and r['timestamp_ms']>=0,'timestamp invalid')
        p=contained(root,r['image']);require(0<p.stat().st_size<=16*1024**2,'image budget')
        with Image.open(p) as im:
            require(im.size==(1920,1080),'original size mismatch');im.verify()
        digest=sha(p);hashes[str(p)]=digest;index[r['image']]=digest
        result.append(dict(image=r['image'],timestamp_ms=r['timestamp_ms'],sha256=digest))
    names=[set(plan[s+'_images']) for s in ('train','validation','test')]
    require(all(names) and all(s<=set(index) for s in names),'missing split source')
    for i in range(3):
        for j in range(i):
            require(not names[i]&names[j],'source split leakage')
            require(not {index[k] for k in names[i]}&{index[k] for k in names[j]},'duplicate source bytes across splits')
    require(set(plan['seed_sha256'])==set.union(*names),'all seeds must be hash-pinned')
    for n,d in plan['seed_sha256'].items():require(index[n]==d,'seed bytes changed: '+n)
    return result,hashes


def image_input(im):
    im=im.convert('RGB').resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR)
    return np.asarray(im,dtype=np.float32).transpose(2,0,1).copy()/255


def input_path(path):
    with Image.open(path) as im:
        require(im.size==(1920,1080),'source resolution')
        return image_input(im)


class Compositor:
    """A source belongs to only one split. Suggestions/scene/OCR are never read.

    Native render and reduced render use identical sampled operations. Whole-scene
    transformations avoid cut/paste seams. Context composites remain an explicitly
    separate, artificial distribution. No benchmark pretends these are new matches.
    """
    def __init__(self,root,plan,split):
        require(split in ('train','validation','test'),'invalid split')
        self.plan=plan;self.split=split
        self.names=list(plan[split+'_images'])
        self.images=[]
        for n in self.names:
            with Image.open(contained(root,n)) as im:self.images.append(im.convert('RGB').copy())
        self.small=[im.resize((WIDTH,HEIGHT),Image.Resampling.BILINEAR) for im in self.images]

    def sample(self,seed,full_resolution=False):
        rng=np.random.default_rng(int(seed));idx=int(rng.integers(len(self.images)))
        iw,ih=(1920,1080) if full_resolution else (WIDTH,HEIGHT)
        kx,ky=iw/WIDTH,ih/HEIGHT
        base=self.images[idx] if full_resolution else self.small[idx]
        mode='whole_scene' if rng.random()<self.plan['composition_modes']['whole_scene'] else 'context_paste'
        boxes=np.zeros((2,4),np.float32);visible=np.ones(2,np.float32);meta=[]
        if mode=='whole_scene':
            sx=float(rng.uniform(.72,1.08));sy=float(rng.uniform(.82,1.06))
            tx=float(rng.uniform(-25,35));ty=float(rng.uniform(-32,10))
            fill=tuple(map(int,rng.integers(0,50,3)))
            canvas=base.transform((iw,ih),Image.Transform.AFFINE,
                (1/sx,0,-tx*kx/sx,0,1/sy,-ty*ky/sy),Image.Resampling.BILINEAR,fillcolor=fill)
            for i,name in enumerate(PANELS):
                l,t,r,b=rect_corners(self.plan['panels'][name]['rect'])*[WIDTH,HEIGHT,WIDTH,HEIGHT]
                box=np.array([l*sx+tx,t*sy+ty,r*sx+tx,b*sy+ty],np.float32)
                boxes[i]=box/[WIDTH,HEIGHT,WIDTH,HEIGHT]
                visible[i]=float(0<=box[0]<box[2]<=WIDTH and 0<=box[1]<box[3]<=HEIGHT)
                meta.append(dict(panel=name,kind='global_transform' if visible[i] else 'clipped',source=self.names[idx]))
        else:
            # Background excludes both original bottom panels; no hidden duplicate.
            top=self.images[idx].crop((0,0,1920,600))
            canvas=top.resize((iw,ih),Image.Resampling.BILINEAR)
            for i,name in enumerate(PANELS):
                si=int(rng.integers(len(self.images)))
                x,y,w,h=self.plan['panels'][name]['rect'];cx=12;cy=4
                # Context outside annotated envelope; zero alpha exists only outside the label.
                src=self.images[si].crop((max(0,x-cx),max(0,y-cy),min(1920,x+w+cx),min(1080,y+h+cy)))
                tw=int(rng.integers(155,256));th=int(rng.integers(21,32))
                dx=int(rng.integers(8,WIDTH-tw-8));lo,hi=((32,122) if i==0 else (140,HEIGHT-th-1))
                dy=int(rng.integers(lo,max(lo+1,hi)))
                boxes[i]=np.array([dx,dy,dx+tw,dy+th])/[WIDTH,HEIGHT,WIDTH,HEIGHT]
                margin_x=max(1,int(tw*cx/w*kx));margin_y=max(1,int(th*cy/h*ky))
                tile=src.resize((int(tw*kx)+2*margin_x,int(th*ky)+2*margin_y),Image.Resampling.BILINEAR)
                mask=Image.new('L',tile.size,0)
                ImageDraw.Draw(mask).rectangle((margin_x,margin_y,tile.width-margin_x-1,tile.height-margin_y-1),fill=255)
                mask=mask.filter(ImageFilter.GaussianBlur(max(.5,min(margin_x,margin_y)/2)))
                canvas.paste(tile,(int(dx*kx)-margin_x,int(dy*ky)-margin_y),mask)
                meta.append(dict(panel=name,kind='feathered_context',source=self.names[si]))
        # Explicit synthetic occlusion; do not infer natural absence from these labels.
        for i,name in enumerate(PANELS):
            occlude=rng.random()<.22
            cover=float(rng.uniform(.4,1.0));left=float(rng.random())
            color=tuple(map(int,rng.integers(0,160,3)))
            if occlude:
                l,t,r,b=boxes[i]*[iw,ih,iw,ih];bw=max(1,r-l);ow=max(1,bw*cover)
                a=int(l+(bw-ow)*left);bb=int(a+ow)
                ImageDraw.Draw(canvas).rectangle((a,int(t),bb,int(b)),fill=color)
                visible[i]=0;meta[i]['kind']='artificially_occluded'
        brightness=float(rng.uniform(.65,1.28));color_gain=float(rng.uniform(.45,1.25))
        canvas=ImageEnhance.Brightness(canvas).enhance(brightness)
        canvas=ImageEnhance.Color(canvas).enhance(color_gain)
        x=image_input(canvas)
        return x,boxes,visible,dict(mode=mode,panels=meta,seed=int(seed)),canvas if full_resolution else None

    def batch(self,seeds):
        data=[self.sample(int(s)) for s in seeds]
        return tuple(np.stack([r[i] for r in data]) for i in range(3))
