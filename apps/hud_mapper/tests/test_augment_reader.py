from pathlib import Path
import unittest
from PIL import Image, ImageDraw

from hm.augment_reader import AugmentReader, TITLE_BOXES, bind_offer
from hm.replay_decision import ReplayDecisionEngine


ROOT = Path(__file__).resolve().parents[3]


class AugmentReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = AugmentReader(ROOT / 'configs')

    def test_three_offer_names_preserve_duplicate_ids(self):
        expected = (
            ('Estudo Paciente', 'catalog_name_ambiguous_id', None),
            ('Vigarista', 'catalog_name_ambiguous_id', None),
            ('Acolito da Congregacao\ndas Bruxas', 'catalog_name_bound',
             'DA_18_CovenTraitAugment'),
        )
        for title, status, expected_id in expected:
            with self.subTest(title=title):
                result = bind_offer(title, '', self.reader.entries)
                self.assertEqual(result['candidate_id'], expected_id)
                self.assertEqual(result['status'], status)

    def test_patch_notes_name_outside_da_prefix_is_available_to_ocr(self):
        for title, expected_id in (
            ('Construção de Companheiro', 'TFT_Augment_ConstructACompanion'),
            ('Forje uma Amizade', 'TFT_Augment_ForgeAFriend')):
            with self.subTest(title=title):
                result = bind_offer(title, '', self.reader.entries)
                self.assertEqual(result['candidate_id'], expected_id)

    def test_archive_preserves_current_and_archived_ids(self):
        self.assertEqual(self.reader.catalog['entry_count'], 758)
        self.assertEqual(self.reader.catalog['supplement_entry_count'], 4)
        self.assertEqual(self.reader.catalog['lookup_entry_count'], 762)
        self.assertEqual(len(self.reader.entries), 762)
        self.assertEqual(len({row['id'] for row in self.reader.entries}),
                         len(self.reader.entries))
        self.assertFalse(self.reader.catalog['live_offer_pool_complete'])
        self.assertFalse(self.reader.catalog['hero_augments_included'])

    def test_missing_current_and_disabled_historical_cards_remain_recognizable(self):
        grace = bind_offer('Graça de Desafiante', '', self.reader.entries)
        self.assertEqual(grace['candidate_id'], 'DA_ChallengersGrace')
        dolls = bind_offer('Matrioscas', '', self.reader.entries)
        self.assertEqual(dolls['status'], 'catalog_name_ambiguous_id')
        self.assertEqual(set(dolls['candidate_ids']),
                         {'DA_NestingDollsPlus', 'DA_NestingDollsPlusPlus'})

    def test_unknown_title_stays_unresolved(self):
        result = bind_offer('campeao inventado', '', self.reader.entries)
        self.assertIsNone(result['candidate_id'])
        self.assertEqual(result['status'], 'unresolved')

    def test_english_replay_title_binds_to_same_catalog(self):
        result = bind_offer('Small Furry Friend', '', self.reader.entries)
        self.assertEqual(result['status'], 'catalog_name_bound')
        self.assertEqual(result['candidate_name'], 'Amiguinho Peludinho')

    def test_waits_for_readable_cards_after_heading_appears(self):
        reader = AugmentReader(ROOT / 'configs')
        reader._ocr = lambda image, **kwargs: 'Choose One'
        frame = Image.new('RGB', (1920, 1080), '#202020')
        pending = reader.observe(frame.tobytes(), 1920, 1080,
                                 frame_id=1, source_ms=1000, epoch=0)
        self.assertEqual(pending['status'], 'appearance_pending')
        self.assertEqual(pending['options'], [])
        draw = ImageDraw.Draw(frame)
        for box in TITLE_BOXES:
            draw.rectangle((box[0]+20, box[1]+5, box[0]+100, box[1]+30),
                           fill='white')
        readable = reader.observe(frame.tobytes(), 1920, 1080,
                                  frame_id=2, source_ms=1500, epoch=0)
        self.assertEqual(readable['status'], 'visible_read')
        self.assertEqual(len(readable['options']), 3)

    def test_motor_one_passes_options_and_explicit_close(self):
        options = [{'slot': index, 'candidate_id': name,
                    'candidate_ids': [name], 'status': 'catalog_name_bound',
                    'observed_title': str(index), 'observed_description': 'texto visto',
                    'candidate_references': self.reader._candidate_references([name]),
                    'training_label': False, 'selection_confirmed': False}
                   for index, name in enumerate(('DA_PatientStudy', 'DA_Hustler',
                                                  'DA_18_CovenTraitAugment'))]
        visible = ReplayDecisionEngine._memory_observation({}, motor1_aux={
            'augment_options': {'selection_visible': True, 'options': options,
                'source_ms': 1200, 'selection_confirmed': False,
                'ground_truth': False, 'catalog': self.reader.catalog}})
        self.assertTrue(visible['augment_selection_visible'])
        self.assertEqual(len(visible['augment_options']), 3)
        self.assertEqual(visible['augment_catalog']['lookup_entry_count'], 762)
        self.assertFalse(visible['augment_catalog']['rules_patch_confirmed_from_replay_client'])
        self.assertEqual(visible['augment_source_ms'], 1200)
        self.assertEqual(visible['augment_options'][2]['candidate_references'][0]
                         ['patch_rule']['shared_lobby_limit'], 1)
        self.assertFalse(visible['augment_selection_confirmed'])
        self.assertFalse(visible['augment_ground_truth'])
        closed = ReplayDecisionEngine._memory_observation({}, motor1_aux={
            'augment_options': {'selection_visible': False, 'options': []}})
        self.assertFalse(closed['augment_selection_visible'])
        self.assertEqual(closed['augment_options'], [])
        self.assertIsNone(closed['augment_catalog'])

    def test_disabled_card_is_retained_with_explicit_patch_rule(self):
        references = self.reader._candidate_references(
            ['DA_HeartOfSteel', 'TFT_Augment_WarmogsBuckle'])
        self.assertEqual({row['patch_rule']['availability'] for row in references},
                         {'temporarily_disabled_18_4b'})


if __name__ == '__main__':
    unittest.main()
