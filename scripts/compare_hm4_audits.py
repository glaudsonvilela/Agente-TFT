"""Compare two HM4 audit JSON files without re-running OCR or models."""
from __future__ import annotations
import argparse, json
from pathlib import Path

FIELDS=("hud.stage","hud.gold","hud.level","hud.xp","player.hp")

def one_session(doc):
    sessions=doc.get("sessions") or []
    if len(sessions)!=1:
        raise ValueError("comparison expects exactly one audited session per file")
    return sessions[0]

def pct_delta(new,old):
    if new is None or old is None:return None
    return new-old

def ratio(new,old):
    if new is None or old in (None,0):return None
    return new/old

def field_view(session,rid):
    row=(session.get("fields") or {}).get(rid) or {}
    return {
        "eligible":row.get("eligible"),
        "fully_observed_rate_when_eligible":row.get("fully_observed_rate_when_eligible"),
        "usable_rate_when_eligible":row.get("usable_rate_when_eligible"),
        "unresolved_rate_when_eligible":row.get("unresolved_rate_when_eligible"),
    }

def compare(old_doc,new_doc):
    old=one_session(old_doc);new=one_session(new_doc)
    op=old.get("pipeline") or {};np=new.get("pipeline") or {}
    fields={}
    for rid in FIELDS:
        a=field_view(old,rid);b=field_view(new,rid)
        fields[rid]={
            "old":a,"new":b,
            "fully_observed_rate_delta":pct_delta(
                b["fully_observed_rate_when_eligible"],a["fully_observed_rate_when_eligible"]),
            "usable_rate_delta":pct_delta(
                b["usable_rate_when_eligible"],a["usable_rate_when_eligible"]),
        }
    return {
        "schema_version":1,
        "old_session":old.get("session_root"),
        "new_session":new.get("session_root"),
        "pipeline":{
            "reader_p50_ms":{
                "old":op.get("reader_source_to_result_p50_ms"),
                "new":np.get("reader_source_to_result_p50_ms"),
                "ratio_new_over_old":ratio(np.get("reader_source_to_result_p50_ms"),
                                           op.get("reader_source_to_result_p50_ms")),
            },
            "reader_p95_ms":{
                "old":op.get("reader_source_to_result_p95_ms"),
                "new":np.get("reader_source_to_result_p95_ms"),
                "ratio_new_over_old":ratio(np.get("reader_source_to_result_p95_ms"),
                                           op.get("reader_source_to_result_p95_ms")),
            },
            "latest_frame_replacement_rate":{
                "old":op.get("latest_frame_replacement_rate"),
                "new":np.get("latest_frame_replacement_rate"),
                "delta":pct_delta(np.get("latest_frame_replacement_rate"),
                                  op.get("latest_frame_replacement_rate")),
            },
            "read_completion_rate_per_submission":{
                "old":op.get("read_completion_rate_per_submission"),
                "new":np.get("read_completion_rate_per_submission"),
                "delta":pct_delta(np.get("read_completion_rate_per_submission"),
                                  op.get("read_completion_rate_per_submission")),
            },
            "hp_source_to_result_p50_ms":{
                "old":op.get("hp_source_to_result_p50_ms"),
                "new":np.get("hp_source_to_result_p50_ms"),
                "ratio_new_over_old":ratio(np.get("hp_source_to_result_p50_ms"),
                                           op.get("hp_source_to_result_p50_ms")),
            },
            "hp_source_to_result_p95_ms":{
                "old":op.get("hp_source_to_result_p95_ms"),
                "new":np.get("hp_source_to_result_p95_ms"),
                "ratio_new_over_old":ratio(np.get("hp_source_to_result_p95_ms"),
                                           op.get("hp_source_to_result_p95_ms")),
            },
            "hp_replacement_rate":{
                "old":op.get("hp_replacement_rate"),
                "new":np.get("hp_replacement_rate"),
                "delta":pct_delta(np.get("hp_replacement_rate"),op.get("hp_replacement_rate")),
            },
        },
        "fields":fields,
        "neural":{
            "old_mode":(old.get("versions") or {}).get("neural_mode"),
            "new_mode":(new.get("versions") or {}).get("neural_mode"),
        },
    }

def self_test():
    def doc(name,p50,replaced,stage):
        return {"sessions":[{
            "session_root":name,
            "pipeline":{
                "reader_source_to_result_p50_ms":p50,
                "reader_source_to_result_p95_ms":p50*1.5,
                "latest_frame_replacement_rate":replaced,
                "read_completion_rate_per_submission":1-replaced,
            },
            "fields":{
                "hud.stage":{
                    "eligible":100,
                    "fully_observed_rate_when_eligible":stage,
                    "usable_rate_when_eligible":stage,
                    "unresolved_rate_when_eligible":1-stage,
                }
            },
            "versions":{"neural_mode":"disabled" if name=="old" else "shadow_diagnostic"},
        }]}
    r=compare(doc("old",6200,.81,.82),doc("new",500,.15,.90))
    assert abs(r["pipeline"]["reader_p50_ms"]["ratio_new_over_old"]-(500/6200))<1e-12
    assert abs(r["pipeline"]["latest_frame_replacement_rate"]["delta"]-(-.66))<1e-12
    assert abs(r["fields"]["hud.stage"]["fully_observed_rate_delta"]-.08)<1e-12
    assert r["neural"]["new_mode"]=="shadow_diagnostic"
    print("HM4_COMPARE_SELF_TEST_OK")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("old",nargs="?")
    p.add_argument("new",nargs="?")
    p.add_argument("--output",default="hm4-comparison.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test();return
    if not a.old or not a.new:
        p.error("old and new audit JSON files are required")
    old=json.loads(Path(a.old).read_text(encoding="utf-8-sig"))
    new=json.loads(Path(a.new).read_text(encoding="utf-8-sig"))
    result=compare(old,new)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("HM4_COMPARISON="+json.dumps(result,ensure_ascii=False,separators=(",",":")))

if __name__=="__main__":
    main()
