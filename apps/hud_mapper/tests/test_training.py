import importlib.util,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
from hm.train import partition,render,accepted_masks,cache_selection

class TrainingContracts(unittest.TestCase):
    def test_evaluation_uses_runtime_geometry_and_min_size(self):
        # Both boxes are in bounds, but neither meets the frozen size rule.
        raw=np.array([[[.2,.2,.21,.6,9],[.2,.2,.7,.201,9]]],np.float32)
        self.assertFalse(accepted_masks(raw).any())
    def test_cache_covers_full_partition(self):
        rows=list(range(1000));chosen=cache_selection(rows,96)
        self.assertEqual(chosen[0],0);self.assertEqual(chosen[-1],999)
        self.assertEqual(len(chosen),96)

    def test_split_by_video_not_adjacent_frames(self):
        rows=[dict(group=g,timestamp=i) for g in ('a','b','c','d','e') for i in range(10)]
        parts,kind=partition(rows);sets=[{r['group'] for r in p} for p in parts]
        self.assertTrue(all(not sets[i]&sets[j] for i in range(3) for j in range(i)))
        self.assertIn('video_hash',kind)
    def test_single_video_not_independent(self):
        _,kind=partition([dict(group='a',timestamp=i) for i in range(40)])
        self.assertIn('not_independent',kind)
    def test_joint_occlusion_and_frame_size(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'frame.png';Image.new('RGB',(1920,1080),(90,120,160)).save(p)
            # Deliberately equal overlapping panel targets: covering one MUST affect both.
            r=dict(path=p,targets=np.array([[.2,.2,.7,.6],[.2,.2,.7,.6]],np.float32),known=np.ones(2,np.float32))
            found=False
            for seed in range(30):
                x,t,v,k,c=render(r,seed)
                self.assertEqual(x.shape,(3,192,320));self.assertEqual(c.shape,(2,4))
                self.assertEqual(v[0],v[1])
                if v[0]==0:found=True
            self.assertTrue(found)
    def test_unlabelled_panels_not_targets(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.png';Image.new('RGB',(1920,1080)).save(p)
            row=dict(path=p,targets=np.zeros((2,4),np.float32),known=np.zeros(2,np.float32))
            _,_,v,k,_=render(row,1);self.assertFalse(v.any());self.assertFalse(k.any())

@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('uimap_lite_l2'),'training dependencies absent')
class ModelContracts(unittest.TestCase):
    def test_parameters_and_actual_optimizer(self):
        import torch
        from uimap_lite_l2.model import UIMapSpatial
        from hm.train import target_loss
        torch.set_num_threads(1);m=UIMapSpatial();self.assertEqual(sum(p.numel() for p in m.parameters()),27726)
        x=torch.rand(2,3,192,320);t=torch.tensor([[[.2,.6,.7,.8],[.1,.8,.9,.98]]]*2)
        v=torch.ones(2,2);before=m.maps.weight.detach().clone();o=torch.optim.Adam(m.parameters(),lr=.001)
        p,h=m.components(x);loss=target_loss(p,h,t,v,v);loss.backward();o.step()
        self.assertFalse(torch.equal(before,m.maps.weight));self.assertTrue(torch.isfinite(loss))

if __name__=='__main__':unittest.main()
