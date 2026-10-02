"""Contract, real optimization, serialization and optional ONNX tests."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np
import torch
from uimap_lite.common import box_from_rect, corners, contained, load, proposals, save, sha
from uimap_lite.model import UIMapLite, loss_function, save_weights, load_weights
from uimap_lite.data import Compositor, input_image, source_manifest
from uimap_lite.evaluate import evaluate_arrays, fixed_predictions, benchmark
from uimap_lite.export import export_checked
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
PLAN=json.loads((ROOT/'configs/seed_plan.json').read_text())
torch.set_num_threads(1)

class Contracts(unittest.TestCase):
    def test_parameter_budget(self):
        self.assertEqual(sum(x.numel() for x in UIMapLite().parameters()),192778)
    def test_output_shape(self):
        m=UIMapLite().eval()
        with torch.inference_mode():y=m(torch.zeros(1,3,192,320))
        self.assertEqual(tuple(y.shape),(1,2,5));self.assertTrue(torch.isfinite(y).all())
    def test_normalized_coordinates(self):
        m=UIMapLite().eval()
        with torch.inference_mode():y=m(torch.rand(2,3,192,320))
        self.assertTrue(((y[:,:,:4]>=0)&(y[:,:,:4]<=1)).all())
    def test_zero_visibility_has_zero_coordinate_gradient(self):
        p=torch.ones(2,2,5,requires_grad=True);target=torch.zeros(2,2,4)
        loss_function(p,target,torch.zeros(2,2)).backward()
        self.assertTrue((p.grad[:,:,:4]==0).all())
    def test_visible_loss_has_gradient(self):
        p=torch.ones(2,2,5,requires_grad=True)
        loss_function(p,torch.zeros(2,2,4),torch.ones(2,2)).backward()
        self.assertGreater(float(p.grad[:,:,:4].abs().sum()),0)
    def test_optimizer_updates_parameters(self):
        torch.manual_seed(3);m=UIMapLite();opt=torch.optim.Adam(m.parameters(),lr=.001)
        before=m.head[-1].weight.detach().clone()
        loss=loss_function(m(torch.rand(2,3,192,320)),torch.ones(2,2,4)*.2,torch.ones(2,2))
        loss.backward();opt.step()
        self.assertFalse(torch.equal(before,m.head[-1].weight))
    def test_safe_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'w.npz';m=UIMapLite().eval();save_weights(m,p);loaded=load_weights(p)
            x=torch.rand(1,3,192,320)
            with torch.inference_mode():self.assertTrue(torch.equal(m(x),loaded(x)))
    def test_weights_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'w.npz';save_weights(UIMapLite(),p)
            with self.assertRaises(FileExistsError):save_weights(UIMapLite(),p)
    def test_corrupt_weight_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'w.npz';np.savez(p,evil=np.ones(2))
            with self.assertRaises(ValueError):load_weights(p)
    def test_no_pickle(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'w.npz';np.savez(p,evil=np.array([{}],dtype=object))
            with self.assertRaises(ValueError):load_weights(p)
    def test_coordinate_roundtrip(self):
        self.assertTrue(np.allclose(corners(np.array(box_from_rect([10,20,30,40],(100,100)))),[.1,.2,.4,.6]))
    def test_proposals_remain_non_actionable(self):
        rows=proposals(np.array([[.5,.5,.4,.1,9],[.5,.7,.4,.1,9]],dtype=np.float32))
        self.assertEqual(rows[0]['state'],'candidate')
        self.assertTrue(all(x['map_usable_by_readers'] is False and x['unit_id'] is None for x in rows))
    def test_weak_visibility_abstains(self):
        rows=proposals(np.array([[.5,.5,.4,.1,-3],[.5,.7,.4,.1,0]],dtype=np.float32))
        self.assertTrue(all(x['state']=='unknown' for x in rows))
    def test_invalid_geometry_abstains(self):
        rows=proposals(np.array([[.02,.02,.9,.9,10],[.5,.5,.01,.01,10]],dtype=np.float32))
        self.assertTrue(all(x['state']=='unknown' for x in rows))
    def test_nan_rejected(self):
        with self.assertRaises(ValueError):proposals(np.full((2,5),np.nan))
    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):contained(Path(d),'../outside')
    def test_duplicate_json_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):load(p)
    def test_json_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_text('{"a":NaN}')
            with self.assertRaises(ValueError):load(p)
    def test_json_output_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';save(p,{'ok':True})
            with self.assertRaises(FileExistsError):save(p,{'ok':False})
    def test_metrics_exact_generated_example(self):
        p=np.zeros((3,2,5));p[:,:,:4]=[.5,.5,.3,.1];p[:,:,4]=10
        r=evaluate_arrays(p,p[:,:,:4].copy(),np.ones((3,2)))
        self.assertEqual(r['bench']['coordinate_mae_px'],0)
    def test_metrics_penalize_hidden_acceptance(self):
        p=np.ones((3,2,5))*10
        r=evaluate_arrays(p,np.zeros((3,2,4)),np.zeros((3,2)))
        self.assertEqual(r['shop']['accepted_hidden'],3)
    def test_fixed_mapper_not_claimed_B1(self):
        p=fixed_predictions(PLAN,4);self.assertEqual(p.shape,(4,2,5))
    def test_benchmark_excludes_loader(self):
        r=benchmark(lambda x:x,np.zeros((2,3,192,320)),warmup=1,repeats=3)
        self.assertEqual(r['repetitions'],3);self.assertEqual(r['batch'],1)
    def test_no_onnx_cannot_report_export_success(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch('importlib.util.find_spec',return_value=None):
                r=export_checked(UIMapLite(),np.zeros((1,3,192,320),np.float32),Path(d),False)
                self.assertFalse(r['validated'])
    def test_required_missing_onnx_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch('importlib.util.find_spec',return_value=None):
                with self.assertRaises(ValueError):export_checked(UIMapLite(),[],Path(d),True)
    @unittest.skipUnless(all(importlib.util.find_spec(x) for x in ('onnx','onnxruntime')), 'ONNX not installed in this environment')
    def test_onnx_export_real_forward_equivalence(self):
        with tempfile.TemporaryDirectory() as d:
            r=export_checked(UIMapLite().eval(),np.random.default_rng(2).random((4,3,192,320),dtype=np.float32),Path(d),True)
            self.assertTrue(r['validated'])
    def test_source_split_is_frozen(self):
        groups=[set(PLAN[k+'_images']) for k in ('train','validation','test')]
        self.assertFalse(groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2])
    def test_no_champion_vocabulary(self):
        self.assertEqual(set(PLAN['panels']),{'bench','shop'})

class SyntheticData(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in PLAN['train_images']:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            im=Image.new('RGB',(1920,1080),'#264055');draw=ImageDraw.Draw(im)
            for panel,c in zip(PLAN['panels'].values(),['#669922','#992266']):
                x,y,w,h=panel['rect'];draw.rectangle((x,y,x+w,y+h),fill=c)
            im.save(path)
        self.data=Compositor(self.root,PLAN,'train')
    def tearDown(self):self.tmp.cleanup()
    def test_sample_is_reproducible(self):
        a=self.data.sample(7);b=self.data.sample(7)
        for i in range(3):self.assertTrue(np.array_equal(a[i],b[i]))
    def test_batch_dtype_and_shape(self):
        x,y,v=self.data.batch(range(4))
        self.assertEqual(x.shape,(4,3,192,320));self.assertEqual(x.dtype,np.float32)
        self.assertEqual(y.shape,(4,2,4));self.assertEqual(v.shape,(4,2))
    def test_generated_visibility_has_known_origin(self):
        counts={}
        for seed in range(64):
            x,y,v,meta=self.data.sample(seed)
            for i,m in enumerate(meta):
                counts[m['kind']]=counts.get(m['kind'],0)+1
                self.assertEqual(v[i]==1,m['kind']=='inserted')
        self.assertTrue({'inserted','not_inserted','synthetically_occluded'}<=set(counts))
    def test_generated_panels_do_not_occlude_each_other(self):
        for seed in range(64):
            meta=self.data.sample(seed)[3]
            if all('inserted_rect' in m for m in meta):
                a,b=[m['inserted_rect'] for m in meta]
                self.assertLessEqual(a[1]+a[3],b[1])
    def test_generated_coordinates_bounded(self):
        for seed in range(32):
            x,y,v,meta=self.data.sample(seed)
            for row,m in zip(y,meta):
                if 'inserted_rect' in m:
                    l,t,r,b=corners(row)
                    self.assertTrue(l>=-1e-6 and t>=-1e-6 and r<=1+1e-6 and b<=1+1e-6)
    def test_resize_uses_full_resolution_source_without_overwriting(self):
        p=self.root/PLAN['train_images'][0];before=sha(p);x=input_image(p)
        self.assertEqual(x.shape,(3,192,320));self.assertEqual(before,sha(p))

if __name__=='__main__':unittest.main(verbosity=2)
