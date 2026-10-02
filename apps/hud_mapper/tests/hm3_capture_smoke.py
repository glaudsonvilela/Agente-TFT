"""Actual selected-window capture through HM3 UI/runtime. No game or anti-cheat."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
import tkinter as tk
from hm.capture_source import list_targets
from hm.runtime_app import runtime_paths
from e1.protocol import terminate

def main():
    p=argparse.ArgumentParser();p.add_argument("--model",required=True);p.add_argument("--output",required=True);p.add_argument("--app");p.add_argument("--ui",action="store_true")
    a=p.parse_args();out=Path(a.output)
    root=tk.Tk();root.title("HM3 live HUD smoke");root.geometry("720x480+40+40")
    c=tk.Canvas(root,bg="#203040");c.pack(fill="both",expand=True);c.create_rectangle(40,40,350,260,fill="#ff0000",tags="moving")
    root.update();time.sleep(.2);root.update()
    target=next(r for r in list_targets(runtime_paths()["configs"]) if r["kind"]=="window" and r["label"]=="HM3 live HUD smoke")
    cmd=([a.app] if a.app else [sys.executable,"apps/hud_mapper/AgenteTFT_HUD_Runtime.py"])+[
        "--capture",f'capture://window/{target["id"]}',"--capture-consent","--model",a.model,"--output",str(out),"--seconds","3",
        "--map-hz","6","--reader-hz","1","--sample-hz","1",("--ui-smoke" if a.ui else "--headless")]
    log=out.with_name(out.name+"-launcher.log");proc=None
    try:
        with log.open("xb") as f:
            proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
            start=time.monotonic()
            while proc.poll() is None:
                root.update();c.itemconfigure("moving",fill="#00ff00" if int(time.monotonic()*5)%2 else "#ff0000")
                if time.monotonic()-start>90:raise TimeoutError("HM3 smoke timeout")
                time.sleep(.02)
        assert proc.returncode==0,log.read_text(errors="replace")[-8000:]
        report=json.loads((out/"summary.json").read_text());manifest=json.loads((out/"training-manifest.json").read_text())
        assert report["execution_complete"] and report["screen_capture_active"]
        assert report["counts"]["mapped_frames"]>0 and report["counts"]["reader_resolution_skipped"]>0
        assert report["counts"].get("reader_native_runs",0)==0,"OCR must not run on incompatible capture"
        assert manifest["samples"] and all(x["targets"] is None for x in manifest["samples"])
        assert not report["torch_loaded_in_mapper"] and not report["profile_promoted"]
        if a.ui:assert report["counts"].get("ui_map",0)>0
        print("HM3_CAPTURE_SMOKE_OK")
    finally:
        if proc and proc.poll() is None:terminate(proc)
        root.destroy()
if __name__=="__main__":main()
