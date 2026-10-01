"""Explicit replay identity is frozen before shop OCR; no new normalizer."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingestion.knowledge_release import build
from ingestion.tests.test_knowledge_release import source
from training.shop_replay_observe import freeze_binding, verify_sources


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'source.json'
        self.input.write_text(json.dumps(source()))
        self.release, self.manifest, _ = build(self.input, selector='18', tft_patch='18.3',
            source_build='16.19', locale='pt_br', output_root=self.root / 'releases')
        self.layout = dict(id='fixture-ui', locale='pt_br')
        self.context = dict(schema_version=1, set_key='18', tft_patch='18.3',
            locale='pt_br', layout_id='fixture-ui', knowledge_release=self.manifest['release_sha256'])
        self.path = self.root / 'context.json'

    def freeze(self):
        self.path.write_text(json.dumps(self.context))
        return freeze_binding(self.path, self.release, self.layout)

    def test_context_and_all_release_components_are_fingerprinted(self):
        with patch('subprocess.Popen', side_effect=AssertionError('preflight cannot execute OCR')):
            context, identity, fingerprints = self.freeze()
        self.assertEqual(identity, self.manifest['release_sha256'])
        self.assertEqual(context, self.context)
        self.assertEqual({Path(p).name for p in fingerprints},
                         {'context.json', 'release.json', 'units.json', 'items.json', 'traits.json'})
        verify_sources(fingerprints)

    def test_wrong_content_pin_is_rejected_even_with_matching_patch(self):
        self.context['knowledge_release'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'content pin'):
            self.freeze()

    def test_unknown_patch_is_not_guessed_before_ocr(self):
        self.context['tft_patch'] = None
        with self.assertRaisesRegex(ValueError, 'set/patch'):
            self.freeze()

    def test_data_changed_after_freeze_is_rejected(self):
        _, _, fingerprints = self.freeze()
        (self.release / 'units.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'input changed'):
            verify_sources(fingerprints)
