"""Pinned, single-thread ONNX item perception. Outputs remain candidates."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time


class ItemIconObserver:
    def __init__(self, root: Path):
        import onnxruntime as ort
        plan=json.loads((root/'configs/catalog/active-item-neural-v1.json').read_text())
        catalog=json.loads((root/'configs/catalog/active-visual-reference-v1.json').read_text())
        reference=json.loads((root/catalog['reference']/'reference.json').read_text())
        folder=root/'models/item-icons'
        for name,digest in plan['files'].items():
            if name not in ('item-icons.onnx','metadata.json'):
                raise ValueError('Unexpected item model artifact')
            path=folder/name
            if path.stat().st_size>2*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('Item model checksum mismatch')
        metadata=json.loads((folder/'metadata.json').read_text())
        if (metadata['set_key']!=catalog['set_key'] or
                metadata['reference_sha256']!=reference['reference_sha256'] or
                plan['reference_sha256']!=metadata['reference_sha256'] or
                metadata.get('game_state_write_allowed') is not False):
            raise ValueError('Item model belongs to another catalog')
        self.classes=metadata['classes'];self.sha=metadata['model_sha256']
        options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        self.session=ort.InferenceSession(str(folder/'item-icons.onnx'),options,providers=['CPUExecutionProvider'])
        if self.session.get_inputs()[0].shape[1:]!=[3,32,32]:
            raise ValueError('Item model input contract changed')

    def observe(self, image, inventory: dict, profile: dict) -> dict:
        import numpy as np
        from PIL import Image
        slots=[];inputs=[]
        for slot in inventory['slots']:
            if slot['status']!='icon_candidate':continue
            rect=slot['rect'];offset=profile['icon_inner_offset'];size=profile['icon_inner_size']
            x,y=rect['x']+offset['x'],rect['y']+offset['y']
            crop=image.crop((x,y,x+size['width'],y+size['height'])).resize((32,32),Image.Resampling.BILINEAR)
            inputs.append(np.asarray(crop,dtype=np.float32).transpose(2,0,1)/255)
            slots.append(slot['slot'])
        start=time.perf_counter()
        records=[]
        if inputs:
            logits=self.session.run(['logits'],{'icons':np.stack(inputs)})[0]
            if logits.shape!=(len(slots),len(self.classes)) or not np.isfinite(logits).all():
                raise ValueError('Invalid neural item output')
            probabilities=np.exp(logits-logits.max(axis=1,keepdims=True))
            probabilities/=probabilities.sum(axis=1,keepdims=True)
            for slot,scores in zip(slots,probabilities):
                top=np.argsort(scores)[-3:][::-1]
                records.append(dict(slot=slot,candidates=[dict(ids=self.classes[i]['ids'],
                    names=sorted(set(self.classes[i]['names'])),score=float(scores[i])) for i in top]))
        return dict(active=True,model_sha256=self.sha,inference_ms=(time.perf_counter()-start)*1000,
                    records=records,mode='diagnostic_candidates',scores_are_calibrated=False,
                    game_state_write_allowed=False)
