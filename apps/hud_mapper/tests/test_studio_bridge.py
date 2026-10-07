from __future__ import annotations

import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from hm.studio_bridge import StudioServer, design_root


class StudioBridgeTests(unittest.TestCase):
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
