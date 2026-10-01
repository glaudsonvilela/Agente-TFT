import argparse
import contextlib
import copy
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from training import player_hp_disjoint_shadow as hp5


def history_plan():
    return {'batches': [
        {'id': 'sparse-regression', 'kind': 'sparse_regression',
         'frames': [{'timestamp_ms': t} for t in range(0, 1_950_001, 50_000)]},
        {'id': 'window-00', 'kind': 'targeted_dense',
         'frames': [{'timestamp_ms': t} for t in range(749_000, 751_000, 250)]}
    ]}


def sequence_rows(start=10_000):
    return [dict(timestamp_ms=t, source_pts=t, source_time_base='1/1000',
                 image=f'frames/{i}.png', sha256='a'*64, decoded_checksum=f'{i:08x}')
            for i, t in enumerate(range(start, start+8000, 250))]


def source_fixture(root):
    hp3, hp2 = root/'hp3', root/'hp2'
    hp3.mkdir(); hp2.mkdir()
    batch = hp3/'sparse-regression'; batch.mkdir()
    profile = root/'profile.json'; profile.write_text('{}')
    probe = root/'probe'; probe.write_bytes(b'frozen executable bytes')
    plan = {'source': str(hp2), 'profile_sha256': hp5.sha256(profile), 'probe_sha256': hp5.sha256(probe),
            'batches': [{'id': 'sparse-regression', 'kind': 'sparse_regression',
                         'frames': [{'timestamp_ms': 50_000}, {'timestamp_ms': 100_000}]}]}
    hp5.write(hp3/'plan.json', plan)
    for path in (hp3/'report.json', batch/'manifest.json', batch/'report.json'):
        hp5.write(path, {})
    hp5.write(hp2/'plan.json', {'source_video': '/fixture-not-opened'})
    hashes = {str(p.relative_to(hp3)): hp5.sha256(p) for p in hp3.rglob('*.json')}
    aid = hashlib.sha256(hp5.canonical({'policy': 'hp3_paired_evidence_review_v1', 'inputs': hashes})).hexdigest()
    audit = root/'hp4'; audit.mkdir()
    hp5.write(audit/'report.json', {'summary': dict(
        audit_policy='hp3_paired_evidence_review_v1', execution_complete=True, audit_id=aid,
        labels_used=False, game_state_updated=False, profile_promoted=False, model_trained=False, ocr_executed=False,
        decision=dict(active_action='retain_baseline', review_action='quarantine_candidate', reasons=['opposing_eligible_attempt'])),
        'provenance': dict(source=str(hp3), input_files_sha256=hashes,
                           recorded_profile_sha256=plan['profile_sha256'], recorded_probe_sha256=plan['probe_sha256'])})
    (audit/'COMPLETE').write_text(aid+'\n')
    return audit/'report.json', profile, probe, hp3


