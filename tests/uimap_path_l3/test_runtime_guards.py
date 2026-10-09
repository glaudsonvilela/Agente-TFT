"""Post-training hardening; no model inference is mocked as a successful neural test."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from training.uimap_path_l3 import legacy
from training.uimap_path_l3.runtime import run
from uimap_lite_l2.common import save,sha

class RuntimeGuards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.bundle=self.root/'bundle';self.bundle.mkdir();self.images=self.root/'images';self.images.mkdir()
        (self.bundle/'candidate-model.onnx').write_bytes(b'not-a-real-model-guard-fixture')
        self.plan=dict(model_schema='l3_edge_nodes_bilinear_targets_v1',activation_allowed=False,
                       base_plan_sha256=sha(legacy.L2/'configs/plan.json'))
        save(self.bundle/'plan.json',self.plan)
        save(self.bundle/'deployment-candidate.json',dict(validated=True,activation_allowed=False,
                        sha256=sha(self.bundle/'candidate-model.onnx')))
        self.rows=[dict(image='frame.png',timestamp_ms=i,sha256='0'*64) for i in range(40)]
        save(self.bundle/'manifest.json',self.rows);self.seal()
    def seal(self):
        p=self.bundle/'COMPLETE.json'
        if p.exists():p.unlink()  # disposable test fixture only
        save(p,{n:sha(self.bundle/n) for n in ('plan.json','deployment-candidate.json','manifest.json','candidate-model.onnx')})
    def tearDown(self):self.tmp.cleanup()
    def test_model_tamper_fails_before_session(self):
        (self.bundle/'candidate-model.onnx').write_bytes(b'changed')
        with patch('training.uimap_path_l3.runtime.LiteRuntime') as session:
            with self.assertRaisesRegex(ValueError,'runtime input seal'):run(self.bundle,self.images,self.root/'out.json')
            session.assert_not_called()
    def test_base_plan_mismatch_fails_before_session(self):
        p=self.bundle/'plan.json';p.unlink();self.plan['base_plan_sha256']='0'*64;save(p,self.plan);self.seal()
        with patch('training.uimap_path_l3.runtime.LiteRuntime') as session:
            with self.assertRaisesRegex(ValueError,'runtime base plan changed'):run(self.bundle,self.images,self.root/'out.json')
            session.assert_not_called()
    def test_outside_image_path_not_decoded(self):
        p=self.bundle/'manifest.json';p.unlink();self.rows[0]['image']='../escape.png';save(p,self.rows);self.seal()
        (self.root/'escape.png').write_bytes(b'x')
        with patch('training.uimap_path_l3.runtime.LiteRuntime'),patch('training.uimap_path_l3.runtime.decode') as decode:
            with self.assertRaises(ValueError):run(self.bundle,self.images,self.root/'out.json')
            decode.assert_not_called()
    def test_image_tamper_not_decoded(self):
        (self.images/'frame.png').write_bytes(b'not-the-pinned-image')
        with patch('training.uimap_path_l3.runtime.LiteRuntime'),patch('training.uimap_path_l3.runtime.decode') as decode:
            with self.assertRaisesRegex(ValueError,'image changed'):run(self.bundle,self.images,self.root/'out.json')
            decode.assert_not_called()

if __name__=='__main__':unittest.main()
