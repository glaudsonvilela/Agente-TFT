"""Contract for the real designer installer and its local setup bridge."""

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hm45_setup_web import SetupController, package_contract, SetupServer


class SetupWindowSmoke(unittest.TestCase):
    def test_designer_and_local_api_are_in_package(self):
        with tempfile.TemporaryDirectory() as temp:
            result = package_contract(Path(temp) / "setup.json")
            self.assertTrue(result["designer_assets_served"])
            self.assertTrue(result["local_setup_api_responded"])

    def test_preflight_install_and_launch_are_real_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = unittest.mock.MagicMock()
            fake.preflight.return_value.wsl_ready = True
            fake.install.return_value = "ready"
            with patch("hm45_setup_web.CoreInstaller", return_value=fake), \
                 patch.dict("os.environ", {"LOCALAPPDATA": temp}), \
                 patch("hm45_setup_web.wsl_available", return_value=True), \
                 patch("hm45_setup_web.subprocess.Popen") as launch:
                controller = SetupController(Path(temp) / "AgenteTFT.exe")
                self._wait_for(controller, "ready_to_install")
                controller.install(False)
                self._wait_for(controller, "ready")
                self.assertTrue(controller.state()["vm_ready"])
                controller.launch()
                launch.assert_called_once()
                self.assertTrue(controller.closed.is_set())

    def test_untrusted_origin_cannot_call_setup(self):
        class Probe:
            def state(self):
                return {"phase": "checking"}
        from hm45_setup_web import design_root
        server = SetupServer(Probe(), design_root())
        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(server.url.split("?")[0] + "api/state", data=b'{"args":[]}',
                              headers={"Content-Type": "application/json", "Origin": "https://example.com"})
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()

    def _wait_for(self, controller, phase):
        end = time.monotonic() + 3
        while controller.state()["phase"] != phase and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(controller.state()["phase"], phase, controller.state()["error"])


if __name__ == "__main__":
    unittest.main()
