"""Geometric replay of frozen L3 sampling; no training, labels or game pixels inferred."""
from pathlib import Path
from collections import Counter
import hashlib,json
import numpy as np

SOURCE=Path(__file__).resolve().parents[2]/'training/uimap_path_l3/data.py'
EXPECTED='02f90741849edee3998d214f39a8fd980f833af1'
SCALE=np.array([1920,1080,1920,1080])
class StubImage:
    def __init__(self,size=(1920,1080)):
        self.size=tuple(size);self.width,self.height=self.size;self.pastes=[];self.draws=[]
    def copy(self):return StubImage(self.size)
    def crop(self,b):return StubImage((b[2]-b[0],b[3]-b[1]))
    def resize(self,size,*a,**k):return StubImage(size)
    def transform(self,size,*a,**k):return StubImage(size)
    def paste(self,tile,xy,alpha):self.pastes.append({'xy':list(xy),'size':list(tile.size)})
    def filter(self,*a):return self
class StubDraw:
    def __init__(self,im):self.im=im
    def rectangle(self,box,fill):self.im.draws.append(list(box))
class Enh:
    def __init__(self,im):self.im=im
    def enhance(self,v):return self.im

def require(v,m):
    if not v:raise ValueError(m)
def load_renderer():
    from types import SimpleNamespace as N
    b=SOURCE.read_bytes();actual=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    require(actual==EXPECTED,'source blob mismatch')
    s=b.decode()
    # Keep Renderer body byte-for-byte. Replace only imports with an explicit no-pixel test harness.
    body=s[s.index('class Renderer:'):]
    ns=dict(np=np,Image=N(new=lambda mode,size,value:StubImage(size),Transform=N(AFFINE=0),Resampling=N(BILINEAR=0)),
            ImageDraw=N(Draw=StubDraw),ImageFilter=N(GaussianBlur=lambda r:r),
            ImageEnhance=N(Brightness=Enh,Color=Enh),PANELS=('bench','shop'),require=require,
            prepare_image=lambda canvas,seed:canvas)
    exec(compile(body,str(SOURCE),'exec'),ns)
    return ns['Renderer']

def overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
def geometry_audit():
    R=load_renderer();output={'frozen_source_git_blob':EXPECTED,'geometry_only':True,
        'game_images_used':False,'neural_inference_executed':False,'causal_explanation_of_user_prediction_errors':False,'splits':{}}
    for split,count,names,seed in [('train',768,10,80300000),('validation',96,2,80310000),('test',192,4,80330000)]:
        r=R.__new__(R);r.names=[f'{split}-source-{i}' for i in range(names)];r.images=[StubImage() for _ in range(names)]
        r.base_plan={'panels':{'bench':{'rect':[358,682,1038,146]},'shop':{'rect':[345,915,1220,160]}}}
        r.plan={'negative_sources':{split:{'image':f'{split}-negative'}}};r.split=split;r.negative=StubImage()
        modes=Counter();visible=Counter();cases=[];cross=[]
        for i in range(count):
            frame,boxes,vis,meta=r.sample(seed+i);b=boxes*SCALE;modes[meta['mode']]+=1
            for k,p in enumerate(('bench','shop')):visible[p]+=int(vis[k])
            if meta['mode']!='context_paste':continue
            area=overlap(*b)
            if area>0:
                # Bench is pasted first; the shop layer is pasted later and can obscure it.
                frac=area/((b[0,2]-b[0,0])*(b[0,3]-b[0,1]))
                cases.append({'seed':seed+i,'bench_box':b[0].tolist(),'shop_box':b[1].tolist(),
                    'overlap_px2':area,'fraction_of_bench_envelope':frac,'visible_labels':vis.astype(int).tolist()})
            # Explicit rectangles drawn after both panels, potentially covering the other label too.
            for c in frame.draws:
                cross.append({'seed':seed+i,'occluder_box':c,'overlap_with_bench_px2':overlap(c,b[0]),
                    'overlap_with_shop_px2':overlap(c,b[1]),'visible_labels':vis.astype(int).tolist()})
        output['splits'][split]={'examples':count,'modes':dict(modes),'visible_labels':dict(visible),
            'intersecting_panel_envelopes':len(cases),
            'intersecting_both_labelled_visible':sum(c['visible_labels']==[1,1] for c in cases),
            'intersecting_bench_labelled_visible':sum(c['visible_labels'][0]==1 for c in cases),
            'largest_overlap_fraction_of_bench':max((c['fraction_of_bench_envelope'] for c in cases),default=0),
            'cases':cases,
            'explicit_occluders_crossing_both_envelopes':[c for c in cross if c['overlap_with_bench_px2']>0 and c['overlap_with_shop_px2']>0]}
    test=output['splits']['test']
    require(test['modes']=={'negative_scene':37,'whole_scene':106,'context_paste':49},'mode replay differs from user summary')
    require(test['visible_labels']=={'bench':124,'shop':120},'label replay differs from user summary')
    output['test_mode_and_visible_counts_match_user_summary']=True
    return output



