"""UI data-patch tests; synthetic inputs are not TFT recognition measurements."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from training.shop_controls_profile import blob_sha, validate_patch, materialize, compare_observations, decode_signature


def fixture():
    base = dict(schema_version=1, id='parent', parent_layout_id='ui', recovery_profile_id='recovery',
                min_text_confidence=.7, controls=[])
    for i, cid in enumerate(('lock', 'buy_xp', 'refresh')):
        base['controls'].append(dict(id=cid, rect=dict(x=200+i*40,y=200,width=16,height=16),
            grid_width=4,grid_height=4,min_similarity=.95,max_rgb_mae=4.,
            templates=[dict(state='free_refresh_appearance' if cid=='refresh' else 'active_appearance',
                            rgb=[10,20,30]*16)],
            price_rect=None if cid=='lock' else dict(x=100,y=100+i*30,width=18,height=20),
            free_count_rect=dict(x=400,y=100,width=18,height=20) if cid=='refresh' else None))
    raw=json.dumps(base).encode()
    patch=dict(schema_version=1,id='candidate',parent_id='parent',parent_git_blob=blob_sha(raw),
               rectangles=[dict(control='refresh',field='free_count_rect',rect=dict(x=390,y=110,width=19,height=20))],
               additional_templates=[])
    return base, raw, patch


class ProfileTests(unittest.TestCase):
    def test_known_git_blob_digest(self):
        self.assertEqual(blob_sha(b''),'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')

    def test_data_patch_preserves_parent_and_algorithm_parameters(self):
        base,raw,patch=fixture(); snapshot=copy.deepcopy(base)
        with tempfile.TemporaryDirectory() as tmp:
            result,_=materialize(base,raw,patch,Path(tmp),dict(frames=[]))
        self.assertEqual(base,snapshot)
        self.assertEqual(result['controls'][:2],base['controls'][:2])
        self.assertEqual(result['min_text_confidence'],.7)
        self.assertEqual(result['controls'][2]['min_similarity'],.95)
        self.assertEqual(result['controls'][2]['max_rgb_mae'],4.)
        self.assertEqual(result['controls'][2]['free_count_rect']['x'],390)

    def test_changed_parent_rejected(self):
        base,raw,patch=fixture()
        with self.assertRaises(ValueError):validate_patch(base,raw+b' ',patch)

    def test_parent_object_cannot_diverge_from_pinned_bytes(self):
        base,raw,patch=fixture();base['min_text_confidence']=.1
        with self.assertRaises(ValueError):validate_patch(base,raw,patch)

    def test_threshold_and_expected_value_overrides_forbidden(self):
        for key in ('min_text_confidence','expected_value','set','ocr_language'):
            base,raw,patch=fixture();patch[key]=0
            with self.assertRaises(ValueError):validate_patch(base,raw,patch)

    def test_duplicate_or_non_numeric_rect_forbidden(self):
        base,raw,patch=fixture();patch['rectangles']*=2
        with self.assertRaises(ValueError):validate_patch(base,raw,patch)
        patch['rectangles']=patch['rectangles'][:1];patch['rectangles'][0]['field']='rect'
        with self.assertRaises(ValueError):validate_patch(base,raw,patch)

    def test_boolean_oversize_and_negative_geometry_forbidden(self):
        for key,val in [('x',-1),('width',True),('height',1000),('width',0)]:
            base,raw,patch=fixture();patch['rectangles'][0]['rect'][key]=val
            with self.assertRaises(ValueError):validate_patch(base,raw,patch)

    def test_unknown_appearance_not_created_by_exclusion(self):
        base,raw,patch=fixture();patch['additional_templates']=[dict(control='lock',state='locked_appearance',
            image='frame.png',sha256='0'*64)]
        with self.assertRaises(ValueError):validate_patch(base,raw,patch)

    def test_seed_is_hashed_frozen_and_has_no_target_number(self):
        base,raw,patch=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'seed.png';path.write_bytes(b'synthetic seed')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            patch['additional_templates']=[dict(control='refresh',state='free_refresh_appearance',image='seed.png',sha256=digest)]
            result,sources=materialize(base,raw,patch,root,dict(frames=[dict(image='seed.png',sha256=digest)]),
                                       decoder=lambda *_:([20,30,40]*16,'a'*64))
            self.assertEqual(len(result['controls'][2]['templates']),2)
            self.assertEqual(sources[str(path)],digest)
            self.assertNotIn('value',result['controls'][2]['templates'][-1])
            with self.assertRaises(ValueError):materialize(base,raw,patch,root,dict(frames=[]))

    def test_changed_seed_during_decode_rejected(self):
        base,raw,patch=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'seed.png';path.write_bytes(b'a');digest=hashlib.sha256(b'a').hexdigest()
            patch['additional_templates']=[dict(control='refresh',state='free_refresh_appearance',image='seed.png',sha256=digest)]
            def mutate(*_):path.write_bytes(b'b');return [20,30,40]*16,'a'*64
            with self.assertRaises(ValueError):
                materialize(base,raw,patch,Path(tmp),dict(frames=[dict(image='seed.png',sha256=digest)]),mutate)

    def test_seed_path_escape_and_duplicates_rejected(self):
        base,raw,patch=fixture()
        for image in ('../outside.png','/tmp/outside.png'):
            patch['additional_templates']=[dict(control='refresh',state='free_refresh_appearance',image=image,sha256='0'*64)]
            with self.assertRaises(ValueError):validate_patch(base,raw,patch)
        patch['additional_templates'][0]['image']='seed.png';patch['additional_templates']*=2
        with self.assertRaises(ValueError):validate_patch(base,raw,patch)

    def test_signature_decoder_uses_exact_integer_centers(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        spec=dict(rect=dict(x=100,y=100,width=8,height=8),grid_width=4,grid_height=4)
        pixels=bytes(v for i in range(64) for v in (i,i,i))
        with patch('training.shop_controls_profile.subprocess.run',return_value=SimpleNamespace(stdout=pixels)) as call:
            result,_=decode_signature(Path('/tmp/seed.png'),spec)
            self.assertEqual(result[::3],[9,11,13,15,25,27,29,31,41,43,45,47,57,59,61,63])
            self.assertIn('format=rgb24,crop=8:8:100:100:exact=1',call.call_args.args[0])
            self.assertEqual(call.call_args.kwargs['timeout'],20)


def observation(value):
    return dict(summary=dict(profile='s2',layout_id='ui',locale='pt_br',ocr_language='eng'),records=[dict(
        read=dict(timestamp_ms=250,slots=[]),controls=dict(controls=[
            dict(id='lock',appearance='unlocked_appearance'),dict(id='buy_xp',appearance='active_appearance'),
            dict(id='refresh',appearance='free_refresh_appearance')],
            numeric_fields=[dict(id=k,value=value) for k in ('buy_xp_price','refresh_price','refresh_free_count')]))])


class ComparisonTests(unittest.TestCase):
    def test_zero_is_readable_and_not_default(self):
        result=compare_observations(observation(None),observation(0))
        self.assertEqual(result['fields']['refresh_price'],{'candidate_only':1})
        self.assertTrue(result['card_observations_unchanged']);self.assertIsNone(result['exact_accuracy'])

    def test_losses_and_conflicts_do_not_get_corrected(self):
        self.assertEqual(compare_observations(observation(4),observation(2))['fields']['refresh_price'],{'both_disagree':1})
        self.assertEqual(compare_observations(observation(4),observation(None))['fields']['refresh_price'],{'baseline_only':1})

    def test_card_and_nonrefresh_visual_changes_are_visible(self):
        a=observation(4);b=copy.deepcopy(a);b['records'][0]['read']['slots']=[1]
        b['records'][0]['controls']['controls'][0]['appearance']='unknown'
        result=compare_observations(a,b)
        self.assertFalse(result['card_observations_unchanged']);self.assertFalse(result['non_refresh_visuals_unchanged'])

    def test_timestamp_and_context_changes_rejected(self):
        a=observation(4);b=observation(4);b['records'][0]['read']['timestamp_ms']=251
        with self.assertRaises(ValueError):compare_observations(a,b)
        b=observation(4);b['summary']['ocr_language']='por'
        with self.assertRaises(ValueError):compare_observations(a,b)

    def test_missing_numeric_field_is_not_silently_zipped(self):
        a=observation(4);b=observation(4);b['records'][0]['controls']['numeric_fields'].pop()
        with self.assertRaises(ValueError):compare_observations(a,b)


if __name__=='__main__':unittest.main()
