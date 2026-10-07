"""Fetch Microsoft's signed Evergreen WebView2 bootstrapper for Windows packages."""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
from urllib.parse import urlparse
from urllib.request import urlopen


URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
DESTINATION = Path(__file__).resolve().parents[1] / "build" / "hm45-webview2" / "MicrosoftEdgeWebview2Setup.exe"


def prepare() -> Path:
    if os.name != "nt":
        raise RuntimeError("O bootstrapper WebView2 deve ser verificado no Windows.")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if not DESTINATION.is_file():
        with urlopen(URL, timeout=45) as response:
            host = urlparse(response.url).hostname or ""
            if not (host == "microsoft.com" or host.endswith(".microsoft.com")):
                raise RuntimeError("O download do WebView2 saiu do domínio Microsoft.")
            payload = response.read(8 * 1024 * 1024 + 1)
        if not 100_000 < len(payload) < 8 * 1024 * 1024:
            raise RuntimeError("Tamanho inesperado do bootstrapper WebView2.")
        DESTINATION.write_bytes(payload)
    if not 100_000 < DESTINATION.stat().st_size < 8 * 1024 * 1024:
        raise RuntimeError("Bootstrapper WebView2 ausente ou incompleto.")
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:AGENTE_TFT_WEBVIEW2_BOOTSTRAPPER; "
        "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { exit 1 }"
    )
    shell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if shell is None:
        raise RuntimeError("PowerShell indisponível para verificar a assinatura WebView2.")
    subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command],
                   env={**os.environ, "AGENTE_TFT_WEBVIEW2_BOOTSTRAPPER": str(DESTINATION)},
                   check=True)
    return DESTINATION


if __name__ == "__main__":
    print(prepare())
