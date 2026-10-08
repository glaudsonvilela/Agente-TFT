"""The Windows client must reach the same persistent Rust decision worker."""
import threading
import unittest

from hm45_core_server import AnalysisCore
from hm45_vm_client import RemoteNativeWorker


class MatchMemoryVMTests(unittest.TestCase):
    def test_rank_request_crosses_windows_vm_bridge_without_pixels(self):
        match_id = '0123456789abcdef0123456789abcdef'

        class Reader:
            def request(self, request, payload=b'', timeout=12):
                self.request_seen = request
                assert payload == b''
                return {'id': request['id'], 'origin': 'rust_live_opportunity_v1',
                        'selected_index': None, 'ranked': [],
                        'memory': {'persistence': 'local_sqlite'}}

        server = object.__new__(AnalysisCore)
        server.reader_lock = threading.Lock()
        server.reader = Reader()

        class VM:
            ready = {'reader_ready': {'rank_advice': True}}
            def request(self, op, frame_id, width=0, height=0, rgb=b'', **fields):
                self.wire = (op, frame_id, width, height, rgb, fields)
                return server.dispatch({'op': op, 'frame_id': frame_id,
                    'width': width, 'height': height, **fields}, rgb), 0.2

        vm = VM()
        client = RemoteNativeWorker(vm, 'reader')
        result = client.request({'op': 'rank_advice', 'id': 42, 'source_ms': 5000,
            'epoch': 0, 'match_id': match_id, 'context': {'gold': 30},
            'observation': {'gold': 30}, 'candidates': []})
        self.assertEqual(result['memory']['persistence'], 'local_sqlite')
        self.assertEqual(server.reader.request_seen['match_id'], match_id)
        self.assertEqual(vm.wire[2:5], (0, 0, b''))

    def test_invalid_match_identity_is_rejected_before_rust(self):
        server = object.__new__(AnalysisCore)
        server.reader_lock = threading.Lock()
        server.reader = object()
        with self.assertRaisesRegex(Exception, 'Estado da partida inválido'):
            server.dispatch({'op': 'rank_advice', 'frame_id': 1,
                'width': 0, 'height': 0, 'source_ms': 0, 'epoch': 0,
                'match_id': '../outside', 'candidates': [],
                'context': {}, 'observation': {}}, b'')


if __name__ == '__main__':
    unittest.main()
