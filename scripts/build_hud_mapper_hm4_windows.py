"""Build compact HM4 Auto: simple source selection, automatic output/model discovery."""
from pathlib import Path
import hashlib, importlib.metadata, json, os, shutil, subprocess, sys, zipfile

root = Path(__file__).resolve().parents[1]
if os.name != 'nt':
    raise SystemExit('Windows build host required')
live_assets = root / 'build/hm4-live-assets'
voice_assets = root / 'build/hm45-voice-assets'
has_voices = (voice_assets / 'VOICE_REPORT.json').is_file()
asset_report = json.loads((live_assets / 'ASSET_REPORT.json').read_text(encoding='utf-8'))
if asset_report.get('model_mode') != 'shadow_diagnostic' or asset_report.get('matching_item_entries', 0) < 100:
    raise SystemExit('Replay-screen assets were not verified')
live_plan = json.loads((root / 'configs/ui/board-hub-live-v1.json').read_text(encoding='utf-8'))
reference = root / live_plan['reference']

stage = root / 'build/hm4-tools'
stage.mkdir(parents=True, exist_ok=False)

tess = Path('C:/Program Files/Tesseract-OCR')
if not (tess / 'tesseract.exe').is_file():
    raise SystemExit('Tesseract unavailable')
td = stage / 'tesseract'
(td / 'tessdata').mkdir(parents=True)
shutil.copy2(tess / 'tesseract.exe', td / 'tesseract.exe')
for p in tess.glob('*.dll'):
    shutil.copy2(p, td / p.name)
for name in ('eng.traineddata', 'osd.traineddata'):
    shutil.copy2(tess / 'tessdata' / name, td / 'tessdata' / name)
for name in ('configs', 'tessconfigs'):
    if (tess / 'tessdata' / name).is_dir():
        shutil.copytree(tess / 'tessdata' / name, td / 'tessdata' / name)

workers = [
    root / 'tools/e1-native/target/release/agente-tft-e1-worker.exe',
    root / 'tools/hm-hp-native/target/release/agente-tft-hm-hp.exe',
    root / 'tools/hm-capture-native/target/release/agente-tft-hm-capture.exe',
]
if any(not p.is_file() for p in workers):
    raise SystemExit('Native HM4 binaries missing')

dist = root / 'dist'
dist.mkdir(exist_ok=True)
folder = dist / 'AgenteTFT-HUD-HM4-Auto'
args = [
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'AgenteTFT-HUD-HM4-Auto',
    '--paths', str(root / 'apps/e1_replay'),
    '--paths', str(root / 'apps/hud_mapper'),
    '--paths', str(root),
    '--distpath', str(dist),
    '--workpath', str(root / 'build/hm4-runtime'),
    '--specpath', str(root / 'build'),
    '--add-data', f'{root / "configs"};configs',
    '--add-data', f'{root / "apps/hud_mapper/assets"};assets',
    '--add-data', f'{reference};{live_plan["reference"]}',
    '--add-data', f'{live_assets / "models"};models',
    '--add-data', f'{live_assets / live_plan["icon_dir"]};{live_plan["icon_dir"]}',
    '--add-data', f'{td};tesseract',
    '--collect-binaries', 'onnxruntime', '--collect-data', 'onnxruntime',
    '--collect-binaries', 'onnx', '--collect-data', 'onnx',
    '--collect-submodules', 'jaraco', '--collect-data', 'jaraco.text',
    '--hidden-import', 'jaraco.context', '--hidden-import', 'jaraco.functools',
    '--hidden-import', 'more_itertools',
    '--hidden-import', 'hm.board_hub_live',
    '--hidden-import', 'hm.replay_coach',
    '--hidden-import', 'hm.voice',
    '--hidden-import', 'hm45_setup',
    '--hidden-import', 'hm45_setup_core',
    '--hidden-import', 'hm45_vm_client',
    '--hidden-import', 'hm45_protocol',
    '--hidden-import', 'hm.vm_bridge',
]
if has_voices:
    voice_report = json.loads((voice_assets / 'VOICE_REPORT.json').read_text(encoding='utf-8'))
    if set(voice_report.get('voices', {})) != {'dii', 'cadu', 'faber'}:
        raise SystemExit('All pinned pt-BR voices are required')
    args += ['--add-data', f'{voice_assets};voices', '--collect-all', 'sherpa_onnx']
for worker in workers:
    args += ['--add-binary', f'{worker};bin']
for module in ('torch', 'torchvision', 'torchaudio', 'hm.train', 'hm.seeds',
               'hm.app', 'hm.capture_app', 'e1.app', 'e1.source', 'e1.pipeline'):
    args += ['--exclude-module', module]
args += [str(root / 'apps/hud_mapper/AgenteTFT_HUD_HM4.py')]
subprocess.run(args, check=True)

from compact_hm3_payload import compact_payload
compaction = compact_payload(folder)
compaction['policy'] = 'hm4_auto_private_payload_compaction_v1'
(dist / 'HM4_COMPACTION_REPORT.json').write_text(json.dumps(compaction, indent=2), encoding='utf-8')
shutil.copy2(root / 'docs/HUD_MAPPER_HM4_AUTO.md', folder / 'LEIA-ME.md')
shutil.copy2(live_assets / 'ASSET_REPORT.json', folder / 'ASSET_REPORT.json')

