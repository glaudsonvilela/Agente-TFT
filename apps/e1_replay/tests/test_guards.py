"""Regression guards for snapshot provenance, cancellation and honest UI metrics."""
import json, queue, tempfile, threading, time, unittest
from pathlib import Path
from e1.metrics import Journal
from e1.pipeline import Options, Session, explanation
from test_e1 import WorkerFixture

class Guards(unittest.TestCase):
    def test_queued_trace_is_a_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'run')
            event={'event':'decision','trace':{'ui_apply_ns':None,'raw':[1,2]}}
            j.emit(event);event['trace']['ui_apply_ns']=99;event['trace']['raw'][0]=9
            j.close({'execution_complete':True})
            r=json.loads((j.path/'trace.jsonl').read_text())
            self.assertIsNone(r['trace']['ui_apply_ns']);self.assertEqual(r['trace']['raw'],[1,2])
    def test_headless_not_labelled_tk(self):
        with tempfile.TemporaryDirectory() as d:
            s=Session(Options('mock','mock',str(Path(d)/'run'),seconds=1),WorkerFixture).start()
            while not s.done.is_set() or not s.results.empty():
                try:s.acknowledge(s.results.get(.1),'headless_test')
                except queue.Empty:pass
            r=s.finish()
            self.assertEqual(r['source_to_tk_apply']['n'],0)
            self.assertEqual(r['capabilities']['native_engine'],'test_double')
            self.assertEqual(r['counts'].get('ui_applied',0),0)
    def test_stop_returns_without_waiting_for_child_close(self):
        class SlowClose(WorkerFixture):
            def close(self):time.sleep(.3)
        with tempfile.TemporaryDirectory() as d:
            s=Session(Options('mock','mock',str(Path(d)/'run'),seconds=5),SlowClose).start()
            until=time.monotonic()+2
            while s.worker is None and time.monotonic()<until:time.sleep(.01)
            t=time.monotonic();s.stop();self.assertLess(time.monotonic()-t,.1)
            s.thread.join(5);self.assertTrue(s.done.is_set());r=s.finish();self.assertFalse(r['execution_complete'])
    def test_double_finish_refused(self):
        with tempfile.TemporaryDirectory() as d:
            s=Session(Options('mock','mock',str(Path(d)/'run'),seconds=1),WorkerFixture).start()
            s.thread.join(3);s.finish()
            with self.assertRaises(RuntimeError):s.finish()
