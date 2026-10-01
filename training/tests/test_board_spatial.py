"""B1 contracts prevent geometric or visual evidence becoming invented state."""
from pathlib import Path
import tempfile
import unittest
from training.board_spatial_evidence import NO_EFFECTS, profile_contract, validate
from training.board_spatial_run import source_path
from training.board_spatial_viewer import write_viewer


def fixture():
    p = dict(id='fixture', schema_version=1, reference_width=1920, reference_height=1080,
        board_topology_id='board-standard-4x7-v1', bench_topology_id='bench-nine-v1',
        board_rows=[[560, 1258, 444], [618, 1330, 519], [557, 1275, 596], [620, 1350, 680]],
        bench_centers=[409, 527, 645, 762, 879, 996, 1112, 1228, 1344], bench_y=792,
        bench_crop_y=682, bench_crop_width=103, bench_crop_height=146,
        reference_sha256='a'*64, geometry_source=dict(sha256='b'*64, role='visible_grid_development_seed_not_independent_validation'),
        bars=dict(max_candidates=128), signature=dict(arena_max_mae=8.0, arena_max_changed_fraction=.20,
                                                     empty_max_mae=5.0, empty_max_changed_fraction=.02))
    bench = [dict(slot=i, rect=dict(x=x-51, y=682, width=103, height=146), ground_pixel=[x, 792],
                  evidence='empty_reference_match', marker_candidates=[], unit_id=None, occupancy=None,
                  empty_signature=dict(rgb_mae=0.0, changed_fraction=0.0)) for i, x in enumerate(p['bench_centers'])]
    cells = [dict(row=r, col=c, screen=[a+(b-a)*c/6, y], occupancy=None)
             for r, (a, b, y) in enumerate(p['board_rows']) for c in range(7)]
    read = dict(timestamp_ms=250, profile=p['id'], projection_status='reference_arena_match',
                arena_scores=[dict(rgb_mae=0.0, changed_fraction=0.0) for _ in range(2)],
                bench=bench, board=cells, markers=[], phase=None, perspective=None, error=None)
    summary = dict(schema_version=1, policy='board_bench_spatial_v1', profile=p['id'], frames=1,
                   board_cells_per_frame=28, bench_slots_per_frame=9, execution_complete=True, errors=0,
                   ocr_process_calls=0, exact_accuracy=None, projection_statuses={'reference_arena_match': 1},
                   bench_evidence={'empty_reference_match': 9}, marker_colors={})
    summary.update({k: False for k in NO_EFFECTS})
    report = dict(summary=summary, records=[dict(read=read, scan_ms=1, decode_and_scan_ms=2)])
    return p, dict(frames=[dict(timestamp_ms=250, image='a.jpg')]), report


class EvidenceTests(unittest.TestCase):
    def test_valid_evidence_has_no_occupancy_or_identity(self):
        p, m, r = fixture()
        profile_contract(p)
        self.assertTrue(validate(r, m, p)['execution_complete'])

    def reject(self, change):
        p, m, r = fixture()
        change(r)
        with self.assertRaises(ValueError):
            validate(r, m, p)

    def test_unsupported_semantic_flags_rejected(self):
        for key in NO_EFFECTS:
            self.reject(lambda r: r['summary'].update({key: True}))

    def test_matching_empty_pixels_cannot_assert_empty_occupancy(self):
        self.reject(lambda r: r['records'][0]['read']['bench'][0].update(occupancy=False))

    def test_board_ground_assignment_cannot_be_invented(self):
        self.reject(lambda r: r['records'][0]['read']['board'][0].update(occupancy=True))

    def test_bad_board_geometry_rejected(self):
        self.reject(lambda r: r['records'][0]['read']['board'][0].update(screen=[1, 2]))

    def test_missing_bench_slot_rejected(self):
        self.reject(lambda r: r['records'][0]['read']['bench'].pop())

    def test_false_aggregate_and_timestamp_rejected(self):
        self.reject(lambda r: r['summary'].update(bench_evidence={'empty_reference_match': 8}))
        self.reject(lambda r: r['records'][0]['read'].update(timestamp_ms=300))

    def test_arena_cannot_match_failing_scores(self):
        self.reject(lambda r: r['records'][0]['read']['arena_scores'][0].update(rgb_mae=100))

    def test_empty_class_must_match_similarity(self):
        self.reject(lambda r: r['records'][0]['read']['bench'][0]['empty_signature'].update(changed_fraction=1))

    def test_unresolved_arena_cannot_reuse_empty_reference(self):
        self.reject(lambda r: r['records'][0]['read'].update(projection_status='unresolved'))

    def test_nonfinite_values_rejected(self):
        self.reject(lambda r: r['records'][0].update(scan_ms=float('nan')))
        self.reject(lambda r: r['records'][0]['read']['arena_scores'][0].update(rgb_mae=float('nan')))

    def test_no_ocr_and_no_accuracy_claim(self):
        self.reject(lambda r: r['summary'].update(ocr_process_calls=1))
        self.reject(lambda r: r['summary'].update(exact_accuracy=1.0))

    def test_reference_hash_and_role_required(self):
        p, _, _ = fixture()
        p['reference_sha256'] = 'latest'
        with self.assertRaises(ValueError): profile_contract(p)

    def test_local_paths_reject_escape_and_non_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'a.jpg').write_bytes(b'image')
            self.assertEqual(source_path(root, 'a.jpg'), root/'a.jpg')
            for value in ('../a.jpg', '/etc/passwd'):
                with self.assertRaises(ValueError): source_path(root, value)
            (root/'a.mp4').write_bytes(b'video')
            with self.assertRaises(ValueError): source_path(root, 'a.mp4')

    def test_viewer_is_self_contained_escapes_data_and_refuses_overwrite(self):
        p, m, r = fixture()
        p['note'] = '</script><script>bad()</script>'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'a.jpg').write_bytes(b'image')
            path = root/'viewer.html'
            write_viewer(path, p, m, r['records'], root)
            text = path.read_text()
            self.assertIn('data:image/jpeg;base64,', text)
            self.assertNotIn('</script><script>bad()', text)
            self.assertNotIn('https://', text)
            with self.assertRaises(FileExistsError): write_viewer(path, p, m, r['records'], root)
