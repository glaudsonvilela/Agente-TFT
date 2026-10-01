import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.perception_registry import Registry, APP_ID, canonical, context_key, profile_key


def incoming(n=1):
    return dict(context=dict(mode='offline_replay', subsystem='player_list', field='hp', recording_sha256='a'*64),
                baseline=dict(reader='hp1', executable_sha256='b'*64, config_sha256='c'*64),
                candidate=dict(reader='hp_text_fit_v1', executable_sha256='b'*64, config_sha256='c'*64),
                payload=dict(fixture=n, independent_accuracy=None), blockers=['opposing_eligible_attempt'])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'registry.sqlite3'

    def test_empty_registry_has_no_active_profile_and_denies_unknown(self):
        with Registry(self.path) as r:
            self.assertEqual(r.inspect()['revision'], 0)
            p = r.permission(incoming()['candidate'])
            self.assertFalse(p['activation_allowed'])
            self.assertFalse(p['shadow_evaluation_allowed'])

    def test_import_is_durable_after_reopen(self):
        with Registry(self.path) as r:
            receipt = r.import_review(**incoming())
            self.assertEqual(receipt['candidate_state'], 'quarantined')
        with Registry(self.path) as r:
            state = r.inspect()
            self.assertEqual(state['revision'], 1)
            self.assertEqual(len(state['snapshot']['profiles']), 2)
            self.assertEqual(r.permission(incoming()['candidate'])['status'], 'quarantined')
            self.assertFalse(r.permission(incoming()['candidate'])['activation_allowed'])

    def test_duplicate_import_is_idempotent_including_stale_retry(self):
        with Registry(self.path) as r:
            a = r.import_review(**incoming(), expected_revision=0)
            b = r.import_review(**incoming(), expected_revision=0)
            self.assertTrue(a['changed']); self.assertFalse(b['changed'])
            self.assertEqual(a['evidence_id'], b['evidence_id'])
            self.assertEqual(b['revision'], 1)

    def test_better_new_review_cannot_clear_historical_block(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            good = incoming(2); good['blockers'] = []
            res = r.import_review(**good)
            self.assertEqual(res['candidate_state'], 'quarantined')
            self.assertEqual(res['blocker_reasons'], ['opposing_eligible_attempt'])
            self.assertTrue(r.permission(good['candidate'])['shadow_evaluation_allowed'])

    def test_profile_content_change_is_not_automatic_approval(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            new = incoming(2); new['candidate']['executable_sha256'] = 'd'*64; new['blockers'] = []
            r.import_review(**new)
            self.assertEqual(r.permission(incoming()['candidate'])['status'], 'quarantined')
            self.assertEqual(r.permission(new['candidate'])['status'], 'shadow_only')
            self.assertFalse(r.permission(new['candidate'])['activation_allowed'])

    def test_new_recording_does_not_clear_same_reader_quarantine(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            new = incoming(2); new['context']['recording_sha256'] = 'd'*64; new['blockers'] = []
            r.import_review(**new)
            self.assertEqual(len(r.inspect()['snapshot']['contexts']), 2)
            self.assertEqual(r.permission(new['candidate'])['status'], 'quarantined')

    def test_reference_is_bound_to_scope_and_cannot_be_replaced_by_import(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            new = incoming(2); new['baseline']['executable_sha256'] = 'd'*64
            with self.assertRaisesRegex(ValueError, 'replacement'):
                r.import_review(**new)
            self.assertEqual(r.inspect()['revision'], 1)

    def test_stale_revision_has_no_partial_changes(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            with self.assertRaisesRegex(ValueError, 'stale registry'):
                r.import_review(**incoming(2), expected_revision=0)
            self.assertEqual(r.inspect()['revision'], 1)

    def test_failure_after_sql_writes_rolls_back_snapshot_and_event(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            before = r.inspect()
            original = r._persist
            def fail(*args):
                original(*args)
                raise RuntimeError('injected before commit')
            with patch.object(r, '_persist', fail):
                with self.assertRaises(RuntimeError):
                    r.import_review(**incoming(2))
            self.assertEqual(r.inspect(), before)
        with Registry(self.path) as r:
            self.assertEqual(r.inspect(), before)

    def test_process_exit_before_commit_does_not_publish_new_snapshot(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
            before = r.inspect()
        code = '''import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1],isolation_level=None)
c.execute("BEGIN IMMEDIATE")
c.execute("UPDATE snapshot SET body='incomplete'")
os._exit(17)
'''
        run = subprocess.run([sys.executable, '-c', code, str(self.path)], timeout=10)
        self.assertEqual(run.returncode, 17)
        with Registry(self.path) as r:
            self.assertEqual(r.inspect(), before)

    def test_simultaneous_imports_serialize_without_lost_update(self):
        with Registry(self.path):
            pass
        def run(n):
            with Registry(self.path) as r:
                return r.import_review(**incoming(n))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, range(1,9)))
        with Registry(self.path) as r:
            self.assertEqual(r.inspect()['revision'], 8)
            self.assertEqual(len(r.inspect()['snapshot']['reviews']), 8)

    def test_simultaneous_duplicate_imports_create_one_event(self):
        with Registry(self.path):
            pass
        def run(_):
            with Registry(self.path) as r:
                return r.import_review(**incoming())
        with ThreadPoolExecutor(max_workers=4) as pool:
            out = list(pool.map(run, range(8)))
        self.assertEqual(sum(x['changed'] for x in out), 1)

    def test_corrupted_snapshot_fails_closed_without_reset(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE snapshot SET body='{}'")
        with self.assertRaises(ValueError):
            Registry(self.path)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT body FROM snapshot').fetchone()[0], '{}')

    def test_modified_event_is_detected(self):
        with Registry(self.path) as r:
            r.import_review(**incoming())
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE events SET previous_hash='tampered'")
        with self.assertRaisesRegex(ValueError, 'chain'):
            Registry(self.path)

    def test_foreign_database_not_overwritten(self):
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE TABLE user_data(value TEXT)')
        with self.assertRaisesRegex(ValueError, 'compatible'):
            Registry(self.path)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('user_data',)])

    def test_unknown_schema_is_not_migrated_silently(self):
        with Registry(self.path):
            pass
        with sqlite3.connect(self.path) as con:
            con.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError): Registry(self.path)

    def test_symlink_targets_are_rejected(self):
        target = self.path.with_name('other.db'); target.write_bytes(b'original')
        self.path.symlink_to(target)
        with self.assertRaises(ValueError): Registry(self.path)
        self.assertEqual(target.read_bytes(), b'original')

    def test_invalid_identity_rejected_before_mutation(self):
        with Registry(self.path) as r:
            for field, value in [('reader','../escape'), ('config_sha256','bad')]:
                obj = incoming(); obj['candidate'][field] = value
                with self.assertRaises(ValueError): r.import_review(**obj)
            self.assertEqual(r.inspect()['revision'], 0)

    def test_nonfinite_payload_and_equal_reader_rejected(self):
        with Registry(self.path) as r:
            obj = incoming(); obj['payload']['score'] = float('nan')
            with self.assertRaises(ValueError): r.import_review(**obj)
            obj = incoming(); obj['candidate'] = obj['baseline'].copy()
            with self.assertRaises(ValueError): r.import_review(**obj)

    def test_input_objects_are_not_mutated_and_duplicate_reasons_collapsed(self):
        obj = incoming(); obj['blockers'] *= 2; before = copy.deepcopy(obj)
        with Registry(self.path) as r:
            result = r.import_review(**obj)
            self.assertEqual(obj, before)
            self.assertEqual(len(result['blocker_reasons']), 1)

    def test_baseline_reference_is_not_production_activation(self):
        obj = incoming()
        with Registry(self.path) as r:
            receipt = r.import_review(**obj)
            self.assertFalse(receipt['active_profile_written'])
            binding = r.inspect()['snapshot']['contexts'][context_key(obj['context'])]
            self.assertEqual(binding['baseline_key'], profile_key(obj['baseline']))
            self.assertFalse(r.permission(obj['baseline'])['activation_allowed'])
