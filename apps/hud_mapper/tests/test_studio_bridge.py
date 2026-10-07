from __future__ import annotations

import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from hm.studio_bridge import StudioController, StudioServer, design_root, package_contract


class StudioBridgeTests(unittest.TestCase):
    def test_package_contract_serves_connected_layout(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as temp:
            report = package_contract(Path(temp) / 'studio.json', probe_webview=False)
            self.assertTrue(report['studio_assets_served'])
            self.assertTrue((Path(temp) / 'studio.json').is_file())

    def test_closing_window_seals_finished_capture(self):
        class Session:
            finished = False
            options = type('Options', (), {'replay_review': True})()
            def __init__(self):
                self.done = threading.Event()
                self.finish_calls = 0
            def request_stop(self):
                self.done.set()
            def finish(self):
                self.finish_calls += 1
                self.finished = True
                return {'execution_complete': True}

        controller = object.__new__(StudioController)
        controller.lock = threading.RLock()
        controller.session = Session()
        controller.last_result = controller.last_error = None
        controller.closed = threading.Event()
        controller.preview_condition = threading.Condition()
        controller.voice = None
        controller.model_updater = type('Updater', (), {
            'activate_pending_if_idle': lambda self: None,
            'check_async': lambda self: None,
        })()
        controller.close()
        self.assertTrue(controller.closed.is_set())
        self.assertEqual(controller.session.finish_calls, 1)
        self.assertEqual(controller.last_result, {'execution_complete': True})

    def test_local_design_server_serves_only_its_tokenized_directory(self):
        server = StudioServer(object(), design_root())
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with urlopen(server.url, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'AGENTE TFT', response.read())
            with urlopen(server.url.split('?')[0] + 'connected.js', timeout=2) as response:
                self.assertIn(b'connectedCoach', response.read())
            for path in ('/index.html', server.url.split('?')[0] + '../../etc/passwd'):
                with self.assertRaises(HTTPError) as error:
                    urlopen('http://127.0.0.1:' + str(server.server_port) + path
                            if path.startswith('/') else path, timeout=2)
                self.assertIn(error.exception.code, (403, 404))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
