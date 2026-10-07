"""Build the guided HM4.5 installer from a verified guest package.

The existing HM4 release builder is intentionally separate. This script refuses
to package a guest without the full ROI/L3/OCR/B4 health contract.
"""

from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
if os.name != "nt":
    raise SystemExit("Windows build host required")
app = ROOT / "dist/AgenteTFT-HUD-HM4-Auto/AgenteTFT-HUD-HM4-Auto.exe"
core = ROOT / "build/hm45-core"
manifest_path = core / "core-package.json"
if not app.is_file() or not manifest_path.is_file():
    raise SystemExit("HM4 app or HM4.5 core package missing")
app_manifest = json.loads((app.parent / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
if (app_manifest.get("offline_voice_options") != [] or
        app_manifest.get("voice_backend") != "elevenlabs_api" or
        app_manifest.get("local_tts_models_bundled") is not False):
    raise SystemExit("HM4.5 requires API voice without local TTS models")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assets = json.loads((ROOT / "build/hm4-live-assets/ASSET_REPORT.json").read_text(encoding="utf-8"))
if (manifest.get("schema_version") != 1 or
        manifest.get("distro_name") != "AgenteTFT-Core-v2" or
        manifest.get("rootfs_file") != "AgenteTFT-Core-v2.tar" or
        manifest.get("analysis_health_contract") != "l3_ocr_b4_roi_v1" or
        manifest.get("linux_container_self_test") is not True or
        manifest.get("neural_location") != "local_inference_server_training" or
        manifest.get("local_neural_weights_bundled") is not True or
        manifest.get("post_session_trainer_bundled") is not False or
        manifest.get("model_sha256") != assets.get("model_sha256") or
        manifest.get("board_reference_sha256") != assets.get("reference_sha256")):
    raise SystemExit("Refusing unverified HM4.5 core manifest")
rootfs = core / manifest["rootfs_file"]
if not rootfs.is_file():
    raise SystemExit("HM4.5 core rootfs missing")
with rootfs.open("rb") as package_file:
    actual_sha256 = hashlib.file_digest(package_file, "sha256").hexdigest()
if actual_sha256 != manifest.get("sha256"):
    raise SystemExit("HM4.5 core SHA-256 mismatch")
with tarfile.open(rootfs, "r") as archive:
    members = {member.name.lstrip("./") for member in archive.getmembers()}
required_members = {
    "opt/agente-tft/bin/health-check",
    "opt/agente-tft/bin/agente-tft-e1-worker",
    "opt/agente-tft/bin/agente-tft-hm-hp",
    "opt/agente-tft/models/deployment-candidate.json",
    "opt/agente-tft/models/candidate-model.onnx",
}
missing_members = sorted(required_members - members)
if missing_members:
    raise SystemExit(f"HM4.5 local helper members missing: {missing_members}")
for forbidden in (
    "opt/agente-tft/learner/selection.json",
    "opt/agente-tft/bin/train-classifier",
    "opt/agente-tft/bin/adjudicate-autonomous-gold",
    "opt/agente-tft/bin/propagate-autonomous-anchors",
):
    if forbidden in members:
        raise SystemExit(f"HM4.5 local package unexpectedly contains neural learner: {forbidden}")

source = ROOT / "scripts/hm45_installer/AgenteTFT_HM45.iss"
destination = ROOT / "build/HM45.iss"
shutil.copy2(source, destination)
iscc = next((path for path in (
    Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
    Path("C:/Program Files/Inno Setup 6/ISCC.exe")) if path.is_file()), None)
if iscc is None:
    raise SystemExit("Inno Setup 6 unavailable")
subprocess.run([str(iscc), str(destination)], cwd=ROOT, check=True)
setup = ROOT / "dist/AgenteTFT-HM45-Setup.exe"
report = {
    "installer_sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
    "installer_bytes": setup.stat().st_size,
    "rootfs_sha256": manifest["sha256"],
    "rootfs_bytes": rootfs.stat().st_size,
    "guest_contract": manifest["analysis_health_contract"],
    "neural_location": "local_inference_server_training",
    "local_neural_weights_bundled": True,
    "post_session_trainer_bundled": False,
    "central_learning_server": "BigBANANA",
    "offline_voice_options": [],
    "voice_backend": "elevenlabs_api",
    "release_ready": False,
    "reason": "Requires a real Windows/WSL2 field test before publication",
}
(ROOT / "dist/HM45_INSTALLER_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report), flush=True)
