"""Audit one HM4 session directory or ZIP without OCR, model execution or image mutation."""
from __future__ import annotations
import argparse, collections, json, zipfile
from pathlib import Path

INTEREST = ("hud.stage","hud.gold","hud.level","hud.xp","player.hp")
NON_ELIGIBLE = {
    "unavailable","not_connected","not_established","registered_not_verified",
    "resolution_incompatible","development_seed_not_verified","badge_not_found",
}
FULLY_USABLE = {
    "single_frame_observation","accepted","observed","offer_text_readable","empty_observed",
}
PARTIAL_USABLE = {"partially_readable"}


class Source:
    def __init__(self,path):
        self.path=Path(path)
        self.zip=zipfile.ZipFile(self.path) if self.path.is_file() else None
    def names(self):
        if self.zip:return self.zip.namelist()
        return [p.relative_to(self.path).as_posix() for p in self.path.rglob("*") if p.is_file()]
    def text(self,name):
        if self.zip:return self.zip.read(name).decode("utf-8-sig")
        return (self.path/name).read_text(encoding="utf-8-sig")
    def lines(self,name):
        if self.zip:
            with self.zip.open(name) as f:
                for raw in f:
                    yield raw.decode("utf-8")
        else:
            with (self.path/name).open(encoding="utf-8") as f:
                yield from f
    def close(self):
        if self.zip:self.zip.close()


def suffix(root,name):
    return root+name if root else name


def compact_values(values,limit=25):
    vals=[]
    seen=set()
    for value in values:
        key=json.dumps(value,ensure_ascii=False,sort_keys=True)
        if key not in seen:
            seen.add(key);vals.append(value)
        if len(vals)>=limit:break
    return vals,len(seen)


def rate(n,d):
    return n/d if d else None


def field_metrics(counter):
    """Separate actual uncertainty from a reader that was not eligible/present."""
    total=sum(counter.values())
    non_eligible=sum(n for status,n in counter.items() if status in NON_ELIGIBLE)
    eligible=max(0,total-non_eligible)
    full=sum(n for status,n in counter.items() if status in FULLY_USABLE)
    partial=sum(n for status,n in counter.items() if status in PARTIAL_USABLE)
    usable=full+partial
    unresolved=max(0,eligible-usable)
    return dict(
        total=total,
        non_eligible=non_eligible,
        eligible=eligible,
        fully_observed=full,
        partially_readable=partial,
        usable=usable,
        unresolved_when_eligible=unresolved,
        fully_observed_rate_when_eligible=rate(full,eligible),
        usable_rate_when_eligible=rate(usable,eligible),
        unresolved_rate_when_eligible=rate(unresolved,eligible),
    )


def neural_metrics(summary):
    enabled=bool((summary.get("versions") or {}).get("neural_enabled"))
    mode=summary.get("neural_mode") or ("shadow_diagnostic" if enabled else "disabled")
    return dict(
        enabled=enabled,
        mode=mode,
        training_label_allowed=bool(summary.get("neural_training_label_allowed",False)),
        game_state_write_allowed=bool(summary.get("neural_game_state_write_allowed",False)),
        reader_input_allowed=bool(summary.get("neural_reader_input_allowed",False)),
        scope=summary.get("neural_scope") or [],
    )


def pipeline_metrics(summary):
    counts=summary.get("counts") or {}
    queues=summary.get("queues") or {}
    submitted=counts.get("native_submitted") or 0
    read=counts.get("read_frames") or 0
    runs=counts.get("reader_native_runs") or 0
    replaced=queues.get("native_replaced") or 0
    timings=summary.get("timings") or {}
    reader=timings.get("readers_source_to_result") or {}
    reader_queue=timings.get("readers_queue") or {}
    return dict(
        native_submitted=submitted,
        read_frames=read,
        reader_native_runs=runs,
        latest_frame_replaced=replaced,
        latest_frame_replacement_rate=rate(replaced,submitted),
        read_completion_rate_per_submission=rate(read,submitted),
        read_completion_rate_per_native_run=rate(read,runs),
        reader_source_to_result_p50_ms=reader.get("p50_ms"),
        reader_source_to_result_p95_ms=reader.get("p95_ms"),
        reader_queue_p50_ms=reader_queue.get("p50_ms"),
        reader_queue_p95_ms=reader_queue.get("p95_ms"),
    )


