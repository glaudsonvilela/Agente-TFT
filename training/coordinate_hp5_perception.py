"""Verify registered HP5 evidence and exercise the A1.5 control plane, no OCR.

This command replays existing status records, not video. Already evaluated data
must produce zero new work intents. It does not change A14 or dispatch a worker.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time

from training.perception_registry import Registry, canonical, context_key, digest, profile_key, require
from training.perception_coordinator import Coordinator, validate_samples


def prepare(source: Path, root: Path, profile: Path, probe: Path) -> tuple[dict, str, list[dict]]:
    from training.register_hp5_profiles import prepare_import
    from training import player_hp_disjoint_shadow as hp5
    incoming = prepare_import(source,root,profile,probe)
    source = source.resolve(strict=True)
    if source.is_file(): source=source.parent
    elif (source/'run'/'COMPLETE.json').is_file(): source=(source/'run').resolve(strict=True)
    fingerprints = incoming['payload']['hp5_file_hashes']

    def read(name: str) -> dict:
        path = hp5.within(source,source/name)
        require(name in fingerprints and hp5.sha256(path)==fingerprints[name], 'source changed after verification')
        value=hp5.load(path)
        require(hp5.sha256(path)==fingerprints[name], 'source changed while reading')
        return value

    sequences=[]
    for w in read('plan.json')['windows']:
        key=w['id']
        frames=read(key+'/manifest.json')['frames']; records=read(key+'/report.json')['records']
        require(len(frames)==len(records), 'sequence size changed')
        samples=[]
        for f,r in zip(frames,records):
            b=r['baseline']; location=b['location']
            count=len(location['candidates'])
            marker=('unknown' if location['budget_exceeded'] else
                    'unique' if count==1 else 'missing' if count==0 else 'ambiguous')
            require(f['timestamp_ms']==r['timestamp_ms']==b['timestamp_ms'], 'sample identity mismatch')
            samples.append(dict(timestamp_ms=f['timestamp_ms'],image_sha256=f['sha256'],status=b['status'],marker=marker))
        validate_samples(samples)
        sequences.append(dict(id=key,samples=samples))
    for name,checksum in fingerprints.items():
        require(hp5.sha256(hp5.within(source,source/name))==checksum, 'source changed before scheduling')
    review=dict(context_key=context_key(incoming['context']),baseline_key=profile_key(incoming['baseline']),
                candidate_key=profile_key(incoming['candidate']),blockers=sorted(set(incoming['blockers'])),evidence=incoming['payload'])
    return incoming,digest(review),sequences


def run(args: argparse.Namespace) -> dict:
    root=args.evidence_root.resolve(strict=True)
    source=args.source.resolve(strict=True)
    source_folder=source.parent if source.is_file() else source
    registry=args.registry.absolute();database=args.database.absolute();output=args.output.absolute()
    require(registry.is_file(), 'A14 registry absent; run register_match001_perception.sh first')
    for path in (registry,database,output):
        require(path.parent.resolve(strict=True).is_relative_to(root), 'destination outside evidence root')
        require(not path.is_symlink(), 'symlink destination not supported')
    require(not database.resolve().is_relative_to(source_folder) and
            not output.resolve().is_relative_to(source_folder), 'destination inside source evidence')
    require(not output.exists(), 'output already exists; no overwrite')
    require(output.resolve()!=database.resolve() and output.resolve()!=registry.resolve(), 'destination collision')
    incoming,eid,sequences=prepare(source,root,args.profile,args.probe)
    with Registry(registry) as r:
        before=r.inspect()
        require(eid in before['snapshot']['reviews'], 'this HP5 evidence is not registered; import A14 first')
    # Output opened exclusively before durable decisions; a failed report write
    # cannot create duplicate reservations on retry (request ids are content-based).
    with output.open('x',encoding='utf-8') as out:
        receipts=[]
        clock=time.time_ns()//1_000_000
        with Coordinator(registry,database) as c:
            for seq in sequences:
                receipt=c.assess(incoming['context'],incoming['baseline'],incoming['candidate'],
                                 seq['samples'],clock,completed_evidence_id=eid)
                receipts.append(dict(sequence=seq['id'],**receipt))
                print('A15_SEQUENCE='+json.dumps(dict(sequence=seq['id'],
                    signal=receipt['decision']['signal']['state'],action=receipt['decision']['action'],
                    samples=receipt['decision']['signal']['samples'],changed=receipt['changed'],
                    intent_created=receipt['intent_created'],candidate_blockers=receipt['current_blockers'])),flush=True)
            state=c.inspect()
        with Coordinator(registry,database) as reopened:
            restored=reopened.inspect()
            require(restored['revision']>=state['revision'] and all(
                r['decision']['request_id'] in restored['decisions'] for r in receipts), 'ledger restart verification failed')
            after=reopened.registry.inspect()
            permission=reopened.registry.permission(incoming['candidate'])
        summary=dict(schema_version=1,policy='a15_diagnostic_coordinator_v1',source_evidence_id=eid,
            sequences=len(receipts),frames=sum(len(s['samples']) for s in sequences),
            actions=dict(Counter(r['decision']['action'] for r in receipts)),
            signals=dict(Counter(r['decision']['signal']['state'] for r in receipts)),
            decisions_written=sum(r['changed'] for r in receipts),
            intents_created=sum(r['intent_created'] for r in receipts),
            ledger_revision=restored['revision'],registry_revision=after['revision'],
            registry_unchanged_during_check=before==after,registry_written=False,
            permission=permission,coordinator_db=str(database),restart_read_verified=True,
            worker_executed=False,ocr_executed=False,media_decoded=False,
            runtime_connected=False,game_state_updated=False,model_trained=False,profile_promoted=False,
            note='verified report replay; visibility cause not inferred; reservation is not execution')
        json.dump(dict(summary=summary,sequences=receipts),out,indent=2,allow_nan=False);out.write('\n')
    print('A15_COORDINATOR='+str(database))
    print('A15_SUMMARY='+json.dumps(summary))
    print('A15_REPORT='+str(output))
    return summary


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','evidence-root','profile','probe','registry','database','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    try:
        run(parser.parse_args())
    except (ValueError,OSError,KeyError,TypeError,sqlite3.Error) as exc:
        parser.exit(2,f'A15_ERROR={exc}\n')

if __name__=='__main__':main()