class PlanningTests(unittest.TestCase):
    def test_three_windows_are_disjoint_from_all_old_timestamps(self):
        excluded = hp5.exclusions(history_plan())
        result = hp5.select_windows(1_958_000, excluded)
        self.assertEqual(len(result), 3)
        for w in result:
            self.assertEqual(w['end_ms']-w['start_ms'], 8000)
            self.assertFalse(any(w['start_ms'] < b and a < w['end_ms'] for a, b in excluded))

    def test_dense_exclusion_includes_between_observations(self):
        plan = {'batches': [{'id': 'window-00', 'kind': 'targeted_dense',
                            'frames': [{'timestamp_ms': 10000}, {'timestamp_ms': 12000}]}]}
        self.assertEqual(hp5.exclusions(plan), [[5000, 17001]])

    def test_predictions_and_order_of_batches_cannot_choose_windows(self):
        plan = history_plan(); other = copy.deepcopy(plan)
        other['batches'].reverse()
        for b in other['batches']:
            for r in b['frames']:
                r.update(expected=36, hp=56, status='accepted', confidence=1.0)
        self.assertEqual(hp5.exclusions(plan), hp5.exclusions(other))

    def test_deterministic_before_any_read(self):
        ex = hp5.exclusions(history_plan())
        self.assertEqual(hp5.select_windows(1_958_000, ex), hp5.select_windows(1_958_000, ex))

    def test_no_available_third_fails_without_reusing_old_frames(self):
        with self.assertRaisesRegex(ValueError, 'insufficient disjoint'):
            hp5.select_windows(120000, [[40000, 80000]])

    def test_invalid_duration_and_old_timestamps(self):
        for d in (0, -1, True, 86_400_001):
            with self.assertRaises(ValueError): hp5.select_windows(d, [])
        for ts in ([1, 1], [2, 1], [True], [-1]):
            p = {'batches': [{'id': 'sparse-regression', 'kind': 'sparse_regression',
                              'frames': [{'timestamp_ms': t} for t in ts]}]}
            with self.assertRaises(ValueError): hp5.exclusions(p)

    def test_invalid_kind_duplicate_batches_and_budgets(self):
        p = history_plan(); p['batches'][0]['kind'] = 'invented'
        with self.assertRaises(ValueError): hp5.exclusions(p)
        p = history_plan(); p['batches'].append(p['batches'][0])
        with self.assertRaises(ValueError): hp5.exclusions(p)
        p = history_plan(); p['batches'][0]['frames'] *= 10
        with self.assertRaises(ValueError): hp5.exclusions(p)

    def test_interval_merge_does_not_mutate_input(self):
        x = [[10, 20], [19, 30], [40, 50]]; before = copy.deepcopy(x)
        self.assertEqual(hp5.merged(x), [[10, 30], [40, 50]])
        self.assertEqual(x, before)


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.window = dict(start_ms=10000, end_ms=18000)
        self.rows = sequence_rows()

    def test_verified_pts_and_cadence(self):
        s = hp5.check_sequence(self.rows, self.window, [])
        self.assertEqual((s['frames'], s['max_gap_ms']), (32, 250))

    def test_boundary_pts_not_synthetic_indices(self):
        self.rows[1]['source_pts'] += 1
        with self.assertRaisesRegex(ValueError, 'PTS'): hp5.check_sequence(self.rows, self.window, [])

    def test_out_of_order_repeated_pts_and_large_gap(self):
        for mutate in (lambda r: r.__setitem__(1, copy.deepcopy(r[0])),
                       lambda r: r.__delitem__(slice(1, 4))):
            rows = copy.deepcopy(self.rows); mutate(rows)
            with self.assertRaises(ValueError): hp5.check_sequence(rows, self.window, [])

    def test_old_evidence_guard_checked_after_decode(self):
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            hp5.check_sequence(self.rows, self.window, [[15000, 15100]])

    def test_frame_at_exclusive_end_is_rejected(self):
        self.rows.append({**self.rows[-1], 'timestamp_ms':18000, 'source_pts':18000, 'image':'new.png'})
        with self.assertRaisesRegex(ValueError, 'outside'): hp5.check_sequence(self.rows, self.window, [])

    def test_truncated_sequence_is_not_success(self):
        for rows in (self.rows[:23], self.rows[:28], self.rows[4:]):
            with self.assertRaises(ValueError): hp5.check_sequence(rows, self.window, [])

    def test_repeated_image_content_reported_not_called_independent(self):
        for r in self.rows: r['decoded_checksum'] = '00000000'
        s = hp5.check_sequence(self.rows, self.window, [])
        self.assertEqual(s['repeated_decoded_checksums'], 31)
        self.assertIn('not independent', s['timestamp_basis'])

    def test_unsafe_path_hash_and_zero_timebase_rejected(self):
        for field, value in [('image', '../escape'), ('sha256', 'short'), ('source_time_base', '0/1')]:
            rows = copy.deepcopy(self.rows); rows[0][field] = value
            with self.assertRaises(ValueError): hp5.check_sequence(rows, self.window, [])


class DecisionTests(unittest.TestCase):
    def test_new_easy_sequence_cannot_clear_quarantine(self):
        d = hp5.inherited_decision({'review_action':'quarantine_candidate', 'reasons':['opposing_eligible_attempt']}, {})
        self.assertEqual(d['review_action'], 'quarantine_candidate')
        self.assertTrue(d['candidate_activation_blocked'])
        self.assertFalse(d['baseline_correctness_established'])

    def test_new_conflict_quarantines_but_never_mutates_active(self):
        d = hp5.inherited_decision({'review_action':'ready_for_disjoint_shadow'}, {'sign_disagreement':1})
        self.assertEqual(d['review_action'], 'quarantine_candidate')
        self.assertEqual(d['active_action'], 'retain_baseline')
        self.assertFalse(d['active_profile_written'])

    def test_gains_are_not_accuracy_or_training_labels(self):
        d = hp5.inherited_decision({'review_action':'hold_candidate'}, {'candidate_only_readable':99})
        self.assertEqual(d['review_action'], 'hold_candidate')
        self.assertFalse(d['human_labels_required'])
        self.assertIn('cannot clear', d['note'])


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audit, self.profile, self.probe, self.hp3 = source_fixture(self.root)

    def context(self):
        return hp5.source_context(self.audit, self.root, self.profile, self.probe)

    def test_verifies_frozen_history_and_binary(self):
        c = self.context()
        self.assertEqual(c['prior_decision']['review_action'], 'quarantine_candidate')
        hp5.verify_inputs(c['input_files_sha256'])

    def test_history_modified_after_audit_is_rejected(self):
        (self.hp3/'sparse-regression/report.json').write_text('{"tampered":true}')
        with self.assertRaisesRegex(ValueError, 'changed'): self.context()

    def test_executable_or_profile_changed_is_rejected(self):
        self.probe.write_bytes(b'new build')
        with self.assertRaisesRegex(ValueError, 'hash changed'): self.context()

    def test_bad_completion_and_audit_id_rejected(self):
        (self.audit.parent/'COMPLETE').write_text('wrong')
        with self.assertRaisesRegex(ValueError, 'completion'): self.context()

    def test_postrun_rehash_catches_change(self):
        c = self.context(); self.profile.write_text('{"changed":1}')
        with self.assertRaisesRegex(ValueError, 'changed'): hp5.verify_inputs(c['input_files_sha256'])

    def test_new_outputs_do_not_overwrite(self):
        p = self.root/'out.json'; hp5.write(p, {'a':1})
        with self.assertRaises(FileExistsError): hp5.write(p, {'a':2})
        self.assertEqual(hp5.load(p), {'a':1})

    def test_duplicate_json_keys_and_nonfinite_are_errors(self):
        p = self.root/'bad.json'
        for text in ('{"x":1,"x":2}', '{"x":NaN}'):
            p.write_text(text)
            with self.assertRaises(ValueError): hp5.load(p)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            other = Path(outside)/'report.json'; other.write_text('{}')
            p = self.hp3/'sparse-regression/report.json'; p.unlink(); p.symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'outside'): self.context()


