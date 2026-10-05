"""Build a small SHA-pinned downloader for the verified HM4.5 offline installer."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "dist/AgenteTFT-HM45-Setup.exe"
TEMPLATE = ROOT / "scripts/hm45_installer/AgenteTFT_HM45_Online.iss"
OUTPUT = ROOT / "dist/AgenteTFT-HM45-Online-Setup.exe"


def render(source: str, *, release_tag: str, sha256: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", release_tag):
        raise ValueError("Invalid release tag")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Invalid installer SHA-256")
    url = ("https://github.com/glaudsonvilela/Agente-TFT/releases/download/"
           f"{release_tag}/AgenteTFT-HM45-Setup.exe")
    expected = {"@@OFFLINE_URL@@": url, "@@OFFLINE_SHA256@@": sha256}
    for placeholder, value in expected.items():
        if source.count(placeholder) != 1:
            raise ValueError(f"Expected one {placeholder} placeholder")
        source = source.replace(placeholder, value)
    if "@@" in source:
        raise ValueError("Unresolved template placeholder")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", default="hm45-lab-0.6.4-20261004")
    args = parser.parse_args()
    if not OFFLINE.is_file():
        raise SystemExit("Build the verified offline installer first")
    with OFFLINE.open("rb") as file:
        sha256 = hashlib.file_digest(file, "sha256").hexdigest()
    report_path = ROOT / "dist/HM45_INSTALLER_REPORT.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("installer_sha256") != sha256:
            raise SystemExit("Offline installer does not match its build report")
    destination = ROOT / "build/HM45-Online.iss"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(TEMPLATE.read_text(encoding="utf-8"),
                                  release_tag=args.release_tag, sha256=sha256), encoding="utf-8")
    iscc = next((path for path in (
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe")) if path.is_file()), None)
    if iscc is None:
        raise SystemExit("Inno Setup 6 unavailable")
    subprocess.run([str(iscc), str(destination)], cwd=ROOT, check=True)
    if OUTPUT.stat().st_size > 10 * 1024**2:
        raise SystemExit("Online installer exceeds its 10 MiB size budget")
    result = {"release_tag": args.release_tag,
              "offline_url": ("https://github.com/glaudsonvilela/Agente-TFT/releases/download/"
                              f"{args.release_tag}/AgenteTFT-HM45-Setup.exe"),
              "offline_sha256": sha256,
              "online_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
              "online_bytes": OUTPUT.stat().st_size,
              "download_verified_before_launch": True}
    (ROOT / "dist/HM45_ONLINE_REPORT.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
