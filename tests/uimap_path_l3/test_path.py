"""Path contracts: geometry, preprocessing, learning target, refinement parity and ONNX."""
import importlib.util
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from training.uimap_path_l3 import legacy
from training.uimap_path_l3.pixels import prepare_image,from_rgb,decode
from training.uimap_path_l3.geometry import (checked_corners,raster_crop,project_regions,panel_decisions,
                       authorize_regions,board_status,checked_homography,transform_points)
from training.uimap_path_l3.refine import refine_diagnostic
from training.uimap_path_l3.evaluate import metrics,grouped,failures
from training.uimap_path_l3.evidence import validate_plan
from uimap_lite_l2.common import load
from uimap_lite_l2.data import image_input
from uimap_lite_l2.refine import refine_panels

PLAN=load(legacy.L2/'configs/plan.json');POLICY=PLAN['evaluation_policy']
RAW=np.array([[.2,.6,.75,.76,5],[.18,.85,.82,.995,5]],np.float32)

class Coordinates(unittest.TestCase):
    def test_border_is_edge_not_last_center(self):self.assertEqual(raster_crop([0,0,1920,1080]),[0,0,1920,1080])
    def test_subpixel_conservative_rounding(self):self.assertEqual(raster_crop([1.2,2.3,20.1,30.9]),[1,2,21,31])
    def test_no_clamp(self):
        for p in [[-1,0,20,20],[0,0,1921,20],[0,30,2,1],[0,0,float('nan'),5]]:
            with self.assertRaises(ValueError):raster_crop(p)
    def test_child_same_transform(self):
        p=project_regions([100,100,500,200],[200,300,1000,500],[[100,100,200,150]])
        self.assertEqual(p,[[200,300,400,400]])
    def test_invalid_child_rejects_whole_group(self):
        with self.assertRaises(ValueError):project_regions([100,100,500,200],[200,300,1000,500],[[100,100,200,150],[0,0,10,10]])
    def test_coarse_never_authorizes(self):
        d=panel_decisions(RAW,POLICY,2)[0]
        self.assertFalse(authorize_regions(2,d,d['coordinate_space'],None,'bench')['allowed'])
        self.assertFalse(authorize_regions(2,d,d['coordinate_space'],.1,'bench')['allowed'])
    def test_old_frame_rejected(self):
        d=panel_decisions(RAW,POLICY,2)[0];d['precision_validated']=True
        self.assertFalse(authorize_regions(3,d,d['coordinate_space'],.1,'bench')['allowed'])
    def test_wrong_space_rejected(self):
        d=panel_decisions(RAW,POLICY,2)[0];d['precision_validated']=True
        self.assertFalse(authorize_regions(2,d,'board_plane',.1,'bench')['allowed'])
    def test_huge_score_does_not_repair_geometry(self):
        a=RAW.copy();a[0,:4]=[-.1,0,.4,.2];a[0,4]=100
        self.assertFalse(panel_decisions(a,POLICY,0)[0]['accepted_as_coarse'])
    def test_board_not_derived_from_shop(self):
        b=board_status();self.assertIsNone(b['cells']);self.assertFalse(b['derived_from_bench_or_shop'])
    def test_homography_roundtrip(self):
        a=np.array([[0,0],[7,0],[7,4],[0,4.]])
        b=np.array([[560,440],[1260,445],[1350,680],[550,675.]])
        h=checked_homography(a,b)
        self.assertLess(abs(transform_points(h,a)-b).max(),1e-8)
        points=np.array([[1.3,2.1],[2.5,.6]])
        self.assertLess(abs(transform_points(np.linalg.inv(h),transform_points(h,points))-points).max(),1e-8)
    def test_degenerate_mapping(self):
        for p in [np.zeros((4,2)),np.array([[0,0],[1,1],[1,0],[0,1]])]:
            with self.assertRaises(ValueError):checked_homography(p,p)
    def test_projective_infinity(self):
        with self.assertRaises(ValueError):transform_points(np.zeros((3,3)),[[1,2]])

