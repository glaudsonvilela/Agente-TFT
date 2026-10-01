"""Mandatory S3 native smoke: unchanged S2 cards, visible/dim/hidden controls."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from training.shop_controls_evidence import compare_cards
from training.shop_replay_observe import run
from training.tests.test_shop_replay_native import png, paint

ROOT = Path(__file__).resolve().parents[2]


def paint_control(pixels, width, spec, index):
    rect, rgb = spec['rect'], spec['templates'][index]['rgb']
    gw, gh = spec['grid_width'], spec['grid_height']
    for y in range(rect['height']):
        for x in range(rect['width']):
            src = (y * gh // rect['height'] * gw + x * gw // rect['width']) * 3
            dst = ((rect['y'] + y) * width + rect['x'] + x) * 3
            pixels[dst:dst+3] = bytes(rgb[src:src+3])


class NativeControlsTests(unittest.TestCase):
    def test_real_controls_do_not_change_card_observations(self):
        required = os.environ.get('TFT_REQUIRE_SHOP3_NATIVE') == '1'
        executable = os.environ.get('TFT_SHOP3_PROBE')
        if not executable or not Path(executable).is_file() or not shutil.which('ffmpeg') or not shutil.which('tesseract'):
            if required: self.fail('required S3 native tools missing')
            self.skipTest('S3 native integration required in HUD media')
        layout_path = ROOT / 'configs/ui/match001-desktop-1920x1080-ptbr-v1.json'
        recovery_path = ROOT / 'configs/ui/match001-shop-recovery-v2.json'
        controls_path = ROOT / 'configs/ui/match001-shop-controls-v1.json'
        layout = json.loads(layout_path.read_text())
        recovery = json.loads(recovery_path.read_text())
        controls = json.loads(controls_path.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for i, choices in enumerate([(0,0,0), (0,1,2), (0,0,1), None]):
                pixels = bytearray(1920*1080*3)
                if choices is not None:
                    for a in layout['panel_anchors'] + recovery['anchors']:
                        paint(pixels, 1920, a['rect'], a['pixels'], a['grid_width'], a['grid_height'])
                    a = layout['empty_template']
                    for slot in layout['slots']:
                        paint(pixels, 1920, slot['empty_region'], a['pixels'], a['grid_width'], a['grid_height'])
                    for spec, choice in zip(controls['controls'], choices):
                        paint_control(pixels, 1920, spec, choice)
                    # Blank numeric ROIs must not manufacture customary prices 4/2.
                    for spec in controls['controls']:
                        for key in ('price_rect', 'free_count_rect'):
                            if spec[key]: paint(pixels, 1920, spec[key], [0], 1, 1)
                image = f'frame-{i}.png'
                png(root / image, 1920, 1080, pixels)
                rows.append(dict(timestamp_ms=i*250, image=image))
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(frames=rows)))
            for extra, name in [(None, 's2'), (controls_path, 's3')]:
                with redirect_stdout(io.StringIO()):
                    run(argparse.Namespace(manifest=manifest, image_root=root, layout=layout_path,
                        probe=Path(executable), output=root/name, recovery_profile=recovery_path,
                        controls_profile=extra, release=None, context=None))
            self.assertTrue(compare_cards(root/'s2/report.json', root/'s3/report.json')['card_observations_unchanged'])
            report = json.loads((root/'s3/report.json').read_text())
            for row, choices in zip(report['records'][:3], [(0,0,0), (0,1,2), (0,0,1)]):
                self.assertEqual([c['appearance'] for c in row['controls']['controls']],
                    [s['templates'][i]['state'] for s,i in zip(controls['controls'], choices)])
                self.assertTrue(all(n['value'] is None for n in row['controls']['numeric_fields']))
                self.assertEqual(row['controls']['ocr_process_calls'], 2)
            self.assertTrue(all(c['status'] == 'unavailable' for c in report['records'][3]['controls']['controls']))
            self.assertEqual(report['summary']['controls_ocr_process_calls'], 6)
            self.assertFalse(report['summary']['game_state_updated'])
            self.assertFalse(report['summary']['controls_metrics']['closed_lock_reference_available'])