licenses = folder / 'THIRD_PARTY'
licenses.mkdir()
for p in tess.rglob('*'):
    if p.is_file() and p.stat().st_size < 1024**2 and any(n in p.name.lower() for n in ('license', 'copying', 'copyright')):
        shutil.copy2(p, licenses / ('tesseract-' + '-'.join(p.relative_to(tess).parts)))
for package in ('numpy', 'Pillow', 'onnxruntime', 'onnx', 'protobuf', 'jaraco.text', 'jaraco.context', 'jaraco.functools') + (('sherpa-onnx', 'sherpa-onnx-core') if has_voices else ()):
    distribution = importlib.metadata.distribution(package)
    for name in distribution.files or []:
        if any(n in str(name).lower() for n in ('license', 'copying', 'copyright')):
            p = Path(distribution.locate_file(name))
            if p.is_file() and p.stat().st_size < 1024**2:
                shutil.copy2(p, licenses / (package + '-' + str(name).replace('/', '-').replace('\\', '-')))
if has_voices:
    for key in ('dii', 'cadu', 'faber'):
        card = 'README.md' if key == 'dii' else 'MODEL_CARD'
        shutil.copy2(voice_assets / key / card, licenses / f'voice-{key}-{card}.txt')

forbidden = ('ffmpeg', 'ffprobe', 'torch', 'libtorch', 'torchvision', 'torchaudio', 'cuda', 'cudnn')
bad = [str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and any(x in p.name.lower() for x in forbidden)]
fonts = [str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in {'.ttf', '.otf', '.woff', '.woff2', '.fon', '.fnt', '.pfb', '.pfa', '.ttc'}]
if bad or fonts:
    raise SystemExit(f'Refuse runtime publication: forbidden={bad[:20]}, fonts={fonts[:20]}')

files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in folder.rglob('*') if p.is_file()}
manifest = dict(
    schema_version=1,
    commit=os.environ.get('GITHUB_SHA'),
    primary_objective='replay_screen_capture_neural_board_hub_and_review_prompts',
    runtime_only=True,
    automatic_model_discovery=True,
    reader_only_fallback=True,
    manual_model_selection=False,
    replay_in_runtime=False,
    ffmpeg_bundled=False,
    pytorch_bundled=False,
    trainer_bundled=False,
    capture='resident_Rust_WGC_D3D11',
    neural='bundled_L3_ONNX_CPU_shadow_diagnostic',
    ocr='Tesseract_private',
    model_weights_included=True,
    model_sha256=asset_report['model_sha256'],
    board_hub_reference_sha256=asset_report['reference_sha256'],
    board_hub_candidate_only=True,
    replay_screen_review_prompts=True,
    offline_voice_options=list(voice_report['voices']) if has_voices else [],
    live_strategy_enabled=False,
    signed=False,
    files=files,
    payload_compaction=compaction,
    build_dependencies=subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True),
)
(folder / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

zip_path = dist / 'AgenteTFT-HUD-HM4-Auto-Windows-x64.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for p in sorted(folder.rglob('*')):
        if p.is_file():
            archive.write(p, Path(folder.name) / p.relative_to(folder))

iss = root / 'build/HM4.iss'
iss.write_text(r'''[Setup]
AppName=Agente TFT Replay Screen Lab
AppVersion=0.5
DefaultDirName={localappdata}\AgenteTFT-HUD-HM4
DefaultGroupName=Agente TFT
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AgenteTFT-HUD-HM4-Auto-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\AgenteTFT-HUD-HM4-Auto.exe
DisableProgramGroupPage=yes
WizardStyle=modern
[Files]
Source: "..\dist\AgenteTFT-HUD-HM4-Auto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\Agente TFT Replay Screen Lab"; Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"
[Run]
Filename: "{app}\AgenteTFT-HUD-HM4-Auto.exe"; Description: "Abrir HUD Mapper HM4 Auto"; Flags: nowait postinstall skipifsilent
''', encoding='utf-8')

iscc = next((p for p in (
    Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'),
    Path('C:/Program Files/Inno Setup 6/ISCC.exe')
) if p.is_file()), None)
if not iscc:
    raise SystemExit('Inno Setup 6 unavailable')
subprocess.run([str(iscc), str(iss)], check=True, cwd=root)

setup = dist / 'AgenteTFT-HUD-HM4-Auto-Setup.exe'
exe = folder / 'AgenteTFT-HUD-HM4-Auto.exe'
report = dict(
    runtime_uncompressed_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
    zip_bytes=zip_path.stat().st_size,
    installer_bytes=setup.stat().st_size,
    zip_sha256=hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    installer_sha256=hashlib.sha256(setup.read_bytes()).hexdigest(),
    exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
    forbidden_payloads=bad,
    font_files=fonts,
    ffmpeg_bundled=False,
    pytorch_bundled=False,
    trainer_bundled=False,
    automatic_model_discovery=True,
    reader_only_fallback=True,
    model_weights_included=True,
    model_sha256=asset_report['model_sha256'],
    board_hub_reference_sha256=asset_report['reference_sha256'],
    replay_screen_review_prompts=True,
    compaction_removed_bytes=compaction['removed_bytes'],
    compaction_removed_files=len(compaction['removed_files']),
)
(dist / 'HM4_PACKAGE_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('HM4_PACKAGE=' + json.dumps(report), flush=True)