def audit_session(src,summary_name,names):
    root=summary_name[:-len("summary.json")]
    summary=json.loads(src.text(summary_name))
    counts=summary.get("counts") or {}
    versions=summary.get("versions") or {}
    manifest_name=suffix(root,"training-manifest.json")
    roi_name=suffix(root,"roi-observations.jsonl")
    collection_name=suffix(root,"collection-metrics.json")
    manifest=json.loads(src.text(manifest_name)) if manifest_name in names else {}
    collection=json.loads(src.text(collection_name)) if collection_name in names else {}

    statuses=collections.defaultdict(collections.Counter)
    values=collections.defaultdict(list)
    image_sizes=collections.Counter()
    transforms=collections.Counter()
    roi_frames=0
    native_executed=0
    normalized_records=0
    if roi_name in names:
        for line in src.lines(roi_name):
            line=line.strip()
            if not line:continue
            row=json.loads(line);roi_frames+=1
            image_sizes[tuple(row.get("image_size") or [])]+=1
            if row.get("native_executed"):native_executed+=1
            plan=row.get("reader_input_transform") or {}
            transforms[plan.get("method","missing")]+=1
            if plan.get("normalized"):normalized_records+=1
            for reg in row.get("regions") or []:
                rid=str(reg.get("id"));status=str(reg.get("status"))
                statuses[rid][status]+=1
                if reg.get("value") is not None:values[rid].append(reg.get("value"))

    fields={}
    for rid in sorted(statuses):
        v,distinct=compact_values(values[rid])
        metrics=field_metrics(statuses[rid])
        fields[rid]=dict(
            statuses=dict(statuses[rid]),
            observed_values=v,
            distinct_values_at_least=distinct,
            **metrics,
        )

    samples=manifest.get("samples") or []
    sample_sizes=collections.Counter((x.get("width"),x.get("height")) for x in samples)
    targets_missing=sum(x.get("targets") is None for x in samples)

    recommendations=[]
    if not versions.get("neural_enabled"):
        recommendations.append("neural_model_not_active")
    if counts.get("reader_resolution_skipped",0):
        recommendations.append("reader_resolution_gate_hit")
    if counts.get("reader_native_runs",0)==0:
        recommendations.append("no_native_reader_execution")
    if samples and targets_missing==len(samples):
        recommendations.append("natural_samples_are_unlabelled")

    empty_field=dict(
        statuses={},observed_values=[],distinct_values_at_least=0,
        total=0,non_eligible=0,eligible=0,fully_observed=0,partially_readable=0,
        usable=0,unresolved_when_eligible=0,
        fully_observed_rate_when_eligible=None,usable_rate_when_eligible=None,
        unresolved_rate_when_eligible=None,
    )
    interest={rid:fields.get(rid,dict(empty_field)) for rid in INTEREST}

    native=(summary.get("source") or {}).get("native") or {}
    target=native.get("target") or {}
    return dict(
        session_root=root,execution_complete=summary.get("execution_complete"),
        error=summary.get("error"),policy=summary.get("policy"),
        elapsed_seconds=summary.get("elapsed_seconds"),
        source_target=dict(kind=target.get("kind"),label=target.get("label"),
                           bounds=target.get("bounds"),device=target.get("device")),
        versions=dict(neural_enabled=versions.get("neural_enabled"),
                      model_sha256=versions.get("model_sha256"),
                      hud=versions.get("hud"),hp=versions.get("hp")),
        neural=neural_metrics(summary),
        pipeline=pipeline_metrics(summary),
        counts=counts,queues=summary.get("queues"),timings=summary.get("timings"),
        coverage=summary.get("coverage"),collection=summary.get("collection"),
        roi=dict(records=roi_frames,native_executed=native_executed,
                 normalized_records=normalized_records,
                 image_sizes={str(k):v for k,v in image_sizes.items()},
                 reader_transforms=dict(transforms)),
        samples=dict(count=len(samples),targets_missing=targets_missing,
                     sizes={str(k):v for k,v in sample_sizes.items()},
                     collection_metrics=collection),
        interest=interest,fields=fields,recommendations=recommendations)


def self_test():
    shop=field_metrics(collections.Counter(
        offer_text_readable=10,partially_readable=2,unknown=3,unavailable=5))
    assert shop["total"]==20 and shop["eligible"]==15
    assert shop["fully_observed"]==10 and shop["usable"]==12
    assert abs(shop["usable_rate_when_eligible"]-0.8)<1e-12
    hp=field_metrics(collections.Counter(
        accepted=224,badge_not_found=43,ocr_uncertain=30,badge_ambiguous=2))
    assert hp["total"]==299 and hp["eligible"]==256 and hp["fully_observed"]==224
    assert abs(hp["fully_observed_rate_when_eligible"]-0.875)<1e-12
    pipe=pipeline_metrics(dict(
        counts=dict(native_submitted=1585,reader_native_runs=300,read_frames=299),
        queues=dict(native_replaced=1284),timings={}))
    assert abs(pipe["latest_frame_replacement_rate"]-(1284/1585))<1e-12
    neural=neural_metrics(dict(
        versions=dict(neural_enabled=True),neural_mode="shadow_diagnostic",
        neural_training_label_allowed=False,neural_game_state_write_allowed=False,
        neural_reader_input_allowed=False,neural_scope=["bench","shop"]))
    assert neural["enabled"] and neural["mode"]=="shadow_diagnostic"
    assert neural["scope"]==["bench","shop"]
    assert not neural["training_label_allowed"]
    assert not neural["game_state_write_allowed"]
    assert not neural["reader_input_allowed"]
    print("HM4_AUDIT_SELF_TEST_OK")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("source",nargs="?",help="HM4 session directory or ZIP")
    p.add_argument("--output",default="hm4-session-audit.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test();return
    if not a.source:
        p.error("source is required unless --self-test is used")
    src=Source(a.source)
    try:
        names=set(src.names())
        summaries=sorted(n for n in names if n.endswith("summary.json"))
        if not summaries:raise SystemExit("No summary.json found")
        result=dict(schema_version=2,source=str(a.source),
                    sessions=[audit_session(src,n,names) for n in summaries])
    finally:
        src.close()
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("HM4_AUDIT="+json.dumps(result,ensure_ascii=False,separators=(",",":")))


if __name__=="__main__":
    main()
