"""Contracts and real optimization tests; no assertion of TFT semantic accuracy."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from training.ui_map_lite.core import decoded,rect_ok,statistics,load_json,inside,write_json


class CoreTests(unittest.TestCase):
    def test_invalid_rectangle_is_not_a_map(self):
        self.assertFalse(rect_ok([.8,.1,.2,.4]))
        self.assertEqual(decoded([.8,.1,.2,.4,.99]*2)[0]['status'],'unresolved')

    def test_low_visibility_abstains(self):
        r=decoded([.1,.1,.9,.5,.79]*2)[0]
        self.assertEqual(r['status'],'unresolved');self.assertIsNone(r['corners_px'])

    def test_proposal_never_becomes_occupancy(self):
        r=decoded([.1,.1,.9,.5,.99]*2)[0]
        self.assertEqual(r['status'],'proposal');self.assertFalse(r['active']);self.assertIsNone(r['unit_id'])
        self.assertIsNone(r['occupancy'])

    def test_nonfinite_output_rejected(self):
        with self.assertRaises(ValueError):decoded([float('nan')]*10)

    def test_shape_rejected(self):
        with self.assertRaises(ValueError):decoded([.5]*8)

    def test_coordinate_scaling(self):
        r=decoded([.1,.1,.9,.5,.99]*2,1000,500)[0]
        self.assertEqual(r['corners_px'][0],[100,50])

    def test_absent_examples_count_false_accepts(self):
        p=[[.1,.1,.9,.5,.99]*2];t=[[.1,.1,.9,.5,0.]*2]
        r=statistics(p,t,[[.1,.1,.9,.5]]*2)
        self.assertEqual(r['per_panel']['bench']['accepted_nonvisible'],1)
        self.assertIsNone(r['semantic_tft_accuracy'])

    def test_no_semantic_metric_from_generated_geometry(self):
        r=statistics([[.1,.1,.9,.5,.99]*2],[[.1,.1,.9,.5,1.]*2],[[.1,.1,.9,.5]]*2)
        self.assertEqual(r['per_panel']['bench']['corner_error_px_p50'],0)
        self.assertFalse(r['independent_match_validation'])

    def test_json_duplicates_fail(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):load_json(p)

    def test_json_nonfinite_fail(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.json';p.write_text('{"a":NaN}')
            with self.assertRaises(ValueError):load_json(p)

    def test_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.json';write_json(p,dict(a=1))
            with self.assertRaises(FileExistsError):write_json(p,dict(a=2))

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):inside(Path(td),'../elsewhere')

    def test_inference_source_has_no_torch_import(self):
        import ast
        for name in ('core','data','export','runtime','viewer'):
            path=Path(__file__).parents[1]/'ui_map_lite'/(name+'.py')
            imports=[n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,(ast.Import,ast.ImportFrom))]
            for node in imports:
                names=[x.name for x in node.names] if isinstance(node,ast.Import) else [node.module or '']
                self.assertFalse(any(n.startswith('torch') for n in names))


def fixture_prepared():
    import numpy as np
    from PIL import Image
    seeds=[];crops={}
    for k,g in enumerate(('train','validation','test')):
        name=g+'.jpg';seeds.append(dict(image=name,split=g,sha256=str(k)*64))
        rng=np.random.default_rng(k)
        crops[name]=[Image.fromarray(rng.integers(0,255,(80,500,3),dtype=np.uint8)) for _ in range(2)]
    return dict(seeds=seeds,crops=crops,boxes=[[358,682,1396,828],[553,929,1553,1070]],frames=[],provenance={})


@unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('PIL'),'optional local data tools')
class DataTests(unittest.TestCase):
    def test_generation_reproducible(self):
        import numpy as np
        from training.ui_map_lite.data import generate
        p=fixture_prepared();a,b=generate(p,'train',6,12);c,d=generate(p,'train',6,12)
        np.testing.assert_array_equal(a,c);np.testing.assert_array_equal(b,d)

    def test_splits_have_distinct_sources(self):
        p=fixture_prepared()
        self.assertEqual(len(set(s['sha256'] for s in p['seeds'])),3)

    def test_generated_boxes_are_bounded(self):
        from training.ui_map_lite.data import generate
        _,ys=generate(fixture_prepared(),'test',80,42)
        for row in ys:
            self.assertTrue(rect_ok(list(map(float,row[:4]))))
            self.assertTrue(rect_ok(list(map(float,row[5:9]))))

    def test_absence_is_rendered_not_predicted(self):
        from training.ui_map_lite.data import generate
        _,ys=generate(fixture_prepared(),'test',80,42)
        self.assertGreater(sum(ys[:,4]==0),0);self.assertGreater(sum(ys[:,4]==1),0)

    def test_sample_budget(self):
        from training.ui_map_lite.data import generate
        with self.assertRaises(ValueError):generate(fixture_prepared(),'train',100000,42)

    def test_no_wrong_resolution(self):
        from PIL import Image
        from training.ui_map_lite.data import read_rgb
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.png';Image.new('RGB',(10,10)).save(p)
            with self.assertRaises(ValueError):read_rgb(p)


@unittest.skipUnless(importlib.util.find_spec('torch'),'optional local training backend')
class TrainingTests(unittest.TestCase):
    def test_small_network_and_export_shapes(self):
        from training.ui_map_lite.model import UIMapLite
        from training.ui_map_lite.export import expected_shapes
        m=UIMapLite()
        self.assertLess(sum(x.numel() for x in m.parameters()),200000)
        self.assertEqual({k:tuple(v.shape) for k,v in m.state_dict().items() if not k.startswith('norms.')},expected_shapes())

    def test_arrays_roundtrip(self):
        import torch
        from training.ui_map_lite.model import UIMapLite
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'m.npz';a=UIMapLite().eval();a.export_arrays(p);b=UIMapLite().eval();b.load_arrays(p)
            with torch.inference_mode():
                x=torch.rand(1,3,192,320)
                torch.testing.assert_close(a(x),b(x),rtol=1e-5,atol=1e-6)

    def test_real_training_changes_parameters(self):
        from training.ui_map_lite.train import train
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'trained';r=train(fixture_prepared(),out,steps=3)
            self.assertTrue(r['model_trained']);self.assertGreater(r['changed_parameter_tensors'],0)
            self.assertTrue((out/'TRAINED.json').exists());self.assertFalse(r['profile_promoted'])

    def test_invalid_parent_rejected(self):
        import numpy as np
        from training.ui_map_lite.model import UIMapLite
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.npz';np.savez(p,unrelated=np.zeros(1,np.float32))
            with self.assertRaises(ValueError):UIMapLite().load_arrays(p)


if __name__=='__main__':unittest.main()
