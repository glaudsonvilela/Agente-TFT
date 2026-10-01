"""HP4: review existing paired HP3 evidence, without OCR, labels or activation."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

STATUSES = {'accepted', 'negative_display', 'badge_not_found', 'badge_ambiguous',
            'ocr_uncertain', 'ocr_conflict', 'search_budget_exceeded', 'read_error'}
READABLE = {'accepted', 'negative_display'}
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def integer(x: Any, lo: int, hi: int) -> bool:
    return type(x) is int and lo <= x <= hi


def number(x: Any, lo: float, hi: float) -> bool:
    return type(x) in (int, float) and math.isfinite(x) and lo <= x <= hi


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def unique_keys(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def signed(text: Any) -> int | None:
    if not isinstance(text, str) or len(text) > 32:
        return None
    compact = ''.join(text.split())
    if not re.fullmatch(r'-?[0-9]{1,3}', compact):
        return None
    value = int(compact)
    return value if -300 <= value <= 300 else None


def check_read(read: dict, at: int) -> None:
    require(isinstance(read, dict), 'read must be an object')
    require(read.get('timestamp_ms') == at and read.get('frame_id') == at, 'read identity mismatch')
    status = read.get('status')
    require(status in STATUSES, 'unknown read status')
    attempts = read.get('attempts')
    require(isinstance(attempts, list) and len(attempts) <= 2, 'invalid attempt budget')
    scales = set()
    eligible = []
    for a in attempts:
        require(isinstance(a, dict) and a.get('scale') in (3, 4), 'invalid OCR scale')
        require(a['scale'] not in scales, 'duplicate OCR scale')
        scales.add(a['scale'])
        c, parsed = a.get('confidence'), a.get('parsed_signed')
        require(c is None or number(c, 0, 1), 'invalid attempt confidence')
        require((parsed is None or integer(parsed, -300, 300)) and parsed == signed(a.get('text')), 'attempt text/value mismatch')
        if a.get('reason') == 'candidate':
            require(integer(parsed, -300, 300) and number(c, .70, 1)
                    and a.get('error') is None, 'ineligible OCR attempt')
            eligible.append(parsed)
    location = read.get('location')
    require(isinstance(location, dict) and isinstance(location.get('candidates'), list), 'missing location')
    require(type(location.get('budget_exceeded')) is bool, 'missing search budget flag')
    require(len(location['candidates']) <= 4096, 'excessive location candidates')
    if status in READABLE:
        value, conf = read.get('signed_hp'), read.get('confidence')
        require(integer(value, -300, 300) and number(conf, .70, 1), 'invalid accepted read')
        require(len(eligible) == 2 and eligible == [value, value], 'accept without two matching eligible scales')
        require(len(location['candidates']) == 1 and not location['budget_exceeded'], 'accept without unique marker')
        require(read.get('error') is None, 'accepted operational error')
        require(abs(conf - min(a['confidence'] for a in attempts)) < 1e-6, 'accepted confidence mismatch')
        require((value >= 0 and status == 'accepted' and type(read.get('hp')) is int and read['hp'] == value)
                or (value < 0 and status == 'negative_display' and read.get('hp') is None), 'signed/unsigned HP mismatch')
    else:
        require(all(read.get(k) is None for k in ('signed_hp', 'hp', 'confidence')), 'unreadable value leaked')
    if status == 'ocr_conflict':
        require(len(eligible) == 2 and eligible[0] != eligible[1], 'conflict without conflicting eligible scales')
    if status == 'read_error':
        require(isinstance(read.get('error'), str) and bool(read['error']), 'missing operational error detail')
    else:
        require(read.get('error') is None and all(a.get('error') is None for a in attempts), 'hidden backend error')


def replay_freshness(reads: list[dict]) -> list[dict]:
    """Audit HP1's existing 750/1500ms contract; never fill or correct a read."""
    last, pending, good = None, None, None
    results = []
    for r in reads:
        at = r['timestamp_ms']
        if last is not None and at - last > 750:
            pending = None
        last = at
        current = None
        if r['status'] == 'accepted':
            hp, conf = r['hp'], r['confidence']
            count, conf = (pending[1] + 1, min(pending[2], conf)) if pending and pending[0] == hp else (1, conf)
            pending = (hp, count, conf)
            if count >= 2:
                current = dict(value=hp, confidence=conf, observed_at_ms=at)
                good = current.copy()
        else:
            pending = None
        age = at - good['observed_at_ms'] if good else None
        results.append(dict(current=current, last_good=good.copy() if good else None,
                            age_ms=age, stale=age is None or age > 1500,
                            confirmations=pending[1] if pending else 0))
    return results


