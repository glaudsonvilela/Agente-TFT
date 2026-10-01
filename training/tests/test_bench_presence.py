"""B2 decision contracts; synthetic hypotheses are not TFT accuracy."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from training.bench_presence_evidence import validate_policy, validate, crop, blob_sha, compare_legacy
ROOT=Path(__file__).resolve().parents[2]


def fixture():
    b=json.loads((ROOT/'configs/ui/match001-board-bench-v1.json').read_text())
    p=json.loads((ROOT/'configs/ui/match001-bench-presence-v1.json').read_text())
    a=dict(offset=[0,0,0],residual_mae=0.0,changed_fraction=0.0,correlation=1.0,reference_spread=10.0)
    rows=[dict(slot=i,crop=crop(p,b,i),status='empty_visual',occupancy=False,appearance=deepcopy(a),
        marker_candidates=[],body_candidates=[],components_total=0,
        reason='textured_empty_reference_match_without_marker_or_body',unit_id=None,ground_point=None) for i in range(9)]
    legacy=dict(timestamp_ms=0,projection_status='reference_arena_match',markers=[])
    extra=dict(timestamp_ms=0,profile=p['id'],surface_status='reference_arena',surface_scores=[deepcopy(a) for _ in range(3)],
        slots=rows,temporal_confirmation=False,ownership_established=False)
    report=dict(records=[dict(read=legacy,bench_presence=extra,bench_presence_scan_ms=1,decode_and_both_scans_ms=20)])
    return b,p,report


def occupied(report):
    r=report['records'][0];r['read']['markers']=[dict(id=0,rect=dict(x=385,y=694,width=64,height=4))]
    s=r['bench_presence']['slots'][0]
    s.update(status='occupied_visual',occupancy=True,marker_candidates=[0],components_total=1,
        body_candidates=[dict(rect=dict(x=395,y=728,width=26,height=69),pixels=1794)],
        reason='single_bar_and_connected_foreground_reaches_support_band')
    s['appearance'].update(residual_mae=25,changed_fraction=.20,correlation=.3)
    return s


class PresenceEvidenceTests(unittest.TestCase):
    def test_valid_empty_hypotheses_not_semantic_confirmation(self):
        b,p,r=fixture();self.assertEqual(validate(r,b,p)['bench_statuses'],{'empty_visual':9})
    def test_valid_joint_occupied_support(self):
        b,p,r=fixture();occupied(r);self.assertEqual(validate(r,b,p)['bench_statuses']['occupied_visual'],1)
    def test_occupancy_cannot_be_invented_from_empty_signature(self):
        b,p,r=fixture();r['records'][0]['bench_presence']['slots'][0]['occupancy']=True
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_body_without_marker_cannot_assert_presence(self):
        b,p,r=fixture();s=occupied(r);r['records'][0]['read']['markers']=[];s['marker_candidates']=[]
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_missing_lower_support_rejected(self):
        b,p,r=fixture();s=occupied(r);s['body_candidates'][0]['rect']['height']=24;s['body_candidates'][0]['pixels']=500
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_clipped_or_broad_component_rejected(self):
        b,p,r=fixture();s=occupied(r);s['body_candidates'][0]['rect']['x']=s['crop']['x']
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_wrong_marker_slot_is_not_nearest_neighbor_assignment(self):
        b,p,r=fixture();occupied(r);r['records'][0]['read']['markers'][0]['rect']['x']=900
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_local_surface_cannot_override_failed_scores(self):
        b,p,r=fixture();q=r['records'][0];q['read']['projection_status']='unresolved';q['bench_presence']['surface_status']='bench_structure_match'
        q['bench_presence']['surface_scores'][0]['correlation']=.5
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_three_local_scores_can_support_bench_without_own_board_claim(self):
        b,p,r=fixture();q=r['records'][0];q['read']['projection_status']='unresolved';q['bench_presence']['surface_status']='bench_structure_match'
        self.assertEqual(validate(r,b,p)['surface_statuses'],{'bench_structure_match':1})
    def test_no_ground_point_or_identity_invention(self):
        b,p,r=fixture();s=occupied(r);s['ground_point']=[400,790]
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_no_false_temporal_confirmation(self):
        b,p,r=fixture();r['records'][0]['bench_presence']['temporal_confirmation']=True
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_nonfinite_and_boolean_occupancy_numbers_rejected(self):
        b,p,r=fixture();r['records'][0]['bench_presence']['surface_scores'][0]['correlation']=float('nan')
        with self.assertRaises(ValueError):validate(r,b,p)
        b,p,r=fixture();r['records'][0]['bench_presence']['slots'][0]['occupancy']=0
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_missing_slots_are_not_silently_zipped(self):
        b,p,r=fixture();r['records'][0]['bench_presence']['slots'].pop()
        with self.assertRaises(ValueError):validate(r,b,p)
    def test_parent_hash_and_unknown_keys_rejected(self):
        b,p,_=fixture();raw=(ROOT/'configs/ui/match001-board-bench-v1.json').read_bytes();validate_policy(p,b,raw)
        with self.assertRaises(ValueError):validate_policy(p,b,raw+b' ')
        p['expected_occupancy']=False
        with self.assertRaises(ValueError):validate_policy(p,b)
    def test_policy_rejects_looser_limits_and_overflow(self):
        b,p,_=fixture();p['max_color_offset']=255
        with self.assertRaises(ValueError):validate_policy(p,b)
        b,p,_=fixture();p['body_top']=2**32-1
        with self.assertRaises(ValueError):validate_policy(p,b)
    def test_legacy_regression_is_full_record_not_counts(self):
        _,_,r=fixture();q=deepcopy(r);q['records'][0]['read']['markers']=[{'different':True}]
        self.assertFalse(compare_legacy(r,q)['b1_observations_unchanged'])
        self.assertTrue(compare_legacy(r,r)['b1_observations_unchanged'])
    def test_pixel_geometry_never_contains_season_roster(self):
        b,p,_=fixture();validate_policy(p,b);self.assertNotIn('champions',p);self.assertNotIn('set_key',p)
    def test_known_git_blob_hash(self):
        self.assertEqual(blob_sha(b''),'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')
