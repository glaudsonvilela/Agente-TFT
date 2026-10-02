"""One packaged HM4 capture/UI cycle against an owned synthetic window."""
import argparse,json,subprocess,sys,time
from pathlib import Path
import tkinter as tk
from hm.capture_source import list_targets
from hm.runtime_app import runtime_paths
from e1.protocol import terminate

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);p.add_argument("--app");p.add_argument("--ui",action="store_true")
    a=p.parse_args();out=Path(a.output)
    root=tk.Tk();root.title("HM4 automatic live smoke");root.overrideredirect(True);root.geometry("1280x720+20+20")
    c=tk.Canvas(root,bg="#203040");c.pack(fill="both",expand=True)
    c.create_rectangle(80,80,760,460,fill="#ff0000",tags="moving")
    root.update();time.sleep(.2);root.update()
    target=next(r for r in list_targets(runtime_paths()["configs"]) if r["kind"]=="window" and r["label"]=="HM4 automatic live smoke")
    cmd=([a.app] if a.app else [sys.executable,"apps/hud_mapper/AgenteTFT_HUD_HM4.py"])+[
        "--capture",f'capture://window/{target["id"]}',"--capture-consent","--output",str(out),"--seconds","5",
        "--map-hz","6","--reader-hz","1","--sample-hz","1",("--ui-smoke" if a.ui else "--headless")]
    log=out.with_name(out.name+"-launcher.log");proc=None
    try:
        with log.open("xb") as f:
            proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
            start=time.monotonic()
            while proc.poll() is None:
                root.update();c.itemconfigure("moving",fill="#00ff00" if int(time.monotonic()*5)%2 else "#ff0000")
                if time.monotonic()-start>90:raise TimeoutError("HM4 smoke timeout")
                time.sleep(.02)
        assert proc.returncode==0,log.read_text(errors="replace")[-8000:]
        report=json.loads((out/"summary.json").read_text())
        manifest=json.loads((out/"training-manifest.json").read_text())
        assert report["execution_complete"] and report["screen_capture_active"]
        assert report["policy"]=="hud_mapper_hm4_auto"
        assert report["counts"]["source_frames"]>0
        assert report["counts"].get("mapped_frames",0)==0
        assert report["counts"].get("reader_resolution_skipped",0)==0
        assert report["counts"].get("reader_normalized_runs",0)>0
        assert report["counts"].get("reader_native_runs",0)>0
        stages=report["timings"]["stages"]
        hud_keys=["hud_stage","hud_gold","hud_level","hud_xp"]
        assert "hud_parallel_wall" in stages and stages["hud_parallel_wall"]["n"]>0
        serial=sum(stages[k]["max_ms"] for k in hud_keys if stages.get(k,{}).get("max_ms") is not None)
        wall=stages["hud_parallel_wall"]["max_ms"]
        assert wall is not None and serial>0 and wall<serial, (wall,serial,stages)
        assert report["neural_scope"]==[]
        assert manifest["samples"] and all(x["targets"] is None for x in manifest["samples"])
        assert not report["torch_loaded_in_mapper"] and not report["profile_promoted"]
        print("HM4_CAPTURE_SMOKE_OK")
    finally:
        if proc and proc.poll() is None:terminate(proc)
        root.destroy()

if __name__=="__main__":
    main()
