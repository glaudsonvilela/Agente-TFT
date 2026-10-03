"""HM4.4 resident OCR reliability gate: repeated worker startups + uncached HUD frames."""
import argparse, json, os, time
from pathlib import Path
from e1.protocol import NativeWorker

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--worker",required=True)
    p.add_argument("--configs",required=True)
    p.add_argument("--output",default="hm44-resident-stress.json")
    p.add_argument("--startups",type=int,default=4)
    p.add_argument("--frames",type=int,default=8)
    a=p.parse_args()
    if not 2<=a.startups<=12 or not 4<=a.frames<=40:
        raise SystemExit("stress budgets outside safe range")
    size=1920*1080*3
    rows=[]
    started=time.perf_counter()
    for startup in range(a.startups):
        env=os.environ.copy()
        env["AGENTE_TFT_RESIDENT_OCR"]="1"
        log=Path(f"hm44-resident-stress-{startup}.stderr.log")
        worker=None
        try:
            worker=NativeWorker(a.worker,a.configs,"tesseract",log=log,env=env)
            backend=worker.ready.get("numeric_hud_ocr_backend")
            text_backend=worker.ready.get("spatial_text_ocr_backend")
            assert backend=="resident_tesseract_c_api_v1", worker.ready
            assert text_backend=="resident_tesseract_c_api_text_v1", worker.ready
            frame_ms=[]
            for index in range(a.frames):
                # Change every byte to force uncached numeric HUD work while keeping shop deferred.
                value=20+((startup*37+index*19)%180)
                payload=bytes([value])*size
                fid=startup*1000+index+1
                header={"op":"frame","id":fid,"source_ms":fid*100,
                        "width":1920,"height":1080,"bytes":len(payload),"include_shop":False}
                at=time.perf_counter()
                out=worker.request(header,payload,timeout=12)
                frame_ms.append((time.perf_counter()-at)*1000.0)
                assert out.get("id")==fid
                assert out.get("numeric_hud_ocr_backend")=="resident_tesseract_c_api_v1"
                assert out.get("spatial_text_ocr_backend")=="resident_tesseract_c_api_text_v1"
            rows.append({"startup":startup,"frames":a.frames,"min_ms":min(frame_ms),
                         "max_ms":max(frame_ms),"mean_ms":sum(frame_ms)/len(frame_ms),
                         "stderr_bytes":log.stat().st_size if log.exists() else 0})
        finally:
            if worker:
                worker.close()
    report={"schema_version":1,"policy":"hm44_resident_worker_reliability_v1",
            "startups":a.startups,"frames_per_startup":a.frames,
            "total_frames":a.startups*a.frames,"rows":rows,
            "elapsed_ms":(time.perf_counter()-started)*1000.0,
            "all_completed":len(rows)==a.startups}
    Path(a.output).write_text(json.dumps(report,indent=2),encoding="utf-8")
    assert report["all_completed"]
    print("HM44_RESIDENT_STRESS="+json.dumps(report,separators=(",",":")))

if __name__=="__main__":
    main()
