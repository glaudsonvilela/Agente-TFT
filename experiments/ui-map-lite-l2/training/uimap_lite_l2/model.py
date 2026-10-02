"""Small fully convolutional heatmaps. No flatten/dense coordinate regressor."""
from __future__ import annotations
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from .common import require


class Conv(nn.Sequential):
    def __init__(self,ci,co,k=3,s=1,p=1):
        super().__init__(nn.Conv2d(ci,co,k,s,p,bias=False),nn.BatchNorm2d(co),nn.ReLU())


class Sep(nn.Sequential):
    def __init__(self,ci,co,s=1,d=1):
        super().__init__(nn.Conv2d(ci,ci,3,s,d,groups=ci,dilation=d,bias=False),
                         nn.BatchNorm2d(ci),nn.ReLU(),Conv(ci,co,1,1,0))


class UIMapSpatial(nn.Module):
    """Four 80x48 maps: TL/BR of bench then shop. Endpoints are not sorted/clipped."""
    def __init__(self):
        super().__init__()
        self.s2=Conv(3,12,3,2,1)
        self.s4=Sep(12,24,2)
        self.s8=nn.Sequential(Sep(24,48,2),Sep(48,48,d=2))
        self.s16=nn.Sequential(Sep(48,80,2),Sep(80,80,d=2))
        self.u8=Conv(128,48,1,1,0)
        self.u4=nn.Sequential(Conv(72,32,1,1,0),Sep(32,32))
        self.maps=nn.Conv2d(32,4,1)
        self.visibility=nn.Linear(160,2)
        y,x=torch.meshgrid((torch.arange(48)+.5)/48,(torch.arange(80)+.5)/80,indexing='ij')
        self.register_buffer('grid_x',x.reshape(1,1,-1))
        self.register_buffer('grid_y',y.reshape(1,1,-1))

    def components(self,image):
        s4=self.s4(self.s2(image));s8=self.s8(s4);s16=self.s16(s8)
        u8=self.u8(torch.cat((s8,F.interpolate(s16,size=(24,40),mode='bilinear',align_corners=False)),1))
        features=self.u4(torch.cat((s4,F.interpolate(u8,size=(48,80),mode='bilinear',align_corners=False)),1))
        maps=self.maps(features)
        vis=self.visibility(torch.cat((s16.mean((2,3)),s16.amax((2,3))),1))
        prob=maps.flatten(2).softmax(-1)
        xy=torch.stack(((prob*self.grid_x).sum(-1),(prob*self.grid_y).sum(-1)),dim=-1)
        panels=torch.cat((xy.reshape(-1,2,4),vis.unsqueeze(-1)),dim=-1)
        return panels,maps

    def forward(self,image):
        return self.components(image)[0]


def loss_function(panels,maps,target,visible):
    # Soft spatial targets are known transformed seed endpoints, NOT inferred text labels.
    n=maps.shape[0]
    xy=target.reshape(n,4,2)
    x=(torch.arange(80,device=maps.device)+.5)/80
    y=(torch.arange(48,device=maps.device)+.5)/48
    distances=((x[None,None,None,:]-xy[:,:,0,None,None])*80)**2+((y[None,None,:,None]-xy[:,:,1,None,None])*48)**2
    truth=(-distances/(2*.8**2)).flatten(2).softmax(-1)
    mask=visible.repeat_interleave(2,1)
    ce=-(truth*maps.flatten(2).log_softmax(-1)).sum(-1)
    heat=(ce*mask).sum()/mask.sum().clamp(min=1)
    delta=F.smooth_l1_loss(panels[:,:,:4],target,reduction='none',beta=.01).mean(-1)
    coord=(delta*visible).sum()/visible.sum().clamp(min=1)
    vis=F.binary_cross_entropy_with_logits(panels[:,:,4],visible)
    return heat+12*coord+vis


def save_weights(model,path):
    with path.open('xb') as f:
        np.savez(f,**{k:v.detach().cpu().numpy() for k,v in model.state_dict().items()})


def load_weights(path):
    import zipfile
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<8*1024**2,'weights invalid')
    with zipfile.ZipFile(path) as z:
        require(sum(i.file_size for i in z.infolist())<8*1024**2,'weight archive budget')
    model=UIMapSpatial();state={};reference=model.state_dict()
    with np.load(path,allow_pickle=False) as a:
        require(set(a.files)==set(reference),'weights schema')
        for k,v in reference.items():
            x=a[k];require(x.shape==tuple(v.shape) and x.dtype==v.numpy().dtype and np.isfinite(x).all(),'bad weights: '+k)
            state[k]=torch.from_numpy(x.copy())
    model.load_state_dict(state,strict=True)
    return model.eval()
