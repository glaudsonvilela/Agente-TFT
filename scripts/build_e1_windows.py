"""Build a portable Windows directory. Run only in Windows CI; no user installation."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys

root=Path(__file__).resolve().parents[1]
if os.name!='nt':raise SystemExit('Windows build host required')
worker=root/'tools/e1-native/target/release/agente-tft-e1-worker.exe'
# Use the actual tool files, not a Chocolatey shim pointing into the build host.
candidates=sorted(Path('C:/ProgramData/chocolatey/lib/ffmpeg').rglob('ffmpeg.exe'))
candidates=[p for p in candidates if p.with_name('ffprobe.exe').is_file()]
if not candidates:raise SystemExit('FFmpeg/ffprobe installation files unavailable')
ff=candidates[0]
tess=Path('C:/Program Files/Tesseract-OCR')
if not (tess/'tesseract.exe').is_file():raise SystemExit('Tesseract install not found')
stage=root/'build/e1-tools'
(stage/'ffmpeg').mkdir(parents=True,exist_ok=False)
(stage/'tesseract/tessdata').mkdir(parents=True,exist_ok=False)
for name in ('ffmpeg.exe','ffprobe.exe'):
    shutil.copy2(ff.parent/name,stage/'ffmpeg'/name)
for p in ff.parent.glob('*.dll'):shutil.copy2(p,stage/'ffmpeg'/p.name)
shutil.copy2(tess/'tesseract.exe',stage/'tesseract/tesseract.exe')
for p in tess.glob('*.dll'):shutil.copy2(p,stage/'tesseract'/p.name)
for name in ('eng.traineddata','osd.traineddata'):
    shutil.copy2(tess/'tessdata'/name,stage/'tesseract/tessdata'/name)
for name in ('configs','tessconfigs'):
    if (tess/'tessdata'/name).is_dir():
        shutil.copytree(tess/'tessdata'/name,stage/'tesseract/tessdata'/name)
# Only executable OCR/video requirements: no font files, ffplay or uninstaller.
args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','AgenteTFT-E1',
      '--paths',str(root/'apps/e1_replay'),'--distpath',str(root/'dist'),'--workpath',str(root/'build/e1'),
      '--specpath',str(root/'build'),'--add-data',f'{root/"configs"};configs',
      '--add-binary',f'{worker};bin','--add-data',f'{stage/"ffmpeg"};ffmpeg',
      '--add-data',f'{stage/"tesseract"};tesseract','--collect-all','onnxruntime',str(root/'apps/e1_replay/AgenteTFT_E1.py')]
subprocess.run(args,check=True)
folder=root/'dist/AgenteTFT-E1'
shutil.copy(root/'docs/E1_REPLAY_LAB.md',folder/'LEIA-ME.md')
license_dir=folder/'THIRD_PARTY';license_dir.mkdir()
for source in [ff.parent.parent,tess]:
    for p in source.rglob('*'):
        if p.is_file() and any(s in p.name.lower() for s in ('license','copying','copyright')) and p.stat().st_size<1024**2:
            shutil.copy(p,license_dir/(source.name+'-'+p.name))
# Verify the final distribution too, not just the staged dependencies.
font_suffixes={'.ttf','.otf','.woff','.woff2','.fon','.fnt','.pfb','.pfa','.ttc'}
fonts=[p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in font_suffixes]
if fonts:raise SystemExit('Unexpected font assets in distribution; do not publish')
files={str(p.relative_to(folder)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in folder.rglob('*') if p.is_file()}
(folder/'BUILD_MANIFEST.json').write_text(json.dumps({'commit':os.environ.get('GITHUB_SHA'),'files':files,
  'signed':False,'tft_or_vanguard_tested':False,'mode':'closed-file-replay-and-fixtures',
  'font_files_bundled':False,'ffplay_bundled':False,
  'python':sys.version,'dependency_freeze':subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True)},indent=2),encoding='utf-8')
shutil.make_archive(str(root/'dist/AgenteTFT-E1-Windows-x64'),'zip',folder.parent,folder.name)
