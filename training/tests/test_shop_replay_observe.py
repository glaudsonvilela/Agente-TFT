import copy
import json
from pathlib import Path
import tempfile
import unittest
from training.shop_replay_observe import prepare
from training.code_health_audit import audit


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'a.jpg').write_bytes(b'fixture bytes, not decoded')
        self.manifest=self.root/'manifest.json'
    def write(self,rows):self.manifest.write_text(json.dumps({'frames':rows}))
    def test_prelabels_and_season_claims_do_not_enter_native_manifest(self):
        rows=[dict(timestamp_ms=0,image='a.jpg',suggestions={'unit':'Alpha'},set=99)]
        self.write(rows);first=prepare(self.manifest,self.root)
        rows[0]['suggestions']={'unit':'Beta'};self.write(rows)
        self.assertEqual(first,prepare(self.manifest,self.root));self.assertFalse(first['labels_used'])
    def test_duplicate_or_backward_time_is_rejected(self):
        for rows in [[dict(timestamp_ms=0,image='a.jpg')]*2,[dict(timestamp_ms=True,image='a.jpg')]]:
            self.write(rows)
            with self.assertRaises(ValueError):prepare(self.manifest,self.root)
    def test_traversal_and_absolute_paths_rejected(self):
        for image in ['../a.jpg',str(self.root/'a.jpg')]:
            self.write([dict(timestamp_ms=0,image=image)])
            with self.assertRaises(ValueError):prepare(self.manifest,self.root)
    def test_code_audit_detects_missing_member_and_python_syntax(self):
        (self.root/'rust').mkdir();(self.root/'rust/Cargo.toml').write_text('[workspace]\nmembers=["missing"]\n')
        (self.root/'bad.py').write_text('if broken')
        r=audit(self.root,['bad.py','rust/Cargo.toml'])
        self.assertEqual({e['kind'] for e in r['errors']},{'python_syntax','missing_workspace_member'})
        self.assertFalse(r['full_semantic_review']);self.assertFalse(r['files_modified'])
    def test_layout_has_no_season_roster_or_patch_binding(self):
        root=Path(__file__).resolve().parents[2]
        layout=json.loads((root/'configs/ui/match001-desktop-1920x1080-ptbr-v1.json').read_text())
        self.assertEqual([s['slot'] for s in layout['slots']],list(range(5)))
        self.assertNotIn('champions',layout);self.assertNotIn('tft_patch',layout)
        ctx=json.loads((root/'configs/contexts/match001-interface.json').read_text())
        self.assertEqual(ctx['set_key'],'TFTSet18');self.assertEqual(ctx['tft_patch'],'18.3')
        self.assertIsNone(ctx['knowledge_release'])
    def test_topology_and_projection_separate(self):
        root=Path(__file__).resolve().parents[2]
        board=json.loads((root/'configs/topology/board-standard-4x7-v1.json').read_text())
        self.assertIsNone(board['pixel_projection']);self.assertFalse(board['set_specific'])
