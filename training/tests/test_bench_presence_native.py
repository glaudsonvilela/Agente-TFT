"""Full B1 -> B2 native comparison; mandatory in the real-media CI job."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from training.board_spatial_run import run as run_b1
from training.bench_presence_run import run as run_b2, preflight
from training.bench_presence_evidence import blob_sha
ROOT=Path(__file__).resolve().parents[2]


class NativePresenceTests(unittest.TestCase):
    def test_real_bench_presence_and_unchanged_b1_without_ocr(self):
        binary=os.environ.get('TFT_BOARD1_PROBE')
        if not binary or not Path(binary).is_file() or not shutil.which('ffmpeg'):
            if os.environ.get('TFT_REQUIRE_BOARD1_NATIVE')=='1':self.fail('mandatory B2 native tools missing')
            self.skipTest('B2 native test mandatory in HUD media')
        from training.tests.test_shop_replay_native import png
        from training.shop_replay_observe import sha
        b=json.loads((ROOT/'configs/ui/match001-board-bench-v1.json').read_text())
        p=json.loads((ROOT/'configs/ui/match001-bench-presence-v1.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def paint(px,r,color):
                for y in range(r['y'],r['y']+r['height']):
                    for x in range(r['x'],r['x']+r['width']):
                        i=(y*1920+x)*3;px[i:i+3]=bytes(color)
            def texture(px,r):
                for y in range(r['y'],r['y']+r['height']):
                    for x in range(r['x'],r['x']+r['width']):
                        v=35 if (x//4+y//4)%2==0 else 70
                        paint(px,dict(x=x,y=y,width=1,height=1),[v,v+5,v+10])
            reference=bytearray(1920*1080*3)
            for a in b['arena_anchors']+p['surface_anchors']:texture(reference,a)
            for c in b['bench_centers']:
                texture(reference,dict(x=c-p['body_width']//2,y=p['body_top'],width=p['body_width'],height=p['body_height']))
            png(root/'reference.png',1920,1080,reference)
            b['reference_image']='reference.png';b['reference_sha256']=sha(root/'reference.png')
            b['geometry_source'].update(image='reference.png',sha256=b['reference_sha256'])
            profile=root/'profile.json';profile.write_text(json.dumps(b))
            p['parent_blob_sha1']=blob_sha(profile.read_bytes())
            policy=root/'presence.json';policy.write_text(json.dumps(p))
            images=[]
            for i in range(6):
                px=bytearray(reference)
                if i in (1,4):paint(px,dict(x=395,y=728,width=26,height=69),[180,180,180])
                if i in (1,5):paint(px,dict(x=385,y=694,width=64,height=4),[20,220,20])
                if i in (2,3):
                    for a in b['arena_anchors']:paint(px,a,[0,0,0])
                if i==3:
                    for a in p['surface_anchors']:paint(px,a,[0,0,0])
                name=f'frame-{i}.png';png(root/name,1920,1080,px)
                images.append(dict(image=name,timestamp_ms=i*250))
            manifest=root/'input.json';manifest.write_text(json.dumps(dict(frames=images,suggestions={'units':'not read'})))
            a=argparse.Namespace(manifest=manifest,image_root=root,profile=profile,
                board_topology=ROOT/'configs/topology/board-standard-4x7-v1.json',
                bench_topology=ROOT/'configs/topology/bench-nine-v1.json',probe=Path(binary),output=root/'b1')
            tools=root/'tools';tools.mkdir();sentinel=root/'ocr-was-called';trap=tools/'tesseract'
            trap.write_text(f'#!/bin/sh\ntouch "{sentinel}"\nexit 99\n');trap.chmod(0o755)
            with patch.dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH']),redirect_stdout(io.StringIO()):
                baseline=run_b1(a)
                a.baseline=root/'b1/report.json';a.presence_profile=policy;a.output=root/'b2'
                result=run_b2(a)
            self.assertFalse(sentinel.exists());self.assertTrue(result['regression']['b1_observations_unchanged'])
            rows=result['records']
            self.assertEqual(rows[0]['bench_presence']['slots'][0]['status'],'empty_visual')
            self.assertEqual(rows[1]['bench_presence']['slots'][0]['status'],'occupied_visual')
            self.assertEqual(rows[2]['bench_presence']['surface_status'],'bench_structure_match')
            self.assertEqual(rows[3]['bench_presence']['surface_status'],'unresolved')
            self.assertEqual(rows[4]['bench_presence']['slots'][0]['status'],'unknown')
            self.assertEqual(rows[5]['bench_presence']['slots'][0]['status'],'ambiguous')
            self.assertEqual([r['read'] for r in baseline['records']],[r['read'] for r in rows])
            self.assertTrue((root/'b2/COMPLETE.json').is_file())
            viewer=(root/'b2/native/viewer.html').read_text();self.assertIn('bench_presence',viewer);self.assertIn('data:image/png;base64,',viewer)
            self.assertFalse(result['summary']['game_state_updated']);self.assertEqual(result['summary']['ocr_process_calls'],0)
            with self.assertRaises(ValueError):run_b2(a)
            policy.write_text('{}')
            with self.assertRaises(ValueError):preflight(a)
