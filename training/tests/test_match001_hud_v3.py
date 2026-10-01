from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
class HudV3Tests(unittest.TestCase):
    def setUp(self):
        self.old=json.loads((ROOT/'configs/hud/tft-1920x1080-match001-v2.json').read_text())
        self.new=json.loads((ROOT/'configs/hud/tft-1920x1080-match001-v3-gray.json').read_text())
    def test_pixels_and_fields_unchanged(self):
        self.assertEqual(self.old['schema_version'],self.new['schema_version'])
        for old,new in zip(self.old['regions'],self.new['regions'],strict=True):
            self.assertEqual(old['field'],new['field'])
            self.assertEqual(old['rect'],new['rect'])
    def test_stage_not_reconfigured_and_hp_not_added(self):
        self.assertEqual(self.old['regions'][0],self.new['regions'][0])
        self.assertNotIn('hp',[x['field'] for x in self.new['regions']])
    def test_confidence_not_relaxed(self):
        for r in self.new['regions'][1:]:
            self.assertEqual(r['policy']['min_confidence'],0.70)
            self.assertEqual(r['policy']['ambiguity_margin'],0.03)
    def test_two_bounded_dark_on_light_attempts(self):
        for r in self.new['regions'][1:]:
            self.assertEqual(r['policy']['attempts'],[
                {'upscale_factor':3,'invert':True},{'upscale_factor':4,'invert':True}])
    def test_runner_is_sparse_explicit_and_non_destructive(self):
        s=(ROOT/'scripts/probe_match001_hud_v3.sh').read_text()
        self.assertIn('--prelabels --numeric-gray --image-root',s)
        self.assertIn('mktemp -d',s)
        self.assertNotIn('hud-replay-inspect',s)
        self.assertNotIn('git reset',s)
if __name__=='__main__':unittest.main()
