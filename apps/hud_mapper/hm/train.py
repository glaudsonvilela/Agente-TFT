"""Bounded offline candidate training on NATURAL samples plus explicit weak supervision.

Inference executable imports this module ONLY for --train, after collection stops.
No neural prediction is promoted to a target, and no candidate is activated.
"""
from __future__ import annotations
from pathlib import Path
import copy, json, time, hashlib
import numpy as np
from PIL import Image,ImageDraw
from .core import load_json, dump, sha, valid_box, Observer, neural_regions
from .seeds import verify_session


def read_examples(folders, allow_weak):
    examples=[];identity=set();receipts=[]
    if not 1<=len(folders)<=32:raise ValueError('Selecione de 1 a 32 sessões')
    for folder in folders:
        root,m,seal=verify_session(folder)
        labels=load_json(root/'supervision/weak-seeds.json',32*1024**2)
        if not allow_weak:raise ValueError('Treino com supervisão fraca exige --allow-weak explícito')
        if labels.get('source_seal_sha256')!=seal:raise ValueError('Supervisão pertence a outra versão da sessão')
        rows={r['sample_id']:r for r in m['samples']}
        for a in labels['records']:
            if a.get('neural_used_as_label') is not False or a.get('supervision')!='profile_template_weak':
                raise ValueError('Origem de supervisão não aceita')
            r=rows[a['sample_id']]
            if a['image_sha256']!=r['image_sha256']:raise ValueError('Rótulo não corresponde à imagem')
            if r['image_sha256'] in identity:continue
            identity.add(r['image_sha256']);p=root/r['image']
            if p.is_symlink() or not p.resolve().is_relative_to(root) or sha(p)!=r['image_sha256']:raise ValueError('Imagem alterada')
            targets=np.zeros((2,4),np.float32);known=np.zeros(2,np.float32)
            for i,name in enumerate(('bench','shop')):
                if name in a['targets']:
                    target=a['targets'][name]
                    if target.get('visible') is not True or not valid_box(target['box'],1920,1080):raise ValueError('Semente inválida')
                    targets[i]=np.asarray(target['box'])/[1920,1080,1920,1080];known[i]=1
            examples.append(dict(path=p,targets=targets,known=known,group=m['source']['sha256'],
                                 timestamp=r['source_ms'],hash=r['image_sha256']))
        receipts.append(dict(session_seal=seal,supervision_sha256=sha(root/'supervision/weak-seeds.json')))
    if len(examples)<24 or any(sum(x['known'][i] for x in examples)<12 for i in range(2)):
        raise ValueError('Faltam sementes: pelo menos 24 imagens distintas e 12 por painel. Colete com referência B1 e loja localizada; desconhecido não vira rótulo.')
    return examples,receipts

def partition(examples):
    groups=sorted({x['group'] for x in examples})
    if len(groups)>=3:
        # Entire video hashes stay disjoint. Re-recording the same file creates no new split.
        ng=len(groups);a=max(1,int(ng*.6));b=max(a+1,int(ng*.8));b=min(ng-1,b)
        sets=[set(groups[:a]),set(groups[a:b]),set(groups[b:])]
        parts=[[x for x in examples if x['group'] in s] for s in sets]
        kind='video_hash_disjoint_but_weak_labels'
    else:
        ordered=sorted(examples,key=lambda x:(x['group'],x['timestamp']))
        n=len(ordered);a=int(n*.6);b=int(n*.8)
        # Discard a boundary example on each side; still SAME-VIDEO development, not independent accuracy.
        parts=[ordered[:a-1],ordered[a+1:b-1],ordered[b+1:]]
        kind='same_video_chronological_development_not_independent'
    if any(len(x)<2 for x in parts):raise ValueError('Partição insuficiente')
    return parts,kind

def accepted_masks(predicted):
    """Use exactly the runtime visibility AND size/bounds rules in evaluation."""
    return np.asarray([[r['status']=='coarse_candidate' for r in neural_regions(a[None],1920,1080)]
                       for a in np.asarray(predicted)],dtype=bool)

def cache_selection(part, count):
    """Spread a bounded cache across the full partition, not its first examples."""
    if not part or count < 1:
        raise ValueError('Empty cache partition')
    return [part[int(i)] for i in np.linspace(0,len(part)-1,count).round().astype(int)]

