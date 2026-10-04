"""CPU training of a small item-art classifier; never invent replay labels.

Official artwork supplies class labels. Replay crops are a separate, explicitly
reviewed evaluation set. Identical artwork with several API IDs stays ambiguous.
This is perception training, not combat simulation or a strategic value network.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import resource


def write(path, value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def run(project: Path, icons: Path, output: Path, evaluation: Path, steps=1200):
    import numpy as np
    from PIL import Image
    import torch
    from torch import nn
    from torch.nn import functional as F
    from training.board_hub_item_candidates import load_reference, select_entries
    if output.exists() or not 100<=steps<=2000:
        raise ValueError('New output and bounded step count required')
    output.mkdir(parents=True)
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(20261004)
    selection=json.loads((project/'configs/catalog/active-visual-reference-v1.json').read_text())
    manifest,entries=load_reference(project/selection['reference'])
    groups={}
    for entry in select_entries(entries,selection['set_key'],selection['match_scope']):
        raw=(icons/entry['icon']).read_bytes()
        with Image.open(icons/entry['icon']) as im:
            pixels=np.asarray(im.convert('RGB').resize((32,32),Image.Resampling.BILINEAR))
        key=hashlib.sha256(pixels.tobytes()).hexdigest()
        group=groups.setdefault(key,dict(pixels=pixels,ids=[],names=[],source_sha256=[]))
        group['ids'].append(entry['id']);group['names'].append(entry['name'])
        group['source_sha256'].append(hashlib.sha256(raw).hexdigest())
    classes=list(groups.values())
    base=torch.from_numpy(np.stack([g['pixels'] for g in classes]).transpose(0,3,1,2).copy()).float()/255
    model=nn.Sequential(nn.Conv2d(3,16,3,padding=1),nn.ReLU(),nn.MaxPool2d(2),
        nn.Conv2d(16,32,3,padding=1),nn.ReLU(),nn.MaxPool2d(2),
        nn.Conv2d(32,32,3,padding=1),nn.ReLU(),nn.AdaptiveAvgPool2d((4,4)),
        nn.Flatten(),nn.Linear(512,len(classes)))
    initial=[p.detach().clone() for p in model.parameters()]
    optimizer=torch.optim.AdamW(model.parameters(),lr=.002,weight_decay=.0001)
    def augmented(indices, generator):
        source=base[indices];n=len(indices)
        theta=torch.zeros(n,2,3)
        # Cropping/translation represents icon interiors, not a full screenshot.
        theta[:,0,0]=torch.rand(n,generator=generator)*.35+.65
        theta[:,1,1]=torch.rand(n,generator=generator)*.35+.65
        theta[:,:,2]=(torch.rand(n,2,generator=generator)-.5)*.20
        pixels=F.grid_sample(source,F.affine_grid(theta,source.shape,align_corners=False),
                             align_corners=False,padding_mode='border')
        brightness=torch.rand(n,1,1,1,generator=generator)*.5+.75
        noise=torch.randn(pixels.shape,generator=generator)*.015
        return (pixels*brightness+noise).clamp(0,1)
    generator=torch.Generator().manual_seed(41004)
    started=time.monotonic();losses=[]
    common=dict(kind='item_icon_classifier',scope='item_art_only',classes=len(classes),
        optimizer_steps_total=steps,source_artworks=len(classes),
        replay_labels_used_for_training=0,simulation_paths=0,combat_learning=False)
    with (output/'training.jsonl').open('x') as log:
        for step in range(steps):
            labels=torch.randint(len(classes),(64,),generator=generator)
            logits=model(augmented(labels,generator));loss=F.cross_entropy(logits,labels)
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
            losses.append(float(loss.detach()))
            if step%25==0 or step==steps-1:
                progress=dict(**common,status='training',optimizer_steps=step+1,
                    loss=losses[-1],elapsed_seconds=time.monotonic()-started,
                    peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                    process_cpu_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime+
                                        resource.getrusage(resource.RUSAGE_SELF).ru_stime)
                write(output/'progress.json',progress)
                log.write(json.dumps(progress)+'\n');log.flush();print(json.dumps(progress),flush=True)
    model.eval()
    with torch.inference_mode():
        vg=torch.Generator().manual_seed(47004)
        labels=torch.arange(len(classes)).repeat(4)
        predictions=torch.cat([model(augmented(batch,vg)).argmax(1) for batch in labels.split(64)])
        synthetic_accuracy=float((predictions==labels).float().mean())
    # Evaluation labels are never read until training has finished.
    heldout=json.loads(evaluation.read_text())
    records=[]
    with torch.inference_mode():
        for row in heldout['samples']:
            path=evaluation.parent/row['image']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Evaluation crop changed')
            with Image.open(path) as image:
                array=np.asarray(image.convert('RGB').resize((32,32),Image.Resampling.BILINEAR)).copy()
            logits=model(torch.from_numpy(array.transpose(2,0,1)[None]).float()/255)[0]
            probabilities=logits.softmax(0);indices=probabilities.topk(3).indices.tolist()
            records.append(dict(**row,correct=row['item_id'] in classes[indices[0]]['ids'],
                candidates=[dict(ids=classes[i]['ids'],score=float(probabilities[i])) for i in indices]))
    torch.onnx.export(model,torch.zeros(1,3,32,32),str(output/'item-icons.onnx'),
        input_names=['icons'],output_names=['logits'],dynamic_axes={'icons':{0:'batch'},'logits':{0:'batch'}},opset_version=17)
    model_hash=hashlib.sha256((output/'item-icons.onnx').read_bytes()).hexdigest()
    metadata=dict(schema_version=1,kind='item_icon_classifier',input_size=32,set_key=selection['set_key'],
        reference_sha256=manifest['reference_sha256'],model_sha256=model_hash,
        classes=[{k:v for k,v in g.items() if k!='pixels'} for g in classes],
        mode='diagnostic_candidates',game_state_write_allowed=False)
    write(output/'metadata.json',metadata)
    changed=sum(not torch.equal(old,new) for old,new in zip(initial,model.parameters()))
    report=dict(**common,status='trained_evaluated',optimizer_steps=steps,changed_parameter_tensors=changed,
        parameter_count=sum(p.numel() for p in model.parameters()),training_seconds=time.monotonic()-started,
        first_50_loss_mean=sum(losses[:50])/50,last_50_loss_mean=sum(losses[-50:])/50,
        synthetic_augmented_top1=synthetic_accuracy,replay_evaluation=records,
        replay_correct=sum(r['correct'] for r in records),replay_total=len(records),
        replay_distinct_items=len({r['item_id'] for r in records}),
        independent_match_validation=False,strategic_learning=False,runtime_promoted=False)
    write(output/'report.json',report)
    write(output/'COMPLETE.json',{name:hashlib.sha256((output/name).read_bytes()).hexdigest()
        for name in ['item-icons.onnx','metadata.json','report.json','training.jsonl']})
    write(output/'progress.json',dict(**common,status='trained_evaluated',optimizer_steps=steps,
                                    elapsed_seconds=time.monotonic()-started))
    print(json.dumps({k:v for k,v in report.items() if k!='replay_evaluation'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['project','icons','output','evaluation']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--steps',type=int,default=1200)
    args=parser.parse_args()
    run(args.project,args.icons,args.output,args.evaluation,args.steps)
