"""Per-user, resumable WSL 2 provisioner for the HM4.5 installer.

This module does not modify other WSL distributions or the global .wslconfig.
The manifest is generated only by the HM4.5 package build after its guest
health contract has been verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Callable


DISTRO_PATTERN = re.compile(r"^AgenteTFT-Core-v[0-9]+$")
HEALTH_EXEC = "/opt/agente-tft/bin/health-check"
RUNONCE_NAME = "AgenteTFTCoreSetup"


class SetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Package:
    distro: str
    rootfs: Path
    sha256: str
    version: str


@dataclass(frozen=True)
class Preflight:
    windows_build: int
    free_gib: float
    memory_gib: float
    virtualization: str
    wsl_ready: bool
    package_verified: bool


def load_package(package_dir: Path) -> Package:
    manifest = package_dir / "core-package.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError("Pacote da VM ausente ou manifesto inválido.") from exc
    if raw.get("schema_version") != 1 or raw.get("analysis_health_contract") != "l3_ocr_b4_roi_v1":
        raise SetupError("Este pacote ainda não comprova L3, OCR e B4 na VM.")
    name = raw.get("distro_name", "")
    filename = raw.get("rootfs_file", "")
    digest = raw.get("sha256", "")
    if not DISTRO_PATTERN.fullmatch(name) or filename != f"{name}.tar" or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SetupError("Identidade ou hash da VM inválidos no manifesto.")
    if not isinstance(raw.get("version"), str) or not raw["version"]:
        raise SetupError("Versão da VM ausente no manifesto.")
    return Package(name, package_dir / filename, digest, raw["version"])


def verify_package(package: Package) -> None:
    try:
        with package.rootfs.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
    except OSError as exc:
        raise SetupError("Arquivo da VM ausente ou ilegível.") from exc
    if digest != package.sha256:
        raise SetupError("O arquivo da VM não passou na verificação SHA-256.")


def default_run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, errors="replace", capture_output=True, timeout=timeout, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def probe_host_core(package: Package, log: Path) -> bool:
    """Prove that the Windows application can reach the WSL service over local IP."""
    from hm45_vm_client import VMCore
    core = VMCore(package.distro, log)
    try:
        return core.ready.get("version") == package.version
    finally:
        core.close()


def _gib(value: int) -> float:
    return round(value / 1024**3, 1)


def memory_bytes() -> int:
    if sys.platform != "win32":
        return 0
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise SetupError("Não foi possível medir a memória do PC.")
    return status.ullTotalPhys


def distro_names(run: Callable = default_run) -> set[str]:
    result = run(["wsl.exe", "--list", "--quiet"])
    if result.returncode != 0:
        raise SetupError("Não foi possível consultar as distribuições WSL.")
    return {line.strip().replace("\x00", "") for line in result.stdout.splitlines() if line.strip()}


class CoreInstaller:
    def __init__(self, package_dir: Path, install_dir: Path, app_exe: Path,
                 run: Callable = default_run, memory: Callable = memory_bytes,
                 build: Callable = lambda: sys.getwindowsversion().build,
                 host_probe: Callable[[Package, Path], bool] = probe_host_core):
        self.package_dir = package_dir
        self.install_dir = install_dir
        self.app_exe = app_exe
        self.run = run
        self.memory = memory
        self.build = build
        self.host_probe = host_probe
        self.last_health_error = None
        self.package = load_package(package_dir)

    def _call(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        try:
            return self.run(args, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SetupError(f"Falha ao executar {args[0]}.") from exc

    def preflight(self, report: Callable[[str], None]) -> Preflight:
        if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise SetupError("É necessário Windows x64.")
        build = self.build()
        if build < 19041:
            raise SetupError("É necessário Windows 10 versão 2004 (build 19041) ou mais recente.")
        report(f"Windows x64: build {build}")
        try:
            package_size = self.package.rootfs.stat().st_size
        except OSError as exc:
            raise SetupError("Arquivo da VM ausente ou ilegível.") from exc
        free = shutil.disk_usage(self.install_dir.parent).free
        required = max(2 * 1024**3, package_size * 3)
        if free < required:
            raise SetupError(f"Espaço insuficiente: {_gib(free)} GiB livres; são necessários {_gib(required)} GiB.")
        report(f"Espaço livre: {_gib(free)} GiB")
        mem = self.memory()
        report(f"Memória física: {_gib(mem)} GiB")
        if mem < 4 * 1024**3:
            raise SetupError("São necessários pelo menos 4 GiB de RAM para este laboratório.")
        if mem < 8 * 1024**3:
            report("Abaixo de 8 GiB: o perfil leve será recomendado.")
        cpu = self._call(["powershell.exe", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty VirtualizationFirmwareEnabled)"], 30)
        virtualization = cpu.stdout.strip().lower()
        if cpu.returncode == 0 and virtualization == "false":
            raise SetupError("A virtualização de hardware está desativada no firmware do PC.")
        virt = "ativa" if virtualization == "true" else "não confirmada; o WSL fará a verificação final"
        report(f"Virtualização: {virt}")
        report("Conferindo integridade da VM incluída no instalador…")
        verify_package(self.package)
        report("Integridade SHA-256: OK")
        status = self._call(["wsl.exe", "--status"], 30)
        ready = status.returncode == 0
        report("WSL: responde; WSL 2 será validado na importação" if ready else
               "WSL 2: precisa ser habilitado")
        return Preflight(build, _gib(free), _gib(mem), virt, ready, True)

    def enable_wsl(self, report: Callable[[str], None]) -> bool:
        report("O Windows solicitará permissão de administrador para habilitar o WSL 2.")
        # Keep the installer in the original user's context. Only feature enablement is elevated.
        command = ("try { $p=Start-Process -FilePath 'wsl.exe' "
                   "-ArgumentList @('--install','--no-distribution') "
                   "-Verb RunAs -Wait -PassThru -ErrorAction Stop; "
                   "if ($null -eq $p) { exit 1 }; exit $p.ExitCode } catch { exit 1 }")
        result = self._call(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-Command", command], 600)
        if result.returncode not in (0, 3010, 1641):
            raise SetupError("O WSL 2 não foi habilitado. Confira a janela de permissão do Windows.")
        if result.returncode == 0 and self._call(["wsl.exe", "--status"], 30).returncode == 0:
            report("WSL 2 habilitado sem necessidade de reinício.")
            return True
        self.register_resume()
        report("O Windows precisa reiniciar. O assistente continuará após o próximo login.")
        return False

    def register_resume(self) -> None:
        import winreg
        command = subprocess.list2cmdline([str(self.app_exe), "--setup-assistant", "--resume-core"])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\RunOnce") as key:
            winreg.SetValueEx(key, RUNONCE_NAME, 0, winreg.REG_SZ, command)

    def clear_resume(self) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\RunOnce", 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUNONCE_NAME)
        except FileNotFoundError:
            pass

    def health(self) -> bool:
        result = self._call(["wsl.exe", "--distribution", self.package.distro,
                             "--exec", HEALTH_EXEC, "--version", self.package.version], 120)
        if result.returncode != 0 or "AGENTETFT_CORE_HEALTH_OK" not in result.stdout:
            self.last_health_error = "O teste L3/OCR/HP/B4 na VM falhou."
            return False
        try:
            if not self.host_probe(self.package, self.install_dir / "vm-host-probe.log"):
                self.last_health_error = "A conexão IP local entre Windows e VM não respondeu."
                return False
        except Exception as exc:
            self.last_health_error = f"A conexão IP local entre Windows e VM falhou: {exc}"
            return False
        self.last_health_error = None
        return True

    def install(self, report: Callable[[str], None]) -> str:
        package = self.package
        verify_package(package)
        names = distro_names(self.run)
        if package.distro in names:
            report(f"VM {package.distro} já existe; verificando saúde.")
            if not self.health():
                raise SetupError("A VM existente falhou no teste de saúde. Ela foi preservada para diagnóstico. " +
                                 str(self.last_health_error or ""))
            self.clear_resume()
            return "ready"
        target = self.install_dir / "distros" / package.distro
        if target.exists() and any(target.iterdir()):
            raise SetupError("Pasta de VM existente sem registro no WSL; preservada para diagnóstico.")
        target.mkdir(parents=True, exist_ok=True)
        report(f"Importando {package.distro} no WSL 2. Isso pode levar alguns minutos.")
        imported = self._call(["wsl.exe", "--import", package.distro, str(target),
                               str(package.rootfs), "--version", "2"], 1200)
        if imported.returncode != 0:
            raise SetupError("A importação da VM falhou. Consulte o log; nenhum outro WSL foi alterado.")
        report("Testando versão, modelo, catálogo e conexão IP Windows–VM…")
        if not self.health():
            raise SetupError("A VM foi importada, mas falhou no teste completo de análise. Ela foi preservada. " +
                             str(self.last_health_error or ""))
        self.clear_resume()
        report("VM validada e pronta para o Agente TFT.")
        return "ready"