def render(example, seed):
    """One native whole-frame affine transform. Covers affect ALL panels and corners."""
    rng=np.random.default_rng(seed)
    with Image.open(example['path']) as im:
        im=im.convert('RGB')
        if im.size!=(1920,1080):raise ValueError('Treino atual requer pixels 1920x1080')
        sx=float(rng.uniform(.84,1.03));sy=float(rng.uniform(.86,1.02))
        tx=float(rng.uniform(-70,90));ty=float(rng.uniform(-85,10))
        image=im.transform((1920,1080),Image.Transform.AFFINE,(1/sx,0,-tx/sx,0,1/sy,-ty/sy),Image.Resampling.BILINEAR)
    boxes=example['targets'].copy()*[1920,1080,1920,1080]
    boxes=boxes*[sx,sy,sx,sy]+[tx,ty,tx,ty]
    visible=np.asarray([valid_box(b,1920,1080) for b in boxes],np.float32)*example['known']
    covers=[]
    if rng.random()<.25:
        panel=int(rng.integers(2));b=boxes[panel]
        if example['known'][panel] and valid_box(b,1920,1080):
            # Entire known panel covered; final labels recomputed for BOTH targets below.
            cover=(int(np.floor(b[0])),int(np.floor(b[1])),int(np.ceil(b[2])),int(np.ceil(b[3])))
            ImageDraw.Draw(image).rectangle(cover,fill=tuple(int(x) for x in rng.integers(0,130,3)));covers.append(cover)
    corner_visible=np.ones((2,4),np.float32)
    for i,b in enumerate(boxes):
        for j,(x,y) in enumerate(((b[0],b[1]),(b[2],b[1]),(b[0],b[3]),(b[2],b[3]))):
            if not(0<=x<=1920 and 0<=y<=1080) or any(c[0]-1<=x<=c[2]+1 and c[1]-1<=y<=c[3]+1 for c in covers):
                corner_visible[i,j]=0
        if not corner_visible[i].all():visible[i]=0
    tensor=np.asarray(image.resize((320,192),Image.Resampling.BILINEAR),np.float32).transpose(2,0,1).copy()/255
    return tensor, (boxes/[1920,1080,1920,1080]).astype(np.float32), visible, example['known'].copy(), corner_visible

def target_loss(p,m,t,v,k):
    import torch
    import torch.nn.functional as F
    xy=t.reshape(-1,4,2);px=(xy[:,:,0]*79).clamp(0,79);py=(xy[:,:,1]*47).clamp(0,47)
    ix=px.floor().long().clamp(max=78);iy=py.floor().long().clamp(max=46);dx=px-ix;dy=py-iy
    truth=torch.zeros((*ix.shape,3840),device=t.device,dtype=t.dtype)
    for ox,oy,w in [(0,0,(1-dx)*(1-dy)),(1,0,dx*(1-dy)),(0,1,(1-dx)*dy),(1,1,dx*dy)]:
        truth.scatter_add_(2,((iy+oy)*80+ix+ox).unsqueeze(-1),w.unsqueeze(-1))
    mask=(v*k).repeat_interleave(2,1)
    heat=(-(truth*m.flatten(2).log_softmax(-1)).sum(-1)*mask).sum()/mask.sum().clamp(min=1)
    diff=F.smooth_l1_loss(p[:,:,:4],t,reduction='none',beta=.005)
    coord=((diff.mean(-1)+.3*diff.amax(-1))*v*k).sum()/(v*k).sum().clamp(min=1)
    vis=(F.binary_cross_entropy_with_logits(p[:,:,4],v,reduction='none')*k).sum()/k.sum().clamp(min=1)
    return heat+12*coord+2*vis

