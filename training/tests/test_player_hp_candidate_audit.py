import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io

from training import player_hp_candidate_audit as m


def reading(value, at):
    attempts = [dict(scale=scale, text=str(value if value is not None else 44),
                     parsed_signed=value if value is not None else 44,
                     confidence=.9 if value is not None else .2,
                     reason='candidate' if value is not None else 'below_min_confidence', error=None)
                for scale in (3, 4)]
    return dict(frame_id=at, timestamp_ms=at,
        status='ocr_uncertain' if value is None else 'negative_display' if value < 0 else 'accepted',
        signed_hp=value, hp=value if value is not None and value >= 0 else None,
        confidence=.9 if value is not None else None, error=None, attempts=attempts,
        location=dict(candidates=[dict(anchor={}, hp_rect={}, marker_score=1.)], raw_peaks=1, budget_exceeded=False))


def fixture(pairs=((100, 100), (100, 100)), kind='targeted_dense', key='window-00', step=250):
    rows, frames = [], []
    for i, (b, c) in enumerate(pairs):
        at = 1000 + i*step
        b, c = reading(b, at), reading(c, at)
        frames.append(dict(timestamp_ms=at, image=f'frames/{i}.png',
                           sha256=hashlib.sha256(str(i).encode()).hexdigest()))
        rows.append(dict(timestamp_ms=at, baseline=b, candidate=c, comparison=m.classify(b, c),
                         baseline_ms=222., candidate_ms=220., decode_ms=1., text_fit=[]))
    summary = dict(exact_accuracy=None, labels_used=False, game_state_updated=False,
                   profile_promoted=False, model_trained=False, execution_complete=True, errors=0,
                   baseline_profile='match001-self-badge-v1', candidate_profile='hp_text_fit_v1')
    for side in ('baseline', 'candidate'):
        fresh = m.replay_freshness([r[side] for r in rows])
        for r, f in zip(rows, fresh):
            r[side+'_freshness'] = f
        summary[side+'_confirmed_frames'] = sum(f['current'] is not None for f in fresh)
        summary[side+'_statuses'] = dict(m.Counter(r[side]['status'] for r in rows))
    summary.update(frames=len(rows), comparison=dict(m.Counter(r['comparison'] for r in rows)))
    plan = dict(batches=[dict(id=key, kind=kind, frames=frames)], labels_used=False,
                profile_sha256='a'*64, probe_sha256='b'*64)
    return plan, {key: dict(summary=summary, records=rows)}


def save_fixture(root, plan, reports):
    summary, _ = m.build_review(plan, reports)
    root.mkdir()
    (root/'plan.json').write_text(json.dumps(plan))
    (root/'report.json').write_text(json.dumps({'summary':summary}))
    for b in plan['batches']:
        d = root/b['id']; d.mkdir()
        (d/'manifest.json').write_text(json.dumps({'frames':b['frames']}))
        (d/'report.json').write_text(json.dumps(reports[b['id']]))


