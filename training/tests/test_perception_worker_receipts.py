"""Execution accounting must not turn attempted/reconciled work into a new run."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from training.tests.test_perception_worker import Fixture
from training.perception_work_source import load


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.f=Fixture(Path(self.tmp.name));self.f.reserve()

    def drain(self):
        with self.f.worker() as w:return w.drain()

    def test_failed_spawn_is_attempt_not_verified_native_execution(self):
        with patch('training.perception_worker.execute_native',side_effect=OSError('cannot spawn')):
            result=self.drain()
        self.assertEqual(result['native_dispatch_attempts'],1)
        self.assertIsNone(result['native_probe_executed']);self.assertIsNone(result['ocr_executed'])
        self.assertEqual(result['outcomes'],{'failed':1})

    def test_reconciled_success_is_not_another_native_run(self):
        with patch('training.perception_worker.execute_native',side_effect=self.f.backend), \
             patch('training.perception_coordinator.Coordinator.finish_intent',side_effect=RuntimeError('stop before ack')):
            with self.assertRaises(RuntimeError):self.drain()
        with patch('training.perception_worker.execute_native',side_effect=AssertionError('no retry')):
            result=self.drain()
        self.assertEqual(result['results_reconciled'],1)
        self.assertEqual(result['native_dispatch_attempts'],0)
        self.assertFalse(result['native_probe_executed']);self.assertFalse(result['ocr_executed'])
        self.assertTrue(result['results'][0]['native_probe_executed'])  # Historical receipt.

    def test_unsealed_attempt_reconciliation_does_not_claim_ocr(self):
        with patch('training.perception_worker.execute_native',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.drain()
        result=self.drain()
        self.assertEqual(result['results_reconciled'],1)
        self.assertFalse(result['native_probe_executed']);self.assertIsNone(result['results'][0]['ocr_executed'])

    def test_new_report_does_not_turn_claim_into_training_or_activation(self):
        with patch('training.perception_worker.execute_native',side_effect=self.f.backend):result=self.drain()
        item=result['results'][0]
        self.assertFalse(item['model_trained']);self.assertFalse(item['profile_promoted'])
        report=load(self.f.store/'worker'/'attempts'/self.f.key/'review.json')
        self.assertTrue(all(c['target_hp'] is None and not c['eligible_for_training'] for c in report['cases']))
