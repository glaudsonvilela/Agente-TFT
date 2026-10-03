"""Deterministic HM4 benchmark for cache, shop cadence, and real HUD+HP parallel wall time."""
import argparse, json, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from e1.protocol import NativeWorker

HUD_STAGES={"hud_stage","hud_gold","hud_level","hud_xp"}
CACHED_WALL_BUDGET_MS=100.0
HUD_ONLY_WALL_BUDGET_MS=1500.0
HUD_PLUS_HP_WALL_BUDGET_MS=1800.0

def stage_rows(result):
    return [x for x in result.get("spans",[]) if isinstance(x,dict)]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--worker",required=True)
    p.add_argument("--hp-worker",required=True)
    p.add_argument("--configs",required=True)
    p.add_argument("--output",default="hm4-cache-benchmark.json")
    p.add_argument("--worker-log")
    p.add_argument("--hp-log")
    a=p.parse_args()

    stable=bytes([24])*(1920*1080*3)
    changed=bytes([25])*(1920*1080*3)
    changed2=bytes([26])*(1920*1080*3)
    worker=NativeWorker(a.worker,a.configs,"tesseract",log=a.worker_log)
    hp_worker=NativeWorker(a.hp_worker,a.configs,"tesseract",log=a.hp_log)
    try:
        def header(frame_id,source_ms,payload,include_shop):
            return {"op":"frame","id":frame_id,"source_ms":source_ms,
                    "width":1920,"height":1080,"bytes":len(payload),
                    "include_shop":include_shop}

        def run(frame_id,source_ms,payload,include_shop=True):
            h=header(frame_id,source_ms,payload,include_shop)
            started=time.perf_counter()
            result=worker.request(h,payload,timeout=20)
            return result,(time.perf_counter()-started)*1000.0

        def run_with_hp(frame_id,source_ms,payload,include_shop=False):
            h=header(frame_id,source_ms,payload,include_shop)
            started=time.perf_counter()
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix="hm4-bench-hp") as pool:
                hp_future=pool.submit(hp_worker.request,h,payload,20)
                main_result=worker.request(h,payload,timeout=20)
                hp_result=hp_future.result(timeout=21)
            return main_result,hp_result,(time.perf_counter()-started)*1000.0

        first,first_wall=run(1,1000,stable,True)
        second,second_wall=run(2,1100,stable,True)
        third,third_wall=run(3,2100,changed,False)
        fourth,fourth_hp,fourth_wall=run_with_hp(4,3100,changed2,False)
    finally:
        worker.close()
        hp_worker.close()

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

    fourth_spans=stage_rows(fourth)
    fourth_hud={row.get("stage"):bool(row.get("cache_exact_hit"))
                for row in fourth_spans if row.get("stage") in HUD_STAGES}
    fourth_stage_names=[row.get("stage") for row in fourth_spans]

    first_native=float(first.get("native_ms") or first_wall)
    second_native=float(second.get("native_ms") or second_wall)
    third_native=float(third.get("native_ms") or third_wall)
    fourth_native=float(fourth.get("native_ms") or fourth_wall)
    fourth_hp_native=float(fourth_hp.get("native_ms") or 0.0)
    ratio=second_native/first_native if first_native>0 else None

    report={
        "schema_version":3,
        "policy":"hm4_runtime_path_benchmark_v3",
        "frame_size":[1920,1080],
        "first_full_fresh":{"main_native_ms":first_native,"wall_ms":first_wall},
        "second_identical_cached":{"main_native_ms":second_native,"wall_ms":second_wall},
        "third_changed_hud_only":{"main_native_ms":third_native,"wall_ms":third_wall},
        "fourth_changed_hud_plus_hp":{
            "main_native_ms":fourth_native,
            "hp_native_ms":fourth_hp_native,
            "combined_wall_ms":fourth_wall,
            "main_frame_id":fourth.get("id"),
            "hp_frame_id":fourth_hp.get("id"),
        },
        "performance_budgets_ms":{
            "cached_wall":CACHED_WALL_BUDGET_MS,
            "changed_hud_only_wall":HUD_ONLY_WALL_BUDGET_MS,
            "changed_hud_plus_hp_wall":HUD_PLUS_HP_WALL_BUDGET_MS,
        },
        "speedup_ratio_identical_over_first":ratio,
        "second_hud_cache_hits":hud_hits,
        "second_shop_cache_hit":shop_hit,
        "second_controls_cache_hit":controls_hit,
        "third_hud_cache_hits":third_hud,
        "third_shop_requested":third.get("shop_requested"),
        "third_numeric_hud_ocr_backend":third.get("numeric_hud_ocr_backend"),
        "third_shop_cadence_reuse":cadence_span,
        "third_stages":third_stage_names,
        "fourth_hud_cache_hits":fourth_hud,
        "fourth_shop_requested":fourth.get("shop_requested"),
        "fourth_numeric_hud_ocr_backend":fourth.get("numeric_hud_ocr_backend"),
        "fourth_stages":fourth_stage_names,
        "same_rgb_payload_second":True,
        "changed_rgb_payload_third":True,
        "changed_rgb_payload_fourth":True,
    }
    Path(a.output).write_text(json.dumps(report,indent=2),encoding="utf-8")

    assert set(hud_hits)==HUD_STAGES and all(hud_hits.values()), hud_hits
    assert shop_hit and controls_hit, report
    assert ratio is not None and ratio < 0.75, report
    assert second_wall < CACHED_WALL_BUDGET_MS, report

    assert set(third_hud)==HUD_STAGES and not any(third_hud.values()), third_hud
    assert third.get("shop_requested") is False, report
    assert cadence_span is not None and cadence_span.get("shop_executed") is False, report
    assert "shop_cards" not in third_stage_names and "shop_controls" not in third_stage_names, report
    assert third_wall < HUD_ONLY_WALL_BUDGET_MS, report

    assert set(fourth_hud)==HUD_STAGES and not any(fourth_hud.values()), fourth_hud
    assert fourth.get("shop_requested") is False, report
    assert "shop_cards" not in fourth_stage_names and "shop_controls" not in fourth_stage_names, report
    assert fourth.get("id")==4 and fourth_hp.get("id")==4, report
    assert fourth_hp_native >= 0.0 and fourth_wall > 0.0, report
    assert fourth_wall < HUD_PLUS_HP_WALL_BUDGET_MS, report

    print("HM4_CACHE_BENCHMARK="+json.dumps(report,separators=(",",":")))

if __name__=="__main__":
    main()
