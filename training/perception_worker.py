"""A1.6: one bounded execution of an existing A15 diagnostic reservation.

No promotion, retry of quarantined readers, model training or gameplay control.
A14/A15 schemas are unchanged. Private attempt folders journal launches/results;
a crash with no sealed result is interrupted, not automatic permission to rerun.
"""
from __future__ import annotations
from collections import Counter
import fcntl
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import time

from training.perception_registry import context_key, digest, profile_key, require
from training.perception_coordinator import Coordinator, scheduling_signal
from training.perception_work_source import load, publish, sha256, sync_dir, verify_source
from training.perception_worker_process import execute_native

POLICY='a16_bounded_worker_v1'
MAX_JOB_AGE_MS=120_000


def now_ms() -> int: return time.time_ns()//1_000_000


def _frozen_copy(src: Path, dst: Path, expected: str, executable: bool=False) -> None:
    require(src.is_file() and not src.is_symlink() and src.stat().st_size<=128*1024*1024,
            'invalid/excessive reader artifact')
    if executable: require(os.access(src,os.X_OK), 'reader is not executable')
    with src.open('rb') as incoming, dst.open('xb') as out:
        shutil.copyfileobj(incoming,out,1024*1024);out.flush();os.fsync(out.fileno())
    require(sha256(dst)==expected==sha256(src), 'reader artifact hash changed')
    if executable: dst.chmod(0o700)


