"""Canonical native-resolution rendering, shared by training and evaluation.

Targets follow the actual context crop/paste transform. No independently rounded
low-resolution margins; no labels from B1/OCR/model predictions.
"""
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageEnhance
from . import legacy
from uimap_lite_l2.common import PANELS,require,contained,sha
from .pixels import prepare_image

class Renderer:
    def __init__(self,root,base_plan,plan,split):
        require(split in ('train','validation','test'),'split')
        self.base_plan=base_plan;self.plan=plan;self.split=split
        self.names=base_plan[split+'_images'];self.images=[]
        for n in self.names:
            with Image.open(contained(root,n)) as im:self.images.append(im.convert('RGB').copy())
        neg=plan['negative_sources'][split]
        p=contained(root,neg['image']);require(sha(p)==neg['sha256'],'negative source changed')
        with Image.open(p) as im:self.negative=im.convert('RGB').copy()

    def sample(self,seed):
        rng=np.random.default_rng(int(seed));j=int(rng.integers(len(self.images)))
        boxes=np.zeros((2,4),np.float32);visible=np.ones(2,np.float32)
        mode=('negative_scene' if rng.random()<.20 else
              'whole_scene' if rng.random()<.65 else 'context_paste')
        meta=dict(seed=int(seed),mode=mode,source=self.names[j],canonical_size=[1920,1080],
                  supervision='known_transform_of_development_seed')
        if mode=='negative_scene':
            canvas=self.negative.copy();visible[:]=0
            meta['source']=self.plan['negative_sources'][self.split]['image']
            meta['supervision']='visual_negative_seed_not_an_independent_match'
        elif mode=='whole_scene':
            sx=float(rng.uniform(.72,1.08));sy=float(rng.uniform(.82,1.06))
            tx=float(rng.uniform(-150,210));ty=float(rng.uniform(-180,56.25))
            canvas=self.images[j].transform((1920,1080),Image.Transform.AFFINE,
                       (1/sx,0,-tx/sx,0,1/sy,-ty/sy),Image.Resampling.BILINEAR,
                       fillcolor=tuple(map(int,rng.integers(0,50,3))))
            for i,n in enumerate(PANELS):
                x,y,w,h=self.base_plan['panels'][n]['rect']
                a=np.array([x*sx+tx,y*sy+ty,(x+w)*sx+tx,(y+h)*sy+ty])
                boxes[i]=a/[1920,1080,1920,1080]
                visible[i]=float(0<=a[0]<a[2]<=1920 and 0<=a[1]<a[3]<=1080)
        else:
            canvas=self.images[j].crop((0,0,1920,600)).resize((1920,1080),Image.Resampling.BILINEAR)
            meta['panel_sources']=[]
            for i,n in enumerate(PANELS):
                si=int(rng.integers(len(self.images)));x,y,w,h=self.base_plan['panels'][n]['rect']
                left,top=max(0,x-12),max(0,y-4)
                right,bottom=min(1920,x+w+12),min(1080,y+h+4)
                src=self.images[si].crop((left,top,right,bottom))
                tw=int(rng.integers(940,1510));th=int(rng.integers(125,180))
                # Resize scale and envelope share the SAME actual integer tile dimensions.
                nw=int(round(tw*src.width/w));nh=int(round(th*src.height/h))
                sx=nw/src.width;sy=nh/src.height
                dx=int(rng.integers(30,max(31,1920-nw-30)))
                lo,hi=((180,690) if i==0 else (780,max(781,1080-nh-1)))
                dy=int(rng.integers(lo,hi))
                tile=src.resize((nw,nh),Image.Resampling.BILINEAR)
                alpha=Image.new('L',src.size,0)
                ImageDraw.Draw(alpha).rectangle((x-left,y-top,x+w-left-1,y+h-top-1),fill=255)
                alpha=alpha.filter(ImageFilter.GaussianBlur(1)).resize((nw,nh),Image.Resampling.BILINEAR)
                canvas.paste(tile,(dx,dy),alpha)
                a=np.array([dx+(x-left)*sx,dy+(y-top)*sy,dx+(x+w-left)*sx,dy+(y+h-top)*sy])
                boxes[i]=a/[1920,1080,1920,1080]
                visible[i]=float(0<=a[0]<a[2]<=1920 and 0<=a[1]<a[3]<=1080)
                meta['panel_sources'].append(self.names[si])
        if mode!='negative_scene':
            for i in range(2):
                if rng.random()<.22:
                    l,t,r,b=boxes[i]*[1920,1080,1920,1080]
                    cover=float(rng.uniform(.4,1));dx=float(rng.random())*(r-l)*(1-cover)
                    ImageDraw.Draw(canvas).rectangle((int(l+dx),int(t),int(l+dx+(r-l)*cover),int(b)),
                                 fill=tuple(map(int,rng.integers(0,160,3))))
                    visible[i]=0
        canvas=ImageEnhance.Brightness(canvas).enhance(float(rng.uniform(.65,1.28)))
        canvas=ImageEnhance.Color(canvas).enhance(float(rng.uniform(.45,1.25)))
        frame=prepare_image(canvas,int(seed))
        return frame,boxes,visible,meta

    def cache(self,count,seed):
        require(1<=count<=1024,'cache budget')
        xs=[];ys=[];vs=[];modes=[]
        for i in range(count):
            f,y,v,m=self.sample(seed+i)
            xs.append(np.rint(f.tensor*255).astype(np.uint8));ys.append(y);vs.append(v);modes.append(m['mode'])
        return np.stack(xs),np.stack(ys),np.stack(vs),modes
