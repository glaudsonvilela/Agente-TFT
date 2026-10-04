import unittest
from companion_service.player_summary import summarize

class PlayerSummaryTests(unittest.TestCase):
    def rows(self):
        return [dict(match_id=str(i),queue='ranked',placement=1 if i>=5 else 8,
                     played_at=100+i,patch='18.3',set='TFTSet18') for i in range(10)]
    def test_ranked_only_deduplicated_and_exact(self):
        rows=self.rows();rows+=[rows[0],dict(rows[0],match_id='normal',queue='normal',placement=1)]
        result=summarize(rows,source='test-fixture',fetched_at=200,current_patch="18.3",current_set="TFTSet18")
        self.assertEqual(result['statistics'],dict(matches=10,average_placement=4.5,wins=5,top4=5,top4_rate=.5))
        self.assertEqual(result['trend']['average_placement_delta'],-7)
        self.assertFalse(result['neural_analysis_applied'])
    def test_cross_patch_trends_rejected_and_invalid_data_excluded(self):
        rows=self.rows();rows[0]['patch']='18.2';rows+=[dict(rows[1],match_id='bad',placement=True)]
        result=summarize(rows,source='test-fixture',fetched_at=200,current_patch="18.3",current_set="TFTSet18")
        self.assertIsNone(result['trend']);self.assertEqual(len(result['by_patch']),1)
        self.assertEqual(result['statistics']['matches'],9)
        self.assertEqual(result['excluded_patch_records'],1)
        self.assertEqual(result['rejected_records'],1)
    def test_empty_is_not_zero_performance(self):
        result=summarize([],source='test-fixture',fetched_at=200,current_patch="18.3",current_set="TFTSet18")
        self.assertIsNone(result['statistics']['average_placement'])
        self.assertIsNone(result['statistics']['top4_rate'])