def pixel_audit():
    from PIL import Image,ImageDraw,ImageFilter,ImageEnhance
    b=SOURCE.read_bytes();require(hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==EXPECTED,'source blob mismatch')
    ns=dict(np=np,Image=Image,ImageDraw=ImageDraw,ImageFilter=ImageFilter,ImageEnhance=ImageEnhance,
            PANELS=('bench','shop'),require=require,prepare_image=lambda canvas,seed:canvas)
    exec(compile(b.decode()[b.decode().index('class Renderer:'):],str(SOURCE),'exec'),ns)
    R=ns['Renderer'];r=R.__new__(R)
    r.base_plan={'panels':{'bench':{'rect':[358,682,1038,146]},'shop':{'rect':[345,915,1220,160]}}}
    r.plan={'negative_sources':{'train':{'image':'synthetic-negative'}}};r.split='train'
    r.names=[f'synthetic-source-{i}' for i in range(10)]
    r.images=[]
    for i in range(10):
     im=Image.new('RGB',(1920,1080),(0,0,0));d=ImageDraw.Draw(im)
     d.rectangle((358,682,1395,827),fill=(230,20,20))
     d.rectangle((345,915,1564,1074),fill=(20,230,20))
     r.images.append(im)
    r.negative=Image.new('RGB',(1920,1080),0)
    im,boxes,vis,meta=r.sample(80300396)
    bounds=boxes*SCALE
    xy=(1000,825);pixel=im.getpixel(xy)
    require(vis.tolist()==[1,1],'unexpected visibility in pixel fixture')
    require(bounds[0,0]<xy[0]<bounds[0,2] and bounds[0,1]<xy[1]<bounds[0,3],'pixel outside bench')
    require(bounds[1,0]<xy[0]<bounds[1,2] and bounds[1,1]<xy[1]<bounds[1,3],'pixel outside shop')
    require(pixel[1]>pixel[0]+50,'pixel must come from later green shop, not red bench')
    result=dict(seed=80300396,synthetic_source_pixels=True,source_images_not_user_images=True,
                source_sample_body_unmodified=True,initialization_bypassed_for_controlled_image_fixture=True,
                frame_size=list(im.size),visible=vis.tolist(),boxes_pixels=bounds.tolist(),
                both_box_contain_probe_pixel=True,pixel_xy=list(xy),pixel_rgb=list(pixel),
                expected_layer='later_pasted_shop',observed_layer='later_pasted_shop',
                bench_occluded_fraction_geometric=overlap(*bounds)/np.prod(bounds[0,2:]-bounds[0,:2]),
                assert_pixel_layer_and_unchanged_label=True)
    return result


def main():
    import argparse, platform
    global SOURCE
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,default=SOURCE,help='Frozen renderer source; exact Git blob is mandatory')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();SOURCE=args.source
    try:
        report=geometry_audit()
        report['pixel_reproduction']=pixel_audit()
        report['environment']={'python':platform.python_version(),'numpy':np.__version__}
        report['scope']='Frozen sampling geometry plus one controlled synthetic RGB rendering; no neural inference or game labels validated'
        text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
        if args.output:
            with args.output.open('x',encoding='utf-8') as f:f.write(text)
        else:print(text,end='')
    except Exception as e:ap.exit(2,'L3_RENDER_AUDIT_ERROR='+str(e)+'\n')
if __name__=='__main__':main()
