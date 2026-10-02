"""Same 27,726-parameter trunk, endpoint grid and unbiased bilinear spatial targets.

This is a NEW model contract: L2 weights remain L2. The L2 center grid cannot
represent screen edges. Clipping previous predictions is not this correction.
"""
import numpy as np
import torch
from torch.nn import functional as F
from . import legacy
from uimap_lite_l2.model import UIMapSpatial, save_weights
from uimap_lite_l2.common import require

MODEL_SCHEMA = 'l3_edge_nodes_bilinear_targets_v1'

class UIMapPath(UIMapSpatial):
    def __init__(self):
        super().__init__()
        y,x=torch.meshgrid(torch.linspace(0,1,48),torch.linspace(0,1,80),indexing='ij')
        self.grid_x.copy_(x.reshape(1,1,-1)); self.grid_y.copy_(y.reshape(1,1,-1))


def spatial_targets(target):
    """Four-node interpolation: expectation equals any in-range target, including borders."""
    xy=target.reshape(-1,4,2)
    px=(xy[:,:,0]*79).clamp(0,79); py=(xy[:,:,1]*47).clamp(0,47)
    ix=px.floor().long().clamp(max=78); iy=py.floor().long().clamp(max=46)
    dx=px-ix;dy=py-iy
    truth=torch.zeros((*ix.shape,48*80),device=target.device,dtype=target.dtype)
    for ox,oy,w in [(0,0,(1-dx)*(1-dy)),(1,0,dx*(1-dy)),(0,1,(1-dx)*dy),(1,1,dx*dy)]:
        truth.scatter_add_(2,((iy+oy)*80+ix+ox).unsqueeze(-1),w.unsqueeze(-1))
    return truth


def loss_function(panels,maps,target,visible):
    truth=spatial_targets(target); mask=visible.repeat_interleave(2,1)
    ce=-(truth*maps.flatten(2).log_softmax(-1)).sum(-1)
    heat=(ce*mask).sum()/mask.sum().clamp(min=1)
    diff=F.smooth_l1_loss(panels[:,:,:4],target,reduction='none',beta=.005)
    mean=(diff.mean(-1)*visible).sum()/visible.sum().clamp(min=1)
    worst=(diff.amax(-1)*visible).sum()/visible.sum().clamp(min=1)
    vis=F.binary_cross_entropy_with_logits(panels[:,:,4],visible)
    return heat+12*mean+4*worst+2*vis


def load_weights(path):
    import zipfile
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<8*1024**2,'invalid L3 weights')
    with zipfile.ZipFile(path) as z:
        require(sum(i.file_size for i in z.infolist())<8*1024**2,'weight byte budget')
    model=UIMapPath();reference=model.state_dict();state={}
    with np.load(path,allow_pickle=False) as data:
        require(set(data.files)==set(reference),'L3 weight schema')
        for k,v in reference.items():
            a=data[k];require(a.shape==tuple(v.shape) and a.dtype==v.numpy().dtype and np.isfinite(a).all(),'bad weight '+k)
            if k in ('grid_x','grid_y'):
                require(np.array_equal(a,v.numpy()),'L2 grid must not be loaded as L3')
            state[k]=torch.from_numpy(a.copy())
    model.load_state_dict(state);return model.eval()
