"""Create explicit WEAK annotations from frozen visual-template evidence, never neural outputs."""
from pathlib import Path
import json
from collections import Counter
from .core import load_json, sha, dump, ENVELOPES, xyxy

def verify_session(root):
    root=Path(root).resolve(strict=True)
    seal=load_json(root/'COMPLETE.json',16*1024**2)
    for name,digest in seal.items():
        p=root/name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or sha(p)!=digest:
            raise ValueError('Sessão alterada: '+name)
    manifest=load_json(root/'training-manifest.json',32*1024**2)
    if manifest.get('policy')!='hm1_natural_mapping_dataset':raise ValueError('Dataset incompatível')
    return root,manifest,sha(root/'COMPLETE.json')

def prepare(root):
    root,m,receipt=verify_session(root)
    samples={r['frame_id']:r for r in m['samples']}
    path=root/'roi-observations.jsonl';labels=[];counts=Counter()
    if path.is_file():
        if path.stat().st_size>128*1024**2:raise ValueError('Observações excedem orçamento')
        with path.open(encoding='utf-8') as f:
            for line in f:
                x=json.loads(line);row=samples.get(x['frame_id'])
                if not row or (row['width'],row['height'])!=(1920,1080):continue
                if abs(row['source_ms']-x['source_ms'])>.001:raise ValueError('Timestamp não corresponde ao PNG')
                answer=x['answer'];targets={}
                if (answer.get('shop') or {}).get('panel_status')=='located':
                    targets['shop']=dict(box=xyxy(ENVELOPES['shop']),visible=True,
                        basis='frozen_shop_visual_anchors',not_independent_truth=True)
                b=answer.get('board') or {}
                if b.get('projection_status')=='reference_arena_match' and not b.get('error'):
                    targets['bench']=dict(box=xyxy(ENVELOPES['bench']),visible=True,
                        basis='B1_arena_reference_weak_not_bank_visibility_proof',not_independent_truth=True)
                if not targets:continue
                counts.update(targets.keys())
                labels.append(dict(sample_id=row['sample_id'],image_sha256=row['image_sha256'],
                    targets=targets,supervision='profile_template_weak',neural_used_as_label=False,
                    corners_independently_observed=False))
    data=dict(schema_version=1,policy='hm1_explicit_weak_seeds_v1',source_seal_sha256=receipt,
              records=labels,counts=dict(counts),activation_allowed=False,
              warning='Reference anchors corroborate a registered layout; they do not prove every corner visible or correct.')
    folder=root/'supervision';folder.mkdir(exist_ok=True);out=folder/'weak-seeds.json'
    if out.exists():
        if load_json(out,32*1024**2)!=data:raise ValueError('Supervisão existente difere; não sobrescrever')
    else:dump(out,data)
    return dict(path=str(out),counts=dict(counts),records=len(labels),ground_truth=False,
                ready_for_experimental_training=all(counts[p]>=12 for p in ('bench','shop')),
                note='Treino fraco exige consentimento explícito; não ativa o modelo.')
