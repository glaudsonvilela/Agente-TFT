"""One packaged HM4 capture/UI cycle against an owned synthetic window."""
import argparse,json,subprocess,sys,time
from pathlib import Path
import tkinter as tk
from hm.capture_source import list_targets
from hm.runtime_app import runtime_paths
from e1.protocol import terminate

CAPTURE_SECONDS=5.0

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);p.add_argument("--app");p.add_argument("--ui",action="store_true");p.add_argument("--replay-review",action="store_true")
    a=p.parse_args();out=Path(a.output)
    root=tk.Tk();root.title("HM4 automatic live smoke");root.geometry(("960x540+40+40" if a.replay_review else "820x540+40+40"))
    c=tk.Canvas(root,bg="#203040");c.pack(fill="both",expand=True)
    c.create_rectangle(60,60,430,300,fill="#ff0000",tags="moving")
    root.update();time.sleep(.2);root.update()
    def capture_target():
        return next(r for r in list_targets(runtime_paths()["configs"])
                    if r["kind"]=="window" and r["label"]=="HM4 automatic live smoke")
    target=capture_target()
    if a.replay_review:
        # WGC includes the window frame; Tk geometry specifies its client area.
        # Match the captured outer bounds to the exact 16:9 reader contract.
        for _ in range(4):
            bounds=target["bounds"]
            captured=(bounds[2]-bounds[0],bounds[3]-bounds[1])
            if captured==(960,540):break
            root.geometry(f"{root.winfo_width()+960-captured[0]}x{root.winfo_height()+540-captured[1]}+40+40")
            root.update();target=capture_target()
        bounds=target["bounds"]
        captured=(bounds[2]-bounds[0],bounds[3]-bounds[1])
        assert captured==(960,540), ("synthetic_capture_size",captured,target["bounds"])
    cmd=([a.app] if a.app else [sys.executable,"apps/hud_mapper/AgenteTFT_HUD_HM4.py"])+[
        "--capture",f'capture://window/{target["id"]}',"--capture-consent","--output",str(out),"--seconds",str(CAPTURE_SECONDS),
        "--map-hz","6","--sample-hz","1",("--ui-smoke" if a.ui else "--headless")]
    if a.replay_review:
        cmd.append("--replay-review")
        if a.app:
            cmd.extend(["--model",str(Path(a.app).parent/"_internal/models/deployment-candidate.json")])
    log=out.with_name(out.name+"-launcher.log");proc=None
    try:
        with log.open("xb") as f:
            proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
            start=time.monotonic()
            while proc.poll() is None:
                root.update();c.itemconfigure("moving",fill="#00ff00" if int(time.monotonic()*5)%2 else "#ff0000")
                if time.monotonic()-start>90:raise TimeoutError("HM4 smoke timeout")
                time.sleep(.02)
        if proc.returncode!=0:
            detail=log.read_text(errors="replace")[-12000:]
            print("HM4_LAUNCHER_FAILURE_BEGIN")
            print(detail)
            for evidence in ("summary.json","PARTIAL.json","COMPLETE.json"):
                path=out/evidence
                if path.exists():
                    print("HM4_EVIDENCE_"+evidence.replace(".","_").upper()+"="+path.read_text(errors="replace")[-12000:])
            print("HM4_LAUNCHER_FAILURE_END")
            raise AssertionError(f"packaged HM4 exited {proc.returncode}")
        report=json.loads((out/"summary.json").read_text())
        manifest=json.loads((out/"training-manifest.json").read_text())
        assert report["execution_complete"] and report["screen_capture_active"]
        assert report["policy"]=="hud_mapper_hm4_auto"
        assert report["counts"]["source_frames"]>0
        if a.replay_review:
            assert report["counts"].get("mapped_frames",0)>0
            assert report["counts"].get("hub_results",0)>0
            assert report["counts"].get("coach_updates",0)>0
            assert report["counts"].get("replay_tips",0)==0  # Blank fixture has no verified action.
            assert report["versions"].get("board_hub_mode")=="replay_screen_candidate_only"
            assert report["neural_scope"]==["bench","shop"]
            assert report["timings"]["coach_source_to_ui_estimate"]["n"]>0
            assert (out/"board-hub-observations.jsonl").is_file()
            assert (out/"replay-tips.jsonl").is_file()
        else:
            assert report["counts"].get("mapped_frames",0)==0
        # Do not pass --reader-hz: prove the packaged HM4 default is 2 Hz.
        # Session elapsed includes preflight and sealing; cadence belongs to the
        # configured active capture window, not process startup/teardown.
        submitted=report["counts"].get("native_submitted",0)
        session_elapsed=float(report.get("elapsed_seconds") or 0.0)
        assert session_elapsed>=CAPTURE_SECONDS, ("hm4_capture_ended_early",session_elapsed,CAPTURE_SECONDS)
        effective_hz=submitted/CAPTURE_SECONDS
        assert effective_hz>=1.5, ("hm4_default_reader_hz",submitted,effective_hz,CAPTURE_SECONDS,session_elapsed)
        # Packaged smoke proves WGC/UI/session sealing only. The owned Tk window
        # is intentionally non-canonical; reader normalization/parallelism are
        # covered by deterministic contracts and Rust tests.
        if not a.replay_review:
            assert report["counts"].get("reader_resolution_skipped",0)>0
            assert report["counts"].get("reader_native_runs",0)==0
        # HM4.3 HP is scheduled independently even when the owned smoke window
        # is non-canonical; the HP worker returns resolution_incompatible quickly.
        assert report["counts"].get("hp_submitted",0)>0
        assert report["counts"].get("hp_results",0)>0
        assert report["timings"]["hp_source_to_result"]["n"]>0
        if not a.replay_review:assert report["neural_scope"]==[]
        assert manifest["samples"] and all(x["targets"] is None for x in manifest["samples"])
        assert not report["torch_loaded_in_mapper"] and not report["profile_promoted"]
        print("HM4_CAPTURE_SMOKE_OK")
    finally:
        if proc and proc.poll() is None:terminate(proc)
        root.destroy()

if __name__=="__main__":
    main()
