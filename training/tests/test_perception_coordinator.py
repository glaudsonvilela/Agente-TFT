import copy
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from training.perception_registry import Registry
from training.perception_coordinator import Coordinator, CoordinatorPolicy, scheduling_signal


def samples(count=24, status='ocr_uncertain', start=1000):
    marker = {'badge_not_found':'missing', 'badge_ambiguous':'ambiguous',
              'search_budget_exceeded':'unknown'}.get(status,'unique')
    return [dict(timestamp_ms=start+250*i, image_sha256=hashlib.sha256(str(start+250*i).encode()).hexdigest(),
                 status=status, marker=marker) for i in range(count)]


def identities():
    context=dict(mode='offline_replay',subsystem='player_list',field='hp',recording_sha256='e'*64)
    baseline=dict(reader='hp1',executable_sha256='a'*64,config_sha256='b'*64)
    candidate=dict(reader='hp_text_fit_v1',executable_sha256='a'*64,config_sha256='b'*64)
    return context,baseline,candidate


class SignalTests(unittest.TestCase):
    def signal(self, rows): return scheduling_signal(rows,CoordinatorPolicy())
    def test_nonoverlapping_bad_blocks_require_persistence(self):
        self.assertEqual(self.signal(samples(8))['state'],'suspect')
        self.assertEqual(self.signal(samples(16))['state'],'suspect')
        s=self.signal(samples(24));self.assertEqual(s['state'],'degraded')
        self.assertEqual(s['evaluated_blocks'],3)
        self.assertEqual(s['consecutive_bad_blocks'],3)
    def test_one_bad_frame_never_reused_as_many_bad_windows(self):
        rows=samples(32,'accepted');rows[8]['status']='ocr_uncertain'
        self.assertEqual(self.signal(rows)['state'],'healthy')
        self.assertEqual(self.signal(rows)['consecutive_bad_blocks'],0)
    def test_missing_marker_is_not_ocr_degradation_or_proven_occlusion(self):
        for status in ('badge_not_found','badge_ambiguous','search_budget_exceeded'):
            s=self.signal(samples(32,status))
            self.assertEqual(s['state'],'visibility_unresolved');self.assertEqual(s['evaluated_blocks'],0)
    def test_read_error_is_not_calibration_signal(self):
        self.assertEqual(self.signal(samples(24,'read_error'))['state'],'operational_error')
    def test_negative_is_signed_read_not_unsigned_label(self):
        self.assertEqual(self.signal(samples(24,'negative_display'))['state'],'healthy')
    def test_same_image_at_new_times_does_not_create_bad_blocks(self):
        rows=samples(32)
        for r in rows:r['image_sha256']='a'*64
        s=self.signal(rows);self.assertEqual(s['state'],'repeated_image')
        self.assertEqual(s['evaluated_blocks'],0)
        self.assertEqual(s['repeated_unique_marker_images'],31)
    def test_sparse_timestamps_reset_support(self):
        rows=samples(32)
        for i,r in enumerate(rows):r['timestamp_ms']=i*50000
        s=self.signal(rows);self.assertEqual(s['state'],'warming_up');self.assertEqual(s['gap_resets'],31)
    def test_visibility_loss_breaks_previous_drift_sequence(self):
        rows=samples(16)+samples(1,'badge_not_found',5000)+samples(8,start=5250)
        self.assertEqual(self.signal(rows)['state'],'suspect')
    def test_recovery_requires_two_good_blocks(self):
        rows=samples(24)+samples(8,'accepted',7000)
        self.assertEqual(self.signal(rows)['state'],'degraded')
        self.assertEqual(self.signal(rows+samples(8,'accepted',9000))['state'],'healthy')
    def test_high_rate_duplicate_or_unordered_inputs_rejected(self):
        rows=samples();rows[1]['timestamp_ms']=rows[0]['timestamp_ms']
        with self.assertRaises(ValueError):self.signal(rows)
        rows=samples();rows[0]['marker']='missing'
        with self.assertRaises(ValueError):self.signal(rows)
        rows=samples();rows[0]['expected_hp']=36
        with self.assertRaises(ValueError):self.signal(rows)
    def test_too_short_time_span_does_not_degrade(self):
        rows=samples(24)
        for i,r in enumerate(rows):r['timestamp_ms']=i
        self.assertEqual(self.signal(rows)['state'],'warming_up')
    def test_policy_invalid_values_rejected(self):
        for policy in (replace(CoordinatorPolicy(),bad_blocks=1),replace(CoordinatorPolicy(),block_samples=True),
                       replace(CoordinatorPolicy(),max_unreadable_rate=float('nan'))):
            with self.assertRaises(ValueError):policy.validate()


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.reg=self.root/'registry.sqlite3';self.db=self.root/'coordinator.sqlite3'
        self.context,self.baseline,self.candidate=identities()
        with Registry(self.reg) as r:
            self.eid=r.import_review(self.context,self.baseline,self.candidate,{'fixture':1},[])['evidence_id']
        self.before=self.reg.read_bytes()
    def new(self,policy=None):return Coordinator(self.reg,self.db,policy)
    def ask(self,c,rows=None,now=100000,prior=None):
        return c.assess(self.context,self.baseline,self.candidate,rows or samples(),now,prior)
    def block(self):
        with Registry(self.reg) as r:
            r.import_review(self.context,self.baseline,self.candidate,{'fixture':2},['opposing_eligible_attempt'])
    def test_evaluated_evidence_skips_work_preserves_registry(self):
        with self.new() as c:
            out=self.ask(c,prior=self.eid)
            self.assertEqual(out['decision']['action'],'skip_already_evaluated')
            self.assertFalse(out['intent_created']);self.assertEqual(c.inspect()['intents'],{})
        self.assertEqual(self.reg.read_bytes(),self.before)
    def test_fresh_degradation_reserves_without_executing(self):
        with self.new() as c:
            out=self.ask(c);self.assertTrue(out['intent_created'])
            self.assertFalse(out['decision']['worker_executed']);self.assertFalse(out['activation_allowed'])
    def test_reopening_does_not_repeat_reservation(self):
        with self.new() as c:first=self.ask(c)
        with self.new() as c:
            second=self.ask(c,now=200000)
            self.assertFalse(second['changed']);self.assertFalse(second['intent_created'])
            self.assertEqual(first['decision'],second['decision']);self.assertEqual(len(c.inspect()['intents']),1)
    def test_missing_marker_does_not_reserve(self):
        with self.new() as c:
            self.assertEqual(self.ask(c,samples(status='badge_not_found'))['decision']['action'],'wait_for_visibility')
    def test_backend_error_does_not_reserve(self):
        with self.new() as c:
            self.assertEqual(self.ask(c,samples(status='read_error'))['decision']['action'],'diagnose_backend_not_calibration')
    def test_quarantined_candidate_requires_new_candidate_not_retry_loop(self):
        self.block()
        with self.new() as c:
            out=self.ask(c)
            self.assertEqual(out['decision']['action'],'block_automatic_retry_quarantined_candidate')
            self.assertTrue(out['decision']['shadow_permission_registered'])
            self.assertFalse(out['intent_created'])
    def test_new_registry_block_visible_on_existing_coordinator(self):
        with self.new() as c:
            self.ask(c,prior=self.eid);self.block()
            out=self.ask(c,now=100001,prior=self.eid)
            self.assertIn('opposing_eligible_attempt',out['current_blockers'])
            self.assertFalse(out['intent_created'])
    def test_unregistered_reader_does_not_gain_permission_by_new_name(self):
        self.candidate={**self.candidate,'reader':'unregistered'}
        with self.new() as c:self.assertEqual(self.ask(c)['decision']['action'],'block_unregistered_candidate')
    def test_unknown_completed_evidence_fails_before_any_reservation(self):
        with self.new() as c:
            with self.assertRaises(ValueError):self.ask(c,prior='d'*64)
            self.assertEqual(c.inspect()['revision'],0)
    def test_outstanding_limit(self):
        with self.new() as c:
            self.ask(c)
            self.assertEqual(self.ask(c,samples(start=20000),now=200000)['decision']['action'],'limit_outstanding_work')
    def test_cooldown_after_finish(self):
        with self.new() as c:
            out=self.ask(c);c.finish_intent(out['decision']['request_id'],'completed',100001)
            self.assertEqual(self.ask(c,samples(start=20000),now=100002)['decision']['action'],'cooldown')
    def test_budget_does_not_reset_after_restart(self):
        policy=replace(CoordinatorPolicy(),max_intents_per_period=1)
        with self.new(policy) as c:
            out=self.ask(c);c.finish_intent(out['decision']['request_id'],'failed',100001)
        with self.new(policy) as c:
            self.assertEqual(self.ask(c,samples(start=20000),now=200000)['decision']['action'],'limit_intent_budget')
    def test_frame_budget(self):
        with self.new(replace(CoordinatorPolicy(),max_frames_per_period=20)) as c:
            self.assertEqual(self.ask(c)['decision']['action'],'limit_frame_budget')
    def test_overlapping_evidence_is_not_new_job(self):
        with self.new() as c:
            first=self.ask(c);c.finish_intent(first['decision']['request_id'],'completed',100001)
            rows=samples(start=4000)
            self.assertEqual(self.ask(c,rows,200000)['decision']['action'],'skip_overlapping_reserved_evidence')
    def test_clock_rollback_fails_closed(self):
        with self.new() as c:
            self.ask(c)
            with self.assertRaisesRegex(ValueError,'clock'):self.ask(c,samples(start=20000),99999)
    def test_changed_status_on_same_frame_identity_fails(self):
        with self.new() as c:
            self.ask(c)
            with self.assertRaisesRegex(ValueError,'changed status'):self.ask(c,samples(status='accepted'),100001)
    def test_atomic_rollback_of_cost_and_decision(self):
        with self.new() as c:
            save=c._save
            def fail(state):save(state);raise RuntimeError('after SQL write before commit')
            with patch.object(c,'_save',side_effect=fail):
                with self.assertRaises(RuntimeError):self.ask(c)
            self.assertEqual(c.inspect()['revision'],0);self.assertEqual(c.inspect()['intents'],{})
            self.assertTrue(self.ask(c)['intent_created'])
    def test_concurrent_requests_create_one_intent(self):
        def run(_):
            with self.new() as c:return self.ask(c)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(sum(x['intent_created'] for x in results),1)
    def test_corruption_and_changed_policy_fail_without_reset(self):
        with self.new() as c:self.ask(c)
        with self.assertRaises(ValueError):self.new(replace(CoordinatorPolicy(),bad_blocks=4))
        db=sqlite3.connect(self.db);db.execute("UPDATE state SET checksum='bad'");db.commit();db.close()
        before=self.db.read_bytes()
        with self.assertRaisesRegex(ValueError,'checksum'):self.new()
        self.assertEqual(self.db.read_bytes(),before)
    def test_registry_missing_is_not_silently_created(self):
        with self.assertRaises(ValueError):Coordinator(self.root/'missing',self.db)
        self.assertFalse(self.db.exists())
    def test_ledger_cannot_alias_registry(self):
        with self.assertRaises(ValueError):Coordinator(self.reg,self.reg)
        self.assertEqual(self.reg.read_bytes(),self.before)
    def test_unknown_database_is_not_overwritten(self):
        db=sqlite3.connect(self.db);db.execute('CREATE TABLE foreign_data(id)');db.commit();db.close()
        with self.assertRaises(ValueError):self.new()
    def test_finish_idempotent_but_cannot_change_outcome(self):
        with self.new() as c:
            key=self.ask(c)['decision']['request_id']
            self.assertTrue(c.finish_intent(key,'completed',100001))
            self.assertFalse(c.finish_intent(key,'completed',100002))
            with self.assertRaises(ValueError):c.finish_intent(key,'failed',100003)

if __name__=='__main__':unittest.main()
