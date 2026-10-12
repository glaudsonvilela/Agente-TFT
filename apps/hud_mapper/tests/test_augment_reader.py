from pathlib import Path
import unittest

from hm.augment_reader import AugmentReader, bind_offer
from hm.replay_decision import ReplayDecisionEngine


ROOT = Path(__file__).resolve().parents[3]


class AugmentReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = AugmentReader(ROOT / 'configs')

    def test_three_offer_names_bind_to_patch_catalog(self):
        expected = (
            ('Estudo Paciente', 'DA_PatientStudy'),
            ('Vigarista', 'DA_Hustler'),
            ('Acolito da Congregacao\ndas Bruxas', 'DA_18_CovenTraitAugment'),
        )
        for title, expected_id in expected:
            with self.subTest(title=title):
                result = bind_offer(title, '', self.reader.entries)
                self.assertEqual(result['candidate_id'], expected_id)
                self.assertEqual(result['status'], 'catalog_name_bound')

    def test_unknown_title_stays_unresolved(self):
        result = bind_offer('campeao inventado', '', self.reader.entries)
        self.assertIsNone(result['candidate_id'])
        self.assertEqual(result['status'], 'unresolved')

    def test_motor_one_passes_options_and_explicit_close(self):
        options = [{'slot': index, 'candidate_id': name,
                    'status': 'catalog_name_bound'}
                   for index, name in enumerate(('DA_PatientStudy', 'DA_Hustler',
                                                  'DA_18_CovenTraitAugment'))]
        visible = ReplayDecisionEngine._memory_observation({}, motor1_aux={
            'augment_options': {'selection_visible': True, 'options': options}})
        self.assertTrue(visible['augment_selection_visible'])
        self.assertEqual(len(visible['augment_options']), 3)
        closed = ReplayDecisionEngine._memory_observation({}, motor1_aux={
            'augment_options': {'selection_visible': False, 'options': []}})
        self.assertFalse(closed['augment_selection_visible'])
        self.assertEqual(closed['augment_options'], [])


if __name__ == '__main__':
    unittest.main()
