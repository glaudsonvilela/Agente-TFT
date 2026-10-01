"""Integrated A14/HP5 report validation. No media or executable is run."""
import argparse
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training.tests.test_register_hp5_profiles import source_fixture
from training.register_hp5_profiles import prepare_import
from training.perception_registry import Registry
from training.coordinate_hp5_perception import prepare, run


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source,self.profile,self.probe=source_fixture(self.root)
        self.registry=self.root/'registry.sqlite3';self.db=self.root/'coordinator.sqlite3'
        with Registry(self.registry) as r:
            self.receipt=r.import_review(**prepare_import(self.source,self.root,self.profile,self.probe))
        self.args=argparse.Namespace(source=self.source,evidence_root=self.root,profile=self.profile,
            probe=self.probe,registry=self.registry,database=self.db,output=self.root/'result.json')
    def execute(self):
        with (redirect_stdout(io.StringIO()), patch('subprocess.run',side_effect=AssertionError('no backend')),
              patch('subprocess.Popen',side_effect=AssertionError('no child'))):
            return run(self.args)
    def test_known_report_creates_zero_intents_and_retains_quarantine(self):
        before=self.registry.read_bytes();s=self.execute()
        self.assertEqual(s['actions'],{'skip_already_evaluated':3});self.assertEqual(s['intents_created'],0)
        self.assertEqual(s['decisions_written'],3);self.assertEqual(s['registry_revision'],1)
        self.assertEqual(s['permission']['status'],'quarantined');self.assertFalse(s['permission']['activation_allowed'])
        self.assertTrue(s['restart_read_verified']);self.assertEqual(self.registry.read_bytes(),before)
    def test_second_run_reuses_decisions_without_another_revision(self):
        first=self.execute();self.args.output=self.root/'second.json';second=self.execute()
        self.assertEqual(second['decisions_written'],0);self.assertEqual(second['ledger_revision'],first['ledger_revision'])
        self.assertEqual(second['intents_created'],0)
    def test_adapter_derives_exact_A14_evidence_id_without_labels(self):
        _,eid,seq=prepare(self.source,self.root,self.profile,self.probe)
        self.assertEqual(eid,self.receipt['evidence_id']);self.assertEqual(len(seq),3)
        for s in seq:
            self.assertEqual(set(s['samples'][0]),{'timestamp_ms','image_sha256','status','marker'})
    def test_forged_source_fails_before_ledger(self):
        p=self.source/'sequence-00'/'report.json';p.write_text('{}')
        with self.assertRaises((ValueError,KeyError)):self.execute()
        self.assertFalse(self.db.exists())
    def test_changed_executable_fails_before_ledger(self):
        self.probe.write_bytes(b'other reader')
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.db.exists())
    def test_wrong_registered_evidence_is_not_imported_implicitly(self):
        other=self.root/'other.sqlite3'
        with Registry(other):pass
        self.args.registry=other
        with self.assertRaisesRegex(ValueError,'not registered'):self.execute()
        self.assertFalse(self.db.exists())
    def test_existing_output_not_overwritten(self):
        self.args.output.write_text('keep')
        with self.assertRaisesRegex(ValueError,'already exists'):self.execute()
        self.assertEqual(self.args.output.read_text(),'keep');self.assertFalse(self.db.exists())
    def test_registry_missing_fails_without_new_file(self):
        self.args.registry=self.root/'missing.sqlite3'
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.args.registry.exists())

if __name__=='__main__':unittest.main()
