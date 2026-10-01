"""S2 regression comparison and required native panel recovery checks."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from ingestion.knowledge_release import canonical
from training.shop_recovery_compare import compare, comparison, read_run, verify_current
from training.shop_replay_observe import run, sha
from training.tests.test_shop_replay_native import paint, png


def write_run(folder, profile, names=None):
    folder.mkdir()
    names = names or ['Alpha'] * 5
    slots = [dict(slot=i, status='offer_text_readable' if name else 'partially_readable',
                  observed_name=name, observed_cost=1, unit_id=None) for i, name in enumerate(names)]
    summary = dict(profile=profile, frames=1, panel_statuses={'located': 1},
                   slot_statuses=dict(Counter(s['status'] for s in slots)), layout_id='fixture',
                   locale='pt_br', ocr_language='eng', execution_complete=True, catalog_status='not_bound',
                   labels_used=False, game_state_updated=False, profile_promoted=False, model_trained=False)
    report = dict(summary=summary, records=[dict(read=dict(timestamp_ms=0, panel_status='located',
                  slots=slots, error=None))], provenance=dict(input_files_sha256={}))
    manifest = dict(frames=[dict(timestamp_ms=0, image='a.png', sha256='a'*64)], labels_used=False)
    (folder/'report.json').write_bytes(canonical(report))
    (folder/'manifest.json').write_bytes(canonical(manifest))
    seal(folder)
    return folder/'report.json'


def seal(folder):
    (folder/'COMPLETE.json').write_bytes(canonical(dict(report_sha256=sha(folder/'report.json'),
                                                      manifest_sha256=sha(folder/'manifest.json'))))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = write_run(self.root/'s1', 'shop_text_atlas_v1')
        self.new = write_run(self.root/'s2', 'shop_text_atlas_v2_local_routing')

    def test_equal_is_agreement_not_accuracy(self):
        value = compare(self.old, self.new)
        self.assertEqual(value['fields']['name'], {'both_equal': 5})
        self.assertIsNone(value['exact_accuracy'])
        self.assertFalse(value['profile_promoted'])

    def test_disagreement_is_never_resolved_by_larger_confidence(self):
        report = json.loads(self.new.read_text())
        report['records'][0]['read']['slots'][0]['observed_name'] = 'Beta'
        report['records'][0]['read']['slots'][0]['name_confidence'] = 0.99
        self.new.write_bytes(canonical(report)); seal(self.new.parent)
        value = compare(self.old, self.new)
        self.assertEqual(value['fields']['name']['both_disagree'], 1)
        self.assertEqual(value['cases'][0]['baseline'], 'Alpha')
        self.assertEqual(value['cases'][0]['candidate'], 'Beta')

    def test_exclusive_loss_is_visible(self):
        report = json.loads(self.new.read_text())
        report['records'][0]['read']['slots'][2]['observed_name'] = None
        self.new.write_bytes(canonical(report)); seal(self.new.parent)
        self.assertEqual(compare(self.old, self.new)['fields']['name']['baseline_only'], 1)

    def test_changed_manifest_cannot_count_as_same_pixels(self):
        path = self.new.parent/'manifest.json'
        value = json.loads(path.read_text()); value['frames'][0]['sha256'] = 'b'*64
        path.write_bytes(canonical(value)); seal(self.new.parent)
        with self.assertRaises(ValueError): compare(self.old, self.new)

    def test_rehashed_false_aggregate_is_rejected(self):
        value = json.loads(self.new.read_text()); value['summary']['slot_statuses'] = {'unknown': 5}
        self.new.write_bytes(canonical(value)); seal(self.new.parent)
        with self.assertRaises(ValueError): read_run(self.new)

    def test_missing_seal_and_modified_bytes_fail(self):
        self.new.write_bytes(self.new.read_bytes() + b' ')
        with self.assertRaises(ValueError): read_run(self.new)
        (self.old.parent/'COMPLETE.json').unlink()
        with self.assertRaises(OSError): read_run(self.old)

    def test_context_or_reader_mismatch_rejected(self):
        value = json.loads(self.new.read_text()); value['summary']['ocr_language'] = 'por'
        self.new.write_bytes(canonical(value)); seal(self.new.parent)
        with self.assertRaises(ValueError): compare(self.old, self.new)
        with self.assertRaises(ValueError): compare(self.old, self.old)

    def test_side_effect_flags_cannot_hide_in_a_sealed_report(self):
        value = json.loads(self.new.read_text()); value['summary']['model_trained'] = True
        self.new.write_bytes(canonical(value)); seal(self.new.parent)
        with self.assertRaises(ValueError): read_run(self.new)

    def test_comparison_preserves_apostrophes_and_does_not_fix_spelling(self):
        self.assertEqual(comparison("Rek'Sai", "rek'sai"), 'both_equal')
        self.assertEqual(comparison('Trevoguari', 'Trovoguari'), 'both_disagree')
        self.assertEqual(comparison(None, None), 'neither')

    def test_current_pixels_checked_before_ocr(self):
        image = self.root/'a.png'; image.write_bytes(b'fixture')
        ui = self.root/'ui.json'; ui.write_text('{}')
        source = self.root/'source.json'; source.write_bytes(canonical(dict(frames=[dict(timestamp_ms=0, image='a.png')])))
        manifest = dict(frames=[dict(timestamp_ms=0, image='a.png', sha256=sha(image))], labels_used=False)
        (self.old.parent/'manifest.json').write_bytes(canonical(manifest))
        value = json.loads(self.old.read_text())
        value['provenance']['input_files_sha256'][str(ui.resolve())] = sha(ui)
        self.old.write_bytes(canonical(value)); seal(self.old.parent)
        verify_current(self.old, source, self.root, ui)
        image.write_bytes(b'changed')
        with self.assertRaises(ValueError): verify_current(self.old, source, self.root, ui)


class NativeRecoveryTests(unittest.TestCase):
    def test_fallback_without_button_text_and_no_false_empty(self):
        required = os.environ.get('TFT_REQUIRE_SHOP1_NATIVE') == '1'
        executable = os.environ.get('TFT_SHOP1_PROBE')
        if not executable or not Path(executable).is_file() or not shutil.which('ffmpeg') or not shutil.which('tesseract'):
            if required: self.fail('required native S2 tools missing')
            self.skipTest('native S2 path required in HUD media')
        project = Path(__file__).resolve().parents[2]
        ui = project/'configs/ui/match001-desktop-1920x1080-ptbr-v1.json'
        recovery = project/'configs/ui/match001-shop-recovery-v2.json'
        layout = json.loads(ui.read_text()); profile = json.loads(recovery.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); width, height = 1920, 1080
            pixels = bytearray(width*height*3)
            for anchor in profile['anchors']:
                paint(pixels, width, anchor['rect'], anchor['pixels'], anchor['grid_width'], anchor['grid_height'])
            template = layout['empty_template']
            for slot in layout['slots']:
                paint(pixels, width, slot['empty_region'], template['pixels'], template['grid_width'], template['grid_height'])
            png(root/'empty.png', width, height, pixels)
            paint(pixels, width, layout['slots'][2]['empty_region'], [0], 1, 1)
            png(root/'unknown.png', width, height, pixels)
            png(root/'hidden.png', width, height, bytearray(width*height*3))
            manifest = root/'manifest.json'
            manifest.write_bytes(canonical(dict(frames=[dict(timestamp_ms=i*250, image=name)
                for i, name in enumerate(['empty.png', 'unknown.png', 'hidden.png'])])))
            def invoke(output, recovery_path):
                with redirect_stdout(io.StringIO()):
                    return run(argparse.Namespace(manifest=manifest, image_root=root, layout=ui,
                        probe=Path(executable), output=output, release=None, context=None, recovery_profile=recovery_path))
            old = invoke(root/'old', None)
            self.assertEqual(old['panel_statuses'], {'unresolved': 3})
            new = invoke(root/'new', recovery)
            report = json.loads((root/'new/report.json').read_text())
            reads = [row['read'] for row in report['records']]
            self.assertEqual(reads[0]['recovery']['panel_source'], 'structural_fallback')
            self.assertEqual([s['status'] for s in reads[0]['slots']], ['empty_observed']*5)
            self.assertEqual(reads[1]['slots'][2]['status'], 'unknown')
            self.assertEqual([s['status'] for s in reads[2]['slots']], ['unavailable']*5)
            self.assertEqual(new['ocr_process_calls'], 2)
            self.assertFalse(new['game_state_updated']); self.assertIsNone(new['exact_accuracy'])
            for suffix, mutation in [('parent', lambda p: p.update(parent_layout_id='wrong')),
                                     ('threshold', lambda p: p['anchors'][0].update(min_similarity=0.5)),
                                     ('semantic_region', lambda p: p['anchors'][0].update(rect=layout['slots'][0]['card']))]:
                invalid = copy.deepcopy(profile); mutation(invalid)
                path = root/(suffix+'.json'); path.write_bytes(canonical(invalid))
                with self.assertRaises(ValueError): invoke(root/suffix, path)
                self.assertFalse((root/suffix/'report.json').exists())
