"""Worker control tests. Backend execution mocked here; native test is separate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training.perception_registry import Registry
from training.perception_coordinator import Coordinator
from training.perception_work_source import sha256,load,publish,submit_observations
from training.perception_worker import Worker,now_ms
from training.tests.test_player_hp_candidate_audit import fixture


class Fixture:
    def __init__(self,root):
        self.root=root;self.store=root/'store';self.store.mkdir()
        self.reg=self.store/'registry.sqlite3';self.coord=self.store/'coordinator.sqlite3'
        self.probe=root/'probe';self.probe.write_bytes(b'test executable not executed');self.probe.chmod(0o700)
        self.profile=root/'profile.json';self.profile.write_text('{}')
        self.context=dict(mode='offline_replay',subsystem='player_list',field='hp',recording_sha256='a'*64)
        self.baseline=dict(reader='hp1',executable_sha256=sha256(self.probe),config_sha256=sha256(self.profile))
        self.candidate=dict(self.baseline,reader='hp_text_fit_v1')
        with Registry(self.reg) as r:r.import_review(self.context,self.baseline,self.candidate,dict(fixture=True),[])
        with Coordinator(self.reg,self.coord):pass
        self.images=root/'pixels';(self.images/'frames').mkdir(parents=True)
        self.plan,reports=fixture(((None,70),)*24)
        self.report=reports['window-00'];self.frames=self.plan['batches'][0]['frames']
        for i,f in enumerate(self.frames):(self.images/f['image']).write_text(str(i))
        self.samples=[dict(timestamp_ms=f['timestamp_ms'],image_sha256=f['sha256'],
                           status=r['baseline']['status'],marker='unique') for f,r in zip(self.frames,self.report['records'])]
        self.inbox=self.store/'worker'/'sources';self.inbox.mkdir(parents=True)

    def reserve(self,clock=None):
        with Coordinator(self.reg,self.coord) as c:
            result=submit_observations(c,self.root,self.inbox,self.context,self.baseline,self.candidate,
                self.frames,self.samples,self.images,now_ms() if clock is None else clock)
        self.key=result['decision']['request_id'];return result

    def worker(self):return Worker(self.reg,self.coord,self.root,self.probe,self.profile)

    def backend(self,*args,**kwargs):publish(args[4],self.report)

    def states(self):
        with Coordinator(self.reg,self.coord) as c:return c.inspect(),c.registry.inspect()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.f=Fixture(Path(self.tmp.name))

    def run_worker(self):
        with self.f.worker() as w:return w.drain()

    def test_empty_queue_never_checks_artifacts_or_runs_subprocess(self):
        before=self.f.states();self.f.probe.unlink()
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no work')):
            s=self.run_worker()
        self.assertEqual(s['jobs_processed'],0);self.assertFalse(s['native_probe_executed'])
        self.assertEqual(before,self.f.states())

    def test_reserved_job_executes_then_records_review_and_acknowledges(self):
        self.assertTrue(self.f.reserve()['intent_created'])
        with patch('training.perception_worker.execute_native',side_effect=self.f.backend) as run:
            s=self.run_worker()
        self.assertEqual(run.call_count,1);self.assertEqual(s['outcomes'],{'completed':1})
        state,reg=self.f.states();self.assertEqual(state['intents'][self.f.key]['status'],'completed')
        self.assertEqual(reg['revision'],2);self.assertFalse(s['profile_promoted']);self.assertFalse(s['model_trained'])

    def test_second_pump_does_not_repeat_completed_task(self):
        self.f.reserve()
        with patch('training.perception_worker.execute_native',side_effect=self.f.backend) as run:
            self.run_worker();s=self.run_worker()
        self.assertEqual(run.call_count,1);self.assertEqual(s['jobs_processed'],0)

    def test_quarantine_added_after_reservation_blocks_dispatch(self):
        self.f.reserve()
        with Registry(self.f.reg) as r:r.import_review(self.f.context,self.f.baseline,self.f.candidate,dict(new_block=True),['sign_disagreement'])
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('blocked')):
            s=self.run_worker()
        self.assertEqual(s['outcomes'],{'failed':1});self.assertIn('quarantined',s['results'][0]['reason'])
        self.assertFalse(s['native_probe_executed'])

    def test_source_hash_change_fails_before_dispatch(self):
        self.f.reserve();(self.f.images/self.f.frames[0]['image']).write_bytes(b'changed')
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no dispatch')):
            s=self.run_worker()
        self.assertEqual(s['outcomes'],{'failed':1});self.assertFalse(s['native_probe_executed'])

    def test_binary_changed_cannot_impersonate_registered_candidate(self):
        self.f.reserve();self.f.probe.write_bytes(b'new executable')
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no dispatch')):
            s=self.run_worker()
        self.assertIn('hash changed',s['results'][0]['reason'])

    def test_missing_source_fails_without_refunding_or_retry(self):
        self.f.reserve();(self.f.inbox/(self.f.key+'.json')).unlink()
        s=self.run_worker();self.assertEqual(s['outcomes'],{'failed':1})
        state,_=self.f.states();self.assertEqual(state['intents'][self.f.key]['frames'],24)
        self.assertEqual(self.run_worker()['jobs_processed'],0)

    def test_expired_reservation_is_not_executed(self):
        self.f.reserve(now_ms()-121000)
        s=self.run_worker();self.assertFalse(s['native_probe_executed'])
        self.assertIn('expired',s['results'][0]['reason'])

    def test_extra_command_field_cannot_dispatch_code(self):
        self.f.reserve();p=self.f.inbox/(self.f.key+'.json');b=load(p);b['command']='injected command'
        p.write_text(json.dumps(b))
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no dispatch')):
            s=self.run_worker()
        self.assertIn('contract',s['results'][0]['reason'])

    def test_worker_instances_share_exclusive_lock(self):
        with self.f.worker():
            with self.assertRaises(BlockingIOError):self.f.worker()

    def test_interrupted_launch_is_not_retried(self):
        self.f.reserve()
        with patch('training.perception_worker.execute_native',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.run_worker()
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no retry')):
            s=self.run_worker()
        self.assertEqual(s['outcomes'],{'interrupted':1});self.assertEqual(s['pending_after'],0)

    def test_result_is_reconciled_after_acknowledgement_crash(self):
        self.f.reserve()
        with patch('training.perception_worker.execute_native',side_effect=self.f.backend), \
             patch('training.perception_coordinator.Coordinator.finish_intent',side_effect=RuntimeError('crash after seal')):
            with self.assertRaisesRegex(RuntimeError,'crash after seal'):self.run_worker()
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no retry')):
            s=self.run_worker()
        self.assertEqual(s['outcomes'],{'completed':1});self.assertEqual(s['pending_after'],0)
        self.assertEqual(self.f.states()[1]['revision'],2)

    def test_invalid_native_confirmation_cannot_complete(self):
        self.f.reserve();self.f.report['records'][0]['candidate_freshness']['current']={'value':70}
        with patch('training.perception_worker.execute_native',side_effect=self.f.backend):s=self.run_worker()
        self.assertEqual(s['outcomes'],{'failed':1});self.assertEqual(self.f.states()[1]['revision'],1)

    def test_postrun_source_change_invalidates_result(self):
        self.f.reserve()
        def backend(*a):
            self.f.backend(*a);(self.f.images/self.f.frames[0]['image']).write_text('changed')
        with patch('training.perception_worker.execute_native',side_effect=backend):s=self.run_worker()
        self.assertEqual(s['outcomes'],{'failed':1});self.assertEqual(self.f.states()[1]['revision'],1)

    def test_postrun_quarantine_is_not_cleared(self):
        self.f.reserve()
        def backend(*a):
            self.f.backend(*a)
            with Registry(self.f.reg) as r:r.import_review(self.f.context,self.f.baseline,self.f.candidate,dict(during=True),['sign_disagreement'])
        with patch('training.perception_worker.execute_native',side_effect=backend):s=self.run_worker()
        self.assertEqual(s['outcomes'],{'failed':1});self.assertEqual(s['blocked_profiles'],1)

    def test_submit_known_evidence_never_publishes_a_job(self):
        with Registry(self.f.reg) as r:eid=next(iter(r.inspect()['snapshot']['reviews']))
        with Coordinator(self.f.reg,self.f.coord) as c:
            result=submit_observations(c,self.f.root,self.f.inbox,self.f.context,self.f.baseline,self.f.candidate,
                self.f.frames,self.f.samples,self.f.images,now_ms(),eid)
        self.assertEqual(result['decision']['action'],'skip_already_evaluated')
        self.assertEqual(list(self.f.inbox.iterdir()),[])

    def test_bad_source_prevents_reservation(self):
        self.f.frames[0]['sha256']='0'*64
        with self.assertRaises(ValueError):self.f.reserve()
        self.assertEqual(self.f.states()[0]['revision'],0)

    def test_reserved_inputs_cannot_change_status(self):
        self.f.reserve();p=self.f.inbox/(self.f.key+'.json');b=load(p);b['samples'][0]['status']='accepted';p.write_text(json.dumps(b))
        s=self.run_worker();self.assertIn('observations differ',s['results'][0]['reason'])

    def test_no_overwrite_of_published_json(self):
        p=self.f.root/'once.json';publish(p,dict(value=1))
        with self.assertRaises(ValueError):publish(p,dict(value=2))
        self.assertEqual(load(p),dict(value=1))

    def test_symbolic_source_escape_rejected(self):
        self.f.reserve();p=self.f.images/self.f.frames[0]['image'];p.unlink();p.symlink_to(self.f.profile)
        s=self.run_worker();self.assertEqual(s['outcomes'],{'failed':1})

    def test_missing_existing_stores_not_silently_initialized(self):
        self.f.coord.unlink()
        with self.assertRaises(ValueError):self.f.worker()
        self.assertFalse(self.f.coord.exists())