class NativeIntegration(unittest.TestCase):
    def test_complete_frozen_evaluation_with_real_media_and_rust(self):
        path = os.environ.get('TFT_HP5_PROBE')
        available = path and Path(path).is_file() and all(shutil.which(x) for x in ('ffmpeg','ffprobe','tesseract'))
        if not available:
            if os.environ.get('TFT_REQUIRE_HP5_NATIVE') == '1':
                self.fail('required Rust/FFmpeg/Tesseract integration unavailable')
            self.skipTest('native HP5 integration is required in HUD media CI')
        from training.player_hp_candidate_audit import audit
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); video = root/'fixture.mkv'
            subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-f','lavfi','-i',
                            'color=black:s=64x64:r=4:d=120','-c:v','ffv1',str(video)], check=True, timeout=30)
            # Small synthetic profile: no match glyph, so no HP must be invented.
            profile = root/'profile.json'
            hp5.write(profile, dict(schema_version=1,name='match001-self-badge-v1',reference_width=64,reference_height=64,
                search_rect=dict(x=0,y=0,width=64,height=64),anchor_width=6,anchor_height=6,
                gold_points=[[0,0],[1,1],[2,2]],dark_points=[[4,4]],min_gold_fraction=.94,min_dark_fraction=.85,
                nms_radius_px=4,max_raw_peaks=256,hp_offset_x=6,hp_offset_y=1,hp_width=10,hp_height=10,max_hp_abs=300,min_confidence=.70))
            probe = Path(path).resolve()
            hp2, hp3, hp4 = root/'hp2', root/'hp3', root/'hp4'
            hp2.mkdir(); hp3.mkdir(); hp4.mkdir()
            hp5.write(hp2/'plan.json', dict(source_video=str(video),video_size=video.stat().st_size,video_mtime_ns=video.stat().st_mtime_ns))
            folder = hp3/'sparse-regression'; folder.mkdir()
            frames=[]
            for i, at in enumerate([0,60000,90000]):
                image=folder/f'prior-{i}.ppm'; image.write_bytes(b'P6\n64 64\n255\n'+b'\0'*(64*64*3))
                frames.append(dict(timestamp_ms=at,image=image.name,sha256=hp5.sha256(image)))
            hp5.write(folder/'manifest.json', {'frames':frames})
            subprocess.run([str(probe),str(folder/'manifest.json'),str(folder),str(profile),str(folder/'report.json')],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=30)
            previous=hp5.load(folder/'report.json')['summary']
            metric_keys=('frames','baseline_statuses','candidate_statuses','comparison','baseline_confirmed_frames','candidate_confirmed_frames')
            hp5.write(hp3/'plan.json', dict(source=str(hp2),profile_sha256=hp5.sha256(profile),probe_sha256=hp5.sha256(probe),labels_used=False,
                batches=[dict(id='sparse-regression',kind='sparse_regression',root=str(folder),frames=frames)]))
            hp5.write(hp3/'report.json', {'summary':dict(execution_complete=True,labels_used=False,game_state_updated=False,
                profile_promoted=False,model_trained=False,groups={'sparse_regression':{k:previous[k] for k in metric_keys}})})
            with contextlib.redirect_stdout(io.StringIO()): audit(hp3,hp4/'audit')
            args=argparse.Namespace(audit=hp4/'audit/report.json',evidence_root=root,video=video,profile=profile,
                                    probe=probe,output=root/'new-shadow')
            with contextlib.redirect_stdout(io.StringIO()): result=hp5.run(args)
            self.assertTrue(result['execution_complete'])
            self.assertGreaterEqual(result['frames'],72)
            self.assertEqual(result['comparison'],{'neither_readable':result['frames']})
            self.assertEqual(result['candidate_confirmed_frames'],0)
            self.assertFalse(result['profile_promoted'])
            self.assertTrue((args.output/'COMPLETE.json').is_file())
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(FileExistsError): hp5.run(args)


if __name__ == '__main__':
    unittest.main()
