"""Bounded edge refinement using only current RGB pixels and a coarse box.

No target coordinates, templates from the test image, OCR values or ground-truth
oracle enter this module. Edges are not guaranteed to be semantic panel borders.
Missing/ambiguous support keeps the unrefined proposal with an explicit reason.
"""
from __future__ import annotations
import time
import numpy as np
from .common import require,decisions


def _edge(gray,coordinate,lo,hi,vertical,config):
    n=gray.shape[1] if vertical else gray.shape[0]
    radius=config['radius_original_px'];c=int(round(coordinate))
    positions=np.arange(max(2,c-radius),min(n-3,c+radius)+1)
    lo,hi=int(np.ceil(lo)),int(np.floor(hi))
    if len(positions)<5 or hi-lo<8:return None,{'reason':'insufficient_search_region'}
    if vertical:
        band=abs(gray[lo:hi,positions+2]-gray[lo:hi,positions-2])
    else:
        band=abs(gray[positions+2,lo:hi]-gray[positions-2,lo:hi]).T
    mean=np.minimum(band,64).mean(0)
    support=(band>=10).mean(0)
    best=int(np.argmax(mean));idx=positions[best]
    alternatives=mean[abs(positions-idx)>3]
    gap=float(mean[best]-(alternatives.max() if len(alternatives) else mean[best]))
    stats=dict(position=int(idx),mean=float(mean[best]),support=float(support[best]),peak_gap=gap)
    valid=(0<best<len(positions)-1 and mean[best]>=config['minimum_edge_mean'] and
           support[best]>=config['minimum_edge_support'] and gap>=config['minimum_peak_gap'])
    stats['reason']='supported' if valid else 'weak_ambiguous_or_boundary_peak'
    return (float(idx) if valid else None),stats


def refine_panels(image,raw,plan):
    start=time.perf_counter_ns();a=np.asarray(image)
    require(a.ndim==3 and a.shape[2]==3 and a.dtype==np.uint8,'refinement expects RGB uint8')
    h,w=a.shape[:2]
    # Policy is expressed in original pixels. Do not silently reinterpret 12px on a thumbnail.
    require((w,h)==tuple(plan['source_size']),'refinement requires original source resolution')
    rows=decisions(raw,plan['evaluation_policy'],(w,h));result=np.asarray(raw).copy();traces=[]
    gray=(a[:,:,0].astype(np.float32)*.299+a[:,:,1]*.587+a[:,:,2]*.114)
    for i,row in enumerate(rows):
        if not row['accepted_as_coarse']:
            traces.append(dict(panel=row['panel'],applied=False,reason='coarse_gate_failed'));continue
        l,t,r,b=np.asarray(row['corners_normalized'])*[w,h,w,h];mx=(r-l)*.1;my=(b-t)*.1
        edges=[_edge(gray,l,t+my,b-my,True,plan['refinement']),
               _edge(gray,t,l+mx,r-mx,False,plan['refinement']),
               _edge(gray,r,t+my,b-my,True,plan['refinement']),
               _edge(gray,b,l+mx,r-mx,False,plan['refinement'])]
        candidate=[v for v,trace in edges];applied=False;reason='not_all_four_edges_supported'
        if all(v is not None for v in candidate):
            nl,nt,nr,nb=candidate
            rel=max(abs((nr-nl)/(r-l)-1),abs((nb-nt)/(b-t)-1))
            temp=result.copy();temp[i,:4]=np.asarray(candidate)/[w,h,w,h]
            if rel<=plan['refinement']['maximum_relative_size_change'] and decisions(temp,plan['evaluation_policy'])[i]['geometry_valid']:
                result=temp;applied=True;reason='four_local_edges_supported_not_semantic_validation'
            else:reason='geometry_or_size_change_rejected'
        traces.append(dict(panel=row['panel'],applied=applied,reason=reason,
                           original_corners=[float(v) for v in [l,t,r,b]],edges=[e for v,e in edges]))
    return result,traces,(time.perf_counter_ns()-start)/1e6
