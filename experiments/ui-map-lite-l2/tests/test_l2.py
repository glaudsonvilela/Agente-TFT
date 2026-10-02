import copy,hashlib,inspect,json,os,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from uimap_lite_l2.common import *
from uimap_lite_l2.evaluate import metrics,benchmark,gate
from uimap_lite_l2.data import Compositor,source_manifest,image_input
from uimap_lite_l2.refine import refine_panels
from uimap_lite_l2.baseline import validate_baseline,locate

PACKAGE=Path(__file__).resolve().parents[1]

def plan():return load(PACKAGE/'configs/plan.json')

def raw():return np.asarray([[.2,.6,.7,.72,5],[.18,.84,.82,.99,5]],np.float32)

class DecisionTests(unittest.TestCase):
    def setUp(self):self.p=plan()['evaluation_policy']
    def test_coarse_is_not_reader_permission(self):
        for d in decisions(raw(),self.p):
            self.assertTrue(d['accepted_as_coarse']);self.assertFalse(d['map_usable_by_readers'])
            self.assertFalse(d['narrow_ocr_crop_safe']);self.assertIsNone(d['unit_id'])
    def test_reversed_is_not_sorted(self):
        x=raw();x[0,0],x[0,2]=x[0,2],x[0,0]
        self.assertFalse(decisions(x,self.p)[0]['geometry_valid'])
    def test_outside_not_clamped(self):
        x=raw();x[1,3]=1.03;self.assertFalse(decisions(x,self.p)[1]['accepted_as_coarse'])
    def test_visibility_alone_not_accepted(self):
        x=raw();x[0,0]=-.03
        r=decisions(x,self.p)[0];self.assertTrue(r['visibility_above_threshold']);self.assertFalse(r['accepted_as_coarse'])
    def test_low_visibility_unknown(self):
        x=raw();x[:,4]=0
        self.assertTrue(all(d['geometry_valid'] and not d['accepted_as_coarse'] for d in decisions(x,self.p)))
    def test_nan_rejected(self):
        x=raw();x[0,1]=np.nan
        with self.assertRaises(ValueError):decisions(x,self.p)
    def test_wrong_shape_rejected(self):
        with self.assertRaises(ValueError):decisions(np.ones((1,5)),self.p)
    def test_minimum_size(self):
        x=raw();x[0,2]=x[0,0]+.001;self.assertFalse(decisions(x,self.p)[0]['accepted_as_coarse'])
    def test_threshold_boundary(self):
        x=raw();x[:,4]=np.float32(self.p['visibility_logit_min']+.00001)
        self.assertTrue(all(d['accepted_as_coarse'] for d in decisions(x,self.p)))
    def test_l1_conversion_does_not_mutate(self):
        x=raw();old=x.copy();y=l1_to_corners(x)
        np.testing.assert_array_equal(x,old);np.testing.assert_allclose(y[:,:2],x[:,:2]-x[:,2:4]/2)

class MetricTests(unittest.TestCase):
    def setUp(self):self.p=plan()['evaluation_policy']
    def test_metric_gate_matches_runtime(self):
        x=raw();x[0,0]=-.2
        m=metrics(x[None],np.zeros((1,2,4)),np.zeros((1,2)),self.p)
        self.assertEqual(m['bench']['visibility_pass_hidden'],1);self.assertEqual(m['bench']['accepted_hidden'],0)
        self.assertEqual(m['shop']['accepted_hidden'],1)
    def test_perfect_geometry(self):
        x=raw()[None];m=metrics(x,x[:,:,:4],np.ones((1,2)),self.p)
        self.assertTrue(all(v['coordinate_mae_px']==0 for v in m.values()));self.assertTrue(gate(m,self.p))
    def test_empty_metrics_error(self):
        with self.assertRaises(ValueError):metrics(np.empty((0,2,5)),np.empty((0,2,4)),np.empty((0,2)),self.p)
    def test_abstain_everything_cannot_pass(self):
        x=raw()[None];x[:,:,4]=-5;m=metrics(x,x[:,:,:4],np.ones((1,2)),self.p)
        self.assertFalse(gate(m,self.p))
    def test_boolean_visibility_only(self):
        with self.assertRaises(ValueError):metrics(raw()[None],np.zeros((1,2,4)),np.full((1,2),.2),self.p)
    def test_benchmark_rejects_one_repeated_frame(self):
        with self.assertRaises(ValueError):benchmark(lambda x:x,np.zeros((2,3,192,320)),1,2)
    def test_benchmark_counts_different_images(self):
        xs=np.stack([np.zeros((3,192,320)),np.ones((3,192,320))])
        m=benchmark(lambda x:x,xs,1,4);self.assertEqual(m['distinct_prepared_tensors'],2)

