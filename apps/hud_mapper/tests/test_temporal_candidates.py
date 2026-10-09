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
    def test_async_unit_votes_keep_source_frame_and_require_repeated_evidence(self):
        memory = TemporalCandidates()
        def async_frame(at, position=2):
            snapshot = frame(at, position=position)
            snapshot['neural_units'] = dict(mode='async_diagnostic_candidates', records=[])
            return snapshot
        def completed(source_ms, frame_id, position=2, candidate='DA_18_Rakan'):
            return dict(source_ms=source_ms, frame_id=frame_id, epoch=1,
                positions=frame(source_ms, position=position)['observed_markers'],
                result=dict(records=[dict(marker_id=7, status='identity_candidate',
                    identity_verified=False, candidate_id=candidate, candidate_name='Rakan')]))

        memory.update(async_frame(1000), epoch=1)
        self.assertTrue(memory.ingest_async_units(completed(1000, 1), epoch=1, now_ms=2000))
        first = memory.update(async_frame(2000), epoch=1)['units'][0]
        self.assertEqual(first['source_frame_id'], 1)
        self.assertIsNone(first['candidate_id'])
        self.assertFalse(memory.ingest_async_units(completed(1000, 1), epoch=1, now_ms=2500))
        self.assertTrue(memory.ingest_async_units(completed(2000, 2), epoch=1, now_ms=3000))
        second = memory.update(async_frame(3000), epoch=1)['units'][0]
        self.assertEqual(second['candidate_id'], 'DA_18_Rakan')
        self.assertEqual(second['source_ms'], 2000)
        self.assertEqual(second['support_frames'], 2)
        self.assertFalse(second['identity_verified'])
        self.assertFalse(memory.ingest_async_units(completed(3000, 3), epoch=2, now_ms=3500))
        moved = memory.update(async_frame(4000, position=3), epoch=1)
        self.assertEqual(moved['units'], [])

    def test_async_unit_votes_reset_after_seek_and_stale_result(self):
        memory = TemporalCandidates()
        snapshot = frame(1000)
        snapshot['neural_units'] = dict(mode='async_diagnostic_candidates', records=[])
        memory.update(snapshot, epoch=1)
        result = dict(source_ms=1000, frame_id=1, epoch=1,
            positions=snapshot['observed_markers'], result=dict(records=[dict(marker_id=7,
                status='identity_candidate', identity_verified=False,
                candidate_id='DA_18_Rakan', candidate_name='Rakan')]))
        self.assertFalse(memory.ingest_async_units(result, epoch=1, now_ms=6000))
        self.assertTrue(memory.ingest_async_units(result, epoch=1, now_ms=2000))
        seek = frame(500)
        seek['neural_units'] = snapshot['neural_units']
        self.assertEqual(memory.update(seek, epoch=2)['units'], [])
        self.assertFalse(memory.ingest_async_units(result, epoch=2, now_ms=1000))

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

    def test_equipped_icon_can_persist_on_a_marker_without_known_cell(self):
        memory = TemporalCandidates()
        one = frame(1000)
        one['observed_markers'][0]['position_candidate'] = None
        one['item_evidence'] = {'inventory': [], 'equipped': [
            {'marker_id': 7, 'slot': 0, 'position_candidate': None,
             'candidate_id': 'emblem', 'candidate_name': 'Emblema'}]}
        self.assertIsNone(memory.update(one, epoch=1)['equipped'][0]['candidate_id'])
        two = frame(2000)
        two['observed_markers'][0]['position_candidate'] = None
        two['item_evidence'] = one['item_evidence']
        result = memory.update(two, epoch=1)
        self.assertEqual(result['equipped'][0]['candidate_name'], 'Emblema')
        self.assertIsNone(result['equipped'][0]['position'])
        self.assertEqual(result['units'], [])


if __name__ == '__main__':
    unittest.main()
