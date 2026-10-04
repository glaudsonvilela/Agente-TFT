import copy
import unittest

from training.board_review import validate
from training.train_scene_gate import split_frames
from training.simulator_lab.attribute_worklist import variables_audit, assert_patch_compatible, attach_official_observations


def frame():
    return dict(sha256='1'*64, pixel_sha256='2'*64, image='frame.png', image_size=[1920, 1080],
                session_id='capture', source_ms=0, scene='board', phase='planning',
                review=dict(method='assistant_visual_review', model_predictions_used_as_labels=False),
                layout=dict(units=[dict(key='a', zone='board', owner='self', box=[10, 10, 50, 50], hex=[0, 0])]),
                entities=[dict(key='a', identity=dict(state='unknown'), stars=None)])


class BoardReviewTests(unittest.TestCase):
    def document(self):
        return dict(schema_version=2, kind='board_review', frames=[frame()])

    def test_partial_labels_do_not_become_empty_or_production_ready(self):
        result = validate(self.document())
        self.assertFalse(result['current_patch_training_ready'])
        self.assertFalse(result['independent_human_validation'])

    def test_unknown_identity_cannot_carry_guessed_name_or_unbound_id(self):
        for identity in [dict(state='unknown', visible_name='Akali'), dict(state='known', id='DA_18_Akali_AD')]:
            doc = self.document(); doc['frames'][0]['entities'][0]['identity'] = identity
            with self.subTest(identity=identity), self.assertRaises(ValueError): validate(doc)

    def test_combat_positions_and_duplicate_hexes_rejected(self):
        doc = self.document(); doc['frames'][0]['phase'] = 'combat'
        with self.assertRaises(ValueError): validate(doc)
        doc = self.document(); u = copy.deepcopy(doc['frames'][0]['layout']['units'][0]); u['key'] = 'b'
        doc['frames'][0]['layout']['units'].append(u)
        with self.assertRaises(ValueError): validate(doc)

    def test_missing_equipped_slots_cannot_claim_complete(self):
        doc = self.document(); doc['frames'][0]['entities'][0]['equipped'] = dict(coverage='complete', slots=[])
        with self.assertRaises(ValueError): validate(doc)

    def test_nonchampion_shop_offer_is_supported(self):
        doc = self.document()
        doc['frames'][0]['shop'] = [dict(slot=4, kind='consumable', cost=0,
            identity=dict(state='known', visible_name='Polimorfia Menor'))]
        validate(doc)
        doc['frames'][0]['shop'][0]['kind'] = 'empty'
        with self.assertRaises(ValueError): validate(doc)

    def test_predictions_duplicate_pixels_and_path_escape_rejected(self):
        for mutation in ['prediction', 'duplicate', 'path']:
            doc = self.document()
            if mutation == 'prediction': doc['frames'][0]['review']['model_predictions_used_as_labels'] = True
            if mutation == 'duplicate': doc['frames'].append(copy.deepcopy(doc['frames'][0]))
            if mutation == 'path': doc['frames'][0]['image'] = '../outside.png'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): validate(doc)

    def test_session_and_pixel_leakage_rejected(self):
        rows = []
        for i, (group, scene) in enumerate([('a', 'board'), ('a', 'lobby'), ('b', 'board'), ('b', 'lobby')]):
            f = frame(); f.update(match_group=group, session_id=group, scene=scene,
                                  sha256=str(i)*64, pixel_sha256=str(i)*64)
            rows.append(f)
        doc = dict(frames=rows, match_group_reviews=[dict(id=g, method='assistant_visual_roster_review',
                   evidence_frame_sha256=[rows[i]['sha256']]) for g, i in [('a', 0), ('b', 2)]])
        train, test = split_frames(doc, 'b'); self.assertEqual((len(train), len(test)), (2, 2))
        rows[2]['session_id'] = 'a'
        with self.assertRaises(ValueError): split_frames(doc, 'b')
        rows[2]['session_id'] = 'b'; rows[2]['pixel_sha256'] = rows[0]['pixel_sha256']
        with self.assertRaises(ValueError): split_frames(doc, 'b')

    def test_invalid_numeric_variables_are_not_coverage(self):
        good, bad = variables_audit(dict(variables=[dict(name='Damage', values=[0, 100, 200]),
            dict(name='Broken', values=[float('nan')]), dict(name='Flag', values=[True])]))
        self.assertEqual(set(good), {'Damage'}); self.assertEqual(len(bad), 2)

    def test_pbe_cannot_replace_requested_patch(self):
        work = dict(kind='seasonal_attribute_worklist', set_key='TFTSet18', patch='pbe', release_sha256='1'*64)
        with self.assertRaises(ValueError):
            assert_patch_compatible(work, set_key='TFTSet18', patch='18.3', release_sha256='1'*64)

    def test_official_partial_values_do_not_fill_missing_stars_or_activate(self):
        work = dict(set_key='TFTSet18', release_sha256='1'*64, champions=[dict(id='a', executable=False)],
                    summary={}, current_patch_training_ready=False)
        facts = dict(kind='official_patch_observations', set_key='TFTSet18', base_release_sha256='1'*64,
                     source_url='https://teamfighttactics.leagueoflegends.com/', facts=[dict(entity_id='a',
                     field='damage', patch='18.3B', values=[10, 20], star_levels=[1, 2],
                     semantics_verified_for_execution=False, formula_binding=None)])
        attach_official_observations(work, facts)
        self.assertEqual(work['champions'][0]['official_observations'][0]['star_levels'], [1, 2])
        self.assertFalse(work['current_patch_training_ready'])
        self.assertFalse(work['champions'][0]['executable'])
        facts['base_release_sha256'] = '2'*64
        with self.assertRaises(ValueError): attach_official_observations(work, facts)


if __name__ == '__main__': unittest.main()