class RefinementTests(unittest.TestCase):
    def test_only_pixels_and_prediction_and_policy(self):
        self.assertEqual(list(inspect.signature(refine_panels).parameters),['image','raw','plan'])
    def test_flat_cannot_refine(self):
        x=raw();r,tr,_=refine_panels(np.zeros((1080,1920,3),np.uint8),x,plan())
        np.testing.assert_array_equal(x,r);self.assertFalse(any(t['applied'] for t in tr))
    def test_invalid_box_not_rescued(self):
        x=raw();x[0,0]=-.1;_,tr,_=refine_panels(np.zeros((1080,1920,3),np.uint8),x,plan())
        self.assertEqual(tr[0]['reason'],'coarse_gate_failed')
    def test_thumbnail_cannot_reinterpret_pixel_radius(self):
        with self.assertRaises(ValueError):refine_panels(np.zeros((192,320,3),np.uint8),raw(),plan())
    def test_no_mutation(self):
        im=np.zeros((1080,1920,3),np.uint8);x=raw();old=x.copy();refine_panels(im,x,plan());np.testing.assert_array_equal(x,old)
    def test_refinement_displacement_bounded(self):
        im=Image.new('RGB',(1920,1080));d=ImageDraw.Draw(im)
        d.rectangle([400,500,1400,700],fill=(220,220,220))
        x=np.array([[394/1920,494/1080,1394/1920,694/1080,6],[.1,.85,.9,.98,-5]],np.float32)
        r,tr,_=refine_panels(np.asarray(im),x,plan())
        self.assertTrue(tr[0]['applied']);delta=abs((r[0,:4]-x[0,:4])*[1920,1080,1920,1080])
        self.assertTrue(np.all(delta<=12.001))
    def test_high_confidence_still_requires_edges(self):
        x=raw();x[:,4]=100;_,tr,_=refine_panels(np.zeros((1080,1920,3),np.uint8),x,plan())
        self.assertFalse(any(t['applied'] for t in tr))

