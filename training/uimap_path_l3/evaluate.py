"""Keep scalar legacy metrics, add per-panel worst-corner tails and per-mode gates."""
import numpy as np
from . import legacy
from uimap_lite_l2.evaluate import metrics as legacy_metrics
from uimap_lite_l2.common import PANELS,decisions,quantile


def metrics(predicted,target,visible,policy):
    p=np.asarray(predicted);t=np.asarray(target);v=np.asarray(visible)
    result=legacy_metrics(p,t,v,policy)
    error=abs(p[:,:,:4]-t)*[1920,1080,1920,1080]
    d=[decisions(x,policy) for x in p]
    for i,n in enumerate(PANELS):
        mask=v[:,i]==1;worst=error[mask,i].max(-1)
        accepted=np.array([x[i]['accepted_as_coarse'] for x in d])
        ae=error[mask & accepted,i].max(-1)
        result[n].update(worst_corner_per_panel_p95_px=quantile(worst,.95),
            accepted_worst_corner_p95_px=quantile(ae,.95),
            all_corners_within_px={str(k):int((worst<=k).sum()) for k in (1,2,4,8,20)},
            natural_accuracy=None,production_map_authorized=False)
    return result


def grouped(predicted,target,visible,modes,policy):
    result={'all':metrics(predicted,target,visible,policy)}
    for mode in sorted(set(modes)):
        ix=np.array([x==mode for x in modes])
        result[mode]=metrics(np.asarray(predicted)[ix],np.asarray(target)[ix],np.asarray(visible)[ix],policy)
    return result


def failures(groups):
    out=[]
    for group,panels in groups.items():
        for name,m in panels.items():
            if m['accepted_hidden']>0:out.append(dict(group=group,panel=name,reason='hidden_accepted',value=m['accepted_hidden']))
            if m['visible_examples']:
                if m['worst_corner_per_panel_p95_px']>40:
                    out.append(dict(group=group,panel=name,reason='worst_corner_tail',value=m['worst_corner_per_panel_p95_px']))
                if m['accepted_visible_fraction']<.5:out.append(dict(group=group,panel=name,reason='coverage_below_half'))
    return out
