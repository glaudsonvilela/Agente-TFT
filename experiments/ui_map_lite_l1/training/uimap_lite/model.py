"""193k-class compact CNN. No text encoder, object vocabulary or pretrained download."""
from __future__ import annotations
import torch
from torch import nn


class Separable(nn.Sequential):
    def __init__(self, incoming: int, outgoing: int):
        super().__init__(nn.Conv2d(incoming, incoming, 3, 2, 1, groups=incoming),
                         nn.BatchNorm2d(incoming), nn.ReLU(), nn.Conv2d(incoming, outgoing, 1),
                         nn.BatchNorm2d(outgoing), nn.ReLU())


class UIMapLite(nn.Module):
    """Input NCHW RGB [0,1], 320x192. Output two [cx,cy,w,h,visibility_logit] rows."""
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 12, 3, 2, 1), nn.BatchNorm2d(12), nn.ReLU(),
            Separable(12, 24), Separable(24, 32),
            Separable(32, 48), Separable(48, 64))
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(64*6*10, 48),
                                  nn.ReLU(), nn.Linear(48, 10))

    def forward(self, image):
        value = self.head(self.features(image)).reshape(-1, 2, 5)
        return torch.cat((value[:, :, :4].sigmoid(), value[:, :, 4:]), dim=-1)


def loss_function(prediction, boxes, visible):
    # Coordinates are supervised only for fully visible synthetic panels.
    delta = torch.nn.functional.smooth_l1_loss(prediction[:, :, :4], boxes,
                                              reduction='none', beta=.02).mean(-1)
    regression = (delta * visible).sum() / visible.sum().clamp(min=1)
    visibility = torch.nn.functional.binary_cross_entropy_with_logits(
        prediction[:, :, 4], visible)
    return 12*regression + visibility


def save_weights(model, path):
    # NPZ contains float arrays only; loading never unpickles Python code.
    import numpy as np
    with path.open('xb') as f:
        np.savez(f, **{k: v.detach().cpu().numpy() for k, v in model.state_dict().items()})


def load_weights(path):
    import numpy as np
    model = UIMapLite()
    reference = model.state_dict()
    if not path.is_file() or path.stat().st_size > 8*1024**2:
        raise ValueError("weights missing or oversized")
    import zipfile
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist()) > 8*1024**2:
            raise ValueError("uncompressed weights exceed budget")
    with np.load(path, allow_pickle=False) as arrays:
        if set(arrays.files) != set(reference):
            raise ValueError('weight schema mismatch')
        state = {}
        for key, value in reference.items():
            a = arrays[key]
            if a.shape != tuple(value.shape) or a.dtype != value.numpy().dtype or not np.isfinite(a).all():
                raise ValueError('invalid weights: '+key)
            state[key] = torch.from_numpy(a.copy())
    model.load_state_dict(state, strict=True)
    return model.eval()
