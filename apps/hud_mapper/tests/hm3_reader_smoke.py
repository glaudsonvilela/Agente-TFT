"""Exercise native OCR worker on compatible 1920x1080 pixels without replay/FFmpeg."""
import argparse,json
from pathlib import Path
from e1.protocol import NativeWorker
from hm.runtime_app import runtime_paths

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    paths=runtime_paths();worker=NativeWorker(paths["worker"],paths["configs"],paths["tesseract"],log=out/"reader-stderr.log")
    try:
        assert worker.ready["ocr_available"]
        raw=bytes(1920*1080*3)
        r=worker.request(dict(op="frame",id=7,source_ms=0,width=1920,height=1080,bytes=len(raw)),raw,timeout=20)
        assert r["id"]==7 and r["origin"]=="observed_pixels"
        assert len(r["hud"])==4 and all(x["value"] is None for x in r["hud"])
        assert any(s["stage"]=="shop_cards" for s in r["spans"])
        (out/"reader-smoke.json").write_text(json.dumps(dict(execution_complete=True,ocr_available=True,
          hud_statuses=[x["status"] for x in r["hud"]],spans=r["spans"],tft_accuracy_tested=False),indent=2),encoding="utf-8")
        print("HM3_READER_SMOKE_OK")
    finally:worker.close()
if __name__=="__main__":main()
