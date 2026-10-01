"""S5 mandatory native isolation check; synthetic UI is not Match001 accuracy."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from training.shop_controls_patch_run import execute as run_patch
from training.shop_numbers_run import execute, preflight
from training.shop_replay_observe import run, sha
from training.tests.test_shop_replay_native import png, paint
from training.tests.test_shop_controls_native import paint_control

ROOT=Path(__file__).resolve().parents[2]


def digit4(pixels):
    # Same synthetic XP glyph in three otherwise different control states.
    for y,row in enumerate(('10010','10010','10010','11111','00010','00010','00010')):
        for x,bit in enumerate(row):
            for dy in range(2):
                for dx in range(2):
                    at=((970+y*2+dy)*1920+390+x*2+dx)*3
                    pixels[at:at+3]=bytes([235 if bit=='1' else 0]*3)


class NativeNumbersTests(unittest.TestCase):
    def test_complete_s4_to_s5_with_independent_xp_and_unchanged_cards(self):
        required=os.environ.get('TFT_REQUIRE_SHOP5_NATIVE')=='1'
        executable=os.environ.get('TFT_SHOP5_PROBE')
        if not executable or not Path(executable).is_file() or not shutil.which('ffmpeg') or not shutil.which('tesseract'):
            if required:self.fail('required S5 native tools missing')
            self.skipTest('S5 native integration mandatory in HUD media')
        ui=ROOT/'configs/ui/match001-desktop-1920x1080-ptbr-v1.json'
        recovery_path=ROOT/'configs/ui/match001-shop-recovery-v2.json'
        base_path=ROOT/'configs/ui/match001-shop-controls-v1.json'
        policy_path=ROOT/'configs/ui/match001-shop-isolated-numbers-v1.json'
        layout=json.loads(ui.read_text());recovery=json.loads(recovery_path.read_text());base=json.loads(base_path.read_text())
        patch=json.loads((ROOT/'configs/ui/match001-shop-controls-v2-patch.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=[]
            for i,choice in enumerate((0,1,1,None)):
                pixels=bytearray(1920*1080*3)
                if choice is not None:
                    for a in layout['panel_anchors']+recovery['anchors']:
                        paint(pixels,1920,a['rect'],a['pixels'],a['grid_width'],a['grid_height'])
                    a=layout['empty_template']
                    for slot in layout['slots']:
                        paint(pixels,1920,slot['empty_region'],a['pixels'],a['grid_width'],a['grid_height'])
                    for spec,index in zip(base['controls'],(0,0,choice)):
                        paint_control(pixels,1920,spec,index)
                    for spec in base['controls']:
                        for key in ('price_rect','free_count_rect'):
                            if spec[key]:paint(pixels,1920,spec[key],[0],1,1)
                    for op in patch['rectangles']:paint(pixels,1920,op['rect'],[0],1,1)
                    digit4(pixels)
                    if i==2:
                        # Alter other fields only; the XP crop stays byte-identical.
                        r=patch['rectangles'][1]['rect']
                        paint(pixels,1920,r,[0,220,220,0],2,2)
                name=f'f{i}.png';png(root/name,1920,1080,pixels)
                rows.append(dict(image=name,timestamp_ms=100+i*250))
            manifest=root/'manifest.json';manifest.write_text(json.dumps(dict(frames=rows)))
            patch['additional_templates']=[dict(control='refresh',state='free_refresh_appearance',
                                               image='f1.png',sha256=sha(root/'f1.png'))]
            patch_path=root/'patch.json';patch_path.write_text(json.dumps(patch))
            with redirect_stdout(io.StringIO()):
                run(argparse.Namespace(manifest=manifest,image_root=root,layout=ui,recovery_profile=recovery_path,
                    controls_profile=base_path,probe=Path(executable),output=root/'s3',release=None,context=None))
                run_patch(argparse.Namespace(baseline=root/'s3/report.json',manifest=manifest,image_root=root,
                    layout=ui,recovery_profile=recovery_path,base_controls=base_path,patch=patch_path,
                    probe=Path(executable),output=root/'s4'))
                args=argparse.Namespace(baseline=root/'s4/report.json',manifest=manifest,image_root=root,layout=ui,
                    recovery_profile=recovery_path,numbers_profile=policy_path,probe=Path(executable),output=root/'s5')
                result=execute(args)
            self.assertTrue(result['summary']['execution_complete'])
            self.assertTrue(result['summary']['native_binary_unchanged'])
            self.assertEqual(result['summary']['baseline_binary_sha256'], sha(Path(executable)))
            self.assertTrue(result['summary']['visual_observations_unchanged'])
            self.assertTrue(result['summary']['card_observations_unchanged'])
            report=json.loads((root/'s5/run/report.json').read_text())
            observed=[r['controls'] for r in report['records']]
            self.assertEqual([r['ocr_process_calls'] for r in observed],[4,6,6,0])
            self.assertEqual(observed[0]['numeric_fields'][0],observed[1]['numeric_fields'][0])
            self.assertEqual(observed[0]['numeric_fields'][0],observed[2]['numeric_fields'][0])
            self.assertEqual(observed[0]['numeric_fields'][1]['rect']['x'],387)
            self.assertEqual(observed[1]['numeric_fields'][1]['rect']['x'],379)
            self.assertTrue(all(n['value'] is None for n in observed[3]['numeric_fields']))
            self.assertIsNone(observed[1]['numeric_fields'][1]['value'])
            self.assertIsNone(observed[1]['numeric_fields'][2]['value'])
            self.assertFalse(report['summary']['game_state_updated'])
            with self.assertRaises(ValueError):execute(args)
            data=(root/'s4/report.json').read_bytes();(root/'s4/report.json').write_bytes(data+b' ')
            with self.assertRaises(ValueError):preflight(args)
