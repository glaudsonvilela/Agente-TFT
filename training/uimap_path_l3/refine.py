"""Lazy strip luma: preserves L2 edge proposals, does not promote them to panel borders.

A coarse envelope need not have a visible edge. Therefore these adjustments are
retained only as diagnostics, never silently applied to a reader map.
"""
import time
import numpy as np
from . import legacy
from uimap_lite_l2.common import require,decisions


def luma(rgb):
    # Same order/dtypes as L2 for output parity; operate on strips, not a full frame.
    return rgb[...,0].astype(np.float32)*.299+rgb[...,1]*.587+rgb[...,2]*.114


def edge(rgb,coordinate,lo,hi,vertical,config):
    n=rgb.shape[1] if vertical else rgb.shape[0]
    c=int(round(coordinate));radius=config['radius_original_px']
    positions=np.arange(max(2,c-radius),min(n-3,c+radius)+1)
    lo,hi=int(np.ceil(lo)),int(np.floor(hi))
    if len(positions)<5 or hi-lo<8:return None,{'reason':'insufficient_search_region'},0
    if vertical:
        plus=rgb[lo:hi,positions+2];minus=rgb[lo:hi,positions-2]
    else:
        plus=rgb[positions+2,lo:hi].transpose(1,0,2);minus=rgb[positions-2,lo:hi].transpose(1,0,2)
    band=abs(luma(plus)-luma(minus));mean=np.minimum(band,64).mean(0);support=(band>=10).mean(0)
    best=int(np.argmax(mean));idx=positions[best];other=mean[abs(positions-idx)>3]
    gap=float(mean[best]-(other.max() if len(other) else mean[best]))
    ok=(0<best<len(positions)-1 and mean[best]>=config['minimum_edge_mean'] and
        support[best]>=config['minimum_edge_support'] and gap>=config['minimum_peak_gap'])
    info=dict(position=int(idx),mean=float(mean[best]),support=float(support[best]),peak_gap=gap,
              reason='supported' if ok else 'weak_ambiguous_or_boundary_peak')
    return float(idx) if ok else None,info,2*plus.shape[0]*plus.shape[1]


def refine_diagnostic(rgb,raw,plan):
    start=time.perf_counter_ns();a=np.asarray(rgb)
    require(a.dtype==np.uint8 and a.shape==(1080,1920,3),'original RGB refinement contract')
    rows=decisions(raw,plan['evaluation_policy']);result=np.asarray(raw).copy();traces=[];visited=0
    for i,row in enumerate(rows):
        if not row['accepted_as_coarse']:
            traces.append(dict(panel=row['panel'],applied=False,reason='coarse_gate_failed'));continue
        l,t,r,b=np.asarray(row['corners_normalized'])*[1920,1080,1920,1080];mx=(r-l)*.1;my=(b-t)*.1
        values=[edge(a,l,t+my,b-my,True,plan['refinement']),edge(a,t,l+mx,r-mx,False,plan['refinement']),
                edge(a,r,t+my,b-my,True,plan['refinement']),edge(a,b,l+mx,r-mx,False,plan['refinement'])]
        visited+=sum(v[2] for v in values);candidate=[v[0] for v in values]
        applied=False;reason='not_all_four_edges_supported'
        if all(v is not None for v in candidate):
            nl,nt,nr,nb=candidate
            relative=max(abs((nr-nl)/(r-l)-1),abs((nb-nt)/(b-t)-1))
            temp=result.copy();temp[i,:4]=np.asarray(candidate)/[1920,1080,1920,1080]
            if relative<=plan['refinement']['maximum_relative_size_change'] and decisions(temp,plan['evaluation_policy'])[i]['geometry_valid']:
                result=temp;applied=True;reason='four_local_edges_supported_not_semantic_validation'
            else:reason='geometry_or_size_change_rejected'
        traces.append(dict(panel=row['panel'],applied=applied,reason=reason,
                     original_corners=list(map(float,[l,t,r,b])),edges=[v[1] for v in values]))
    return result,traces,dict(ms=(time.perf_counter_ns()-start)/1e6,luma_samples=visited,
              full_frame_luma_allocated=False,refinement_used_by_readers=False)
