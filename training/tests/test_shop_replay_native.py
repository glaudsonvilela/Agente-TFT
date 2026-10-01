"""Mandatory native S1 contract smoke in HUD media; not Match001 accuracy."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zlib
from training.shop_replay_observe import run


def png(path,width,height,pixels):
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+bytes(pixels[y*width*3:(y+1)*width*3]) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+
                     chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


def paint(pixels,width,rect,grid,gw,gh):
    for y in range(rect['height']):
        for x in range(rect['width']):
            value=grid[min(gh-1,y*gh//rect['height'])*gw+min(gw-1,x*gw//rect['width'])]
            at=((rect['y']+y)*width+rect['x']+x)*3
            pixels[at:at+3]=bytes([value])*3


class NativeShopTests(unittest.TestCase):
    def test_native_empty_unknown_and_hidden_are_distinct(self):
        required=os.environ.get('TFT_REQUIRE_SHOP1_NATIVE')=='1'
        executable=os.environ.get('TFT_SHOP1_PROBE')
        if not executable or not Path(executable).is_file() or not shutil.which('ffmpeg') or not shutil.which('tesseract'):
            if required:self.fail('required S1 native tools missing')
            self.skipTest('native shop test is mandatory in HUD media')
        project=Path(__file__).resolve().parents[2]
        profile=project/'configs/ui/match001-desktop-1920x1080-ptbr-v1.json'
        layout=json.loads(profile.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);w,h=1920,1080;pixels=bytearray([0])*(w*h*3)
            for a in layout['panel_anchors']:
                paint(pixels,w,a['rect'],a['pixels'],a['grid_width'],a['grid_height'])
            empty=layout['empty_template']
            for slot in layout['slots']:
                paint(pixels,w,slot['empty_region'],empty['pixels'],empty['grid_width'],empty['grid_height'])
            png(root/'empty.png',w,h,pixels)
            # One slot is no longer an empty marker, but contains no readable text.
            paint(pixels,w,layout['slots'][2]['empty_region'],[0],1,1)
            png(root/'uncertain.png',w,h,pixels)
            png(root/'hidden.png',w,h,bytearray(w*h*3))
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'frames':[dict(timestamp_ms=i*250,image=name)
                for i,name in enumerate(['empty.png','uncertain.png','hidden.png'])]}))
            with redirect_stdout(io.StringIO()):
                summary=run(argparse.Namespace(manifest=manifest,image_root=root,layout=profile,
                    probe=Path(executable),output=root/'out',release=None,context=None))
            report=json.loads((root/'out/report.json').read_text())
            self.assertEqual([s['status'] for s in report['records'][0]['read']['slots']],['empty_observed']*5)
            self.assertEqual(report['records'][1]['read']['slots'][2]['status'],'unknown')
            self.assertEqual([s['status'] for s in report['records'][2]['read']['slots']],['unavailable']*5)
            self.assertEqual(summary['ocr_process_calls'],2)
            self.assertFalse(summary['game_state_updated']);self.assertFalse(summary['model_trained'])
            self.assertIsNone(summary['exact_accuracy'])
            self.assertTrue((root/'out/COMPLETE.json').is_file())
