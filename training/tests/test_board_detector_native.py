"""Required B3 integration: real pretrained weights, Rust baseline and FFmpeg, not TFT accuracy."""
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

ROOT = Path(__file__).resolve().parents[2]


class PretrainedNativeTests(unittest.TestCase):
    def test_real_weights_and_frozen_native_baseline(self):
        binary = os.environ.get('TFT_BOARD3_B1_PROBE')
        if not binary or not Path(binary).is_file() or not shutil.which('ffmpeg'):
            if os.environ.get('TFT_REQUIRE_BOARD3_NATIVE')=='1':
                self.fail('B3 pretrained integration is mandatory in this job')
            self.skipTest('B3 pretrained integration runs in dedicated workflow')
        from training.tests.test_shop_replay_native import png
        from training.shop_replay_observe import sha
        from training.board_spatial_run import run as b1_run
        from training.board_detector_run import run, preflight
        p=json.loads((ROOT/'configs/ui/match001-board-bench-v1.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def paint(pixels,r,c):
                for y in range(r['y'],r['y']+r['height']):
                    for x in range(r['x'],r['x']+r['width']):
                        i=(y*1920+x)*3;pixels[i:i+3]=bytes(c)
            ref=bytearray(1920*1080*3)
            for a in p['arena_anchors']:
                paint(ref,a,[40,60,80]);paint(ref,dict(a,width=a['width']//2),[100,140,190])
            png(root/'reference.png',1920,1080,ref)
            p['reference_image']='reference.png';p['reference_sha256']=sha(root/'reference.png')
            p['geometry_source'].update(image='reference.png',sha256=p['reference_sha256'])
            rows=[]
            for index in range(2):
                image=bytearray(ref)
                if index:
                    paint(image,dict(x=600,y=400,width=50,height=120),[140,140,140])
                    paint(image,dict(x=600,y=375,width=64,height=4),[20,220,20])
                name=f'frame-{index}.png';png(root/name,1920,1080,image)
                rows.append(dict(image=name,timestamp_ms=index*250))
            profile=root/'profile.json';profile.write_text(json.dumps(p))
            manifest=root/'input.json';manifest.write_text(json.dumps(dict(frames=rows)))
            common=dict(manifest=manifest,image_root=root,profile=profile,
                board_topology=ROOT/'configs/topology/board-standard-4x7-v1.json',
                bench_topology=ROOT/'configs/topology/bench-nine-v1.json',probe=Path(binary))
            with redirect_stdout(io.StringIO()):b1_run(argparse.Namespace(**common,output=root/'b1'))
            args=argparse.Namespace(**common,baseline=root/'b1/report.json',
                detector_policy=ROOT/'configs/vision/board-open-vocabulary-v1.json',
                model_cache=Path(os.environ.get('TFT_BOARD3_MODEL_CACHE',str(root/'model-cache'))),
                output=root/'comparison')
            tools=root/'tools';tools.mkdir();marker=root/'ocr-called'
            trap=tools/'tesseract';trap.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n');trap.chmod(0o755)
            with patch.dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH']):
                report=run(args)
            self.assertFalse(marker.exists())
            self.assertTrue(report['regression']['b1_observations_unchanged'])
            self.assertEqual(report['summary']['model_forward_passes'],2)
            self.assertEqual(report['model']['model_class'],'GroundingDinoForObjectDetection')
            self.assertGreater(report['model']['pretrained_parameters'],100_000_000)
            self.assertEqual(report['summary']['weights_sha256'],
                '1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3')
            self.assertTrue((args.output/'COMPLETE.json').is_file())
            self.assertTrue((args.output/'viewer.html').is_file())
            self.assertFalse(report['summary']['model_trained'])
            self.assertIsNone(report['summary']['exact_accuracy'])
            for row in report['records']:
                self.assertEqual(len(row['comparison']['bench']),9)
                self.assertEqual(len(row['decoded_rgb_sha256']),64)
            # These images verify execution contracts, not semantic recognition.
            with self.assertRaises(ValueError):run(args)
            (root/'frame-0.png').write_bytes(b'changed')
            with self.assertRaises(ValueError):preflight(args)
