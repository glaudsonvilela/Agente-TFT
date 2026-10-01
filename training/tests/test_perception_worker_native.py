"""Required media CI: actual reserved worker -> Rust pair -> audit -> A14 -> A15.

Synthetic marker with blank digits, not a real TFT accuracy/training benchmark.
No existing user registry is changed to make the test eligible.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from training.perception_registry import Registry
from training.perception_coordinator import Coordinator
from training.perception_work_source import sha256,publish,submit_observations
from training.perception_worker import Worker,now_ms


def png(path,pixels,width,height):
    def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    rows=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+
                     chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b''))


class NativeWorkerTests(unittest.TestCase):
    def test_real_native_reservation_lifecycle(self):
        executable=os.environ.get('TFT_A16_PROBE','')
        ready=bool(executable and Path(executable).is_file() and shutil.which('ffmpeg') and shutil.which('tesseract'))
        if not ready:
            if os.environ.get('TFT_REQUIRE_A16_NATIVE')=='1':self.fail('required A16 native backends absent')
            self.skipTest('native worker integration required in HUD media CI')
        probe=Path(executable).resolve()
        profile=Path('configs/player-list/match001-self-badge-v1.json').resolve()
        p=json.loads(profile.read_text())
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);images=root/'images';images.mkdir();store=root/'store';store.mkdir()
            frames=[]
            pixels=bytearray(1920*1080*3)
            for x,y in p['gold_points']:
                at=((340+y)*1920+1771+x)*3;pixels[at:at+3]=bytes([190,165,80])
            for i in range(24):
                pixels[0]=i+1;path=images/f'frame_{i:02d}.png';png(path,pixels,1920,1080)
                frames.append(dict(timestamp_ms=1000+250*i,image=path.name,sha256=sha256(path)))
            publish(root/'manifest.json',dict(frames=frames))
            # Actual observation producer for this fixture. Values are ignored by
            # scheduling; the blank HP region should yield unique-marker unknowns.
            env=os.environ.copy();env['OMP_THREAD_LIMIT']='1'
            subprocess.run([str(probe),str(root/'manifest.json'),str(images),str(profile),str(root/'initial.json')],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120,check=True,env=env)
            report=json.loads((root/'initial.json').read_text())
            samples=[]
            for f,r in zip(frames,report['records']):
                b=r['baseline'];self.assertEqual(b['status'],'ocr_uncertain')
                self.assertEqual(len(b['location']['candidates']),1)
                samples.append(dict(timestamp_ms=f['timestamp_ms'],image_sha256=f['sha256'],status=b['status'],marker='unique'))
            self.assertEqual(len(samples),24)
            context=dict(mode='offline_replay',subsystem='player_list',field='hp',recording_sha256='a'*64)
            baseline=dict(reader='hp1',executable_sha256=sha256(probe),config_sha256=sha256(profile))
            candidate=dict(baseline,reader='hp_text_fit_v1')
            reg=store/'registry.sqlite3';coord=store/'coordinator.sqlite3'
            with Registry(reg) as r:r.import_review(context,baseline,candidate,dict(synthetic_worker_fixture=True),[])
            inbox=store/'worker'/'sources';inbox.mkdir(parents=True)
            with Coordinator(reg,coord) as c:
                reservation=submit_observations(c,root,inbox,context,baseline,candidate,frames,samples,images,now_ms())
            self.assertTrue(reservation['intent_created'])
            with Worker(reg,coord,root,probe,profile) as w:result=w.drain()
            self.assertEqual(result['outcomes'],{'completed':1},result)
            self.assertTrue(result['native_probe_executed']);self.assertTrue(result['ocr_executed'])
            self.assertFalse(result['profile_promoted']);self.assertEqual(result['registry_revision_after'],2)
            self.assertEqual(result['results'][0]['metrics']['comparison'],{'neither_readable':24})
            with Worker(reg,coord,root,probe,profile) as w:again=w.drain()
            self.assertEqual(again['jobs_processed'],0)
            self.assertFalse(again['native_probe_executed'])
