"""Isolated-field UI and trace contracts, not native recognition accuracy."""
import copy
import json
from pathlib import Path
import unittest

from training.shop_numbers_policy import validate_policy, selected_rect
from training.shop_controls_evidence import validate_controls, f32

ROOT = Path(__file__).resolve().parents[2]


def fixture(free=False):
    policy = json.loads((ROOT/'configs/ui/match001-shop-isolated-numbers-v1.json').read_text())
    def rect(x,y,w,h): return dict(x=x,y=y,width=w,height=h)
    profile = dict(id=policy['controls_profile_id'],min_text_confidence=0.70,controls=[
        dict(id='lock',rect=rect(1512,890,30,27),price_rect=None,free_count_rect=None,
             templates=[dict(state='unlocked_appearance')],min_similarity=0.95,max_rgb_mae=12.0),
        dict(id='buy_xp',rect=rect(488,942,37,41),price_rect=rect(387,967,18,21),free_count_rect=None,
             templates=[dict(state='active_appearance'),dict(state='dimmed_appearance')],min_similarity=0.95,max_rgb_mae=12.0),
        dict(id='refresh',rect=rect(496,1029,30,30),price_rect=rect(379,1040,25,27),free_count_rect=rect(465,1012,19,20),
             templates=[dict(state=s) for s in ('active_appearance','dimmed_appearance','free_refresh_appearance')],
             min_similarity=0.95,max_rgb_mae=4.0)])
    layout=dict(reference_width=1920,reference_height=1080,slots=[dict(card=rect(600,910,150,160))])
    controls=[]
    for spec in profile['controls']:
        state='free_refresh_appearance' if free and spec['id']=='refresh' else spec['templates'][0]['state']
        scores=[dict(state=t['state'],similarity=1.0 if t['state']==state else -1.0,
                     rgb_mae=0.0 if t['state']==state else 200.0,eligible=t['state']==state) for t in spec['templates']]
        controls.append(dict(id=spec['id'],rect=spec['rect'],status='observed',appearance=state,scores=scores,action_allowed=None))
    fields=[]; routing=[]
    for spec, visual in zip(profile['controls'],controls):
        for key,suffix in [('price_rect','price'),('free_count_rect','free_count')]:
            if spec[key] is None: continue
            field_id=spec['id']+'_'+suffix
            enabled=suffix=='price' or free
            chosen=selected_rect(policy,field_id,visual['appearance']) if enabled else spec[key]
            fields.append(dict(id=field_id,rect=chosen,status='observed' if enabled else 'not_observed',
                value=0 if enabled else None,confidence=0.9 if enabled else None,
                attempts=[dict(scale=s,text='0',confidence=0.9,reason='eligible') for s in (3,4)] if enabled else []))
            if enabled: routing.extend(dict(scale=s) for s in (3,4))
    result=dict(profile=profile['id'],timestamp_ms=100,controls=controls,numeric_fields=fields,routing=routing,
                ocr_process_calls=len(routing),error=None,temporal_confirmation=False)
    report=dict(summary=dict(controls_numeric_mode='isolated_field_v1',control_numbers_policy=policy['id']),
                records=[dict(read=dict(timestamp_ms=100,panel_status='located'),controls=result)])
    return profile,policy,layout,report


class NumbersTests(unittest.TestCase):
    def test_policy_and_output_valid(self):
        for free in (False,True):
            c,p,l,r=fixture(free);validate_policy(p,c,l)
            self.assertEqual(validate_controls(r,c,p)['controls_ocr_process_calls'],6 if free else 4)
    def test_zero_readable_does_not_imply_free_count(self):
        c,p,l,r=fixture();m=validate_controls(r,c,p)
        self.assertNotIn('refresh_free_count',m['numeric_readable'])
    def test_state_selects_price_geometry(self):
        c,p,l,r=fixture()
        self.assertEqual(selected_rect(p,'refresh_price','active_appearance')['x'],387)
        self.assertEqual(selected_rect(p,'refresh_price','free_refresh_appearance')['x'],379)
    def test_injected_value_or_threshold_rejected(self):
        for key in ('expected','min_confidence','champions'):
            c,p,l,r=fixture();p[key]=4
            with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_wrong_parent_rejected(self):
        c,p,l,r=fixture();p['controls_profile_id']='other'
        with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_unknown_nested_keys_rejected(self):
        c,p,l,r=fixture();p['fields'][0]['regions'][0]['rect']['expected']=4
        with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_missing_or_reordered_states_rejected(self):
        c,p,l,r=fixture();p['fields'][1]['regions'].reverse()
        with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_duplicate_fields_rejected(self):
        c,p,l,r=fixture();p['fields'][1]=copy.deepcopy(p['fields'][0])
        with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_geometry_limits_and_non_integer_coordinates(self):
        for x in (True,-1,1.5,2**32):
            c,p,l,r=fixture();p['fields'][0]['regions'][0]['rect']['x']=x
            with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_overlap_with_control_rejected(self):
        c,p,l,r=fixture();p['fields'][0]['regions'][0]['rect']=copy.deepcopy(c['controls'][1]['rect'])
        with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_simultaneous_numeric_overlap_rejected(self):
        c,p,l,r=fixture();p['fields'][2]['regions'][0]['rect']=copy.deepcopy(p['fields'][1]['regions'][2]['rect'])
        with self.assertRaises(ValueError):validate_policy(p,c,l)
    def test_no_geometry_from_unknown_state(self):
        c,p,l,r=fixture()
        with self.assertRaises(ValueError):selected_rect(p,'refresh_price','unknown')
    def test_wrong_runtime_rectangle_rejected(self):
        c,p,l,r=fixture();r['records'][0]['controls']['numeric_fields'][1]['rect']=c['controls'][2]['price_rect']
        with self.assertRaises(ValueError):validate_controls(r,c,p)
    def test_underreported_calls_rejected(self):
        c,p,l,r=fixture(True);r['records'][0]['controls']['ocr_process_calls']=2
        with self.assertRaises(ValueError):validate_controls(r,c,p)
    def test_missing_or_reordered_routing_rejected(self):
        c,p,l,r=fixture();r['records'][0]['controls']['routing'].pop()
        with self.assertRaises(ValueError):validate_controls(r,c,p)
    def test_cross_scale_conflict_not_accepted(self):
        c,p,l,r=fixture();r['records'][0]['controls']['numeric_fields'][0]['attempts'][1]['text']='1'
        with self.assertRaises(ValueError):validate_controls(r,c,p)
    def test_threshold_is_not_lowered(self):
        c,p,l,r=fixture();r['records'][0]['controls']['numeric_fields'][0]['attempts'][1]['confidence']=0.69
        with self.assertRaises(ValueError):validate_controls(r,c,p)
    def test_wrong_mode_or_omitted_policy_rejected(self):
        c,p,l,r=fixture()
        with self.assertRaises(ValueError):validate_controls(r,c)
        r['summary']['control_numbers_policy']='other'
        with self.assertRaises(ValueError):validate_controls(r,c,p)
    def test_f32_threshold_still_valid(self):
        c,p,l,r=fixture();f=r['records'][0]['controls']['numeric_fields'][0]
        f['confidence']=f32(0.70)
        for a in f['attempts']:a['confidence']=f32(0.70)
        self.assertEqual(validate_controls(r,c,p)['numeric_readable']['buy_xp_price'],1)
