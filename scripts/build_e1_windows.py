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
args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','AgenteTFT-E1',
      '--paths',str(root/'apps/e1_replay'),'--distpath',str(root/'dist'),'--workpath',str(root/'build/e1'),
      '--specpath',str(root/'build'),'--add-data',f'{root/"configs"};configs',
      '--add-binary',f'{worker};bin','--add-data',f'{ff.parent};ffmpeg',
      '--add-data',f'{tess};tesseract','--collect-all','onnxruntime',str(root/'apps/e1_replay/AgenteTFT_E1.py')]
subprocess.run(args,check=True)
folder=root/'dist/AgenteTFT-E1'
shutil.copy(root/'docs/E1_REPLAY_LAB.md',folder/'LEIA-ME.md')
license_dir=folder/'THIRD_PARTY';license_dir.mkdir()
# Keep software license notices distributed with the installed tools; don't strip dependencies.
for source in [ff.parent.parent,tess]:
    for p in source.rglob('*'):
        if p.is_file() and any(s in p.name.lower() for s in ('license','copying','copyright')) and p.stat().st_size<1024**2:
            shutil.copy(p,license_dir/(source.name+'-'+p.name))
files={str(p.relative_to(folder)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in folder.rglob('*') if p.is_file()}
(folder/'BUILD_MANIFEST.json').write_text(json.dumps({'commit':os.environ.get('GITHUB_SHA'),'files':files,
  'signed':False,'tft_or_vanguard_tested':False,'mode':'closed-file-replay-and-fixtures',
  'python':sys.version,'dependency_freeze':subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True)},indent=2),encoding='utf-8')
shutil.make_archive(str(root/'dist/AgenteTFT-E1-Windows-x64'),'zip',folder.parent,folder.name)
