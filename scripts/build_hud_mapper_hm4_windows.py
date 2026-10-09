"""Build compact HM4 Auto: simple source selection, automatic output/model discovery."""
from pathlib import Path
import hashlib, importlib.metadata, json, os, shutil, subprocess, sys, zipfile
from prepare_tessdata_best import MODEL_SHA256, prepare as prepare_ocr_model

root = Path(__file__).resolve().parents[1]
if os.name != 'nt':
    raise SystemExit('Windows build host required')
live_assets = root / 'build/hm4-live-assets'
asset_report = json.loads((live_assets / 'ASSET_REPORT.json').read_text(encoding='utf-8'))
if asset_report.get('model_mode') != 'shadow_diagnostic' or asset_report.get('matching_item_entries', 0) < 100:
    raise SystemExit('Replay-screen assets were not verified')
live_plan = json.loads((root / 'configs/catalog/active-visual-reference-v1.json').read_text(encoding='utf-8'))
reference = root / live_plan['reference']
knowledge_plan = json.loads((root / 'configs/catalog/active-knowledge-release-v1.json').read_text(encoding='utf-8'))
knowledge_reference = root / knowledge_plan['reference']

stage = root / 'build/hm4-tools'
stage.mkdir(parents=True, exist_ok=False)

tess = Path('C:/Program Files/Tesseract-OCR')
if not (tess / 'tesseract.exe').is_file():
    raise SystemExit('Tesseract unavailable')
td = stage / 'tesseract'
(td / 'tessdata').mkdir(parents=True)
ocr_model = prepare_ocr_model()
shutil.copy2(tess / 'tesseract.exe', td / 'tesseract.exe')
for p in tess.glob('*.dll'):
    shutil.copy2(p, td / p.name)
shutil.copy2(ocr_model / 'eng.traineddata', td / 'tessdata/eng.traineddata')
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
item_native = root / 'tools/hm-item-native/target/release/agente_tft_hm_item_native.dll'
if not item_native.is_file():
    subprocess.run(['cargo', 'build', '--release', '--manifest-path',
                    str(root / 'tools/hm-item-native/Cargo.toml')], check=True)
if not item_native.is_file():
    raise SystemExit('Native item gallery build did not produce its DLL')

dist = root / 'dist'
dist.mkdir(exist_ok=True)
folder = dist / 'AgenteTFT-HUD-HM4-Auto'
args = [
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'AgenteTFT-HUD-HM4-Auto',
    '--icon', str(root / 'ui/tauri-design/icons/icon.ico'),
    '--paths', str(root / 'apps/e1_replay'),
    '--paths', str(root / 'apps/hud_mapper'),
    '--paths', str(root),
    '--distpath', str(dist),
    '--workpath', str(root / 'build/hm4-runtime'),
    '--specpath', str(root / 'build'),
    '--add-data', f'{root / "configs"};configs',
    '--add-data', f'{root / "apps/hud_mapper/assets"};assets',
    '--add-data', f'{root / "ui/tauri-design"};ui/tauri-design',
    '--add-data', f'{reference};{live_plan["reference"]}',
    '--add-data', f'{knowledge_reference};{knowledge_plan["reference"]}',
    '--add-data', f'{live_assets / "models"};models',
    '--add-data', f'{live_assets / live_plan["icon_dir"]};{live_plan["icon_dir"]}',
    '--add-data', f'{td};tesseract',
    '--collect-binaries', 'onnxruntime', '--collect-data', 'onnxruntime',
    '--collect-binaries', 'onnx', '--collect-data', 'onnx',
    '--collect-submodules', 'jaraco', '--collect-data', 'jaraco.text',
    '--hidden-import', 'jaraco.context', '--hidden-import', 'jaraco.functools',
    '--hidden-import', 'more_itertools',
    '--hidden-import', 'hm.board_hub_live',
    '--hidden-import', 'hm.item_visual_native',
    '--hidden-import', 'hm.item_movement',
    '--hidden-import', 'hm.temporal_candidates',
    '--hidden-import', 'hm.replay_coach',
    '--hidden-import', 'hm.replay_decision',
    '--hidden-import', 'hm.match_identity',
    '--hidden-import', 'hm.voice',
    '--hidden-import', 'hm45_setup',
    '--hidden-import', 'hm45_setup_web',
    '--hidden-import', 'browser_shell',
    '--hidden-import', 'hm45_setup_core',
    '--hidden-import', 'hm45_vm_client',
    '--hidden-import', 'hm45_protocol',
    '--hidden-import', 'hm.vm_bridge',
    '--hidden-import', 'hm.learning_capture',
    '--hidden-import', 'hm.post_session_learning',
    '--hidden-import', 'hm.neural_service',
    '--hidden-import', 'hm.model_update',
    '--hidden-import', 'hm.unit_head',
    '--hidden-import', 'hm.studio_bridge',
]
for worker in workers:
    args += ['--add-binary', f'{worker};bin']
