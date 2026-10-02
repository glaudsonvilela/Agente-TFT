"""Unit/real media tests. Mocks are explicit, native integration is separate."""
import json, queue, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
from e1.pipeline import Options, Session, Latest, explanation
from e1.source import Frame, VideoSource, local_video, fixture_frames
from e1.metrics import Journal, quantiles

class WorkerFixture:
    """Protocol test double, never used by the product."""
    ready={'ocr_available':True,'pid':-1}
    def __init__(self,*a):pass
    def request(self,h,payload=b'',timeout=12):
        return dict(id=h['id'],source_ms=h['source_ms'],origin='fixture_input',state={'revision':h['id']},
                    report={'all':[{}]},decision={'action':{'type':'hold_econ'},'evidence':[]},spans=[],blockers=[])
    def close(self):pass

class Contracts(unittest.TestCase):
    def test_latest_bounded(self):
        q=Latest();self.assertIsNone(q.put(1));self.assertEqual(q.put(2),1);self.assertEqual(q.get(),2)
    def test_percentiles_from_traces(self):
        q=quantiles([1,2,100]);self.assertEqual(q['n'],3);self.assertEqual(q['p50_ms'],2)
    def test_absence_not_zero(self):self.assertIsNone(quantiles([])['p95_ms'])
    def test_live_source_rejected(self):
        with self.assertRaises(ValueError):Options('w','c','o',mode='live').validate()
    def test_network_not_video(self):
        with self.assertRaises(ValueError):local_video('https://example.com/a.mp4')
    def test_no_missing_video(self):
        with self.assertRaises(ValueError):Options('w','c','o',mode='replay').validate()
    def test_budget(self):
        for d in [0,601,float('nan')]:
            with self.assertRaises(ValueError):Options('w','c','o',seconds=d).validate()
    def test_output_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileExistsError):Journal(d)
    def test_output_sealed(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'out');j.emit({'event':'x'});j.close({'execution_complete':True})
            self.assertTrue((j.path/'COMPLETE.json').is_file())
    def test_fixture_is_not_ocr(self):
        fs=list(fixture_frames(threading.Event(),.01));self.assertEqual(len(fs),0)
    def test_causal_fixture_clock(self):
        fs=list(fixture_frames(threading.Event(),.5,4));self.assertEqual([x.id for x in fs],[0,1])
        self.assertTrue(all(f.ready_ns>=f.due_ns for f in fs))
    def test_explanation_keeps_origin(self):
        a=WorkerFixture().request({'id':1,'source_ms':0});self.assertIn('CONTROLADO',explanation(a)[0])
    def test_visual_not_fake_tip(self):
        a=WorkerFixture().request({'id':1,'source_ms':0});a['origin']='observed_pixels'
        self.assertEqual(explanation(a)[1],'abstention')
    def test_mocked_scheduler_not_native_claim(self):
        with tempfile.TemporaryDirectory() as d:
            o=Options('mock','mock',str(Path(d)/'out'),seconds=1,reader_hz=30,injected_wait_ms=300)
            s=Session(o,WorkerFixture).start()
            while not s.done.is_set() or not s.results.empty():
                try:s.acknowledge(s.results.get(.03),'headless_test_double')
                except queue.Empty:pass
            r=s.finish();self.assertTrue(r['execution_complete']);self.assertEqual(r['source_to_tk_apply']['n'],0)
            self.assertEqual(s.counts['source_frames'],4);self.assertGreater(s.counts['processed'],0)
    def test_cpu_delay_does_not_pause_producer(self):
        with tempfile.TemporaryDirectory() as d:
            s=Session(Options('m','c',str(Path(d)/'o'),seconds=1,reader_hz=30,injected_wait_ms=700),WorkerFixture).start()
            s.thread.join(6);self.assertTrue(s.done.is_set())
            r=s.finish();self.assertEqual(r['counts']['source_frames'],4);self.assertGreater(r['counts'].get('reader_pending_superseded',0),0)

class Media(unittest.TestCase):
    def test_real_ffmpeg_pts_and_rgb(self):
        import shutil,subprocess
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'closed.mkv'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=96x64:r=5:d=0.6','-c:v','ffv1',str(p)],check=True)
            src=VideoSource(p)
            try:fs=list(src.frames(threading.Event(),1))
            finally:src.close()
            self.assertEqual(len(fs),3);self.assertEqual([round(f.pts_ms) for f in fs],[0,200,400]);self.assertEqual(len(fs[0].rgb),96*64*3)
