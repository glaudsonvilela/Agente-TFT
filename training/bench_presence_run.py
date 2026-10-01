"""B2 explicit bench presence experiment, with complete frozen B1 regression."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
from collections import Counter
from ingestion.knowledge_release import canonical, load
from training.shop_replay_observe import sha, verify_sources
from training.board_spatial_run import preflight as spatial_preflight, run as spatial_run
from training.board_spatial_evidence import require, validate as validate_spatial
from training.bench_presence_evidence import validate_policy, validate, compare_legacy


def preflight(args,with_probe=True):
    p,manifest,sources=spatial_preflight(args,with_probe=with_probe)
    policy,ph=load(args.presence_profile)
    validate_policy(policy,p,args.profile.read_bytes())
    baseline=args.baseline.resolve(strict=True)
    require(baseline.is_file() and baseline.name=='report.json', 'B1 report required')
    old_manifest=baseline.parent/'manifest.json';seal_path=baseline.parent/'COMPLETE.json'
    seal,sh=load(seal_path);old,oh=load(baseline);m,mh=load(old_manifest)
    require(oh==seal['report_sha256'] and mh==seal['manifest_sha256'], 'B1 completion/hash mismatch')
    require(m==manifest, 'not the same B1 frame identities/hashes')
    validate_spatial(old,m,p)
    require(all('bench_presence' not in r for r in old['records']), 'baseline must be B1 without B2')
    require(old.get('provenance',{}).get('input_files_sha256',{}).get(str(args.profile.resolve()))==sha(args.profile), 'B1 UI identity mismatch')
    sources.update({str(baseline):oh,str(old_manifest):mh,str(seal_path):sh,str(args.presence_profile.resolve()):ph})
    verify_sources(sources)
    return p,policy,manifest,sources,old


def percentile(values,q):
    values=sorted(values);x=(len(values)-1)*q;i=int(x);j=min(i+1,len(values)-1)
    return values[i]+(values[j]-values[i])*(x-i)


def run(args):
    p,policy,manifest,sources,old=preflight(args)
    out=args.output.absolute();require(not out.exists(),'B2 output exists; no overwrite')
    out.mkdir(parents=True,exist_ok=False)
    child=argparse.Namespace(**vars(args));child.output=out/'native'
    # Existing launcher/decoder/manifest/timeout/hasher and viewer, not a copied runner.
    with redirect_stdout(io.StringIO()): report=spatial_run(child)
    metrics=validate(report,p,policy);regression=compare_legacy(old,report)
    (out/'regression.json').write_bytes(canonical(regression))
    print('BOARD2_REGRESSION='+json.dumps(regression))
    require(regression['b1_observations_unchanged'],'B1 observations changed; inspect native report; B2 not sealed')
    verify_sources(sources)
    times=[r['bench_presence_scan_ms'] for r in report['records']]
    combined=[r['decode_and_both_scans_ms'] for r in report['records']]
    summary=dict(schema_version=1,policy='bench_presence_hypotheses_v1',profile=policy['id'],frames=len(manifest['frames']),
        **metrics,b1_observations_unchanged=True,bench_slots_per_frame=9,
        presence_scan_ms_p50=percentile(times,.5),presence_scan_ms_p95=percentile(times,.95),
        decode_and_both_scans_ms_p50=percentile(combined,.5),decode_and_both_scans_ms_p95=percentile(combined,.95),
        execution_complete=True,ocr_process_calls=0,exact_accuracy=None,labels_used=False,
        temporal_confirmation=False,unit_identity_established=False,ground_assignment_established=False,
        ownership_established=False,game_state_updated=False,model_trained=False,profile_promoted=False,
        backend_versions_frozen=False,metric_kind='bench_image_level_hypotheses_same_recording',
        warning='Not validated occupancy accuracy. Local structural match does not identify owner/phase; B1 guide/board states unchanged.')
    result=dict(summary=summary,regression=regression,records=report['records'],
        provenance=dict(input_files_sha256=sources,native_report_sha256=sha(out/'native/report.json'),
            baseline_report=str(args.baseline.resolve()),same_recording_development=True))
    (out/'report.json').write_bytes(canonical(result))
    (out/'COMPLETE.json').write_bytes(canonical(dict(report_sha256=sha(out/'report.json'),
        native_report_sha256=sha(out/'native/report.json'),viewer_sha256=sha(out/'native/viewer.html'))))
    for r in report['records']:
        x=r['bench_presence']
        print('BOARD2_FRAME='+json.dumps(dict(timestamp_ms=x['timestamp_ms'],surface=x['surface_status'],
            statuses=dict(Counter(s['status'] for s in x['slots'])),
            occupied_slots=[s['slot'] for s in x['slots'] if s['occupancy'] is True],
            empty_slots=[s['slot'] for s in x['slots'] if s['occupancy'] is False],scan_ms=r['bench_presence_scan_ms'])))
    print('BOARD2_SUMMARY='+json.dumps(summary))
    print('BOARD2_REPORT='+str(out/'report.json'))
    print('BOARD2_VIEWER='+str(out/'native/viewer.html'))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('baseline','manifest','image-root','profile','presence-profile','board-topology','bench-topology','probe','output'):
        p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--preflight-only',action='store_true')
    a=p.parse_args()
    try:
        if a.preflight_only: preflight(a,with_probe=False);print('BOARD2_PREFLIGHT_OK=true')
        else: run(a)
    except (ValueError,OSError,KeyError,TypeError,subprocess.TimeoutExpired) as e: p.exit(2,f'BOARD2_ERROR={e}\n')


if __name__=='__main__': main()
