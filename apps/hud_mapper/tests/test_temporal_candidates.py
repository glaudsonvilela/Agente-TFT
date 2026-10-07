import unittest

from hm.temporal_candidates import TemporalCandidates


def frame(at, unit='DA_18_Rakan', item='TFT_Item_BFSword', *, position=2):
    place = dict(status='candidate_only', zone='board', row=1, cell_or_slot=position)
    return dict(timestamp_ms=at,
        observed_markers=[dict(marker_id=7, position_candidate=place)],
        neural_units=dict(records=[dict(marker_id=7, candidate_id=unit,
                                         candidate_name='Rakan' if unit else None)]),
        item_visual_native=dict(inventory=[dict(slot=0, candidate_id=item,
            candidates=[dict(names=['Espada G.p.C.'])])], equipped=[]))


class TemporalCandidateTests(unittest.TestCase):
    def test_two_frames_make_persistent_hypotheses_without_verifying_them(self):
        memory = TemporalCandidates()
        first = memory.update(frame(1000), epoch=1)
        self.assertIsNone(first['units'][0]['candidate_id'])
        second = memory.update(frame(2000), epoch=1)
        self.assertEqual(second['units'][0]['candidate_id'], 'DA_18_Rakan')
        self.assertEqual(second['inventory'][0]['candidate_name'], 'Espada G.p.C.')
        self.assertEqual(second['units'][0]['support_frames'], 2)
        self.assertFalse(second['units'][0]['identity_verified'])
        self.assertFalse(second['score_is_probability'])
        lost = memory.update(frame(3000, unit=None, item=None), epoch=1)
        self.assertIsNone(lost['units'][0]['candidate_id'])
        self.assertIsNone(lost['inventory'][0]['candidate_id'])

    def test_seek_move_and_conflict_cannot_reuse_an_old_identity(self):
        memory = TemporalCandidates()
        memory.update(frame(1000), epoch=1)
        memory.update(frame(2000), epoch=1)
        moved = memory.update(frame(3000, position=3), epoch=1)
        self.assertIsNone(moved['units'][0]['candidate_id'])
        conflict = memory.update(frame(4000, unit='DA_18_Akali_AD'), epoch=1)
        self.assertIsNone(conflict['units'][0]['candidate_id'])
        seek = memory.update(frame(1000), epoch=2)
        self.assertIsNone(seek['units'][0]['candidate_id'])
        self.assertEqual(seek['units'][0]['observed_frames'], 1)

    def test_stale_gap_and_missing_position_do_not_invent_board_members(self):
        memory = TemporalCandidates()
        memory.update(frame(1000), epoch=1)
        gap = memory.update(frame(7000), epoch=1)
        self.assertIsNone(gap['units'][0]['candidate_id'])
        unknown = frame(8000)
        unknown['observed_markers'][0]['position_candidate'] = {'status':'unavailable'}
        result = memory.update(unknown, epoch=1)
        self.assertEqual(result['units'], [])


if __name__ == '__main__':
    unittest.main()