def classify(b: dict, c: dict) -> str:
    rb, rc = b['status'] in READABLE, c['status'] in READABLE
    if rb and rc:
        return 'both_readable_equal' if b['signed_hp'] == c['signed_hp'] else 'both_readable_disagree'
    return 'baseline_only_readable' if rb else 'candidate_only_readable' if rc else 'neither_readable'


def review_batch(batch: dict, report: dict) -> tuple[dict, list[dict]]:
    frames, rows, s = batch['frames'], report.get('records'), report.get('summary', {})
    require(isinstance(rows, list) and len(rows) == len(frames), 'record count mismatch')
    for key in ('labels_used', 'game_state_updated', 'profile_promoted', 'model_trained'):
        require(s.get(key) is False, 'non-diagnostic source')
    require(s.get('exact_accuracy') is None and s.get('execution_complete') is True, 'incomplete source')
    require(s.get('baseline_profile') == 'match001-self-badge-v1'
            and s.get('candidate_profile') == 'hp_text_fit_v1', 'unsupported reader pair')
    bc, cc, comp, cases = Counter(), Counter(), Counter(), []
    previous_readable = {}
    for frame, row in zip(frames, rows):
        at = frame['timestamp_ms']
        require(row.get('timestamp_ms') == at, 'paired record order mismatch')
        b, c = row['baseline'], row['candidate']
        check_read(b, at); check_read(c, at)
        require(b['location'] == c['location'], 'text fitting changed marker localization')
        cls = classify(b, c)
        require(row.get('comparison') == cls, 'paired classification mismatch')
        bc[b['status']] += 1; cc[c['status']] += 1; comp[cls] += 1
        for name in ('baseline_ms', 'candidate_ms', 'decode_ms'):
            require(number(row.get(name), 0, 120_000), 'invalid measured duration')
        reasons = []
        if cls != 'both_readable_equal':
            reasons.append(cls)
        # Partial, high-confidence opposing attempts are not hidden by a final
        # unknown/conflict on that side. They are warning evidence, NOT labels.
        for accepted, other in ((b, c), (c, b)):
            if accepted['status'] not in READABLE:
                continue
            for a in other['attempts']:
                if a['reason'] == 'candidate' and a['parsed_signed'] != accepted['signed_hp']:
                    reasons.append('opposing_eligible_attempt')
                    if (a['parsed_signed'] < 0) != (accepted['signed_hp'] < 0):
                        reasons.append('sign_disagreement')
        increases = []
        for side, read in (('baseline', b), ('candidate', c)):
            if read['status'] not in READABLE:
                continue
            previous = previous_readable.get(side)
            if previous and read['signed_hp'] > previous['value']:
                reasons.append('observed_increase_not_proven_error')
                increases.append(dict(reader=side, from_value=previous['value'],
                                      from_ms=previous['timestamp_ms'], to_value=read['signed_hp'],
                                      to_ms=at, gap_ms=at-previous['timestamp_ms']))
            previous_readable[side] = dict(value=read['signed_hp'], timestamp_ms=at)
        if reasons:
            item = dict(batch=batch['id'], kind=batch['kind'], timestamp_ms=at,
                        image=frame['image'], image_sha256=frame['sha256'],
                        reasons=sorted(set(reasons)), comparison=cls,
                        baseline=b, candidate=c, text_fit=row.get('text_fit', []),
                        observed_increases=increases, target_hp=None, eligible_for_training=False)
            item['case_id'] = hashlib.sha256(canonical(item)).hexdigest()
            cases.append(item)
    counts = {}
    for side in ('baseline', 'candidate'):
        expected = replay_freshness([r[side] for r in rows])
        require(all(r.get(side+'_freshness') == f for r, f in zip(rows, expected)), 'temporal evidence mismatch')
        counts[side+'_confirmed_frames'] = sum(f['current'] is not None for f in expected)
    metrics = dict(frames=len(rows), baseline_statuses=dict(bc), candidate_statuses=dict(cc), comparison=dict(comp), **counts)
    for key, value in metrics.items():
        require(s.get(key) == value, 'batch summary differs from records: '+key)
    errors = sum('read_error' in (r['baseline']['status'], r['candidate']['status']) for r in rows)
    require(type(s.get('errors')) is int and s['errors'] == errors, 'operational error count mismatch')
    return metrics, cases


