"""Audit one HM4 session directory or ZIP without OCR, model execution or image mutation."""
from __future__ import annotations
import argparse, collections, json, zipfile
from pathlib import Path

INTEREST = ("hud.stage","hud.gold","hud.level","hud.xp","player.hp")


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
    all_regions=sorted(statuses)
    for rid in all_regions:
        v,distinct=compact_values(values[rid])
        total=sum(statuses[rid].values())
        unknown=sum(n for status,n in statuses[rid].items()
                    if status in ("unknown","unavailable","not_connected","not_established",
                                  "registered_not_verified","resolution_incompatible"))
        fields[rid]=dict(total=total,statuses=dict(statuses[rid]),unknown_like=unknown,
                         unknown_like_rate=(unknown/total if total else None),
                         observed_values=v,distinct_values_at_least=distinct)

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
    interest={}
    for rid in INTEREST:
        interest[rid]=fields.get(rid,dict(total=0,statuses={},unknown_like=0,
                                          unknown_like_rate=None,observed_values=[],
                                          distinct_values_at_least=0))

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


def main():
    p=argparse.ArgumentParser()
    p.add_argument("source",help="HM4 session directory or ZIP")
    p.add_argument("--output",default="hm4-session-audit.json")
    a=p.parse_args()
    src=Source(a.source)
    try:
        names=set(src.names())
        summaries=sorted(n for n in names if n.endswith("summary.json"))
        if not summaries:raise SystemExit("No summary.json found")
        result=dict(schema_version=1,source=str(a.source),
                    sessions=[audit_session(src,n,names) for n in summaries])
    finally:
        src.close()
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("HM4_AUDIT="+json.dumps(result,ensure_ascii=False,separators=(",",":")))


if __name__=="__main__":
    main()