class CandidateAuditTests(unittest.TestCase):
    def test_equal_readers_never_promote(self):
        s, cases = m.build_review(*fixture())
        self.assertEqual(cases, [])
        self.assertFalse(s['profile_promoted'])
        self.assertEqual(s['decision']['review_action'], 'keep_baseline_no_operational_gain')

    def test_exclusive_gain_only_ready_for_new_shadow(self):
        s, cases = m.build_review(*fixture(((None, 45), (None, 45))))
        self.assertEqual(s['decision']['review_action'], 'ready_for_disjoint_shadow')
        self.assertEqual(s['groups']['targeted_dense']['candidate_confirmed_frames'], 1)
        self.assertFalse(s['profile_promoted'])
        self.assertTrue(all(c['target_hp'] is None and not c['eligible_for_training'] for c in cases))

    def test_one_loss_blocks_despite_many_gains(self):
        s, _ = m.build_review(*fixture(((None, 45), (None, 45), (81, None))))
        self.assertEqual(s['decision']['review_action'], 'hold_candidate')
        self.assertIn('baseline_only_readable', s['decision']['reasons'])

    def test_accepted_disagreement_quarantines_without_picking_value(self):
        s, cases = m.build_review(*fixture(((36, 56),)))
        self.assertEqual(s['decision']['review_action'], 'quarantine_candidate')
        self.assertEqual(cases[0]['baseline']['signed_hp'], 36)
        self.assertEqual(cases[0]['candidate']['signed_hp'], 56)
        self.assertIsNone(cases[0]['target_hp'])

    def test_partial_eligible_opposition_is_visible(self):
        p, reports = fixture(((None, 81),))
        b = reports['window-00']['records'][0]['baseline']
        b['attempts'][0].update(text='87', parsed_signed=87, confidence=.8, reason='candidate')
        s, cases = m.build_review(p, reports)
        self.assertEqual(s['decision']['review_action'], 'quarantine_candidate')
        self.assertIn('opposing_eligible_attempt', cases[0]['reasons'])

    def test_sign_opposition_is_not_cast_to_unsigned(self):
        s, cases = m.build_review(*fixture(((-7, 7),)))
        self.assertIn('sign_disagreement', cases[0]['reasons'])
        self.assertEqual(s['decision']['review_action'], 'quarantine_candidate')

    def test_negative_gain_does_not_confirm_unsigned_hp(self):
        s, cases = m.build_review(*fixture(((None, -7), (None, -7))))
        g = s['groups']['targeted_dense']
        self.assertEqual(g['candidate_statuses'], {'negative_display':2})
        self.assertEqual(g['candidate_confirmed_frames'], 0)
        self.assertIsNone(cases[0]['candidate']['hp'])

    def test_sparse_and_dense_remain_separate(self):
        p, r = fixture(((None, 45), (None, 45)))
        p2, r2 = fixture(((81, 81), (81, None)), 'sparse_regression', 'sparse-regression', 50000)
        p['batches'].extend(p2['batches']); r.update(r2)
        s, _ = m.build_review(p, r)
        self.assertEqual(set(s['groups']), {'targeted_dense', 'sparse_regression'})
        self.assertEqual(s['groups']['sparse_regression']['candidate_confirmed_frames'], 0)

    def test_forged_temporal_confirmation_fails(self):
        p, r = fixture(((81, 81), (81, 81)), step=50000)
        r['window-00']['records'][1]['candidate_freshness']['current'] = {'value':81}
        with self.assertRaisesRegex(ValueError, 'temporal'):
            m.build_review(p, r)

    def test_missing_breaks_temporal_confirmation(self):
        s, _ = m.build_review(*fixture(((81, 81), (None, None), (81, 81))))
        self.assertEqual(s['groups']['targeted_dense']['baseline_confirmed_frames'], 0)

    def test_low_confidence_cannot_be_accepted(self):
        p, r = fixture(); r['window-00']['records'][0]['candidate']['attempts'][0]['confidence'] = .69
        with self.assertRaises(ValueError): m.build_review(p, r)

    def test_no_two_scale_acceptance_with_only_one_attempt(self):
        p, r = fixture(); r['window-00']['records'][0]['candidate']['attempts'].pop()
        with self.assertRaises(ValueError): m.build_review(p, r)

    def test_changed_localization_fails(self):
        p, r = fixture(); r['window-00']['records'][0]['candidate']['location']['raw_peaks'] = 2
        with self.assertRaisesRegex(ValueError, 'localization'): m.build_review(p, r)

    def test_summary_tampering_fails(self):
        p, r = fixture(); r['window-00']['summary']['frames'] = 999
        with self.assertRaisesRegex(ValueError, 'summary'): m.build_review(p, r)

    def test_invalid_numeric_inputs_fail(self):
        for val in (float('nan'), float('inf'), True, -.1):
            with self.subTest(val=val):
                p, r = fixture(); r['window-00']['records'][0]['candidate']['confidence'] = val
                with self.assertRaises(ValueError): m.build_review(p, r)

    def test_unsigned_negative_and_bool_value_rejected(self):
        for v in (-7, True):
            p, r = fixture(); r['window-00']['records'][0]['candidate']['hp'] = v
            with self.assertRaises(ValueError): m.build_review(p, r)

    def test_duplicate_order_and_traversal_rejected(self):
        for bad in ('../outside', '/tmp/out', 'window-00/../outside'):
            p, r = fixture(); p['batches'][0]['id'] = bad
            with self.assertRaises(ValueError): m.build_review(p, r)
        p, r = fixture(); p['batches'][0]['frames'][1]['timestamp_ms'] = 1000
        with self.assertRaises(ValueError): m.build_review(p, r)

    def test_expected_labels_cannot_influence_review(self):
        p, r = fixture(((None, 45),)); before = m.build_review(p, r)
        p['batches'][0]['frames'][0]['expected'] = 999
        r['window-00']['records'][0]['expected'] = 999
        self.assertEqual(before, m.build_review(p, r))

    def test_budget_and_extra_reports_rejected(self):
        p, r = fixture(); p['batches'] *= 12
        with self.assertRaises(ValueError): m.build_review(p, r)
        p, r = fixture(); r['extra'] = copy.deepcopy(r['window-00'])
        with self.assertRaises(ValueError): m.build_review(p, r)

    def test_input_side_effect_flag_fails(self):
        for flag in ('labels_used', 'game_state_updated', 'profile_promoted', 'model_trained'):
            p, r = fixture(); r['window-00']['summary'][flag] = True
            with self.assertRaises(ValueError): m.build_review(p, r)

    def test_file_audit_is_reproducible_read_only_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'source'
            save_fixture(source, *fixture(((81, None),)))
            before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            with redirect_stdout(io.StringIO()):
                a = m.audit(source, root/'out1'); b = m.audit(source, root/'out2')
            self.assertEqual(a['audit_id'], b['audit_id'])
            self.assertEqual(before, {str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()})
            self.assertTrue((root/'out1/COMPLETE').is_file())
            cases = [json.loads(x) for x in (root/'out1/cases.jsonl').read_text().splitlines()]
            self.assertEqual(len(cases), 1)
            with self.assertRaises(FileExistsError): m.audit(source, root/'out1')
            with self.assertRaises(ValueError): m.audit(source, source/'child')

    def test_files_reject_duplicate_keys_aggregate_tamper_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'source'; save_fixture(source, *fixture())
            aggregate = source/'report.json'; original = aggregate.read_text()
            aggregate.write_text('{"summary":{},"summary":{}}')
            with self.assertRaisesRegex(ValueError, 'duplicate'): m.audit(source, root/'out')
            bad = json.loads(original); bad['summary']['groups']['targeted_dense']['frames'] = 99
            aggregate.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, 'aggregate'): m.audit(source, root/'out')
            aggregate.unlink(); other = root/'external.json'; other.write_text(original)
            aggregate.symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'escaped'): m.audit(source, root/'out')
            self.assertFalse((root/'out').exists())

    def test_json_byte_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir()
            (source/'plan.json').write_bytes(b' '*(m.MAX_FILE_BYTES+1))
            with self.assertRaisesRegex(ValueError, 'budget'): m.audit(source, root/'out')


if __name__ == '__main__':
    unittest.main()
