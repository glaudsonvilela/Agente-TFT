"""Build compact HM3: capture/ONNX/OCR only, with verified portable and installed tests."""
from pathlib import Path
import hashlib, importlib.metadata, json, os, shutil, subprocess, sys, zipfile

root = Path(__file__).resolve().parents[1]
if os.name != 'nt':
    raise SystemExit('Windows build host required')
stage = root / 'build/hm3-tools'
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
    raise SystemExit('Native HM3 binaries missing')
dist = root / 'dist'
dist.mkdir(exist_ok=True)
folder = dist / 'AgenteTFT-HUD-HM3'
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--name', 'AgenteTFT-HUD-HM3', '--paths', str(root / 'apps/e1_replay'),
        '--paths', str(root / 'apps/hud_mapper'), '--distpath', str(dist),
        '--workpath', str(root / 'build/hm3-runtime'), '--specpath', str(root / 'build'),
        '--add-data', f'{root / "configs"};configs', '--add-data', f'{td};tesseract',
        '--collect-binaries', 'onnxruntime', '--collect-data', 'onnxruntime',
        '--collect-binaries', 'onnx', '--collect-data', 'onnx',
        # Explicit small setuptools runtime dependencies. No trainer is reintroduced.
        '--collect-submodules', 'jaraco', '--collect-data', 'jaraco.text',
        '--hidden-import', 'jaraco.context', '--hidden-import', 'jaraco.functools',
        '--hidden-import', 'more_itertools']
for worker in workers:
    args += ['--add-binary', f'{worker};bin']
for module in ('torch', 'torchvision', 'torchaudio', 'hm.train', 'hm.seeds',
               'hm.app', 'hm.capture_app', 'e1.app', 'e1.source', 'e1.pipeline'):
    args += ['--exclude-module', module]
args += [str(root / 'apps/hud_mapper/AgenteTFT_HUD_Runtime.py')]
subprocess.run(args, check=True)
shutil.copy2(root / 'docs/HUD_MAPPER_HM3_RUNTIME.md', folder / 'LEIA-ME.md')
licenses = folder / 'THIRD_PARTY'
licenses.mkdir()
for p in tess.rglob('*'):
    if p.is_file() and p.stat().st_size < 1024**2 and any(n in p.name.lower() for n in ('license', 'copying', 'copyright')):
        shutil.copy2(p, licenses / ('tesseract-' + '-'.join(p.relative_to(tess).parts)))
# Preserve available dependency notices, not their entire distributions.
for package in ('numpy', 'Pillow', 'onnxruntime', 'onnx', 'protobuf', 'jaraco.text', 'jaraco.context', 'jaraco.functools'):
    distribution = importlib.metadata.distribution(package)
    for name in distribution.files or []:
        if any(n in str(name).lower() for n in ('license', 'copying', 'copyright')):
            p = Path(distribution.locate_file(name))
            if p.is_file() and p.stat().st_size < 1024**2:
                shutil.copy2(p, licenses / (package + '-' + str(name).replace('/', '-').replace('\\', '-')))
forbidden = ('ffmpeg', 'ffprobe', 'torch', 'libtorch', 'torchvision', 'torchaudio', 'cuda', 'cudnn')
bad = [str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and any(x in p.name.lower() for x in forbidden)]
fonts = [str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in {'.ttf', '.otf', '.woff', '.woff2', '.fon', '.fnt', '.pfb', '.pfa', '.ttc'}]
if bad or fonts:
    raise SystemExit(f'Refuse runtime publication: forbidden={bad[:20]}, fonts={fonts[:20]}')
files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
manifest = dict(schema_version=1, commit=os.environ.get('GITHUB_SHA'), primary_objective='live_HUD_mapping',
                runtime_only=True, replay_in_runtime=False, ffmpeg_bundled=False, pytorch_bundled=False,
                trainer_bundled=False, capture='resident_Rust_WGC_D3D11', neural='ONNX_CPU_L2_L3',
                ocr='Tesseract_private', model_weights_included=False, signed=False, files=files,
                build_dependencies=subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True))
(folder / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
zip_path = dist / 'AgenteTFT-HUD-HM3-Runtime-Windows-x64.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for p in sorted(folder.rglob('*')):
        if p.is_file():
            archive.write(p, Path(folder.name) / p.relative_to(folder))
iss = root / 'build/HM3.iss'
iss.write_text(r'''[Setup]
AppName=Agente TFT HUD Mapper HM3
AppVersion=0.3
DefaultDirName={localappdata}\AgenteTFT-HUD-HM3
DefaultGroupName=Agente TFT
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AgenteTFT-HUD-HM3-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\AgenteTFT-HUD-HM3.exe
DisableProgramGroupPage=yes
WizardStyle=modern
[Files]
Source: "..\dist\AgenteTFT-HUD-HM3\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\Agente TFT HUD Mapper HM3"; Filename: "{app}\AgenteTFT-HUD-HM3.exe"
[Run]
Filename: "{app}\AgenteTFT-HUD-HM3.exe"; Description: "Abrir HUD Mapper HM3"; Flags: nowait postinstall skipifsilent
''', encoding='utf-8')
iscc = next((p for p in (Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'), Path('C:/Program Files/Inno Setup 6/ISCC.exe')) if p.is_file()), None)
if not iscc:
    raise SystemExit('Inno Setup 6 unavailable')
subprocess.run([str(iscc), str(iss)], check=True, cwd=root)
setup = dist / 'AgenteTFT-HUD-HM3-Setup.exe'
report = dict(runtime_uncompressed_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
              zip_bytes=zip_path.stat().st_size, installer_bytes=setup.stat().st_size,
              zip_sha256=hashlib.sha256(zip_path.read_bytes()).hexdigest(),
              installer_sha256=hashlib.sha256(setup.read_bytes()).hexdigest(),
              exe_sha256=hashlib.sha256((folder / 'AgenteTFT-HUD-HM3.exe').read_bytes()).hexdigest(),
              forbidden_payloads=bad, font_files=fonts, ffmpeg_bundled=False, pytorch_bundled=False, trainer_bundled=False)
(dist / 'HM3_PACKAGE_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('HM3_PACKAGE=' + json.dumps(report), flush=True)
