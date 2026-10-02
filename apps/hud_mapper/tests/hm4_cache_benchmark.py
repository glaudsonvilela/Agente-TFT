"""Deterministic HM4 benchmark for exact cache and decoupled shop cadence."""
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

    stable=bytes([24])*(1920*1080*3)
    changed=bytes([25])*(1920*1080*3)
    worker=NativeWorker(a.worker,a.configs,"tesseract")
    try:
        def run(frame_id,source_ms,payload,include_shop=True):
            header={"op":"frame","id":frame_id,"source_ms":source_ms,
                    "width":1920,"height":1080,"bytes":len(payload),
                    "include_shop":include_shop}
            started=time.perf_counter()
            result=worker.request(header,payload,timeout=20)
            wall_ms=(time.perf_counter()-started)*1000.0
            return result,wall_ms

        first,first_wall=run(1,1000,stable,True)
        second,second_wall=run(2,1100,stable,True)
        third,third_wall=run(3,2100,changed,False)
    finally:
        worker.close()

    second_spans=stage_rows(second)
    hud_hits={row.get("stage"):bool(row.get("cache_exact_hit"))
              for row in second_spans if row.get("stage") in HUD_STAGES}
    shop_hit=next((bool(row.get("cache_exact_hit")) for row in second_spans
                   if row.get("stage")=="shop_cards"),False)
    controls_hit=next((bool(row.get("cache_exact_hit")) for row in second_spans
                       if row.get("stage")=="shop_controls"),False)

    third_spans=stage_rows(third)
    third_hud={row.get("stage"):bool(row.get("cache_exact_hit"))
               for row in third_spans if row.get("stage") in HUD_STAGES}
    third_stage_names=[row.get("stage") for row in third_spans]
    cadence_span=next((row for row in third_spans
                       if row.get("stage")=="shop_cadence_reuse"),None)

    first_native=float(first.get("native_ms") or first_wall)
    second_native=float(second.get("native_ms") or second_wall)
    third_native=float(third.get("native_ms") or third_wall)
    ratio=second_native/first_native if first_native>0 else None

    report={
        "schema_version":2,
        "policy":"hm4_reader_cache_and_shop_cadence_benchmark_v2",
        "frame_size":[1920,1080],
        "first_full_fresh":{"native_ms":first_native,"wall_ms":first_wall},
        "second_identical_cached":{"native_ms":second_native,"wall_ms":second_wall},
        "third_changed_hud_only":{"native_ms":third_native,"wall_ms":third_wall},
        "speedup_ratio_identical_over_first":ratio,
        "second_hud_cache_hits":hud_hits,
        "second_shop_cache_hit":shop_hit,
        "second_controls_cache_hit":controls_hit,
        "third_hud_cache_hits":third_hud,
        "third_shop_requested":third.get("shop_requested"),
        "third_shop_cadence_reuse":cadence_span,
        "third_stages":third_stage_names,
        "same_rgb_payload_second":True,
        "changed_rgb_payload_third":True,
    }
    Path(a.output).write_text(json.dumps(report,indent=2),encoding="utf-8")

    assert set(hud_hits)==HUD_STAGES and all(hud_hits.values()), hud_hits
    assert shop_hit and controls_hit, report
    assert ratio is not None and ratio < 0.75, report

    assert set(third_hud)==HUD_STAGES and not any(third_hud.values()), third_hud
    assert third.get("shop_requested") is False, report
    assert cadence_span is not None and cadence_span.get("shop_executed") is False, report
    assert "shop_cards" not in third_stage_names, report
    assert "shop_controls" not in third_stage_names, report

    print("HM4_CACHE_BENCHMARK="+json.dumps(report,separators=(",",":")))

if __name__=="__main__":
    main()
