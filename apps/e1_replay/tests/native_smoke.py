"""Run against the compiled worker and real Tesseract/FFmpeg, no inferred game labels."""
import argparse,json,os,subprocess,sys,tempfile,time
from pathlib import Path
from e1.app import default_paths
from e1.protocol import NativeWorker
from e1.pipeline import Options,Session
from PIL import Image,ImageDraw,ImageFont
import queue


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    paths=default_paths()
    worker=NativeWorker(paths['worker'],paths['configs'],paths['tesseract'])
    try:
        assert worker.ready['ocr_available'], 'real Tesseract required'
        cases=[worker.request(dict(op='fixture',id=i,source_ms=i*1000,case=i)) for i in range(4)]
        assert all(r['origin']=='fixture_input' for r in cases)
        assert any(r['decision']['action']['type']!='wait' for r in cases)
        assert len(cases[1]['report']['all'])>1
        # True pixel pipeline: black source does NOT supply hidden known game values.
        raw=bytes(1920*1080*3)
        r=worker.request(dict(op='frame',id=100,source_ms=1234,width=1920,height=1080,bytes=len(raw)),raw)
        assert r['origin']=='observed_pixels' and r['resolution_compatible']
        assert len(r['hud'])==4 and r['decision']['action']['type']=='wait'
        assert all(x['value'] is None for x in r['hud'])
        assert any(s['stage']=='shop_cards' for s in r['spans'])
        # A fixture at an unsupported size is rejected for reader use, not implicitly resized.
        r2=worker.request(dict(op='frame',id=101,source_ms=1500,width=2,height=2,bytes=12),bytes(12))
        assert not r2['resolution_compatible'] and not r2['hud']
    finally:worker.close()
    # Exercise the actual application scheduler plus compiled engine.
    s=Session(Options(**paths,mode='fixtures',output=str(out/'fixture'),seconds=2,reader_hz=4)).start()
    while not s.done.is_set() or not s.results.empty():
        try:s.acknowledge(s.results.get(.1),'headless_native_smoke')
        except queue.Empty:pass
    summary=s.finish();assert summary['execution_complete'] and summary['counts']['processed']>0
    # Real local video with changing PTS; no FPS re-timing and no wait for perception.
    video=out/'input.mkv'
    subprocess.run([paths['ffmpeg'],'-v','error','-f','lavfi','-i','color=black:s=1920x1080:r=10:d=1','-c:v','ffv1',str(video)],check=True,timeout=30)
    s=Session(Options(**paths,mode='replay',video=str(video),output=str(out/'pixels'),seconds=1,reader_hz=10)).start()
    while not s.done.is_set() or not s.results.empty():
        try:s.acknowledge(s.results.get(.1),'headless_native_smoke')
        except queue.Empty:pass
    visual=s.finish();assert visual['execution_complete'] and visual['counts']['source_frames']==10
    assert visual['counts']['processed']>0 and visual['counts'].get('fixture_action',0)==0
    receipt={'actual_native_engine':True,'actual_tesseract':True,'actual_ffmpeg':True,
             'tft_accuracy_tested':False,'fixture_actions':[x['decision']['action']['type'] for x in cases],
             'pixel_summary':visual,'fixture_summary':summary,'ui_measured':False}
    (out/'native-smoke.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('E1_NATIVE_SMOKE_OK')
if __name__=='__main__':main()