class IOTests(unittest.TestCase):
    def test_save_never_overwrites(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.json';save(p,{'a':1})
            with self.assertRaises(FileExistsError):save(p,{})
    def test_json_duplicate_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x'
            for txt in ['{"a":1,"a":2}','{"a":NaN}']:
                p.write_text(txt)
                with self.assertRaises(ValueError):load(p)
    def test_escape_path(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):contained(Path(t),'../secret')
    def test_symlink_json(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x';p.write_text('{}');q=Path(t)/'y';q.symlink_to(p)
            with self.assertRaises(ValueError):load(q)
    def test_policy_is_frozen(self):
        p=plan();p['refinement']['radius_original_px']=99
        with self.assertRaises(ValueError):validate_policy(p)
    def test_missing_completed_baseline_fails(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):locate(Path(t))
    def test_corrupt_seal_not_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);save(p/'COMPLETE.json',{'weights.npz':'0'*64});(p/'weights.npz').write_bytes(b'wrong')
            with self.assertRaises(ValueError):validate_baseline(p)

class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
    def test_shape_and_small_budget(self):
        import torch
        from uimap_lite_l2.model import UIMapSpatial
        m=UIMapSpatial().eval();self.assertLess(sum(p.numel() for p in m.parameters()),192778)
        self.assertFalse(any(isinstance(p,torch.nn.Flatten) for p in m.modules()))
        a,h=m.components(torch.zeros(1,3,192,320));self.assertEqual(tuple(h.shape),(1,4,48,80))
        self.assertEqual(tuple(a.shape),(1,2,5));self.assertTrue(bool(((a[:,:,:4]>=0)&(a[:,:,:4]<=1)).all()))
    def test_heatmaps_have_gradients(self):
        import torch
        from uimap_lite_l2.model import UIMapSpatial,loss_function
        m=UIMapSpatial();p,h=m.components(torch.rand(2,3,192,320));y=torch.tensor(raw()[:,:4]).repeat(2,1,1)
        loss=loss_function(p,h,y,torch.ones(2,2));loss.backward()
        self.assertGreater(float(m.maps.weight.grad.abs().sum()),0)
    def test_all_hidden_loss_finite(self):
        import torch
        from uimap_lite_l2.model import UIMapSpatial,loss_function
        m=UIMapSpatial();p,h=m.components(torch.zeros(2,3,192,320))
        loss=loss_function(p,h,torch.zeros(2,2,4),torch.zeros(2,2));self.assertTrue(bool(torch.isfinite(loss)))
    def test_weight_roundtrip_exact(self):
        import torch
        from uimap_lite_l2.model import UIMapSpatial,save_weights,load_weights
        with tempfile.TemporaryDirectory() as t:
            torch.manual_seed(9);m=UIMapSpatial().eval();p=Path(t)/'w.npz';save_weights(m,p);other=load_weights(p)
            x=torch.rand(1,3,192,320);np.testing.assert_array_equal(m(x).detach().numpy(),other(x).detach().numpy())
    def test_weight_no_overwrite(self):
        from uimap_lite_l2.model import UIMapSpatial,save_weights
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'w.npz';save_weights(UIMapSpatial(),p)
            with self.assertRaises(FileExistsError):save_weights(UIMapSpatial(),p)
    def test_invalid_npz_schema(self):
        from uimap_lite_l2.model import load_weights
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'w.npz';np.savez(p,fake=np.zeros(1))
            with self.assertRaises(ValueError):load_weights(p)
    def test_onnx_real_forward(self):
        import importlib.util
        if not all(importlib.util.find_spec(n) for n in ('onnx','onnxruntime')):
            if os.environ.get('LITE2_REQUIRE_ONNX')=='1':self.fail('ONNX integration is mandatory in installer')
            self.skipTest('ONNX not installed in this environment')
        from uimap_lite_l2.model import UIMapSpatial
        from uimap_lite_l2.export import export_checked
        with tempfile.TemporaryDirectory() as t:
            m=UIMapSpatial().eval();r=export_checked(m,np.random.default_rng(7).random((3,3,192,320),dtype=np.float32),Path(t),True)
            self.assertTrue(r['validated'])
    def test_runtime_import_does_not_import_torch(self):
        p=subprocess.run([sys.executable,'-B','-c','import uimap_lite_l2.runtime,sys;assert "torch" not in sys.modules'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

class DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'frames').mkdir()
        self.p=plan()
        for k in ('train','validation','test'):
            n='frames/'+k+'.png';self.p[k+'_images']=[n]
            im=Image.new('RGB',(1920,1080),(25,40,55));d=ImageDraw.Draw(im)
            d.rectangle([358,682,1396,828],fill=(60,120,130));d.rectangle([345,915,1565,1075],fill=(80,40,160));im.save(self.root/n)
    def tearDown(self):self.tmp.cleanup()
    def test_seed_reproducible(self):
        c=Compositor(self.root,self.p,'train');a=c.sample(67);b=c.sample(67)
        for i in range(3):np.testing.assert_array_equal(a[i],b[i])
        self.assertEqual(a[3],b[3])
    def test_render_size_does_not_change_labels(self):
        c=Compositor(self.root,self.p,'train')
        for seed in [2,3,5,8]:
            a=c.sample(seed);b=c.sample(seed,True)
            np.testing.assert_array_equal(a[1],b[1]);np.testing.assert_array_equal(a[2],b[2]);self.assertEqual(a[3],b[3])
    def test_visible_targets_contained(self):
        c=Compositor(self.root,self.p,'train')
        for seed in range(24):
            x,y,v,_,_=c.sample(seed);self.assertEqual(x.shape,(3,192,320))
            self.assertTrue(np.all((y[v==1]>=0)&(y[v==1]<=1)))
    def test_multiple_modes_and_hidden_cases(self):
        c=Compositor(self.root,self.p,'train');rows=[c.sample(i) for i in range(20)]
        self.assertEqual({r[3]['mode'] for r in rows},{'whole_scene','context_paste'})
        self.assertTrue(any((r[2]==0).any() for r in rows))
    def test_no_suggestions_argument(self):
        self.assertEqual(list(inspect.signature(Compositor).parameters),['root','plan','split'])

if __name__=='__main__':unittest.main()
