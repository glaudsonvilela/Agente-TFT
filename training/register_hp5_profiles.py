"""Import verified HP5 + inherited HP4 evidence into the persistent A1.4 registry.

No video/image decode, OCR, label assignment, binary execution or activation.
The native executable/config are rehashed; media pixels are NOT revalidated.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from training.perception_registry import Registry, canonical, hash_value, require


def prepare_import(source: Path, root: Path, profile: Path, probe: Path) -> dict:
    from training import player_hp_disjoint_shadow as hp5
    from training.player_hp_candidate_audit import build_review, review_batch

    root = root.resolve(strict=True)
    source = source.resolve(strict=True)
    if source.is_file():
        require(source.name == 'report.json', 'expected HP5 report.json')
        source = source.parent
    elif (source/'run'/'COMPLETE.json').is_file():
        source = (source/'run').resolve(strict=True)
    require(source.is_relative_to(root) and source.is_dir(), 'HP5 outside evidence root')
    fingerprints: dict[str, str] = {}
    consumed = 0

    def read(name: str) -> dict:
        nonlocal consumed
        path = hp5.within(source, source/name)
        size = path.stat().st_size
        require(size <= hp5.MAX_JSON, 'HP5 JSON byte budget exceeded')
        consumed += size
        require(consumed <= hp5.MAX_HISTORY_BYTES, 'HP5 total JSON byte budget exceeded')
        before = hp5.sha256(path)
        obj = hp5.load(path)
        require(hp5.sha256(path) == before, 'HP5 source changed during read')
        fingerprints[str(path)] = before
        return obj

    complete, plan, report = read('COMPLETE.json'), read('plan.json'), read('report.json')
    require(complete == dict(plan_sha256=fingerprints[str(source/'plan.json')],
                             report_sha256=fingerprints[str(source/'report.json')]), 'HP5 completion hashes mismatch')
    require(plan.get('policy') == hp5.POLICY and plan.get('schema_version') == 1, 'unsupported HP5 plan')
    require(plan.get('selection_uses_values') is False and plan.get('selection_frozen_before_decode') is True
            and plan.get('candidate_parameter_search') is False and plan.get('same_recording') is True
            and plan.get('independent_match') is False, 'invalid selection contract')
    inputs = plan.get('input_files_sha256')
    require(isinstance(inputs, dict) and 4 <= len(inputs) <= 32, 'invalid HP5 source fingerprints')
    audits = [Path(p) for p in inputs if Path(p).name == 'report.json'
              and str(Path(p).parent/'COMPLETE') in inputs]
    require(len(audits) == 1, 'missing/ambiguous inherited HP4 audit')
    context = hp5.source_context(audits[0], root, profile.resolve(strict=True), probe.resolve(strict=True))
    for key, value in context.items():
        require(plan.get(key) == value, 'frozen HP5 context differs from source: '+key)
    old_plan = hp5.load(Path(context['hp3'])/'plan.json')
    old_reports = {b['id']: hp5.load(Path(context['hp3'])/b['id']/'report.json') for b in old_plan['batches']}
    rebuilt, _ = build_review(old_plan, old_reports)
    require(rebuilt == {k:v for k,v in context['audit_summary'].items() if k != 'audit_id'}, 'inherited audit changed')

    windows = plan.get('windows')
    require(isinstance(windows, list) and len(windows) == 3, 'expected three frozen sequences')
    metrics, cases = [], []
    for i, window in enumerate(windows):
        key = f'sequence-{i:02d}'
        require(window.get('id') == key and type(window.get('start_ms')) is int
                and window.get('end_ms') == window['start_ms']+8000, 'invalid sequence identity/length')
        manifest, native = read(key+'/manifest.json'), read(key+'/report.json')
        require(manifest.get('labels_used') is False and manifest.get('frozen_plan_sha256') == complete['plan_sha256'],
                'sequence manifest not bound to frozen plan')
        rows = manifest.get('frames')
        require(isinstance(rows, list), 'missing sequence frames')
        timing = hp5.check_sequence(rows, window, context['excluded'])
        values, found = review_batch(dict(id=key, kind='disjoint_shadow_same_recording', frames=rows), native)
        item = dict(id=key, window=window, **values, timing=timing)
        require(read(key+'/review.json') == dict(metrics=item, cases=found), 'sequence review changed')
        metrics.append(item)
        cases.extend(found)
    require(report.get('windows') == metrics, 'HP5 windows do not match native reports')
    baseline, candidate, comparisons = Counter(), Counter(), Counter()
    for m in metrics:
        baseline.update(m['baseline_statuses']); candidate.update(m['candidate_statuses']); comparisons.update(m['comparison'])
    risks = Counter(reason for c in cases for reason in c['reasons'])
    s = report.get('summary', {})
    computed = dict(sequences=3, frames=sum(m['frames'] for m in metrics), baseline_statuses=dict(baseline),
        candidate_statuses=dict(candidate), comparison=dict(comparisons), risk_counts=dict(risks),
        baseline_confirmed_frames=sum(m['baseline_confirmed_frames'] for m in metrics),
        candidate_confirmed_frames=sum(m['candidate_confirmed_frames'] for m in metrics),
        decision=hp5.inherited_decision(context['prior_decision'], risks))
    for key, value in computed.items():
        require(s.get(key) == value, 'HP5 aggregate mismatch: '+key)
    require(s.get('schema_version') == 1 and s.get('policy') == hp5.POLICY and s.get('execution_complete') is True
            and s.get('exact_accuracy') is None and s.get('frozen_plan_sha256') == complete['plan_sha256']
            and s.get('metric_kind') == 'disjoint_shadow_same_recording', 'invalid HP5 summary')
    for key in ('labels_used','model_trained','game_state_updated','profile_promoted'):
        require(s.get(key) is False, 'non-diagnostic HP5 evidence')
    require(hash_value(plan.get('video_sha256')), 'missing recorded video hash')
    hp5.verify_inputs(context['input_files_sha256'])
    hp5.verify_inputs(fingerprints)
    return dict(
        context=dict(mode='offline_replay', subsystem='player_list', field='hp', recording_sha256=plan['video_sha256']),
        baseline=dict(reader='hp1', executable_sha256=old_plan['probe_sha256'], config_sha256=old_plan['profile_sha256']),
        candidate=dict(reader='hp_text_fit_v1', executable_sha256=old_plan['probe_sha256'], config_sha256=old_plan['profile_sha256']),
        payload=dict(hp5_summary=s, hp4_audit_id=context['audit_id'], hp4_decision=context['prior_decision'],
            hp5_file_hashes={str(Path(p).relative_to(source)): h for p,h in fingerprints.items()},
            media_identity='recorded hashes only; video/image bytes not revalidated by registry import',
            patch=None, set=None, runtime_environment_identity_complete=False),
        blockers=sorted(set(s['decision']['inherited_reasons'] +
            [k for k in ('both_readable_disagree','opposing_eligible_attempt','sign_disagreement','baseline_only_readable') if risks[k]] +
            (['historical_quarantine'] if s['decision']['review_action'] == 'quarantine_candidate' else [])))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','evidence-root','profile','probe','registry'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        # Verify every source BEFORE opening/creating the durable store.
        incoming = prepare_import(args.source, args.evidence_root, args.profile, args.probe)
        destination = args.registry.absolute()
        require(destination.parent.resolve().is_relative_to(args.evidence_root.resolve(strict=True)), 'registry outside local evidence root')
        with Registry(destination) as registry:
            receipt = registry.import_review(**incoming)
        # A new connection proves that the committed state, not a cached object,
        # supplies the persisted blocker and activation permission.
        with Registry(destination) as reopened:
            permission = reopened.permission(incoming['candidate'])
            require(reopened.inspect()['revision'] >= receipt['revision'], 'registry did not persist')
        print('A14_REGISTRY='+str(destination))
        print('A14_SUMMARY='+json.dumps(dict(**receipt, permission=permission,
            restart_read_verified=True, registry_written=receipt['changed'], ocr_executed=False,
            media_decoded=False, human_labels_required=False, runtime_connected=False)))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(2, f'A14_ERROR={exc}\n')


if __name__ == '__main__':
    main()
