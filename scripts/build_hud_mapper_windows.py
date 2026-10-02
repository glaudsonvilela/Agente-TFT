"""Portable HUD Mapper build, using E1 native/media dependencies without system installation."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
root=Path(__file__).resolve().parents[1]
if os.name!='nt':raise SystemExit('Windows build host required')
# Same explicit media staging contract as E1; do not build an unrelated second package.
stage=root/'build/hud-tools'
(stage/'ffmpeg').mkdir(parents=True,exist_ok=False)
(stage/'tesseract/tessdata').mkdir(parents=True,exist_ok=False)
ff=next((p for p in sorted(Path('C:/ProgramData/chocolatey/lib/ffmpeg').rglob('ffmpeg.exe')) if p.with_name('ffprobe.exe').is_file()),None)
tess=Path('C:/Program Files/Tesseract-OCR')
if ff is None or not (tess/'tesseract.exe').is_file():raise SystemExit('Media dependencies unavailable')
for name in ('ffmpeg.exe','ffprobe.exe'):shutil.copy2(ff.parent/name,stage/'ffmpeg'/name)
for p in ff.parent.glob('*.dll'):shutil.copy2(p,stage/'ffmpeg'/p.name)
shutil.copy2(tess/'tesseract.exe',stage/'tesseract/tesseract.exe')
for p in tess.glob('*.dll'):shutil.copy2(p,stage/'tesseract'/p.name)
for name in ('eng.traineddata','osd.traineddata'):shutil.copy2(tess/'tessdata'/name,stage/'tesseract/tessdata'/name)
for name in ('configs','tessconfigs'):
    if (tess/'tessdata'/name).is_dir():shutil.copytree(tess/'tessdata'/name,stage/'tesseract/tessdata'/name)
worker=root/'tools/e1-native/target/release/agente-tft-e1-worker.exe'
hp=root/'tools/hm-hp-native/target/release/agente-tft-hm-hp.exe'
args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','AgenteTFT-HUD',
 '--paths',str(root/'apps/e1_replay'),'--paths',str(root/'apps/hud_mapper'),
 '--paths',str(root/'experiments/ui-map-lite-l2/training'),
 '--distpath',str(root/'dist'),'--workpath',str(root/'build/hud-mapper'),'--specpath',str(root/'build'),
 '--add-data',f'{root/"configs"};configs','--add-binary',f'{worker};bin','--add-binary',f'{hp};bin',
 '--add-data',f'{stage/"ffmpeg"};ffmpeg','--add-data',f'{stage/"tesseract"};tesseract',
 '--collect-binaries','onnxruntime','--collect-data','onnxruntime','--collect-binaries','onnx','--collect-data','onnx',
 str(root/'apps/hud_mapper/AgenteTFT_HUD.py')]
subprocess.run(args,check=True)
folder=root/'dist/AgenteTFT-HUD'
shutil.copy(root/'docs/HUD_MAPPER_HM1.md',folder/'LEIA-ME.md')
license_dir=folder/'THIRD_PARTY';license_dir.mkdir()
for source in (ff.parent.parent,tess):
    for p in source.rglob('*'):
        if p.is_file() and any(v in p.name.lower() for v in ('license','copying','copyright')) and p.stat().st_size<1024**2:
            shutil.copy2(p,license_dir/(source.name+'-'+p.name))
# Main and offline trainer share a private directory, but torch is imported ONLY by --train.
fonts=[p for p in folder.rglob('*') if p.suffix.lower() in {'.ttf','.otf','.woff','.woff2','.fon','.fnt','.pfb','.pfa','.ttc'}]
if fonts:raise SystemExit('Font assets found; refuse publication')
files={str(p.relative_to(folder)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
(folder/'BUILD_MANIFEST.json').write_text(json.dumps(dict(commit=os.environ.get('GITHUB_SHA'),files=files,signed=False,
 primary_objective='HUD_mapping_and_natural_training',mode='closed_local_replay',user_weights_included=False,
 training_is_separate_process=True,torch_imported_on_mapping_path=False,font_files_bundled=False,
 dependency_freeze=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True)),indent=2),encoding='utf-8')
shutil.make_archive(str(root/'dist/AgenteTFT-HUD-Mapper-Windows-x64'),'zip',folder.parent,folder.name)
