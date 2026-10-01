"""Mandatory B1 native integration. Synthetic geometry is not TFT accuracy."""
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
from training.board_spatial_run import run, preflight

ROOT = Path(__file__).resolve().parents[2]


class NativeSpatialTests(unittest.TestCase):
    def test_real_decoder_and_native_reader_without_ocr(self):
        binary = os.environ.get('TFT_BOARD1_PROBE')
        if not binary or not Path(binary).is_file() or not shutil.which('ffmpeg'):
            if os.environ.get('TFT_REQUIRE_BOARD1_NATIVE') == '1':
                self.fail('required B1 native tools missing')
            self.skipTest('B1 integration is mandatory in HUD media')
        from training.tests.test_shop_replay_native import png
        from training.shop_replay_observe import sha
        p = json.loads((ROOT/'configs/ui/match001-board-bench-v1.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def paint(pixels, r, color):
                for y in range(r['y'], r['y']+r['height']):
                    for x in range(r['x'], r['x']+r['width']):
                        i = (y*1920+x)*3
                        pixels[i:i+3] = bytes(color)
            reference = bytearray(1920*1080*3)
            for a in p['arena_anchors']:
                paint(reference, a, [40, 60, 80])
                paint(reference, dict(a, width=a['width']//2), [100, 140, 190])
            png(root/'reference.png', 1920, 1080, reference)
            p['reference_image'] = 'reference.png'
            p['reference_sha256'] = sha(root/'reference.png')
            p['geometry_source'].update(image='reference.png', sha256=p['reference_sha256'])
            images = []
            for index in range(3):
                pixels = bytearray(reference) if index < 2 else bytearray(1920*1080*3)
                paint(pixels, dict(x=385 if index else 600, y=694 if index else 350, width=64, height=4), [20, 220, 20])
                name = f'frame-{index}.png'
                png(root/name, 1920, 1080, pixels)
                images.append(dict(image=name, timestamp_ms=index*250))
            profile = root/'profile.json'
            profile.write_text(json.dumps(p))
            manifest = root/'input.json'
            manifest.write_text(json.dumps(dict(frames=images, suggestions={'not_used': True})))
            args = argparse.Namespace(manifest=manifest, image_root=root, profile=profile,
                board_topology=ROOT/'configs/topology/board-standard-4x7-v1.json',
                bench_topology=ROOT/'configs/topology/bench-nine-v1.json', probe=Path(binary), output=root/'result')
            fake = root/'tools'
            fake.mkdir()
            marker = root/'ocr-was-called'
            trap = fake/'tesseract'
            trap.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n')
            trap.chmod(0o755)
            with patch.dict(os.environ, PATH=str(fake)+os.pathsep+os.environ['PATH']), redirect_stdout(io.StringIO()):
                report = run(args)
            self.assertFalse(marker.exists())
            self.assertEqual(report['summary']['ocr_process_calls'], 0)
            self.assertEqual(report['summary']['projection_statuses'], {'reference_arena_match': 2, 'unresolved': 1})
            self.assertEqual(report['records'][1]['read']['bench'][0]['evidence'], 'bar_candidate')
            self.assertTrue(all(b['evidence'] == 'projection_unavailable' for b in report['records'][2]['read']['bench']))
            self.assertTrue((root/'result/viewer.html').is_file())
            self.assertTrue((root/'result/COMPLETE.json').is_file())
            self.assertFalse(report['summary']['occupancy_established'])
            with self.assertRaises(ValueError): run(args)
            (root/'reference.png').write_bytes(b'changed')
            with self.assertRaises(ValueError): preflight(args)