args += ['--add-binary', f'{item_native};bin']
for module in ('torch', 'torchvision', 'torchaudio', 'sherpa_onnx', 'sherpa_onnx_core', 'supertonic', 'hm.train', 'hm.seeds',
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
shutil.copy2(ocr_model / 'LICENSE', licenses / 'tessdata_best-LICENSE')
for p in tess.rglob('*'):
    if p.is_file() and p.stat().st_size < 1024**2 and any(n in p.name.lower() for n in ('license', 'copying', 'copyright')):
        shutil.copy2(p, licenses / ('tesseract-' + '-'.join(p.relative_to(tess).parts)))
for package in ('numpy', 'Pillow', 'onnxruntime', 'onnx', 'protobuf', 'jaraco.text', 'jaraco.context', 'jaraco.functools'):
    distribution = importlib.metadata.distribution(package)
    for name in distribution.files or []:
        if any(n in str(name).lower() for n in ('license', 'copying', 'copyright')):
            p = Path(distribution.locate_file(name))
            if p.is_file() and p.stat().st_size < 1024**2:
                shutil.copy2(p, licenses / (package + '-' + str(name).replace('/', '-').replace('\\', '-')))
forbidden = ('ffmpeg', 'ffprobe', 'torch', 'libtorch', 'torchvision', 'torchaudio', 'cuda', 'cudnn', 'sherpa', 'supertonic', 'espeak', 'voice_styles')
bad = [str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and any(x in p.relative_to(folder).as_posix().lower() for x in forbidden)]
fonts = [str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in {'.ttf', '.otf', '.woff', '.woff2', '.fon', '.fnt', '.pfb', '.pfa', '.ttc'}
         and not p.relative_to(folder).as_posix().startswith('_internal/ui/tauri-design/assets/manrope-')]
if bad or fonts:
    raise SystemExit(f'Refuse runtime publication: forbidden={bad[:20]}, fonts={fonts[:20]}')

files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in folder.rglob('*') if p.is_file()}
bundled_ocr = [name for name in files if name.endswith('/tessdata/eng.traineddata')]
traineddata = [name for name in files if '/tessdata/' in name and name.endswith('.traineddata')]
if len(bundled_ocr) != 1 or traineddata != bundled_ocr or files[bundled_ocr[0]] != MODEL_SHA256:
    raise SystemExit(f'Expected exactly one verified tessdata_best English model: {bundled_ocr}')
manifest = dict(
    schema_version=1,
    commit=os.environ.get('GITHUB_SHA'),
    primary_objective='live_and_replay_screen_capture_local_coaching_and_post_match_learning',
    runtime_only=True,
    automatic_model_discovery=True,
    reader_only_fallback=True,
    manual_model_selection=False,
    replay_in_runtime=False,
    ffmpeg_bundled=False,
    pytorch_bundled=False,
    trainer_bundled=False,
    shadow_learning_capture_bundled=True,
    post_session_learning_job_bundled=True,
    post_session_linux_trainer_bundled=False,
    central_learning_server='BigBANANA',
    zero_click_model_updates=True,
    model_update_user_confirmation_required=False,
    model_update_activate_during_match=False,
    capture='resident_Rust_WGC_D3D11',
    neural='local_inference_server_training',
    ocr='Tesseract_tessdata_best_eng',
    ocr_model_sha256=MODEL_SHA256,
    model_weights_included=True,
    model_sha256=asset_report['model_sha256'],
    board_hub_reference_sha256=asset_report['reference_sha256'],
    board_hub_candidate_only=True,
    replay_screen_review_prompts=True,
    offline_voice_options=[],
    voice_backend='elevenlabs_api',
    voice_narration_paused=True,
    voice_service_configured=bool(json.loads((root / 'configs/services/voice.json').read_text())['service_url']),
    voice_api_credentials_bundled=False,
    local_tts_models_bundled=False,
    live_strategy_enabled=True,
    live_strategy_mode='lab_bundled_patch_provenance',
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

exe = folder / 'AgenteTFT-HUD-HM4-Auto.exe'
report = dict(
    runtime_uncompressed_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
    zip_bytes=zip_path.stat().st_size,
    zip_sha256=hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
    clr_free_local_ui=True,
    vm_installer_built_separately=True,
    ffmpeg_bundled=False,
    pytorch_bundled=False,
    trainer_bundled=False,
    central_learning_server='BigBANANA',
    model_sha256=asset_report['model_sha256'],
    board_hub_reference_sha256=asset_report['reference_sha256'],
    compaction_removed_bytes=compaction['removed_bytes'],
    compaction_removed_files=len(compaction['removed_files']),
)
(dist / 'HM4_PACKAGE_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('HM4_PACKAGE=' + json.dumps(report), flush=True)
