"""Safety contracts for the WSL installation state machine."""

from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hm45_setup_core import CoreInstaller, SetupError, configure_headless_wslg, load_package, restart_windows, verify_package, wait_wsl_after_restart, wsl_available, wsl_names


class FakeWindows:
    def __init__(self):
        self.calls = []
        self.wsl_ready = True
        self.status_failures = 0
        self.distros = set()
        self.import_fails = False
        self.health_ok = True
        self.enable_code = 0
        self.empty_list_is_error = False
        self.virtualization = "True"

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        if args[:2] == ["wsl.exe", "--status"]:
            if self.status_failures:
                self.status_failures -= 1
                return subprocess.CompletedProcess(args, 1, "", "WSL is starting")
            return subprocess.CompletedProcess(args, 0 if self.wsl_ready else 1, "", "")
        if args[:3] == ["wsl.exe", "--list", "--quiet"]:
            if self.empty_list_is_error and not self.distros:
                return subprocess.CompletedProcess(args, 1, "", "There are no installed distributions.")
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
                                               self.virtualization, "")
        if args[0] == "shutdown.exe":
            return subprocess.CompletedProcess(args, 0, "", "")
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

    def test_cim_false_does_not_block_wsl_import(self):
        self.fake.virtualization = "False"
        messages = []
        with patch("hm45_setup_core.sys.platform", "win32"), patch("hm45_setup_core.platform.machine", return_value="AMD64"):
            preflight = self.installer.preflight(messages.append)
        self.assertTrue(preflight.package_verified)
        self.assertIn("será testada pelo WSL 2", preflight.virtualization)
        self.assertEqual(self.installer.install(messages.append), "ready")
        self.assertTrue(any(call[:2] == ["wsl.exe", "--import"] for call in self.fake.calls))

    def test_headless_wslg_preserves_other_global_settings_and_backup(self):
        config = self.base / ".wslconfig"
        original = b"[wsl2]\r\nmemory=4GB\r\nguiApplications=true ; previous value\r\n[experimental]\r\nsparseVhd=true\r\n"
        config.write_bytes(original)
        backup = configure_headless_wslg(config)
        self.assertEqual(backup.read_bytes(), original)
        self.assertIn(b"guiApplications=false ; previous value", config.read_bytes())
        self.assertIn(b"sparseVhd=true", config.read_bytes())
        self.assertIsNone(configure_headless_wslg(config))

    def test_headless_wslg_rejects_ambiguous_config_without_change(self):
        config = self.base / ".wslconfig"
        original = b"[wsl2]\nguiApplications=true\nguiApplications=false\n"
        config.write_bytes(original)
        with self.assertRaisesRegex(SetupError, "duplicado"):
            configure_headless_wslg(config)
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse(list(self.base.glob(".wslconfig.AgenteTFT-*")))

    def test_headless_wslg_preserves_windows_powershell_utf16_config(self):
        config = self.base / ".wslconfig"
        original = b"\xff\xfe" + "[wsl2]\r\nmemory=3GB\r\n".encode("utf-16-le")
        config.write_bytes(original)
        backup = configure_headless_wslg(config)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(config.read_bytes()[:2], b"\xff\xfe")
        self.assertIn("guiApplications=false", config.read_bytes()[2:].decode("utf-16-le"))

    def test_headless_wslg_resumes_after_restart_and_rolls_back_on_registration_failure(self):
        config = self.base / ".wslconfig"
        original = b"[wsl2]\nmemory=4GB\n"
        config.write_bytes(original)
        self.installer.register_resume = lambda extra_args=(): (_ for _ in ()).throw(OSError("registry failed"))
        with patch.dict(os.environ, {"USERPROFILE": str(self.base)}):
            with self.assertRaisesRegex(OSError, "registry failed"):
                self.installer.use_headless_wsl(lambda _: None)
        self.assertEqual(config.read_bytes(), original)
        resumed = []
        self.installer.register_resume = lambda extra_args=(): resumed.append(extra_args)
        with patch.dict(os.environ, {"USERPROFILE": str(self.base)}):
            self.assertFalse(self.installer.use_headless_wsl(lambda _: None))
        self.assertEqual(resumed, [("--resume-headless",)])
        self.assertIn(b"guiApplications=false", config.read_bytes())

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

    def test_new_packaged_guest_imports_beside_old_guest(self):
        self.fake.distros.add("AgenteTFT-Core-v1")
        self.tar.rename(self.core / "AgenteTFT-Core-v2.tar")
        self.manifest["distro_name"] = "AgenteTFT-Core-v2"
        self.manifest["rootfs_file"] = "AgenteTFT-Core-v2.tar"
        self.manifest["version"] = "0.6.1"
        (self.core / "core-package.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        upgraded = CoreInstaller(self.core, self.base / "installed", self.base / "App.exe",
                                 run=self.fake, memory=lambda: 8 * 1024**3,
                                 build=lambda: 26100, host_probe=lambda package, log: True)
        upgraded.clear_resume = lambda: None
        self.assertEqual(upgraded.install(lambda _: None), "ready")
        self.assertEqual(self.fake.distros, {"AgenteTFT-Core-v1", "AgenteTFT-Core-v2"})
        self.assertFalse(any("--unregister" in call for call in self.fake.calls))

    def test_first_import_after_reboot_with_no_wsl_distribution(self):
        self.fake.empty_list_is_error = True
        self.assertEqual(self.installer.install(lambda _: None), "ready")
        self.assertIn("AgenteTFT-Core-v1", self.fake.distros)
        self.assertEqual(sum(call[:2] == ["wsl.exe", "--import"] for call in self.fake.calls), 1)

    def test_no_distribution_message_is_not_missing_wsl(self):
        self.fake.wsl_ready = False
        self.fake.empty_list_is_error = True
        self.assertTrue(wsl_available(self.fake))
        self.assertEqual(self.installer.install(lambda _: None), "ready")

    def test_resume_waits_for_wsl_startup(self):
        self.fake.status_failures = 2
        wait_wsl_after_restart(self.fake, attempts=3, pause=lambda _: None)
        self.assertEqual(self.fake.status_failures, 0)

    def test_utf16_wsl_listing_is_normalized(self):
        self.assertEqual(wsl_names("ÿþA\x00g\x00e\x00n\x00t\x00e\x00T\x00F\x00T\x00-\x00C\x00o\x00r\x00e\x00-\x00v\x001\x00\r\x00\n\x00"),
                         {"AgenteTFT-Core-v1"})

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

    def test_restart_button_uses_normal_windows_restart_without_forcing_apps(self):
        restart_windows(self.fake)
        self.assertIn(["shutdown.exe", "/r", "/t", "0"], self.fake.calls)


if __name__ == "__main__":
    unittest.main()
