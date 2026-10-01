import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from training import player_hp_text_fit as m

class TextFitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'hp2';self.source.mkdir()
        m.write(self.source/'prepared.json',{'complete':True})
        m.write(self.source/'plan.json',{'windows':[{'id':'window-00'}]})
        self.window=self.source/'window-00';self.window.mkdir()
        self.image=self.window/'a.ppm';self.image.write_bytes(b'P6\n1 1\n255\n\x00\x00\x00')
        self.manifest={'frames':[{'timestamp_ms':100,'image':'a.ppm','sha256':m.sha256(self.image)}]}
        m.write(self.window/'manifest.json',self.manifest)
    def tearDown(self):self.tmp.cleanup()
    def test_plan_strips_labels_and_preserves_source_identity(self):
        x=m.load(self.window/'manifest.json');x['frames'][0]['expected']=56
        (self.window/'manifest.json').write_text(json.dumps(x))
        p=m.batches(self.source,None,None)
        self.assertEqual(set(p[0]['frames'][0]),{'timestamp_ms','image','sha256'})
        self.assertEqual(p[0]['frames'][0]['timestamp_ms'],100)
    def test_modified_source_image_rejected(self):
        self.image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash'):m.batches(self.source,None,None)
    def test_missing_hash_rejected_for_dense(self):
        x=copy.deepcopy(self.manifest);del x['frames'][0]['sha256']
        with self.assertRaisesRegex(ValueError,'hash'):m.validate_manifest(x,self.window,True)
    def test_duplicate_image_and_timestamp_rejected(self):
        x=copy.deepcopy(self.manifest);x['frames']*=2
        with self.assertRaises(ValueError):m.validate_manifest(x,self.window,True)
        x['frames'][1]=dict(x['frames'][1],timestamp_ms=350)
        with self.assertRaisesRegex(ValueError,'reused'):m.validate_manifest(x,self.window,True)
    def test_traversal_and_symlink_escape_rejected(self):
        for name in ('../a.ppm','/etc/passwd',''):
            with self.assertRaises(ValueError):m.contained(self.window,name)
        (self.window/'escape').symlink_to(self.source/'prepared.json')
        with self.assertRaises(ValueError):m.contained(self.window,'escape')
    def test_window_id_cannot_escape(self):
        (self.source/'plan.json').write_text(json.dumps({'windows':[{'id':'../window-00'}]}))
        with self.assertRaises(ValueError):m.batches(self.source,None,None)
    def test_incomplete_extraction_rejected(self):
        (self.source/'prepared.json').write_text('{"complete":false}')
        with self.assertRaisesRegex(ValueError,'incomplete'):m.batches(self.source,None,None)
    def test_unique_write_refuses_overwrite(self):
        with self.assertRaises(FileExistsError):m.write(self.window/'manifest.json',{})
    def test_sparse_has_own_group_and_no_expected(self):
        p=m.batches(self.source,self.window/'manifest.json',self.window)
        self.assertEqual([b['kind'] for b in p],['targeted_dense','sparse_regression'])
    def report(self):
        read={'timestamp_ms':100,'status':'ocr_uncertain','signed_hp':None,'location':{'candidates':[]}}
        return {'summary':{'execution_complete':True,'errors':0,'frames':1,'labels_used':False,
            'game_state_updated':False,'profile_promoted':False,'model_trained':False,
            'baseline_statuses':{'ocr_uncertain':1},'candidate_statuses':{'ocr_uncertain':1},
            'comparison':{'neither_readable':1}},
            'records':[{'timestamp_ms':100,'baseline':copy.deepcopy(read),'candidate':copy.deepcopy(read),'comparison':'neither_readable'}]}
    def test_summary_matches_native_records(self):
        report=self.report();m.verify_report(report,self.manifest)
        report['summary']['comparison']={'both_readable_equal':1}
        with self.assertRaisesRegex(ValueError,'summary'):m.verify_report(report,self.manifest)
    def test_mismatched_native_pair_timestamp_rejected(self):
        r=self.report();r['records'][0]['candidate']['timestamp_ms']=99
        with self.assertRaisesRegex(ValueError,'timestamp'):m.verify_report(r,self.manifest)
    def test_changed_localization_rejected(self):
        r=self.report();r['records'][0]['candidate']['location']={'candidates':[{}]}
        with self.assertRaisesRegex(ValueError,'localization'):m.verify_report(r,self.manifest)
    def test_state_or_promotion_not_allowed(self):
        r=self.report();r['summary']['profile_promoted']=True
        with self.assertRaisesRegex(ValueError,'diagnostic'):m.verify_report(r,self.manifest)
    def test_disagreement_is_not_promoted_to_agreement(self):
        r=self.report()
        r['records'][0]['baseline'].update(status='accepted',signed_hp=36)
        r['records'][0]['candidate'].update(status='accepted',signed_hp=56)
        with self.assertRaisesRegex(ValueError,'classification'):m.verify_report(r,self.manifest)
    def test_timeout_kills_process_group(self):
        fake=unittest.mock.Mock();fake.pid=123
        fake.wait.side_effect=[subprocess.TimeoutExpired('fixture',1),-9]
        with patch.object(m.subprocess,'Popen',return_value=fake),patch.object(m.os,'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError,'timeout'):
                m.run_child(['fixture'],self.root/'out.log',self.root/'err.log',timeout=1)
            kill.assert_called_once_with(123,m.signal.SIGKILL)
    def test_native_fit_path_with_real_media_and_ocr(self):
        binary=os.environ.get('TFT_HP3_PROBE')
        required=os.environ.get('TFT_REQUIRE_HP3_NATIVE')=='1'
        available=binary and Path(binary).is_file() and shutil.which('ffmpeg') and shutil.which('tesseract')
        if not available:
            if required:self.fail('native HP3 integration required but dependencies missing')
            self.skipTest('requires compiled HP3, FFmpeg and Tesseract')
        repo=Path(__file__).resolve().parents[2]
        profile=repo/'configs/player-list/match001-self-badge-v1.json'
        p=m.load(profile)
        w,h=1920,1080;pixels=bytearray(w*h*3)
        def pixel(x,y,rgb):
            i=(y*w+x)*3;pixels[i:i+3]=bytes(rgb)
        ax,ay=1771,340
        for dx,dy in p['gold_points']:pixel(ax+dx,ay+dy,[190,165,80])
        # Synthetic disconnected sign + strokes; checks the real preparation path,
        # not numerical accuracy of an artificial typeface.
        hx,hy=ax+p['hp_offset_x'],ay+p['hp_offset_y']
        for y in range(6,22):
            for x in range(21,32):pixel(hx+x,hy+y,[230,230,230])
        for y in range(15,17):
            for x in range(13,19):pixel(hx+x,hy+y,[230,230,230])
        self.image.write_bytes(f'P6\n{w} {h}\n255\n'.encode()+pixels)
        mpath=self.root/'native-manifest.json'
        m.write(mpath,{'frames':[{'timestamp_ms':100,'image':'a.ppm'}]})
        report=self.root/'native-report.json'
        result=subprocess.run([binary,str(mpath),str(self.window),str(profile),str(report)],capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        native=m.load(report);s=m.verify_report(native,self.manifest)
        self.assertEqual(s['text_fitted_frames'],1)
        self.assertEqual(len(native['records'][0]['text_fit']),2)
        self.assertFalse(s['profile_promoted'])
        result=subprocess.run([binary,str(mpath),str(self.window),str(profile),str(report)],capture_output=True,timeout=30)
        self.assertNotEqual(result.returncode,0)

if __name__=='__main__':unittest.main()
