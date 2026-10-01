"""Pure contracts; do not claim real model execution from these tests."""
import copy
import json
from pathlib import Path
import unittest
from training.board_detector_core import (policy_contract, detections, compare_frame, summarize,
                                          overlap, iou, percentile)
from training.board_detector_run import regression

ROOT = Path(__file__).resolve().parents[2]


def policy():
    return json.loads((ROOT/'configs/vision/board-open-vocabulary-v1.json').read_text())


def b1():
    return dict(timestamp_ms=250, projection_status='unresolved',
        markers=[dict(id=0, rect=dict(x=5, y=5, width=20, height=4))],
        bench=[dict(slot=i, rect=dict(x=i*30, y=0, width=28, height=80),
                    marker_candidates=[], evidence='projection_unavailable') for i in range(9)])


def raw(box=None, score=.7, label='a creature'):
    return dict(box=box or [2, 2, 27, 65], score=score, label=label)


def detected(items=None):
    return detections([raw()] if items is None else items,
                      dict(x=0, y=0, width=300, height=100), policy())


class DetectorContracts(unittest.TestCase):
    def test_policy_has_no_champion_or_season_vocabulary(self):
        self.assertEqual(policy_contract(policy())['id'], 'board-open-vocabulary-v1')

    def test_pin_changes_are_rejected(self):
        for k in ['model_id', 'model_revision', 'weights_sha256']:
            p=policy();p[k]='different'
            with self.assertRaises(ValueError): policy_contract(p)

    def test_prompt_cannot_be_selected_by_result(self):
        p=policy();p['prompt']='a champion with 100 HP'
        with self.assertRaises(ValueError): policy_contract(p)

    def test_threshold_and_budget_changes_fail(self):
        for k in ['box_threshold', 'text_threshold', 'nms_iou', 'max_detections', 'cpu_threads']:
            p=policy();p[k]=float('nan')
            with self.assertRaises(ValueError): policy_contract(p)

    def test_extra_fields_and_boolean_budgets_fail(self):
        p=policy();p['expected_count']=3
        with self.assertRaises(ValueError): policy_contract(p)
        p=policy();p['cpu_threads']=True
        with self.assertRaises(ValueError): policy_contract(p)

    def test_crop_coordinates_are_restored(self):
        r=detections([raw()],dict(x=340,y=130,width=1120,height=710),policy())['proposals'][0]
        self.assertEqual((r['rect']['x'],r['rect']['y']),(342,132))
        self.assertIsNone(r['board_cell']);self.assertIsNone(r['ground_point']);self.assertIsNone(r['unit_id'])

    def test_no_detections_does_not_fill_empty_bench(self):
        r=compare_frame(b1(),detected([]))
        self.assertTrue(all(x['occupancy'] is None and x['comparison']=='neither_signal' for x in r['bench']))

    def test_neural_proposals_can_exist_without_arena_match(self):
        r=compare_frame(b1(),detected())
        self.assertEqual(r['bench'][0]['comparison'],'neural_box_only')
        self.assertIsNone(r['bench'][0]['occupancy'])

    def test_overlap_never_changes_baseline(self):
        old=b1();before=copy.deepcopy(old)
        compare_frame(old,detected());self.assertEqual(old,before)

    def test_empty_reference_conflict_is_visible(self):
        old=b1();old['bench'][0]['evidence']='empty_reference_match'
        r=compare_frame(old,detected())
        self.assertTrue(r['bench'][0]['reference_empty_with_neural_overlap'])

    def test_nms_keeps_best_and_records_suppressed_count(self):
        r=detected([raw(score=.7),raw(score=.9)])
        self.assertEqual(len(r['proposals']),1);self.assertEqual(r['nms_suppressed'],1)
        self.assertEqual(r['proposals'][0]['score'],.9)

    def test_nonoverlapping_objects_not_suppressed(self):
        r=detected([raw(),raw([50,5,65,50])]);self.assertEqual(len(r['proposals']),2)

    def test_invalid_boxes_and_scores_are_operational_errors(self):
        for x in [raw([float('nan'),0,20,20]), raw([5,5,2,2]),raw(score=float('nan')),
                  raw(score=True), raw(score=2), raw(label=None)]:
            with self.assertRaises(ValueError): detected([x])

    def test_threshold_rejects_without_retry(self):
        r=detected([raw(score=.29)]);self.assertFalse(r['proposals']);self.assertEqual(r['rejected'],1)

    def test_clipping_is_explicit_not_ground_assignment(self):
        r=detected([raw([-3,-3,27,65])])['proposals'][0]
        self.assertTrue(r['clipped']);self.assertIsNone(r['ground_point'])

    def test_outside_boxes_are_rejected(self):
        r=detected([raw([400,20,500,80])]);self.assertFalse(r['proposals'])

    def test_raw_budget_is_not_silently_truncated(self):
        with self.assertRaises(ValueError): detected([raw()]*901)

    def test_overlap_edges_are_half_open(self):
        a=dict(x=0,y=0,width=2,height=2);b=dict(x=2,y=0,width=2,height=2)
        self.assertFalse(overlap(a,b));self.assertEqual(iou(a,b),0);self.assertEqual(iou(a,a),1)

    def test_both_signals_is_not_two_units(self):
        old=b1();old['bench'][0]['marker_candidates']=[0]
        r=compare_frame(old,detected())
        self.assertEqual(r['bench'][0]['comparison'],'both_signals');self.assertIsNone(r['bench'][0]['unit_id'])

    def test_regression_compares_whole_read_not_counts(self):
        a={'records':[{'read':b1()}]};b=copy.deepcopy(a);b['records'][0]['read']['markers'][0]['rect']['x']=6
        self.assertFalse(regression(a,b)['b1_observations_unchanged'])
        self.assertTrue(regression(a,a)['b1_observations_unchanged'])

    def test_regression_missing_frame_fails(self):
        with self.assertRaises(ValueError): regression({'records':[{}]},{'records':[]})

    def test_summary_has_no_accuracy_or_promotion(self):
        old=b1();d=detected();r=dict(b1=old,neural=d,comparison=compare_frame(old,d),model_ms=5,decode_ms=2,candidate_total_ms=8)
        s=summarize([r],{'frames':1})
        self.assertEqual(s['frames'],1);self.assertEqual(s['neural_proposals'],1)
        for k in ['exact_accuracy','false_positive_rate','false_negative_rate']:self.assertIsNone(s[k])
        for k in ['profile_promoted','game_state_updated','model_trained','labels_used','occupancy_validated']:self.assertFalse(s[k])
        self.assertEqual(s['ocr_process_calls'],0)

    def test_empty_summary_is_failure_not_perfect_result(self):
        with self.assertRaises(ValueError): summarize([], {})

    def test_quantile_does_not_claim_mean_stage_latency(self):
        self.assertIsNone(percentile([], .5));self.assertEqual(percentile([1,3],.5),2)


if __name__ == '__main__': unittest.main()
