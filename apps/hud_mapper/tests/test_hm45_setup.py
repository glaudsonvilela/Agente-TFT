"""Safety contracts for the WSL installation state machine."""

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hm45_setup_core import CoreInstaller, SetupError, load_package, verify_package


class FakeWindows:
    def __init__(self):
        self.calls = []
        self.wsl_ready = True
        self.distros = set()
        self.import_fails = False
        self.health_ok = True
        self.enable_code = 0

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        if args[:2] == ["wsl.exe", "--status"]:
            return subprocess.CompletedProcess(args, 0 if self.wsl_ready else 1, "", "")
        if args[:3] == ["wsl.exe", "--list", "--quiet"]:
            return subprocess.CompletedProcess(args, 0, "\n".join(sorted(self.distros)), "")
        if args[:2] == ["wsl.exe", "--import"]:
            if self.import_fails:
                return subprocess.CompletedProcess(args, 1, "", "error")
            self.distros.add(args[2])
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["wsl.exe", "--distribution"]:
            return subprocess.CompletedProcess(args, 0 if self.health_ok else 1,
                                               "AGENTETFT_CORE_HEALTH_OK" if self.health_ok else "", "")
        if args[0] == "powershell.exe":
            return subprocess.CompletedProcess(args, self.enable_code if "-ExecutionPolicy" in args else 0,
                                               "True", "")
        raise AssertionError(args)


class SetupContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.core = self.base / "core"
        self.core.mkdir()
        self.tar = self.core / "AgenteTFT-Core-v1.tar"
        self.tar.write_bytes(b"test fixture, not a distributable VM")
        self.manifest = {
            "schema_version": 1,
            "distro_name": "AgenteTFT-Core-v1",
            "rootfs_file": self.tar.name,
            "sha256": hashlib.sha256(self.tar.read_bytes()).hexdigest(),
            "version": "0.6.0",
            "analysis_health_contract": "l3_ocr_b4_roi_v1",
        }
        (self.core / "core-package.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.fake = FakeWindows()
        self.installer = CoreInstaller(self.core, self.base / "installed", self.base / "App.exe",
                                       run=self.fake, memory=lambda: 8 * 1024**3, build=lambda: 26100,
                                       host_probe=lambda package, log: True)
        self.installer.clear_resume = lambda: None
        self.installer.register_resume = lambda: None

    def test_hash_tampering_stops_before_import(self):
        self.tar.write_bytes(b"modified rootfs")
        with patch("hm45_setup_core.sys.platform", "win32"), patch("hm45_setup_core.platform.machine", return_value="AMD64"):
            with self.assertRaisesRegex(SetupError, "SHA-256"):
                self.installer.preflight(lambda _: None)
        self.assertFalse(any(call[:2] == ["wsl.exe", "--import"] for call in self.fake.calls))

    def test_manifest_rejects_other_distro_and_missing_contract(self):
        self.manifest["distro_name"] = "Ubuntu"
        (self.core / "core-package.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(SetupError):
            load_package(self.core)
        self.manifest["distro_name"] = "AgenteTFT-Core-v1"
        self.manifest.pop("analysis_health_contract")
        (self.core / "core-package.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(SetupError):
            load_package(self.core)

    def test_import_health_and_idempotence(self):
        verify_package(self.installer.package)
        self.assertEqual(self.installer.install(lambda _: None), "ready")
        self.assertEqual(self.installer.install(lambda _: None), "ready")
        imports = [call for call in self.fake.calls if call[:2] == ["wsl.exe", "--import"]]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0][2], "AgenteTFT-Core-v1")
        self.assertEqual(imports[0][-2:], ["--version", "2"])
        self.assertFalse(any("--unregister" in call for call in self.fake.calls))

    def test_existing_unhealthy_vm_is_preserved(self):
        self.fake.distros.add("AgenteTFT-Core-v1")
        self.fake.health_ok = False
        with self.assertRaisesRegex(SetupError, "preservada"):
            self.installer.install(lambda _: None)
        self.assertFalse(any(call[:2] == ["wsl.exe", "--import"] for call in self.fake.calls))
        self.assertFalse(any("--unregister" in call for call in self.fake.calls))

    def test_windows_to_wsl_ip_must_pass_before_ready(self):
        self.fake.distros.add("AgenteTFT-Core-v1")
        self.installer.host_probe = lambda package, log: False
        with self.assertRaisesRegex(SetupError, "preservada"):
            self.installer.install(lambda _: None)
        self.assertIn("conexão IP local", self.installer.last_health_error)

    def test_reboot_registers_resume_without_import(self):
        self.fake.wsl_ready = False
        self.fake.enable_code = 3010
        resumed = []
        self.installer.register_resume = lambda: resumed.append(True)
        self.assertFalse(self.installer.enable_wsl(lambda _: None))
        self.assertEqual(resumed, [True])
        self.assertFalse(any(call[:2] == ["wsl.exe", "--import"] for call in self.fake.calls))


if __name__ == "__main__":
    unittest.main()
