"""End-to-end report/import tests; no media or native executable is run."""
from contextlib import redirect_stdout
from collections import Counter
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training import player_hp_candidate_audit as hp4
from training import player_hp_disjoint_shadow as hp5
from training.tests.test_player_hp_candidate_audit import fixture, save_fixture, reading
from training.register_hp5_profiles import prepare_import
from training.perception_registry import Registry


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False))


def source_fixture(root):
    hp2, hp3, source = root/'hp2', root/'hp3', root/'hp5'
    hp2.mkdir(); source.mkdir()
    profile, probe = root/'profile.json', root/'probe'
    profile.write_text('{}'); probe.write_bytes(b'frozen test bytes; not executed')
    plan, reports = fixture(((36,56),))
    plan.update(source=str(hp2), profile_sha256=hp5.sha256(profile), probe_sha256=hp5.sha256(probe))
    save_fixture(hp3, plan, reports)
    write(hp2/'plan.json', dict(source_video='/synthetic-video-not-opened'))
    with redirect_stdout(io.StringIO()):
        hp4.audit(hp3, root/'audit')
    context = hp5.source_context(root/'audit'/'report.json', root, profile, probe)
    windows = hp5.select_windows(90000, context['excluded'])
    freeze = dict(schema_version=1, policy=hp5.POLICY, windows=windows, **context,
                  selection_uses_values=False, selection_frozen_before_decode=True,
                  candidate_parameter_search=False, same_recording=True, independent_match=False,
                  video_sha256='e'*64)
    write(source/'plan.json', freeze)
    plan_hash = hp5.sha256(source/'plan.json')
    metrics = []
    for w in windows:
        folder = source/w['id']; folder.mkdir()
        frames = [dict(timestamp_ms=t, source_pts=t, source_time_base='1/1000',
                      image=f'frames/{i}.png', sha256='f'*64, decoded_checksum=f'{i:08x}')
                  for i,t in enumerate(range(w['start_ms'], w['end_ms'],250))]
        records = []
        for frame in frames:
            at = frame['timestamp_ms']
            records.append(dict(timestamp_ms=at, baseline=reading(70,at), candidate=reading(70,at),
                                comparison='both_readable_equal', baseline_ms=1., candidate_ms=1., decode_ms=1., text_fit=[]))
        for side in ('baseline','candidate'):
            fresh = hp4.replay_freshness([r[side] for r in records])
            for r,f in zip(records,fresh): r[side+'_freshness'] = f
        summary = dict(schema_version=1, frames=32, errors=0, execution_complete=True,
                       baseline_profile='match001-self-badge-v1', candidate_profile='hp_text_fit_v1',
                       baseline_statuses={'accepted':32}, candidate_statuses={'accepted':32},
                       comparison={'both_readable_equal':32}, baseline_confirmed_frames=31, candidate_confirmed_frames=31,
                       exact_accuracy=None, labels_used=False, model_trained=False, game_state_updated=False, profile_promoted=False)
        native = dict(summary=summary, records=records)
        write(folder/'manifest.json', dict(frames=frames, labels_used=False, frozen_plan_sha256=plan_hash))
        write(folder/'report.json', native)
        values,cases = hp4.review_batch(dict(id=w['id'],kind='disjoint_shadow_same_recording',frames=frames),native)
        entry = dict(id=w['id'],window=w,**values,timing=hp5.check_sequence(frames,w,context['excluded']))
        write(folder/'review.json', dict(metrics=entry,cases=cases)); metrics.append(entry)
    summary = dict(schema_version=1, policy=hp5.POLICY, sequences=3, frames=96,
                   baseline_statuses={'accepted':96}, candidate_statuses={'accepted':96},
                   comparison={'both_readable_equal':96}, risk_counts={},
                   baseline_confirmed_frames=93, candidate_confirmed_frames=93,
                   decision=hp5.inherited_decision(context['prior_decision'], {}),
                   execution_complete=True, labels_used=False, exact_accuracy=None, model_trained=False,
                   game_state_updated=False, profile_promoted=False, frozen_plan_sha256=plan_hash,
                   metric_kind='disjoint_shadow_same_recording')
    write(source/'report.json', dict(summary=summary,windows=metrics))
    seal(source)
    return source, profile, probe


def seal(source):
    write(source/'COMPLETE.json', dict(report_sha256=hp5.sha256(source/'report.json'),plan_sha256=hp5.sha256(source/'plan.json')))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source,self.profile,self.probe=source_fixture(self.root)

    def prepare(self):
        return prepare_import(self.source,self.root,self.profile,self.probe)

    def test_report_chain_imported_without_executing_any_backend(self):
        with patch('subprocess.run',side_effect=AssertionError('no subprocess allowed')), \
             patch('subprocess.Popen',side_effect=AssertionError('no subprocess allowed')):
            data=self.prepare()
            with Registry(self.root/'registry.sqlite3') as r:
                result=r.import_review(**data)
            with Registry(self.root/'registry.sqlite3') as r:
                self.assertEqual(r.permission(data['candidate'])['status'],'quarantined')
        self.assertEqual(result['revision'],1)
        self.assertIn('historical_quarantine',result['blocker_reasons'])
        self.assertFalse(result['active_profile_written'])

    def test_import_of_same_report_is_idempotent(self):
        with Registry(self.root/'registry.sqlite3') as r:
            self.assertTrue(r.import_review(**self.prepare())['changed'])
            self.assertFalse(r.import_review(**self.prepare())['changed'])

    def test_complete_marker_is_required(self):
        (self.source/'COMPLETE.json').unlink()
        with self.assertRaises(OSError): self.prepare()

    def test_report_checksum_change_is_rejected(self):
        report=hp5.load(self.source/'report.json'); report['summary']['frames']=97
        write(self.source/'report.json',report)
        with self.assertRaisesRegex(ValueError,'completion hashes'): self.prepare()

    def test_consistently_rehashed_false_aggregate_still_rejected(self):
        report=hp5.load(self.source/'report.json'); report['summary']['frames']=97
        write(self.source/'report.json',report); seal(self.source)
        with self.assertRaisesRegex(ValueError,'aggregate mismatch'): self.prepare()

    def test_clearing_inherited_quarantine_is_rejected(self):
        plan=hp5.load(self.source/'plan.json'); plan['prior_decision']['review_action']='ready_for_disjoint_shadow'
        write(self.source/'plan.json',plan); seal(self.source)
        with self.assertRaisesRegex(ValueError,'context differs'): self.prepare()

    def test_binary_changes_do_not_relabel_the_same_reader(self):
        self.probe.write_bytes(b'different binary')
        with self.assertRaisesRegex(ValueError,'hash changed'): self.prepare()

    def test_false_temporal_confirmation_rejected(self):
        path=self.source/'sequence-00'/'report.json'
        report=hp5.load(path); report['records'][0]['baseline_freshness']['current']={'value':70}
        write(path,report)
        with self.assertRaisesRegex(ValueError,'temporal evidence'): self.prepare()

    def test_sequence_manifest_symlink_escape_is_rejected(self):
        path=self.source/'sequence-00'/'manifest.json'
        outside=self.root/'outside.json'; outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'outside evidence'): self.prepare()

    def test_decision_is_recomputed_not_trusted_from_summary(self):
        report=hp5.load(self.source/'report.json'); report['summary']['decision']['candidate_activation_blocked']=False
        write(self.source/'report.json',report); seal(self.source)
        with self.assertRaisesRegex(ValueError,'aggregate mismatch'): self.prepare()
