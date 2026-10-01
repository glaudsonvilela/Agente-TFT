"""S4 mandatory integration: unchanged native reader plus a versioned UI patch."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from training.shop_controls_profile import decode_signature
from training.shop_controls_patch_run import execute, preflight
from training.shop_replay_observe import run, sha
from training.tests.test_shop_replay_native import png, paint
from training.tests.test_shop_controls_native import paint_control

ROOT = Path(__file__).resolve().parents[2]


class NativePatchTests(unittest.TestCase):
    def test_frozen_reader_with_data_patch_and_no_invented_numbers(self):
        required = os.environ.get('TFT_REQUIRE_SHOP4_NATIVE') == '1'
        executable = os.environ.get('TFT_SHOP4_PROBE')
        if not executable or not Path(executable).is_file() or not shutil.which('ffmpeg') or not shutil.which('tesseract'):
            if required:
                self.fail('required S4 native tools missing')
            self.skipTest('S4 integration mandatory in HUD media')
        layout_path = ROOT / 'configs/ui/match001-desktop-1920x1080-ptbr-v1.json'
        recovery_path = ROOT / 'configs/ui/match001-shop-recovery-v2.json'
        controls_path = ROOT / 'configs/ui/match001-shop-controls-v1.json'
        layout = json.loads(layout_path.read_text())
        recovery = json.loads(recovery_path.read_text())
        base = json.loads(controls_path.read_text())
        production_patch = json.loads((ROOT / 'configs/ui/match001-shop-controls-v2-patch.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixels = bytearray(1920 * 1080 * 3)
            for a in layout['panel_anchors'] + recovery['anchors']:
                paint(pixels, 1920, a['rect'], a['pixels'], a['grid_width'], a['grid_height'])
            a = layout['empty_template']
            for slot in layout['slots']:
                paint(pixels, 1920, slot['empty_region'], a['pixels'], a['grid_width'], a['grid_height'])
            for spec, choice in zip(base['controls'], (0, 0, 1)):
                paint_control(pixels, 1920, spec, choice)
            for spec in base['controls']:
                for key in ('price_rect', 'free_count_rect'):
                    if spec[key]:
                        paint(pixels, 1920, spec[key], [0], 1, 1)
            for op in production_patch['rectangles']:
                paint(pixels, 1920, op['rect'], [0], 1, 1)
            png(root / 'visible.png', 1920, 1080, pixels)
            png(root / 'hidden.png', 1920, 1080, bytearray(1920*1080*3))
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(frames=[dict(image='visible.png', timestamp_ms=100),
                                                       dict(image='hidden.png', timestamp_ms=350)])))
            spec = base['controls'][2]
            rgb, _ = decode_signature(root / 'visible.png', spec)
            expected = []
            r = spec['rect']
            for y in range(spec['grid_height']):
                sy = r['y'] + (2*y+1)*r['height']//(2*spec['grid_height'])
                for x in range(spec['grid_width']):
                    sx = r['x'] + (2*x+1)*r['width']//(2*spec['grid_width'])
                    at = (sy*1920+sx)*3
                    expected.extend(pixels[at:at+3])
            self.assertEqual(rgb, expected)
            with redirect_stdout(io.StringIO()):
                run(argparse.Namespace(manifest=manifest, image_root=root, layout=layout_path,
                    recovery_profile=recovery_path, controls_profile=controls_path, probe=Path(executable),
                    output=root / 's3', release=None, context=None))
            patch = dict(production_patch)
            patch['additional_templates'] = [dict(control='refresh',state='free_refresh_appearance',
                image='visible.png', sha256=sha(root / 'visible.png'))]
            patch_path = root / 'patch.json'
            patch_path.write_text(json.dumps(patch))
            args = argparse.Namespace(baseline=root/'s3/report.json', manifest=manifest,image_root=root,
                layout=layout_path,recovery_profile=recovery_path,base_controls=controls_path,
                patch=patch_path,probe=Path(executable),output=root/'s4')
            with redirect_stdout(io.StringIO()):
                result = execute(args)
            self.assertTrue(result['summary']['execution_complete'])
            self.assertTrue(result['summary']['card_observations_unchanged'])
            self.assertTrue(result['summary']['non_refresh_visuals_unchanged'])
            self.assertFalse(result['summary']['compiled'])
            report = json.loads((root/'s4/run/report.json').read_text())
            for row in report['records']:
                self.assertTrue(all(n['value'] is None for n in row['controls']['numeric_fields']))
            self.assertEqual(report['records'][1]['controls']['controls'][2]['status'], 'unavailable')
            self.assertFalse(report['summary']['controls_metrics']['closed_lock_reference_available'])
            with self.assertRaises(ValueError):
                execute(args)
            copied = root / 'changed-probe'
            copied.write_bytes(b'not the frozen executable')
            args.probe = copied
            with self.assertRaises(ValueError):
                preflight(args)