def train(folders,metadata,output,steps=400,allow_weak=False):
    if not 1<=int(steps)<=1400:raise ValueError('Treino limitado a 1400 passos')
    import torch
    from uimap_lite_l2.model import load_weights,save_weights
    from uimap_lite_l2.export import export_checked
    examples,receipts=read_examples(folders,allow_weak);parts,split_kind=partition(examples)
    observer=Observer(metadata);npz=Path(metadata).with_name('weights.npz')
    if not npz.is_file():raise ValueError('weights.npz da mesma execução é necessário para treinar')
    parent_hash=sha(npz);torch.set_num_threads(2);torch.manual_seed(9201);torch.use_deterministic_algorithms(True)
    parent=load_weights(npz);model=copy.deepcopy(parent)
    # Verify the NPZ is the SAME network as the selected ONNX before changing grids.
    from types import SimpleNamespace
    with Image.open(examples[0]['path']) as im:im=im.convert('RGB');rgb=im.tobytes()
    probe=SimpleNamespace(id=0,width=1920,height=1080,rgb=rgb)
    old=observer.observe(probe)['raw']
    x=np.asarray(im.resize((320,192),Image.Resampling.BILINEAR),np.float32).transpose(2,0,1).copy()[None]/255
    with torch.inference_mode():check=parent(torch.from_numpy(x)).numpy()
    if np.max(abs(check-np.asarray(old)))>1e-4:raise ValueError('NPZ e ONNX não pertencem ao mesmo modelo')
    out=Path(output)
    if out.exists() or out.is_symlink():raise ValueError('Destino de candidata já existe')
    out.mkdir(parents=True,exist_ok=False)
    dump(out/'provenance.json',dict(policy='hm1_natural_weak_training_v1',parent_npz_sha256=parent_hash,
       parent_onnx_sha256=observer.hash,sessions=receipts,split=split_kind,
       labels='explicit_profile_template_weak',neural_predictions_used_as_labels=False,
       activation_allowed=False,source_counts=[len(p) for p in parts]))
    y,gx=torch.meshgrid(torch.linspace(0,1,48),torch.linspace(0,1,80),indexing='ij')
    model.grid_x.copy_(gx.reshape(1,1,-1));model.grid_y.copy_(y.reshape(1,1,-1))
    save_weights(model,out/'initial-weights.npz')
    start=time.perf_counter();caches=[]
    for j,(part,count) in enumerate(zip(parts,(96,24,32))):
        rows=[render(example,930000+j*10000+i) for i,example in enumerate(cache_selection(part,count))]
        caches.append(tuple(np.stack([r[k] for r in rows]) for k in range(4)))
    opt=torch.optim.Adam(model.parameters(),lr=.0005);rng=np.random.default_rng(9201)
    def loss_for(cache):
        model.eval();values=[]
        with torch.inference_mode():
            for i in range(0,len(cache[0]),8):
                args=[torch.from_numpy(z[i:i+8]) for z in cache];p,m=model.components(args[0]);values.append(float(target_loss(p,m,*args[1:])))
        return float(np.mean(values))
    best=loss_for(caches[1]);best_step=0;state=copy.deepcopy(model.state_dict());history=[]
    with (out/'training.jsonl').open('x',encoding='utf-8') as log:
        for step in range(1,steps+1):
            ids=rng.integers(0,len(caches[0][0]),8);args=[torch.from_numpy(z[ids]) for z in caches[0]]
            model.train();opt.zero_grad(set_to_none=True);p,m=model.components(args[0]);loss=target_loss(p,m,*args[1:])
            if not torch.isfinite(loss):raise ValueError('Loss não finita')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step()
            if step%50==0 or step==steps:
                value=loss_for(caches[1]);r=dict(step=step,loss=float(loss.detach()),validation_loss=value)
                history.append(r);log.write(json.dumps(r)+'\n');log.flush();print('HM_TRAIN='+json.dumps(r),flush=True)
                if value<best:best=value;best_step=step;state=copy.deepcopy(model.state_dict())
    save_weights(model,out/'last-weights.npz')
    model.load_state_dict(state);model.eval();save_weights(model,out/'weights.npz')
    def evaluate(net):
        cache=caches[2]
        with torch.inference_mode():a=net(torch.from_numpy(cache[0])).numpy()
        result={};accepted_all=accepted_masks(a)
        for i,name in enumerate(('bench','shop')):
            known=cache[3][:,i]>0;visible=cache[2][:,i]>0
            error=abs(a[:,i,:4]-cache[1][:,i])*[1920,1080,1920,1080]
            accepted=accepted_all[:,i]
            mask=known&visible
            result[name]=dict(weak_reference_mae_px=float(error[mask].mean()) if mask.any() else None,
                weak_reference_worst_corner_p95_px=float(np.quantile(error[mask].max(-1),.95)) if mask.any() else None,
                hidden_accepted=int((accepted&known&~visible).sum()),visible=int(mask.sum()),
                natural_accuracy=None,labels_are_weak=True)
        return result
    results=dict(parent=evaluate(parent),candidate=evaluate(model))
    exported=export_checked(model,caches[1][0][:16],out,True)
    with np.load(out/'initial-weights.npz',allow_pickle=False) as initial:
        delta=sum(float(abs(v.detach().numpy()-initial[k]).sum()) for k,v in model.named_parameters())
    report=dict(policy='hm1_after_session_training',parameters=sum(p.numel() for p in model.parameters()),
        selected_step=best_step,training_steps=steps,optimization_steps_executed=steps,model_trained=delta>0,parameter_l1_delta=delta,
        history=history,paired=results,export=exported,split=split_kind,
        training_seconds=time.perf_counter()-start,activation_allowed=False,profile_promoted=False,
        readers_modified=False,natural_accuracy=None,supervision='explicit_weak_templates_plus_known_transforms')
    if sha(npz)!=parent_hash:raise ValueError('Modelo pai alterado durante o treino')
    observer.verify()
    for row in examples:
        if sha(row['path'])!=row['hash']:raise ValueError('Imagem mudou durante treino')
    dump(out/'report.json',report)
    dump(out/'COMPLETE.json',{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()})
    print('HM_TRAIN_REPORT='+str(out/'report.json'),flush=True)
    return report
