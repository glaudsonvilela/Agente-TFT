import json, queue, tempfile, unittest, threading, time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
from hm.core import valid_box,crop_box,neural_regions,ENVELOPES,xyxy,sha,load_json
from hm.dataset import Latest,Store
from hm.seeds import prepare,verify_session

class Geometry(unittest.TestCase):
    def test_outside_before_rounding(self):
        self.assertFalse(valid_box([-.01,0,5,5],10,10))
        with self.assertRaises(ValueError):crop_box([-.01,0,5,5],10,10)
    def test_inverted_never_sorted(self):
        self.assertFalse(valid_box([5,0,1,2],10,10))
    def test_exact_edges(self):self.assertEqual(crop_box([0,0,1920,1080],1920,1080),(0,0,1920,1080))
    def test_crop_uses_half_open_edges(self):self.assertEqual(crop_box([.2,.2,4.1,4.1],10,10),(0,0,5,5))
    def test_endpoint_semantics(self):
        raw=np.array([[[.1,.2,.8,.5,4],[.1,.7,.8,.9,4]]]);r=neural_regions(raw,1920,1080)
        self.assertEqual(r[0]['box'],[192,216,1536,540]);self.assertFalse(r[0]['delta_is_error'])
    def test_visibility_threshold_not_lowered(self):
        raw=[[[.1,.2,.8,.5,1],[.1,.7,.8,.9,1]]]
        self.assertTrue(all(r['status']=='unknown' for r in neural_regions(raw,1920,1080)))
    def test_geometry_not_visible_label(self):
        raw=[[[-.1,.2,.8,.5,8],[.1,.7,.8,1.01,8]]]
        self.assertTrue(all(r['status']=='unknown' for r in neural_regions(raw,1920,1080)))
    def test_nan_rejected(self):
        raw=np.zeros((1,2,5));raw[0,0,0]=np.nan
        with self.assertRaises(ValueError):neural_regions(raw,1920,1080)
    def test_wrong_network_shape_rejected(self):
        with self.assertRaises(ValueError):neural_regions(np.zeros((1,4,5)),1920,1080)
    def test_no_implicit_crop_permission(self):
        r=neural_regions([[[.1,.1,.8,.8,9],[.1,.1,.8,.8,9]]],1920,1080)
        self.assertTrue(all(x['map_usable_by_readers'] is False and x['ground_truth'] is False for x in r))
    def test_different_resolution_explicit(self):
        r=neural_regions([[[.1,.1,.8,.8,9],[.1,.1,.8,.8,9]]],1280,720)
        self.assertTrue(all(x['unsupported_resolution'] and x['delta_from_seed_px'] is None for x in r))
    def test_frozen_seed_exact(self):
        self.assertEqual(ENVELOPES['shop'],[345,915,1220,160]);self.assertEqual(ENVELOPES['bench'],[358,682,1038,146])

class Collection(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'session'
    def frame(self,i=0):return SimpleNamespace(id=i,pts_ms=i*1000.,width=20,height=10,rgb=bytes([i%255,12,30])*200)
    def close(self,s):return s.close(dict(session_id='fixture',source={'sha256':'fixture','path':'not-a-real-video'},execution_complete=True,versions={}))
    def test_latest_not_fifo(self):
        q=Latest();q.put(1);q.put(2);self.assertEqual(q.get(),2);self.assertEqual(q.replaced,1)
    def test_no_existing_output_overwrite(self):
        self.root.mkdir()
        with self.assertRaises(ValueError):Store(self.root)
    def test_png_pixels_match_source_and_no_labels(self):
        s=Store(self.root,reserve_bytes=0);f=self.frame();s.emit('periodic',dict(frame_id=0),f,True);self.close(s)
        m=load_json(self.root/'training-manifest.json');r=m['samples'][0]
        with Image.open(self.root/r['image']) as im:self.assertEqual(im.tobytes(),f.rgb)
        self.assertIsNone(r['targets']);self.assertFalse(r['neural_predictions_are_labels'])
        self.assertEqual(sha(self.root/r['image']),r['image_sha256'])
    def test_duplicate_frame_gets_late_reader_crops(self):
        s=Store(self.root,reserve_bytes=0);f=self.frame();s.emit('periodic',dict(frame_id=0),f,True)
        s.emit('roi-observations',dict(frame_id=0,regions=[dict(id='hud.gold',box=[0,0,4,4],status='unknown')]),f,True)
        self.close(s);m=load_json(self.root/'training-manifest.json')
        self.assertEqual(len(m['samples']),1);self.assertEqual(len(m['samples'][0]['crops']),1)
    def test_invalid_neural_box_never_cropped(self):
        s=Store(self.root,reserve_bytes=0);s.emit('mapping-events',dict(regions=[dict(id='neural.bench',box=[-1,0,8,8],status='unknown')]),self.frame(),True)
        self.close(s);m=load_json(self.root/'training-manifest.json');self.assertEqual(m['samples'][0]['crops'],[])
    def test_sample_limit_explicit(self):
        s=Store(self.root,max_samples=1,reserve_bytes=0)
        for i in range(2):s.emit('periodic',dict(frame_id=i),self.frame(i),True)
        r=self.close(s);self.assertEqual(r['collection']['samples_saved'],1);self.assertEqual(r['collection']['sample_limit_skipped'],1)
    def test_corrupted_session_rejected(self):
        s=Store(self.root,reserve_bytes=0);s.emit('periodic',dict(frame_id=0),self.frame(),True);self.close(s)
        (self.root/'samples/000000000.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):verify_session(self.root)
    def test_neural_only_cannot_create_training_seed(self):
        s=Store(self.root,reserve_bytes=0);s.emit('mapping-events',dict(regions=[dict(id='neural.bench',box=[0,0,8,8],status='coarse_candidate')]),self.frame(),True)
        self.close(s);r=prepare(self.root);self.assertEqual(r['records'],0);self.assertFalse(r['ready_for_experimental_training'])
    def test_no_annotations_during_collection(self):
        s=Store(self.root,reserve_bytes=0);self.close(s);self.assertFalse((self.root/'supervision').exists())
    def test_finalize_twice_rejected(self):
        s=Store(self.root,reserve_bytes=0);self.close(s)
        with self.assertRaises(RuntimeError):self.close(s)

if __name__=='__main__':unittest.main()
