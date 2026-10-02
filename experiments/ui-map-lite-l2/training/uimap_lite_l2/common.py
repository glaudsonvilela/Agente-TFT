"""Shared evaluation/runtime decision. Coordinates, visibility and deployment are distinct."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import numpy as np

WIDTH, HEIGHT = 320, 192
PANELS = ('bench', 'shop')
POLICY = 'uimap-lite-l2-spatial-v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path, limit=32*1024**2):
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and p.stat().st_size <= limit, 'invalid JSON file: '+str(p))
    def unique(pairs):
        result = {}
        for k,v in pairs:
            require(k not in result, 'duplicate JSON key: '+k)
            result[k] = v
        return result
    def invalid(x):
        raise ValueError('nonfinite JSON: '+x)
    return json.loads(p.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def save(path, obj):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        f.write('\n'); f.flush()


def contained(root, name):
    p = Path(name)
    require(isinstance(name,str) and name and not p.is_absolute() and '..' not in p.parts,
            'unsafe relative path')
    r = Path(root).resolve(strict=True)
    result = (r/p).resolve(strict=True)
    require(result.is_relative_to(r) and result.is_file(), 'file outside root')
    return result


def rect_corners(rect, size=(1920,1080)):
    x,y,w,h = rect
    return np.asarray([x/size[0], y/size[1], (x+w)/size[0], (y+h)/size[1]],np.float32)


def l1_to_corners(raw):
    raw = np.asarray(raw)
    r = raw.copy()
    r[...,0:2] = raw[...,0:2] - raw[...,2:4]/2
    r[...,2:4] = raw[...,0:2] + raw[...,2:4]/2
    return r


def validate_policy(plan):
    require(plan['schema_version']==2 and plan['id']==POLICY, 'unsupported L2 plan')
    require(plan['input_size']==[WIDTH,HEIGHT] and plan['source_size']==[1920,1080], 'size changed')
    require(set(plan['panels'])==set(PANELS), 'panel schema')
    policy = plan['evaluation_policy']
    require(policy['visibility_logit_min']==2.1972245773362196 and
            policy['min_width_fraction']==.08 and policy['min_height_fraction']==.015,
            'decision thresholds differ from frozen L2 policy')
    require(type(plan['training_steps']) is int and 1<=plan['training_steps']<=2400, 'step budget')
    require(type(plan['batch_size']) is int and 1<=plan['batch_size']<=16, 'batch budget')
    require(plan['thread_count'] in (1,2), 'thread budget')
    r=plan['refinement']
    require(r=={'radius_original_px':12,'minimum_edge_mean':12.0,'minimum_edge_support':.35,
                'minimum_peak_gap':1.5,'maximum_relative_size_change':.08}, 'refinement policy changed')
    return plan


def decisions(raw, policy, size=(1920,1080)):
    a=np.asarray(raw,dtype=np.float32)
    require(a.shape==(2,5) and np.isfinite(a).all(), 'invalid panel output')
    result=[]
    for name,row in zip(PANELS,a):
        l,t,r,b,score=map(float,row)
        geometry=(0<=l<r<=1 and 0<=t<b<=1 and r-l>=policy['min_width_fraction']
                  and b-t>=policy['min_height_fraction'])
        visible=score>=policy['visibility_logit_min']
        accepted=bool(geometry and visible)
        result.append(dict(panel=name,state='coarse_candidate' if accepted else 'unknown',
            corners_normalized=[l,t,r,b],box_pixels=[l*size[0],t*size[1],(r-l)*size[0],(b-t)*size[1]],
            visibility_logit=score,visibility_above_threshold=bool(visible),geometry_valid=bool(geometry),
            accepted_as_coarse=accepted,score_calibrated=False,map_usable_by_readers=False,
            narrow_ocr_crop_safe=False,occupancy=None,unit_id=None))
    return result


def quantile(x,q):
    return float(np.quantile(x,q)) if len(x) else None
