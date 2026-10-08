"""Contract for the real designer installer and its local setup bridge."""

from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
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
                def opened_studio(*_args, **kwargs):
                    Path(kwargs["env"]["AGENTE_TFT_STUDIO_URL_FILE"]).write_text(
                        "http://127.0.0.1:61234/token/?connected=1#studio", encoding="utf-8")
                    return SimpleNamespace(poll=lambda: None)
                launch.side_effect = opened_studio
                result = controller.launch()
                launch.assert_called_once()
                self.assertEqual(result["url"], "http://127.0.0.1:61234/token/?connected=1#studio")
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

    def test_failed_studio_start_keeps_installer_open_with_error(self):
        with tempfile.TemporaryDirectory() as temp:
            controller = object.__new__(SetupController)
            controller.lock = threading.RLock()
            controller.vm_ready = True
            controller.closed = threading.Event()
            controller.app_exe = Path(temp) / "AgenteTFT.exe"
            controller.log_path = Path(temp) / "setup.log"
            controller._report = lambda _message: None
            with patch("hm45_setup_web.subprocess.Popen",
                       return_value=SimpleNamespace(poll=lambda: 1)):
                with self.assertRaisesRegex(RuntimeError, "encerrou antes"):
                    controller.launch()
            self.assertFalse(controller.closed.is_set())

    def _wait_for(self, controller, phase):
        end = time.monotonic() + 3
        while controller.state()["phase"] != phase and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(controller.state()["phase"], phase, controller.state()["error"])


if __name__ == "__main__":
    unittest.main()
