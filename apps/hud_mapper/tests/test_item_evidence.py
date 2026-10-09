import unittest

from hm.item_evidence import reconcile


def template(item_id, name):
    return {'candidates': [{'catalog_options': [
        {'visual_id': item_id, 'attribute_id': item_id, 'name': name}]}]}


def native(item_id):
    return {'candidates': [{'attribute_ids': [item_id]}]}


class ItemEvidenceTest(unittest.TestCase):
    def test_agreement_names_inventory_and_equipped_without_promoting_identity(self):
        snapshot = {
            'inventory': {'candidate_slots': [dict(slot=1, **template('sword', 'Espada'))]},
            'item_visual_native': {
                'inventory': [dict(slot=1, **native('sword'))],
                'equipped': [dict(marker_id=7, slot=0, **native('sunfire'))]},
            'neural_items': {'active': True, 'records': [
                {'slot': 1, 'candidates': [{'ids': ['sword']}]}]},
            'observed_markers': [{'marker_id': 7, 'position_candidate': None,
                                  'equipped_slots': [dict(slot=0, **template('sunfire', 'Capa'))]}]}
        result = reconcile(snapshot)
        self.assertEqual(result['inventory'][0]['candidate_id'], 'sword')
        self.assertEqual(result['equipped'][0]['candidate_name'], 'Capa')
        self.assertFalse(result['identity_verified'])
        self.assertFalse(result['training_label_allowed'])

    def test_disagreement_abstains_even_when_neural_and_template_agree(self):
        snapshot = {
            'inventory': {'candidate_slots': [dict(slot=3, **template('rod', 'Bastão'))]},
            'item_visual_native': {'inventory': [dict(slot=3, **native('vest'))],
                                   'equipped': []},
            'neural_items': {'active': True, 'records': [
                {'slot': 3, 'candidates': [{'ids': ['rod']}]}]},
            'observed_markers': []}
        result = reconcile(snapshot)
        self.assertEqual(result['inventory'][0]['status'], 'conflicting_or_missing_evidence')
        self.assertIsNone(result['inventory'][0]['candidate_id'])

    def test_equipped_visual_id_remains_named_when_attribute_row_is_absent(self):
        snapshot = {
            'inventory': {'candidate_slots': []},
            'item_visual_native': {'inventory': [], 'equipped': [
                {'marker_id': 2, 'slot': 0, 'candidates': [
                    {'attribute_ids': [], 'visual_ids': ['emblem']}]}]},
            'neural_items': {'active': False, 'records': []},
            'observed_markers': [{'marker_id': 2, 'position_candidate': None,
                                  'equipped_slots': [{'slot': 0, 'candidates': [
                                      {'catalog_options': [{'visual_id': 'emblem',
                                                            'attribute_id': None,
                                                            'name': 'Emblema'}]}]}]}]}
        row = reconcile(snapshot)['equipped'][0]
        self.assertEqual(row['candidate_name'], 'Emblema')
        self.assertEqual(row['catalog_binding'], 'visual_id_only')
        self.assertFalse(row['identity_verified'])


if __name__ == '__main__':
    unittest.main()