class Pixels(unittest.TestCase):
    def setUp(self):self.im=Image.fromarray(np.random.default_rng(8).integers(0,256,(1080,1920,3),np.uint8))
    def test_same_rgb_and_legacy_tensor(self):
        f=prepare_image(self.im,4);self.assertTrue(np.array_equal(f.tensor,image_input(self.im)))
    def test_frame_is_readonly(self):
        f=prepare_image(self.im);self.assertFalse(f.rgb.flags.writeable);self.assertFalse(f.tensor.flags.writeable)
    def test_source_shape(self):
        with self.assertRaises(ValueError):prepare_image(Image.new('RGB',(320,192)))
    def test_single_open(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.png';self.im.save(p)
            with patch('PIL.Image.open',wraps=Image.open) as op:
                decode(p,0);self.assertEqual(op.call_count,1)
    def test_uint8_required(self):
        with self.assertRaises(ValueError):from_rgb(np.zeros((1080,1920,3),np.float32),0)
    def test_cache_quantization_exact(self):
        x=prepare_image(self.im).tensor;y=np.rint(x*255).astype(np.uint8).astype(np.float32)/255
        self.assertTrue(np.array_equal(x,y))

class Refiner(unittest.TestCase):
    def test_lazy_no_visible_panel(self):
        a=RAW.copy();a[:,4]=-10
        with patch('training.uimap_path_l3.refine.luma',side_effect=AssertionError('must be lazy')):
            _,_,s=refine_diagnostic(np.zeros((1080,1920,3),np.uint8),a,PLAN)
        self.assertEqual(s['luma_samples'],0)
    def test_random_pixel_parity(self):
        rgb=np.random.default_rng(9).integers(0,256,(1080,1920,3),np.uint8)
        a,t,_=refine_panels(rgb,RAW,PLAN);b,u,s=refine_diagnostic(rgb,RAW,PLAN)
        self.assertTrue(np.array_equal(a,b));self.assertEqual(t,u);self.assertFalse(s['refinement_used_by_readers'])
    def test_positive_edge_parity(self):
        rgb=np.full((1080,1920,3),20,np.uint8);rgb[400:600,400:1200]=230
        p=np.array([[398/1920,398/1080,1198/1920,598/1080,7],RAW[1]],np.float32)
        a,t,_=refine_panels(rgb,p,PLAN);b,u,_=refine_diagnostic(rgb,p,PLAN)
        self.assertTrue(np.array_equal(a,b));self.assertEqual(t,u)
    def test_edge_is_only_diagnostic(self):
        _,_,s=refine_diagnostic(np.zeros((1080,1920,3),np.uint8),RAW,PLAN)
        self.assertFalse(s['full_frame_luma_allocated']);self.assertFalse(s['refinement_used_by_readers'])

class Metrics(unittest.TestCase):
    def test_mode_tail_not_hidden_in_average(self):
        p=np.repeat(RAW[None],20,0);t=p[:,:,:4].copy();v=np.ones((20,2),np.float32)
        p[0,0,0]+=.1
        g=grouped(p,t,v,['bad']+['normal']*19,POLICY)
        self.assertTrue(any(x['group']=='bad' and x['reason']=='worst_corner_tail' for x in failures(g)))
    def test_hidden_acceptance_separate(self):
        m=metrics(RAW[None],RAW[None,:,:4],np.zeros((1,2)),POLICY)
        self.assertEqual(m['shop']['accepted_hidden'],1);self.assertIsNone(m['shop']['natural_accuracy'])
    def test_geometry_failure_separate(self):
        p=RAW.copy();p[0,2]=-.3
        m=metrics(p[None],RAW[None,:,:4],np.ones((1,2)),POLICY)
        self.assertEqual(m['bench']['geometry_invalid'],1);self.assertEqual(m['bench']['accepted_visible'],0)

class Model(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
    def test_parameter_budget(self):
        from training.uimap_path_l3.model import UIMapPath
        self.assertEqual(sum(p.numel() for p in UIMapPath().parameters()),27726)
    def test_l2_unreachable_border_reproduced(self):
        from uimap_lite_l2.model import UIMapSpatial
        m=UIMapSpatial();self.assertAlmostEqual(float(m.grid_y.max())*1080,1068.75,places=3)
    def test_l3_endpoint_support(self):
        from training.uimap_path_l3.model import UIMapPath
        m=UIMapPath();self.assertEqual(float(m.grid_x.min()),0);self.assertEqual(float(m.grid_y.max()),1)
    def test_targets_expectation(self):
        import torch
        from training.uimap_path_l3.model import spatial_targets,UIMapPath
        t=torch.tensor([[[0,0,1,1],[.01,.2,.9,.999]]]);q=spatial_targets(t);m=UIMapPath()
        xy=torch.stack(((q*m.grid_x).sum(-1),(q*m.grid_y).sum(-1)),-1).reshape(1,2,4)
        self.assertLess(float((xy-t).abs().max()),1e-6)
    def test_targets_probability_mass(self):
        import torch
        from training.uimap_path_l3.model import spatial_targets
        q=spatial_targets(torch.rand(5,2,4));self.assertTrue(torch.allclose(q.sum(-1),torch.ones(5,4)))
    def test_finite_loss_with_hidden_outside(self):
        import torch
        from training.uimap_path_l3.model import UIMapPath,loss_function
        m=UIMapPath();p,h=m.components(torch.rand(2,3,192,320));l=loss_function(p,h,torch.ones(2,2,4)*-1,torch.zeros(2,2))
        self.assertTrue(torch.isfinite(l));l.backward()
    def test_l2_weights_not_l3(self):
        from uimap_lite_l2.model import UIMapSpatial,save_weights
        from training.uimap_path_l3.model import load_weights
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.npz';save_weights(UIMapSpatial(),p)
            with self.assertRaises(ValueError):load_weights(p)
    def test_l3_weights_roundtrip(self):
        from training.uimap_path_l3.model import UIMapPath,load_weights,save_weights
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.npz';m=UIMapPath();save_weights(m,p);n=load_weights(p)
            for k,v in m.state_dict().items():self.assertTrue(np.array_equal(v.numpy(),n.state_dict()[k].numpy()))

class Native(unittest.TestCase):
    def test_real_optimization_onnx_and_fresh_process(self):
        available=all(importlib.util.find_spec(x) for x in ('onnx','onnxruntime'))
        if not available:
            if os.environ.get('UIMAP_PATH_REQUIRE_ONNX')=='1':self.fail('mandatory ONNX unavailable')
            self.skipTest('ONNX dependencies unavailable locally')
        import torch,subprocess
        from training.uimap_path_l3.model import UIMapPath,loss_function
        from uimap_lite_l2.export import export_checked
        torch.manual_seed(11);m=UIMapPath();opt=torch.optim.Adam(m.parameters(),lr=.001)
        x=torch.rand(4,3,192,320);target=torch.tensor([[[.2,.6,.75,.76],[.18,.85,.82,.995]]]*4)
        initial={k:v.detach().clone() for k,v in m.named_parameters()}
        for _ in range(5):
            opt.zero_grad();p,h=m.components(x);loss=loss_function(p,h,target,torch.ones(4,2));loss.backward();opt.step()
        self.assertTrue(any(not torch.equal(initial[k],v) for k,v in m.named_parameters()))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);info=export_checked(m.eval(),x.numpy(),p,True)
            self.assertTrue(info['validated'])
            code='from training.uimap_path_l3.runtime import LiteRuntime; import sys,numpy as np; e=LiteRuntime(sys.argv[1],sys.argv[2]); y=e.infer(np.zeros((1,3,192,320),np.float32)); assert y.shape==(1,2,5); assert "torch" not in sys.modules; print("fresh_onnx_no_torch=true")'
            r=subprocess.run([sys.executable,'-B','-c',code,str(p/'candidate-model.onnx'),info['sha256']],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn('fresh_onnx_no_torch=true',r.stdout)


class Rendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from training.uimap_path_l3.data import Renderer
        from uimap_lite_l2.common import sha
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        image=np.zeros((1080,1920,3),np.uint8);image[680:830,350:1400]=[90,110,140];image[915:1075,345:1565]=[150,80,50]
        Image.fromarray(image).save(cls.root/'positive.png');Image.new('RGB',(1920,1080),(10,12,14)).save(cls.root/'negative.png')
        base=dict(PLAN,train_images=['positive.png'],validation_images=['positive.png'],test_images=['positive.png'])
        cls.plan={'negative_sources':{k:{'image':'negative.png','sha256':sha(cls.root/'negative.png')} for k in ('train','validation','test')}}
        cls.renderer=Renderer(cls.root,base,cls.plan,'train')
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_reproducible_native_pixels(self):
        a=self.renderer.sample(123);b=self.renderer.sample(123)
        self.assertTrue(np.array_equal(a[0].tensor,b[0].tensor));self.assertTrue(np.array_equal(a[1],b[1]))
    def test_only_one_render_contract(self):
        f,_,_,m=self.renderer.sample(124)
        self.assertEqual(m['canonical_size'],[1920,1080]);self.assertEqual(f.rgb.shape,(1080,1920,3))
        self.assertTrue(np.array_equal(f.tensor,image_input(Image.fromarray(f.rgb))))
    def test_visible_targets_inside_frame(self):
        for seed in range(8):
            _,y,v,_=self.renderer.sample(seed)
            for i in range(2):
                if v[i]:self.assertTrue(0<=y[i,0]<y[i,2]<=1 and 0<=y[i,1]<y[i,3]<=1)
    def test_negative_seed_remains_labelled_negative(self):
        found=False
        for seed in range(10):
            _,_,v,m=self.renderer.sample(seed)
            if m['mode']=='negative_scene':self.assertEqual(v.tolist(),[0.,0.]);found=True
        self.assertTrue(found)
    def test_uint8_cache_equals_canonical_input(self):
        x,y,v,m=self.renderer.cache(2,100)
        f,a,b,_=self.renderer.sample(100)
        self.assertTrue(np.array_equal(x[0].astype(np.float32)/255,f.tensor))
        self.assertTrue(np.array_equal(y[0],a));self.assertTrue(np.array_equal(v[0],b))
    def test_corrupt_negative_is_rejected(self):
        from training.uimap_path_l3.data import Renderer
        base=dict(PLAN,train_images=['positive.png'])
        bad={'negative_sources':{'train':{'image':'negative.png','sha256':'0'*64}}}
        with self.assertRaises(ValueError):Renderer(self.root,base,bad,'train')

class Scope(unittest.TestCase):
    def test_shop_must_not_recalibrate_bench(self):
        d=panel_decisions(RAW,POLICY,0)[1];d['precision_validated']=True
        self.assertFalse(authorize_regions(0,d,d['coordinate_space'],.1,'bench')['allowed'])
    def test_large_error_cannot_authorize_crop(self):
        d=panel_decisions(RAW,POLICY,0)[0];d['precision_validated']=True
        self.assertFalse(authorize_regions(0,d,d['coordinate_space'],9,'bench')['allowed'])
    def test_distinct_profiles_cannot_fake_shared_frame(self):
        d=panel_decisions(RAW,POLICY,0)[0]
        self.assertFalse(d['child_rois_authorized']);self.assertFalse(d['map_usable_by_readers'])


if __name__=='__main__':unittest.main()
