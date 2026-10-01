"""Training-only small CNN. No downloads, text encoder, object vocabulary or pretrained model."""
from __future__ import annotations
import numpy as np
import torch
from torch import nn
from .core import LAYERS, require


class UIMapLite(nn.Module):
    def __init__(self):
        super().__init__()
        self.convs = nn.ModuleList(nn.Conv2d(a,b,k,stride=s,padding=k//2,groups=g)
                                   for a,b,k,s,g in LAYERS)
        self.norms = nn.ModuleList(nn.BatchNorm2d(b) for _,b,_,_,_ in LAYERS)
        self.pool = nn.AvgPool2d((3,4))
        self.fc = nn.Linear(64*4*5,96)
        self.head = nn.Linear(96,10)

    def forward(self, image):
        x = image
        for layer, norm in zip(self.convs,self.norms):
            x = torch.relu(norm(layer(x)))
        x = self.pool(x).flatten(1)
        x = torch.relu(self.fc(x))
        return torch.sigmoid(self.head(x))

    def export_arrays(self, path):
        require(not self.training,'export requires evaluation mode')
        arrays = {}
        for i,(conv,norm) in enumerate(zip(self.convs,self.norms)):
            factor=norm.weight.detach()/torch.sqrt(norm.running_var+norm.eps)
            arrays[f'convs.{i}.weight']=(conv.weight.detach()*factor[:,None,None,None]).numpy()
            arrays[f'convs.{i}.bias']=((conv.bias.detach()-norm.running_mean)*factor+norm.bias.detach()).numpy()
        for name in ('fc','head'):
            layer=getattr(self,name)
            arrays[name+'.weight']=layer.weight.detach().numpy()
            arrays[name+'.bias']=layer.bias.detach().numpy()
        with path.open('xb') as f:
            np.savez(f, **arrays)

    def load_arrays(self, path):
        with np.load(path,allow_pickle=False) as f:
            expected = {k:v for k,v in self.state_dict().items() if not k.startswith('norms.')}
            require(set(f.files)==set(expected), 'weights schema mismatch')
            state = {}
            for k, t in expected.items():
                x = f[k]
                require(x.dtype==np.float32 and x.shape==tuple(t.shape)
                        and np.isfinite(x).all(), 'invalid weight '+k)
                state[k] = torch.from_numpy(x.copy())
        current=self.state_dict();current.update(state)
        self.load_state_dict(current,strict=True)
        # Folded inference checkpoint is a warm start, not optimizer/BN-state resume.
        for norm in self.norms:
            norm.running_mean.zero_();norm.running_var.fill_(1.)
            with torch.no_grad():
                norm.weight.fill_((1+norm.eps)**.5);norm.bias.zero_()
