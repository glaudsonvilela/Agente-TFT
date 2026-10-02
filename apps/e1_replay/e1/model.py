"""Optional frozen UI-map observation. Never drives a crop or trains weights."""
from pathlib import Path
import json, time
from .metrics import digest

class MapObserver:
    def __init__(self, metadata):
        import onnxruntime as ort
        p = Path(metadata).resolve(strict=True)
        if p.name != 'deployment-candidate.json' or p.stat().st_size > 65536:
            raise ValueError('Selecione deployment-candidate.json da execução L2/L3.')
        meta = json.loads(p.read_text(encoding='utf-8'))
        model = p.parent / 'candidate-model.onnx'
        if model.is_symlink() or not model.is_file() or model.stat().st_size > 8 * 1024**2:
            raise ValueError('Modelo ONNX inválido')
        if meta.get('activation_allowed') is not False or not meta.get('validated') or digest(model) != meta['sha256']:
            raise ValueError('Paridade/selo ONNX inválido; não usar outro peso como fallback.')
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.add_session_config_entry('session.intra_op.allow_spinning', '0')
        t = time.perf_counter_ns()
        self.session = ort.InferenceSession(str(model), opts, providers=['CPUExecutionProvider'])
        self.load_ms = (time.perf_counter_ns() - t) / 1e6
        ins, outs = self.session.get_inputs(), self.session.get_outputs()
        if len(ins) != 1 or ins[0].name != 'image' or ins[0].shape != [1, 3, 192, 320] or outs[0].shape != [1, 2, 5]:
            raise ValueError('Contrato do modelo incompatível')
        self.hash = meta['sha256']

    def observe(self, frame):
        import numpy as np
        from PIL import Image
        t = time.perf_counter_ns()
        small = Image.frombytes('RGB', (frame.width, frame.height), frame.rgb).resize((320, 192), Image.Resampling.BILINEAR)
        a = np.asarray(small, dtype=np.float32).transpose(2, 0, 1).copy()[None] / 255
        prep = (time.perf_counter_ns() - t) / 1e6
        t = time.perf_counter_ns()
        out = self.session.run(['panels'], {'image': a})[0]
        elapsed = (time.perf_counter_ns() - t) / 1e6
        if out.shape != (1, 2, 5) or not np.isfinite(out).all():
            raise ValueError('Saída neural inválida')
        return dict(status='real_diagnostic_only', sha256=self.hash, raw=out.tolist(),
                    resize_ms=prep, inference_ms=elapsed, frame_id=frame.id,
                    map_usable_by_readers=False, model_trained=False, profile_promoted=False)