def build_review(plan: dict, reports: dict) -> tuple[dict, list[dict]]:
    batches = plan.get('batches')
    require(isinstance(batches, list) and 1 <= len(batches) <= 11, 'require 1..11 batches')
    require(plan.get('labels_used') is False, 'labeled input not supported by diagnostic audit')
    groups, cases, seen, total = {}, [], set(), 0
    for b in batches:
        key, kind, frames = b.get('id'), b.get('kind'), b.get('frames')
        require(isinstance(key, str) and key not in seen, 'duplicate/invalid batch id')
        require((kind == 'targeted_dense' and re.fullmatch(r'window-[0-9]{2}', key) is not None)
                or (kind == 'sparse_regression' and key == 'sparse-regression'), 'unsafe batch id/kind')
        seen.add(key)
        require(isinstance(frames, list) and 1 <= len(frames) <= 128, 'frame budget invalid')
        total += len(frames); require(total <= 160, 'total frame budget exceeded')
        last, images = -1, set()
        for f in frames:
            at, image, checksum = f.get('timestamp_ms'), f.get('image'), f.get('sha256')
            require(integer(at, 0, 86_400_000) and at > last, 'duplicate/out-of-order frame time')
            require(isinstance(image, str) and image and not Path(image).is_absolute()
                    and '..' not in Path(image).parts and image not in images, 'unsafe/repeated image path')
            require(isinstance(checksum, str) and re.fullmatch('[0-9a-f]{64}', checksum) is not None, 'missing frame hash')
            images.add(image); last = at
        require(key in reports, 'missing batch report')
        metrics, batch_cases = review_batch(b, reports[key]); cases.extend(batch_cases)
        group = groups.setdefault(kind, dict(frames=0, baseline_statuses=Counter(), candidate_statuses=Counter(),
                        comparison=Counter(), baseline_confirmed_frames=0, candidate_confirmed_frames=0))
        for name in ('frames', 'baseline_confirmed_frames', 'candidate_confirmed_frames'):
            group[name] += metrics[name]
        for name in ('baseline_statuses', 'candidate_statuses', 'comparison'):
            group[name].update(metrics[name])
    require(set(reports) == seen, 'unexpected batch reports')
    risks = Counter(reason for c in cases for reason in c['reasons'])
    severe = any(risks[k] for k in ('both_readable_disagree', 'opposing_eligible_attempt', 'sign_disagreement'))
    losses = risks['baseline_only_readable']
    gains = risks['candidate_only_readable']
    action = ('quarantine_candidate' if severe else 'hold_candidate' if losses else
              'ready_for_disjoint_shadow' if gains else 'keep_baseline_no_operational_gain')
    decision = dict(review_action=action, active_action='retain_baseline',
        reasons=['retrospective_evidence_never_activates_a_profile'] +
                [key for key in ('both_readable_disagree', 'opposing_eligible_attempt', 'sign_disagreement', 'baseline_only_readable') if risks[key]],
        requires_new_shadow_evaluation=True, human_labels_required=False,
        note='availability losses are not proven semantic errors; readiness is not promotion')
    summary = dict(schema_version=1, audit_policy='hp3_paired_evidence_review_v1', batches=len(batches),
        groups=groups, case_count=len(cases), risk_counts=dict(risks), decision=decision,
        execution_complete=True, exact_accuracy=None, labels_used=False,
        game_state_updated=False, profile_promoted=False, model_trained=False, ocr_executed=False,
        metric_kind='existing_paired_evidence_audit')
    return summary, cases