class Worker:
    """Single-user local POSIX worker; shared lock is tied to the A15 database.

    A reservation and a process are not one distributed transaction. Sealed results
    are reconciled with A15 idempotently. An unsealed attempt fails closed after a
    crash. Never delete attempt folders to enable retries of the same request.
    """
    def __init__(self, registry: Path, coordinator: Path, evidence_root: Path,
                 probe: Path, profile: Path):
        self.root=evidence_root.resolve(strict=True)
        self.database=coordinator.absolute();self.probe=probe.absolute();self.profile=profile.absolute()
        require(self.database.is_file() and registry.is_file(), 'A14/A15 stores must already exist')
        require(self.database.parent.resolve().is_relative_to(self.root), 'coordinator outside evidence root')
        self.home=self.database.parent/'worker';self.inbox=self.home/'sources';self.attempts=self.home/'attempts'
        for p in (self.home,self.inbox,self.attempts):
            require(not p.is_symlink(), 'worker directory is a symlink')
            p.mkdir(exist_ok=True)
        self.fd=os.open(str(self.database)+'.a16.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            require(stat.S_ISREG(os.fstat(self.fd).st_mode), 'worker lock is not a regular file')
            fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.c=Coordinator(registry,self.database)
        except BaseException:
            os.close(self.fd);raise

    def __enter__(self): return self
    def __exit__(self,*exc):
        self.c.__exit__(*exc);os.close(self.fd)

    def _binding(self, decision: dict, task: dict) -> tuple[dict,dict,dict,dict]:
        current=self.c.registry.inspect();s=current['snapshot']
        binding=s['contexts'].get(decision['context_key'])
        require(binding is not None, 'registered context disappeared')
        baseline=s['profiles'][binding['baseline_key']]['identity']
        p=s['profiles'].get(decision['candidate_key']);require(p is not None,'unregistered candidate')
        candidate=p['identity'];context=binding['context']
        ck,bk,pk=context_key(context),profile_key(baseline),profile_key(candidate)
        pair=digest(dict(context=ck,baseline=bk,candidate=pk))
        key=digest(dict(pair=pair,frames=decision['source_frames']))
        require(decision['request_id']==key and decision['pair_key']==task['pair_key']==pair
            and task['context_key']==ck and task['source_frames']==decision['source_frames'],
            'reservation identity mismatch')
        require(decision['action']=='reserve_shadow_intent' and decision['completed_evidence_id'] is None
            and decision['activation_allowed'] is False and task['frames']==decision['cost_frames']
            and task['frames']==len(task['source_frames']) and 1<=task['frames']<=128,
            'not a valid bounded diagnostic reservation')
        require((baseline['reader'],candidate['reader'])==('hp1','hp_text_fit_v1'),
                'unsupported native reader pair; no arbitrary executable dispatch')
        require(baseline['executable_sha256']==candidate['executable_sha256']
                and baseline['config_sha256']==candidate['config_sha256'], 'unsupported paired artifact identities')
        return context,baseline,candidate,current

    def _permission(self, decision: dict, task: dict) -> tuple[dict,dict,dict,dict]:
        result=self._binding(decision,task)
        candidate=result[2];snapshot=result[3]['snapshot']
        require(not snapshot['profiles'][profile_key(candidate)]['blocks'], 'candidate_quarantined_before_execution')
        return result

    def _finish(self,key: str, outcome: dict, folder: Path) -> dict:
        if not (folder/'FINAL.json').exists():
            publish(folder/'FINAL.json',dict(body=outcome,sha256=digest(outcome)))
        result='completed' if outcome['state']=='completed' else 'failed'
        self.c.finish_intent(key,result,now_ms())
        return outcome

    def _resume(self,key: str, folder: Path) -> dict:
        require(not folder.is_symlink() and folder.is_dir(), 'invalid existing attempt path')
        final=folder/'FINAL.json'
        if final.exists():
            obj=load(final);body=obj['body']
            require(digest(body)==obj['sha256'] and body['request_id']==key
                    and body['state'] in {'completed','failed','interrupted'}, 'corrupt worker result; no retry')
            if body['state']=='completed':
                require(sha256(folder/'report.json')==body['report_sha256'], 'completed result changed')
                review=self.c.registry.inspect()['snapshot']['reviews'].get(body['registry_evidence_id'])
                require(review is not None and review['evidence'].get('request_id')==key
                    and review['evidence'].get('report_sha256')==body['report_sha256'],
                    'result registry receipt missing/mismatched')
            return dict(self._finish(key,body,folder),result_reconciled=True)
        # The inherited process lock ensures the old supervisor has released its
        # execution before recovery reaches here. Do not trust an unsealed report.
        body=dict(request_id=key,state='interrupted',reason='unsealed_prior_attempt_no_automatic_retry',
                  native_probe_executed=None,ocr_executed=None,native_dispatch_attempted=False,
                  profile_promoted=False,game_state_updated=False,model_trained=False)
        return dict(self._finish(key,body,folder),result_reconciled=True)

    def _execute(self,key: str,decision: dict,task: dict) -> dict:
        folder=self.attempts/key
        if folder.exists() or folder.is_symlink(): return self._resume(key,folder)
        folder.mkdir(mode=0o700);sync_dir(self.attempts)
        dispatched=False;native_returned=False
        try:
            publish(folder/'CLAIM.json',dict(policy=POLICY,request_id=key,decision_sha256=digest(decision),
                claimed_at_ms=now_ms(),note='claim precedes spawn; no automatic retry after interruption'))
            require(0<=now_ms()-task['reserved_at_ms']<=MAX_JOB_AGE_MS, 'reservation_expired_or_clock_regressed')
            context,baseline,candidate,before=self._permission(decision,task)
            source_path=self.inbox/(key+'.json');bundle=load(source_path);source_hash=sha256(source_path)
            source,inputs=verify_source(self.root,bundle,decision)
            signal=scheduling_signal(bundle['samples'],self.c.policy)
            require(signal==decision['signal'] and signal['state']=='degraded', 'invalid deterioration support')
            publish(folder/'manifest.json',dict(frames=source['frames']))
            _frozen_copy(self.probe,folder/'probe',candidate['executable_sha256'],True)
            _frozen_copy(self.profile,folder/'profile.json',candidate['config_sha256'])
            publish(folder/'source.json',dict(bundle=bundle,source_sha256=source_hash,inputs=inputs,
                registry_revision=before['revision'],registry_event_tip=before['event_tip'],
                baseline=baseline,candidate=candidate,context=context))
            # Recheck current blockers immediately before dispatch, not just the
            # permission recorded when A15 reserved the work.
            self._permission(decision,task)
            require(self.c.inspect()['intents'][key]['status']=='reserved', 'reservation already acknowledged')
            dispatched=True
            execute_native(folder/'probe',folder/'manifest.json',Path(source['image_root']),
                folder/'profile.json',folder/'report.json',folder,self.fd)
            native_returned=True
            from training.player_hp_candidate_audit import review_batch
            report=load(folder/'report.json')
            metrics,cases=review_batch(dict(id=key,kind='a16_diagnostic_worker',frames=source['frames']),report)
            # Same-frame re-observation changing status is retained as failed
            # evidence, not treated as the original scheduling observation.
            for sample,row in zip(bundle['samples'],report['records']):
                require(sample['status']==row['baseline']['status'], 'baseline_status_changed_since_reservation')
            require(sha256(source_path)==source_hash, 'work source changed during execution')
            for path,expected in inputs.items(): require(sha256(Path(path))==expected, 'source image changed during execution')
            for path,expected in ((self.probe,candidate['executable_sha256']),(self.profile,candidate['config_sha256']),
                                  (folder/'probe',candidate['executable_sha256']),(folder/'profile.json',candidate['config_sha256'])):
                require(sha256(path)==expected, 'reader artifact changed during execution')
            self._permission(decision,task)
            risks=Counter(reason for case in cases for reason in case['reasons'])
            blockers=[k for k in ('both_readable_disagree','opposing_eligible_attempt','sign_disagreement','baseline_only_readable') if risks[k]]
            publish(folder/'review.json',dict(metrics=metrics,cases=cases,risks=dict(risks),labels_used=False))
            receipt=self.c.registry.import_review(context,baseline,candidate,
                dict(kind='a16_native_diagnostic',request_id=key,report_sha256=sha256(folder/'report.json'),
                    source_sha256=source_hash,review_sha256=sha256(folder/'review.json'),metrics=metrics,
                    runtime_environment_identity_complete=False,exact_accuracy=None),blockers)
            # A concurrent blocker added during execution cannot be cleared by
            # import_review; it is sticky and reported in the durable receipt.
            body=dict(request_id=key,state='completed',reason='validated_native_diagnostic',
                native_probe_executed=True,native_dispatch_attempted=True,
                ocr_executed=any(r[side]['attempts'] for r in report['records'] for side in ('baseline','candidate')),
                report_sha256=sha256(folder/'report.json'),registry_evidence_id=receipt['evidence_id'],
                registry_receipt=receipt,metrics=metrics,risks=dict(risks),profile_promoted=False,
                game_state_updated=False,model_trained=False)
        except (ValueError,OSError,KeyError,TypeError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as exc:
            body=dict(request_id=key,state='failed',reason=str(exc)[:1000],
                native_probe_executed=True if native_returned else None if dispatched else False,
                native_dispatch_attempted=dispatched,ocr_executed=None if dispatched else False,
                profile_promoted=False,game_state_updated=False,model_trained=False)
        return self._finish(key,body,folder)

    def drain(self) -> dict:
        state=self.c.inspect();before=self.c.registry.inspect()
        require(now_ms()>=state['last_clock_ms'], 'scheduling clock moved backwards')
        pending=[(k,t) for k,t in state['intents'].items() if t['status']=='reserved']
        pending.sort(key=lambda item:(item[1]['reserved_at_ms'],item[0]))
        results=[]
        # Deliberately at most one reservation per explicit pump, never a daemon.
        for key,task in pending[:1]: results.append(self._execute(key,state['decisions'][key],task))
        after=self.c.inspect();reg=self.c.registry.inspect()
        fresh=[r for r in results if not r.get('result_reconciled',False)]
        def activity(name):
            if any(r[name] is True for r in fresh):return True
            return None if any(r[name] is None for r in fresh) else False
        return dict(schema_version=1,policy=POLICY,pending_before=len(pending),jobs_processed=len(results),
            pending_after=sum(t['status']=='reserved' for t in after['intents'].values()),
            outcomes=dict(Counter(r['state'] for r in results)),results=results,
            results_reconciled=sum(r.get('result_reconciled',False) for r in results),
            native_dispatch_attempts=sum(r['native_dispatch_attempted'] for r in fresh),
            native_probe_executed=activity('native_probe_executed'),ocr_executed=activity('ocr_executed'),
            ledger_revision_before=state['revision'],ledger_revision_after=after['revision'],
            registry_revision_before=before['revision'],registry_revision_after=reg['revision'],
            registry_unchanged=before==reg,coordinator_unchanged=state==after,
            blocked_profiles=sum(bool(p['blocks']) for p in reg['snapshot']['profiles'].values()),
            activation_allowed=False,profile_promoted=False,game_state_updated=False,model_trained=False,
            continuous_capture_connected=False,note='worker connected to A15; execution flags refer to this pump, not reconciled history')
