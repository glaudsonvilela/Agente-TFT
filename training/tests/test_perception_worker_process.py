"""Real POSIX process tests, not OCR accuracy tests."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from training.perception_worker_process import execute_native


def stopped(pid):
    path=Path(f'/proc/{pid}/stat')
    return not path.exists() or path.read_text().split()[2]=='Z'


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.fd=os.open(self.root/'lock',os.O_CREAT|os.O_RDWR,0o600);self.addCleanup(os.close,self.fd)

    def script(self,body):
        p=self.root/'probe';p.write_text('#!'+sys.executable+'\n'+body);p.chmod(0o700);return p

    def call(self,p,timeout=2):
        execute_native(p,self.root/'m',self.root/'i',self.root/'p',self.root/'r',self.root,self.fd,timeout)

    def test_successful_child_is_waited_and_logs_preserved(self):
        p=self.script('print("process fixture")\n');self.call(p)
        self.assertIn('process fixture',(self.root/'events.jsonl').read_text())

    def test_nonzero_exit_is_not_success(self):
        p=self.script('raise SystemExit(7)\n')
        with self.assertRaisesRegex(RuntimeError,'7'):self.call(p)

    def test_timeout_kills_child_and_its_sleep_descendant(self):
        ids=self.root/'pids'
        p=self.script('import os,subprocess,time\nfrom pathlib import Path\n'
                      'child=subprocess.Popen(["sleep","30"])\n'
                      f'Path({str(ids)!r}).write_text(str(os.getpid())+","+str(child.pid))\n'
                      'time.sleep(30)\n')
        start=time.monotonic()
        with self.assertRaisesRegex(RuntimeError,'124'):self.call(p,1)
        self.assertLess(time.monotonic()-start,6)
        for pid in map(int,ids.read_text().split(',')):
            deadline=time.monotonic()+3
            while not stopped(pid) and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(stopped(pid))

    def test_parent_death_closes_pipe_and_cancels_native_group(self):
        ids=self.root/'pids'
        p=self.script('import os,subprocess,time\nfrom pathlib import Path\n'
                      'child=subprocess.Popen(["sleep","30"])\n'
                      f'Path({str(ids)!r}).write_text(str(os.getpid())+","+str(child.pid))\n'
                      'time.sleep(30)\n')
        command=('import os\nfrom pathlib import Path\n'
                 'from training.perception_worker_process import execute_native\n'
                 f'r=Path({str(self.root)!r})\n'
                 'fd=os.open(r/"lock",os.O_RDWR)\n'
                 'execute_native(r/"probe",r/"m",r/"i",r/"p",r/"r",r,fd,30)\n')
        parent=subprocess.Popen([sys.executable,'-c',command])
        try:
            deadline=time.monotonic()+5
            while not ids.exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(ids.exists());parent.kill();parent.wait()
            for pid in map(int,ids.read_text().split(',')):
                deadline=time.monotonic()+4
                while not stopped(pid) and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(stopped(pid))
        finally:
            if parent.poll() is None:parent.kill();parent.wait()