def audit(source: Path, output: Path) -> dict:
    source = source.resolve(strict=True)
    require(source.is_dir(), 'source must be an HP3 directory')
    output = output.resolve()
    require(output != source and not output.is_relative_to(source), 'output must be outside source evidence')
    fingerprints, consumed = {}, 0
    def load(name: str) -> dict:
        nonlocal consumed
        path = (source/name).resolve(strict=True)
        require(path.is_relative_to(source) and path.is_file(), 'input path escaped evidence root')
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES+1)
        consumed += len(data)
        require(len(data) <= MAX_FILE_BYTES and consumed <= MAX_TOTAL_BYTES, 'JSON byte budget exceeded')
        value = json.loads(data, object_pairs_hook=unique_keys,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        require(isinstance(value, dict), 'expected JSON object')
        fingerprints[name] = hashlib.sha256(data).hexdigest()
        return value
    plan, old = load('plan.json'), load('report.json')
    require(isinstance(plan.get('batches'), list) and len(plan['batches']) <= 11, 'invalid plan')
    reports = {}
    for b in plan['batches']:
        key = b.get('id', '')
        require(isinstance(key, str) and re.fullmatch(r'(window-[0-9]{2}|sparse-regression)', key) is not None,
                'unsafe batch directory')
        require(key not in reports, 'duplicate batch directory')
        require(load(key+'/manifest.json').get('frames') == b['frames'], 'saved manifest changed')
        reports[key] = load(key+'/report.json')
    summary, cases = build_review(plan, reports)
    require(old.get('summary', {}).get('groups') == summary['groups'], 'aggregate summary mismatch')
    for key in ('labels_used', 'game_state_updated', 'profile_promoted', 'model_trained'):
        require(old['summary'].get(key) is False, 'aggregate source is not diagnostic-only')
    require(old['summary'].get('execution_complete') is True, 'aggregate source incomplete')
    # Snapshot fingerprints are audit-time identities, not signatures of the
    # original run. No source image, executable or profile is reopened here.
    provenance = dict(source=str(source), input_files_sha256=fingerprints,
        recorded_profile_sha256=plan.get('profile_sha256'), recorded_probe_sha256=plan.get('probe_sha256'),
        image_hashes='copied from HP3 plan; image bytes not rehashed by this audit')
    for name, digest in fingerprints.copy().items():
        load(name)
        require(fingerprints[name] == digest, 'source changed during audit')
    summary['audit_id'] = hashlib.sha256(canonical(dict(policy=summary['audit_policy'], inputs=fingerprints))).hexdigest()
    # Validate everything first; only then create a NEW destination.
    output.mkdir(parents=False, exist_ok=False)
    with (output/'cases.jsonl').open('x', encoding='utf-8') as stream:
        for case in cases:
            stream.write(canonical(case).decode()+'\n')
    with (output/'report.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(summary=summary, provenance=provenance), stream, indent=2, allow_nan=False)
        stream.write('\n')
    (output/'COMPLETE').write_text(summary['audit_id']+'\n', encoding='utf-8')
    for case in cases:
        if case['comparison'] == 'baseline_only_readable' or any(x in case['reasons'] for x in
                ('both_readable_disagree', 'opposing_eligible_attempt', 'sign_disagreement', 'observed_increase_not_proven_error')):
            print('HP4_CASE='+json.dumps(case, ensure_ascii=False))
    print('HP4_SUMMARY='+json.dumps(summary, ensure_ascii=False))
    print('HP4_REPORT='+str(output/'report.json'))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        audit(args.source, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'HP4_ERROR={exc}\n')


if __name__ == '__main__':
    main()
