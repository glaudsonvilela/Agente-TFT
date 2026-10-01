"""The opt-in image policy must never change geometry, gates or label scope."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class Match001HudV3Tests(unittest.TestCase):
    def setUp(self):
        self.v2 = json.loads((ROOT/'configs/hud/tft-1920x1080-match001-v2.json').read_text())
        self.v3 = json.loads((ROOT/'configs/hud/tft-1920x1080-match001-v3.json').read_text())

    def test_identical_rois_no_hp_no_resolution_change(self):
        self.assertEqual(self.v3['schema_version'], self.v2['schema_version'])
        for key in ('reference_width','reference_height'):
            self.assertEqual(self.v3[key], self.v2[key])
        self.assertEqual([r['field'] for r in self.v3['regions']], ['stage','gold','level','xp'])
        for old, new in zip(self.v2['regions'], self.v3['regions'], strict=True):
            self.assertEqual(old['rect'], new['rect'])

    def test_stage_is_byte_equivalent_configuration(self):
        self.assertEqual(self.v2['regions'][0], self.v3['regions'][0])

    def test_unchanged_thresholds_and_three_fixed_attempts(self):
        for region in self.v3['regions'][1:]:
            p = region['policy']
            self.assertEqual(p['min_confidence'], 0.70)
            self.assertEqual(p['ambiguity_margin'], 0.03)
            self.assertEqual(p['page_segmentation'], 7)
            self.assertEqual(p['attempts'], [{'upscale_factor':s,'invert':True} for s in (3,4,5)])

    def test_color_projection_only_gold_and_fraction_only_xp(self):
        for region in self.v3['regions'][1:]:
            p = region['policy']
            self.assertEqual(p['image_mode'], 'neutral_gray_bilinear' if region['field']=='gold' else 'gray_bilinear')
            self.assertEqual(p['require_xp_fraction'], region['field']=='xp')

if __name__ == '__main__':
    unittest.main()
