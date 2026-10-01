"""Required dedicated CI: real optimization, pure ONNX export and fresh inference process."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REQUIRED=os.environ.get('TFT_REQUIRE_UIMAP_NATIVE')=='1'
AVAILABLE=all(importlib.util.find_spec(x) for x in ('torch','onnx','onnxruntime','PIL','numpy'))
if REQUIRED and not AVAILABLE:raise RuntimeError('U1 native test dependencies missing')


@unittest.skipUnless(AVAILABLE,'dedicated UI-Map workflow installs dependencies')
class NativeTests(unittest.TestCase):
    def test_training_export_parity_without_torch_in_runtime(self):
        from training.tests.test_ui_map_lite import fixture_prepared
        from training.ui_map_lite.train import train
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'train';train(fixture_prepared(),out,steps=8)
            code=r'''
import sys,time,json,resource,numpy as np,onnxruntime as ort
from pathlib import Path
from training.ui_map_lite.export import export
p=Path(sys.argv[1]);q=p/'model.onnx';info=export(p/'model.npz',q)
s=ort.SessionOptions();s.intra_op_num_threads=1;s.inter_op_num_threads=1
r=ort.InferenceSession(str(q),s,providers=['CPUExecutionProvider'])
with np.load(p/'parity.npz',allow_pickle=False) as f:
    xs,expected=f['inputs'],f['outputs']
y=np.concatenate([r.run(None,{'image':x[None]})[0] for x in xs])
assert np.max(np.abs(y-expected))<2e-5
assert 'torch' not in sys.modules
assert info['parameters']<200000
times=[]
for i in range(200):
    start=time.perf_counter();r.run(None,{'image':xs[i%len(xs)][None]});times.append((time.perf_counter()-start)*1000)
print('UIMAP_NATIVE_PARITY_OK=true')
print('UIMAP_NATIVE_BENCHMARK='+json.dumps(dict(p50_ms=float(np.percentile(times,50)),p95_ms=float(np.percentile(times,95)),model_bytes=info['model_bytes'],parameters=info['parameters'],max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,scope='synthetic CI tensors; not user PC; no capture cost')))
'''
            result=subprocess.run([sys.executable,'-c',code,str(out)],capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('UIMAP_NATIVE_PARITY_OK=true',result.stdout)
            print(result.stdout,flush=True)


    def test_full_loader_training_runtime_and_seal(self):
        import json
        from training.tests.test_ui_map_lite_sources import fixture_dataset
        from training.ui_map_lite.data import prepare
        from training.ui_map_lite.train import train
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);spec,images,manifest=fixture_dataset(root)
            prepared=prepare(root,spec,images,manifest)
            out=root/'train';train(prepared,out,steps=3)
            args=[sys.executable,'-m','training.ui_map_lite.runtime','--project',str(root),
                  '--spec',str(spec),'--image-root',str(images),'--manifest',str(manifest),
                  '--train',str(out),'--output',str(root/'evaluation')]
            result=subprocess.run(args,capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=json.loads((root/'evaluation/report.json').read_text())
            self.assertEqual(report['summary']['frames'],3)
            self.assertFalse(report['summary']['inference_imported_torch'])
            self.assertFalse(report['summary']['profile_promoted'])
            self.assertTrue((root/'evaluation/COMPLETE.json').is_file())
            self.assertTrue((root/'evaluation/viewer.html').is_file())
            with (out/'model.npz').open('ab') as f:f.write(b'changed')
            args[-1]=str(root/'tampered')
            broken=subprocess.run(args,capture_output=True,text=True,timeout=120)
            self.assertNotEqual(broken.returncode,0)
            self.assertFalse((root/'tampered/COMPLETE.json').exists())


if __name__=='__main__':unittest.main()
