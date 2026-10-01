"""HP5: frozen-reader shadow evaluation outside the previously sampled intervals.

No active profile writes, parameter search, expected HP, or training labels.
Extraction and paired read auditing reuse HP2/HP3/HP4, with their limits intact.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

POLICY = 'hp5_disjoint_frozen_pair_v1'
WINDOWS = 3
DURATION_MS = 8000
CHUNK_MS = 2000
GUARD_MS = 5000
MAX_SEQUENCE_FRAMES = 48
MAX_TOTAL_FRAMES = 144
MAX_JSON = 16 * 1024 * 1024
MAX_HISTORY_BYTES = 64 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}')


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict:
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key')
            out[key] = value
        return out
    with path.open('rb') as f:
        data = f.read(MAX_JSON + 1)
    require(len(data) <= MAX_JSON, 'JSON byte budget exceeded')
    obj = json.loads(data, object_pairs_hook=pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    require(isinstance(obj, dict), 'expected JSON object')
    return obj


def write(path: Path, obj: Any) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def within(root: Path, path: Path) -> Path:
    result = path.resolve(strict=True)
    require(result.is_relative_to(root.resolve(strict=True)), 'path outside evidence root')
    return result


def merged(ranges: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted(ranges):
        require(type(a) is int and type(b) is int and 0 <= a < b, 'invalid interval')
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def exclusions(plan: dict) -> list[list[int]]:
    """Uses ONLY sample identity/time, not old statuses or numeric predictions."""
    batches = plan.get('batches')
    require(isinstance(batches, list) and 1 <= len(batches) <= 11, 'invalid HP3 batches')
    ranges, ids, total = [], set(), 0
    for batch in batches:
        key, kind, rows = batch.get('id'), batch.get('kind'), batch.get('frames')
        require(isinstance(key, str) and key not in ids, 'invalid/duplicate batch id')
        require((kind == 'targeted_dense' and re.fullmatch(r'window-\d{2}', key) is not None)
                or (kind == 'sparse_regression' and key == 'sparse-regression'), 'invalid batch kind')
        ids.add(key)
        require(isinstance(rows, list) and 1 <= len(rows) <= 128, 'invalid previous frame budget')
        total += len(rows)
        require(total <= 160, 'previous total frame budget exceeded')
        times = [row.get('timestamp_ms') for row in rows]
        require(all(type(t) is int and 0 <= t <= 86_400_000 for t in times), 'invalid old timestamp')
        require(all(a < b for a, b in zip(times, times[1:])), 'repeated/unordered old timestamps')
        intervals = [(times[0], times[-1])] if kind == 'targeted_dense' else [(t, t) for t in times]
        ranges.extend([max(0, a-GUARD_MS), b+GUARD_MS+1] for a, b in intervals)
    return merged(ranges)


def select_windows(duration_ms: int, excluded: list[list[int]]) -> list[dict]:
    """One centered clip in the largest eligible gap of each temporal third.

    Ties prefer the earlier gap. No retries or reselection after viewing outputs.
    """
    require(type(duration_ms) is int and 0 < duration_ms <= 86_400_000, 'invalid duration')
    excluded = merged(excluded)
    result = []
    for i in range(WINDOWS):
        lo = max(GUARD_MS, duration_ms*i//WINDOWS)
        hi = min(duration_ms-GUARD_MS, duration_ms*(i+1)//WINDOWS)
        free, cursor = [], lo
        for a, b in excluded:
            if b <= cursor or a >= hi:
                continue
            if a > cursor:
                free.append((cursor, min(a, hi)))
            cursor = max(cursor, b)
        if cursor < hi:
            free.append((cursor, hi))
        free = [(a, b) for a, b in free if b-a >= DURATION_MS]
        require(bool(free), 'insufficient disjoint interval in a temporal third; no fallback to old frames')
        a, b = min(free, key=lambda p: (-(p[1]-p[0]), p[0]))
        start = (a+b-DURATION_MS)//2
        result.append(dict(id=f'sequence-{i:02d}', start_ms=start, end_ms=start+DURATION_MS,
                           center_ms=start+DURATION_MS//2, eligible_gap=[a, b]))
    return result


def check_sequence(rows: list[dict], window: dict, excluded: list[list[int]]) -> dict:
    require(24 <= len(rows) < MAX_SEQUENCE_FRAMES, 'incomplete/excessive sequence frames')
    times, previous, seen = [], None, set()
    for row in rows:
        require(type(row.get('source_pts')) is int, 'missing decoded PTS')
        base = Fraction(row['source_time_base'])
        require(base > 0, 'invalid source time base')
        exact = row['source_pts'] * base * 1000
        at = row.get('timestamp_ms')
        require(type(at) is int and at == math.ceil(exact), 'timestamp does not equal decoded PTS')
        require(window['start_ms'] <= exact < window['end_ms'], 'decoded PTS outside frozen window')
        require(not any(a <= exact < b for a, b in excluded), 'decoded PTS overlaps prior evidence guard')
        if previous is not None:
            require(250 <= exact-previous <= 500, 'source cadence/gap outside dense evaluation limits')
        image, checksum = row.get('image'), row.get('sha256')
        require(isinstance(image, str) and not Path(image).is_absolute() and '..' not in Path(image).parts
                and image not in seen, 'unsafe/duplicate source image')
        require(isinstance(checksum, str) and SHA.fullmatch(checksum) is not None, 'missing image hash')
        require(isinstance(row.get('decoded_checksum'), str), 'missing decoded checksum')
        seen.add(image); times.append(exact); previous = exact
    require(times[0]-window['start_ms'] <= 500 and window['end_ms']-times[-1] <= 500,
            'source sequence truncated at an edge')
    return dict(frames=len(rows), max_gap_ms=float(max(b-a for a, b in zip(times, times[1:]))),
                repeated_decoded_checksums=len(rows)-len({r['decoded_checksum'] for r in rows}),
                timestamp_basis='decoded source PTS; distinct time is not independent visual evidence')


def inherited_decision(previous: dict, risks: dict) -> dict:
    # New easy sequences must NEVER erase an unresolved previous conflict.
    severe = any(risks.get(k, 0) for k in ('both_readable_disagree', 'opposing_eligible_attempt', 'sign_disagreement'))
    quarantine = previous.get('review_action') == 'quarantine_candidate' or severe
    return dict(review_action='quarantine_candidate' if quarantine else 'hold_candidate',
                inherited_review_action=previous.get('review_action'), inherited_reasons=previous.get('reasons', []),
                active_action='retain_baseline', active_profile_written=False,
                candidate_activation_blocked=True, baseline_correctness_established=False,
                requires_new_shadow_evaluation=True, human_labels_required=False,
                note='new disjoint data cannot clear historical blockers or establish accuracy')


def source_context(audit_path: Path, evidence_root: Path, profile: Path, probe: Path) -> dict:
    root = evidence_root.resolve(strict=True)
    audit_path = within(root, audit_path)
    require(audit_path.is_file(), 'require audit/report.json from HP4')
    obj = load(audit_path)
    s, provenance = obj['summary'], obj['provenance']
    require(s.get('audit_policy') == 'hp3_paired_evidence_review_v1' and s.get('execution_complete') is True,
            'require complete HP4 audit')
    for name in ('labels_used', 'game_state_updated', 'profile_promoted', 'model_trained', 'ocr_executed'):
        require(s.get(name) is False, 'non-diagnostic HP4 history')
    require(s.get('decision', {}).get('active_action') == 'retain_baseline', 'unsupported active action')
    fingerprints = provenance['input_files_sha256']
    require(isinstance(fingerprints, dict) and 4 <= len(fingerprints) <= 24, 'invalid history fingerprints')
    expected_id = hashlib.sha256(canonical(dict(policy=s['audit_policy'], inputs=fingerprints))).hexdigest()
    require(expected_id == s.get('audit_id'), 'audit id mismatch')
    marker = within(root, audit_path.parent/'COMPLETE')
    require(marker.stat().st_size <= 128 and marker.read_text().strip() == expected_id, 'missing/wrong HP4 completion marker')
    hp3 = within(root, Path(provenance['source']))
    files, total = {}, 0
    for name, digest in fingerprints.items():
        require(isinstance(name, str) and re.fullmatch(r'(plan\.json|report\.json|(window-\d{2}|sparse-regression)/(manifest|report)\.json)', name) is not None,
                'unsafe historical fingerprint path')
        require(isinstance(digest, str) and SHA.fullmatch(digest) is not None, 'bad historical hash')
        path = within(hp3, hp3/name)
        require(path.is_file() and path.stat().st_size <= MAX_JSON, 'excessive historical file')
        total += path.stat().st_size
        require(total <= MAX_HISTORY_BYTES and sha256(path) == digest, 'historical evidence changed')
        files[str(path)] = digest
    plan = load(hp3/'plan.json')
    require('plan.json' in fingerprints and 'report.json' in fingerprints, 'missing history roots')
    for b in plan.get('batches', []):
        require(all(b['id']+'/'+n in fingerprints for n in ('manifest.json', 'report.json')), 'unaudited historical batch')
    excluded = exclusions(plan)
    for path, field in ((profile, 'profile_sha256'), (probe, 'probe_sha256')):
        require(path.is_file(), 'frozen reader/profile missing')
        digest = sha256(path)
        require(digest == plan.get(field) == provenance.get('recorded_'+field),
                'frozen profile/binary hash changed; do not silently evaluate another reader')
        files[str(path.resolve())] = digest
    hp2 = within(root, Path(plan['source']))
    hp2_plan = within(hp2, hp2/'plan.json')
    source = load(hp2_plan)
    files[str(hp2_plan)] = sha256(hp2_plan)
    files[str(audit_path)] = sha256(audit_path)
    files[str(marker)] = sha256(marker)
    return dict(excluded=excluded, prior_decision=s['decision'], audit_id=expected_id,
                input_files_sha256=files, prior_video=source, hp3=str(hp3), audit_summary=s)


def verify_inputs(files: dict[str, str]) -> None:
    for path, digest in files.items():
        require(sha256(Path(path)) == digest, 'input changed during frozen evaluation')


def run(args: argparse.Namespace) -> dict:
    # Lazy imports keep pure selection/validation unit tests independent of media.
    from training.player_hp_dense import extract_window, video_metadata
    from training.player_hp_text_fit import run_child
    from training.player_hp_candidate_audit import build_review, review_batch

    video, profile, probe = (p.resolve(strict=True) for p in (args.video, args.profile, args.probe))
    context = source_context(args.audit, args.evidence_root, profile, probe)
    previous_plan = load(Path(context['hp3'])/'plan.json')
    previous_reports = {b['id']: load(Path(context['hp3'])/b['id']/'report.json') for b in previous_plan['batches']}
    rebuilt, _ = build_review(previous_plan, previous_reports)
    require(rebuilt == {k: v for k, v in context['audit_summary'].items() if k != 'audit_id'},
            'HP4 decision/summary differs from its fingerprinted source records')
    require(video.is_file(), 'require local recording')
    old_video = context['prior_video']
    require(video == Path(old_video['source_video']).resolve(strict=True), 'video path differs from HP2 history')
    require((video.stat().st_size, video.stat().st_mtime_ns) == (old_video['video_size'], old_video['video_mtime_ns']),
            'video size/mtime changed since HP2; identity needs reconciliation')
    meta = video_metadata(video)
    duration = math.floor(float(meta['format']['duration'])*1000)
    windows = select_windows(duration, context['excluded'])
    video_hash = sha256(video)  # New content identity; cannot retroactively certify HP2 bytes.
    out = args.output.resolve()
    require(out.is_relative_to(args.evidence_root.resolve(strict=True))
            and not out.is_relative_to(Path(context['hp3']))
            and not out.is_relative_to(args.audit.resolve().parent), 'unsafe output location')
    out.mkdir(exist_ok=False)
    freeze = dict(schema_version=1, policy=POLICY, windows=windows, exclusion_guard_ms=GUARD_MS,
                  **context, video=str(video), video_sha256=video_hash,
                  prior_video_identity='HP2 size/mtime only; new SHA256 is not retrospective identity proof',
                  selection_uses_values=False, selection_frozen_before_decode=True,
                  candidate_parameter_search=False, same_recording=True, independent_match=False)
    write(out/'plan.json', freeze)
    plan_hash = sha256(out/'plan.json')
    print('HP5_PLAN='+json.dumps(dict(plan_sha256=plan_hash, windows=windows)), flush=True)
    metrics, all_cases = [], []
    for window in windows:
        verify_inputs(context['input_files_sha256'])
        folder = out/window['id']; folder.mkdir()
        rows = []
        for j, start in enumerate(range(window['start_ms'], window['end_ms'], CHUNK_MS)):
            chunk = folder/f'chunk-{j:02d}'
            bounds = dict(id=chunk.name, start_ms=start, center_ms=start+CHUNK_MS//2, end_ms=start+CHUNK_MS)
            print(f"HP5_EXTRACT={window['id']}/{chunk.name}", flush=True)
            m = extract_window(video, bounds, chunk, duration)
            for r in m['frames']:
                rows.append({**r, 'image': str(Path(chunk.name)/r['image'])})
        timing = check_sequence(rows, window, context['excluded'])
        require(sum(m['frames'] for m in metrics)+len(rows) <= MAX_TOTAL_FRAMES, 'total frame budget exceeded')
        manifest = dict(frames=rows, time_basis='decoded source PTS', labels_used=False, frozen_plan_sha256=plan_hash)
        write(folder/'manifest.json', manifest)
        command = [str(probe), str(folder/'manifest.json'), str(folder), str(profile), str(folder/'report.json')]
        write(folder/'command.json', command)
        # One native process/tracker pair for all four adjacent chunks; reset between sequences.
        print('HP5_RUN='+window['id'], flush=True)
        run_child(command, folder/'events.jsonl', folder/'probe.stderr', timeout=120)
        for row in rows:
            require(sha256(within(folder, folder/row['image'])) == row['sha256'], 'new source image changed')
        report = load(folder/'report.json')
        batch = dict(id=window['id'], kind='disjoint_shadow_same_recording', frames=rows)
        values, cases = review_batch(batch, report)
        entry = dict(id=window['id'], window=window, **values, timing=timing)
        metrics.append(entry); all_cases.extend(cases)
        write(folder/'review.json', dict(metrics=entry, cases=cases))
        print('HP5_WINDOW='+json.dumps(entry), flush=True)
    verify_inputs(context['input_files_sha256'])
    require(sha256(video) == video_hash and sha256(out/'plan.json') == plan_hash, 'video/frozen plan changed')
    risks = Counter(reason for case in all_cases for reason in case['reasons'])
    baseline, candidate, comparisons = Counter(), Counter(), Counter()
    for m in metrics:
        baseline.update(m['baseline_statuses']); candidate.update(m['candidate_statuses']); comparisons.update(m['comparison'])
    summary = dict(schema_version=1, policy=POLICY, sequences=len(metrics), frames=sum(m['frames'] for m in metrics),
                   baseline_statuses=dict(baseline), candidate_statuses=dict(candidate), comparison=dict(comparisons),
                   baseline_confirmed_frames=sum(m['baseline_confirmed_frames'] for m in metrics),
                   candidate_confirmed_frames=sum(m['candidate_confirmed_frames'] for m in metrics),
                   risk_counts=dict(risks), decision=inherited_decision(context['prior_decision'], risks),
                   execution_complete=True, labels_used=False, exact_accuracy=None, model_trained=False,
                   game_state_updated=False, profile_promoted=False, frozen_plan_sha256=plan_hash,
                   metric_kind='disjoint_shadow_same_recording',
                   warning='temporal disjointness is not independent-match accuracy; historical quarantine persists')
    with (out/'cases.jsonl').open('x', encoding='utf-8') as f:
        for case in all_cases:
            f.write(canonical(case).decode()+'\n')
    write(out/'report.json', dict(summary=summary, windows=metrics))
    write(out/'COMPLETE.json', dict(report_sha256=sha256(out/'report.json'), plan_sha256=plan_hash))
    print('HP5_SUMMARY='+json.dumps(summary), flush=True)
    print('HP5_REPORT='+str(out/'report.json'), flush=True)
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('audit', 'evidence-root', 'video', 'profile', 'probe', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    try:
        run(args)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        p.exit(2, f'HP5_ERROR={exc}\n')


if __name__ == '__main__':
    main()
