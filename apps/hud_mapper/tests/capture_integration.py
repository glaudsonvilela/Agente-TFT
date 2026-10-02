"""Real Windows captured pixels -> existing HM mapper/ONNX/readers -> PNGs/telemetry.
Owned colored test window, no TFT or anti-cheat. Runs source or packaged executable.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path
import tkinter as tk
from hm.app import paths
from hm.capture_source import list_targets
from e1.protocol import terminate


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--output',required=True)
    p.add_argument('--app');p.add_argument('--ui',action='store_true');a=p.parse_args()
    if os.name!='nt':raise RuntimeError('Actual Windows integration required')
    out=Path(a.output)
    if out.exists():raise ValueError('Existing capture output')
    root=tk.Tk();root.title('HM2 mapper capture integration');root.geometry('680x440+20+20')
    canvas=tk.Canvas(root,bg='#203040');canvas.pack(fill='both',expand=True)
    canvas.create_rectangle(30,30,330,240,fill='#ff0000',tags='moving')
    root.update();time.sleep(.25);root.update()
    rows=list_targets(paths()['configs'])
    target=next(r for r in rows if r['kind']=='window' and r['label']=='HM2 mapper capture integration')
    cmd=[a.app] if a.app else [sys.executable,'apps/hud_mapper/AgenteTFT_HUD.py']
    cmd += ['--capture',f"capture://window/{target['id']}",'--capture-consent','--model',a.model,
            '--output',str(out),'--seconds','3','--ui-smoke' if a.ui else '--headless']
    logfile=out.with_name(out.name+'-launcher.log');proc=None
    try:
        with logfile.open('xb') as log:
            proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            start=time.monotonic()
            while proc.poll() is None:
                root.update();canvas.itemconfigure('moving',fill='#00ff00' if int(time.monotonic()*4)%2 else '#ff0000')
                if time.monotonic()-start>80:raise TimeoutError('Full capture mapper integration timed out')
                time.sleep(.025)
        assert proc.returncode==0,logfile.read_text(errors='replace')[-8000:]
        report=json.loads((out/'summary.json').read_text());m=json.loads((out/'training-manifest.json').read_text())
        assert report['execution_complete'],report
        assert report['screen_capture_active'] and report['source']['native']['backend']=='own_rust_wgc_d3d11_v1'
        assert report['counts']['mapped_frames']>0 and report['counts']['read_frames']>0
        assert m['samples'] and all(r['capture']['capture_ns']>0 for r in m['samples'])
        assert report['source']['latency_basis']=='native_QPC_acquisition_before_readback_not_compositor_or_scanout'
        assert all(r['capture']['timing']['original_timestamp_modified'] is False for r in m['samples'])
        assert all(r['targets'] is None for r in m['samples'])
        assert not report['torch_loaded_in_mapper'] and not report['profile_promoted']
        assert report['source']['sha256'] is None and not report['source']['closed_local_file']
        if a.ui:assert report['counts'].get('ui_map',0)>0
        print('HM2_CAPTURE_MAPPER_INTEGRATION_OK',flush=True)
    finally:
        if proc and proc.poll() is None:terminate(proc)
        root.destroy()

if __name__=='__main__':main()
