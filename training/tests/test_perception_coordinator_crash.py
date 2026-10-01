import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from training.perception_registry import Registry
from training.perception_coordinator import Coordinator
from training.tests.test_perception_coordinator import identities, samples


class CrashTests(unittest.TestCase):
    def test_abrupt_process_exit_before_commit_leaves_no_intent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);reg=root/'registry.sqlite3';db=root/'coordinator.sqlite3'
            context,baseline,candidate=identities()
            with Registry(reg) as r:r.import_review(context,baseline,candidate,{'fixture':1},[])
            with Coordinator(reg,db):pass
            script="""
import os,sys
from pathlib import Path
from training.perception_coordinator import Coordinator
from training.tests.test_perception_coordinator import identities,samples
with Coordinator(Path(sys.argv[1]),Path(sys.argv[2])) as c:
    save=c._save
    def crash(state):
        save(state)
        os._exit(77)
    c._save=crash
    context,baseline,candidate=identities()
    c.assess(context,baseline,candidate,samples(),100000)
"""
            result=subprocess.run([sys.executable,'-c',script,str(reg),str(db)],
                                  cwd=Path(__file__).resolve().parents[2],timeout=10,check=False)
            self.assertEqual(result.returncode,77)
            with Coordinator(reg,db) as c:
                self.assertEqual(c.inspect()['intents'],{})
                self.assertEqual(c.inspect()['revision'],0)
                self.assertTrue(c.assess(context,baseline,candidate,samples(),100000)['intent_created'])

if __name__=='__main__':unittest.main()
