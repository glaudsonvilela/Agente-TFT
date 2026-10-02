"""Deterministic HM4 cache benchmark: same immutable 1920x1080 RGB frame twice."""
import argparse, json, time
from pathlib import Path
from e1.protocol import NativeWorker

HUD_STAGES={"hud_stage","hud_gold","hud_level","hud_xp"}

def stage_rows(result):
    return [x for x in result.get("spans",[]) if isinstance(x,dict)]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--worker",required=True)
    p.add_argument("--configs",required=True)
    p.add_argument("--output",default="hm4-cache-benchmark.json")
    a=p.parse_args()

    pixels=bytes([24])*(1920*1080*3)
    worker=NativeWorker(a.worker,a.configs,"tesseract")
    try:
        def run(frame_id,source_ms):
            header={"op":"frame","id":frame_id,"source_ms":source_ms,
                    "width":1920,"height":1080,"bytes":len(pixels)}
            started=time.perf_counter()
            result=worker.request(header,pixels,timeout=20)
            wall_ms=(time.perf_counter()-started)*1000.0
            return result,wall_ms

        first,first_wall=run(1,1000)
        second,second_wall=run(2,1100)
    finally:
        worker.close()

    second_spans=stage_rows(second)
    hud_hits={row.get("stage"):bool(row.get("cache_exact_hit"))
              for row in second_spans if row.get("stage") in HUD_STAGES}
    shop_hit=next((bool(row.get("cache_exact_hit")) for row in second_spans
                   if row.get("stage")=="shop_cards"),False)
    controls_hit=next((bool(row.get("cache_exact_hit")) for row in second_spans
                       if row.get("stage")=="shop_controls"),False)

    first_native=float(first.get("native_ms") or first_wall)
    second_native=float(second.get("native_ms") or second_wall)
    ratio=second_native/first_native if first_native>0 else None

    report={
        "schema_version":1,
        "policy":"hm4_exact_reader_cache_benchmark_v1",
        "frame_size":[1920,1080],
        "first":{"native_ms":first_native,"wall_ms":first_wall},
        "second":{"native_ms":second_native,"wall_ms":second_wall},
        "speedup_ratio_second_over_first":ratio,
        "hud_cache_hits":hud_hits,
        "shop_cache_hit":shop_hit,
        "controls_cache_hit":controls_hit,
        "same_rgb_payload":True,
    }
    Path(a.output).write_text(json.dumps(report,indent=2),encoding="utf-8")
    assert set(hud_hits)==HUD_STAGES and all(hud_hits.values()), hud_hits
    assert shop_hit, report
    assert controls_hit, report
    assert ratio is not None and ratio < 0.75, report
    print("HM4_CACHE_BENCHMARK="+json.dumps(report,separators=(",",":")))

if __name__=="__main__":
    main()
