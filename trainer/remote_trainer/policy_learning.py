"""Bounded status reader for the separate simulation worker; never loads tensors."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time


def small_json(path):
    if path.is_symlink() or path.stat().st_size > 128 * 1024:
        raise ValueError('Invalid status file')
    return json.loads(path.read_text())


def policy_learning_jobs(db_path: Path | None):
    if db_path is None:
        return []
    root = Path(db_path).parent / 'policy-runs'
    jobs = []
    for folder in sorted(root.glob('*'), reverse=True)[:10]:
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            progress = small_json(folder / 'progress.json')
            if progress.get('kind') != 'policy_selfplay' or progress.get('runtime_promoted') is not False:
                continue
            row = {k: progress.get(k) for k in ['status', 'scope', 'iterations', 'transitions',
                'matches_completed', 'optimizer_steps', 'changed_parameter_tensors', 'combat_calls',
                'elapsed_seconds', 'peak_rss_mib', 'process_cpu_seconds', 'cpu_threads',
                'checkpoint_iteration', 'updated_at_ms', 'reason', 'error']}
            row['matches_goal'] = progress.get('matches_goal')
            row.update(id=folder.name, current_patch_training_ready=False,
                       runtime_promoted=False, training_improvement_proven=False,
                       checkpoint_verified=False)
            if row['status'] in ('initializing', 'collecting', 'optimizing', 'checkpoint_saved'):
                if time.time() - (folder / 'progress.json').stat().st_mtime > 60:
                    row['status'] = 'progress_not_recent'
            seal_path = folder / 'checkpoint.json'
            if seal_path.exists():
                seal = small_json(seal_path)
                name = seal['path']
                if Path(name).name != name:
                    raise ValueError('Unsafe checkpoint path')
                checkpoint = folder / name
                if checkpoint.is_symlink() or checkpoint.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError('Invalid checkpoint')
                # Hash only; do not unpickle even user-uploaded local artifacts.
                row['checkpoint_verified'] = hashlib.sha256(checkpoint.read_bytes()).hexdigest() == seal['sha256']
            jobs.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return jobs


def simulation_coverage(db_path: Path | None):
    if db_path is None:
        return None
    try:
        report = small_json(Path(db_path).parent / 'simulation-coverage.json')
        if report.get('kind') != 'simulation_coverage':
            return None
        return {k: report.get(k) for k in ['set_key', 'patch', 'champions',
            'champions_with_complete_stats', 'champions_with_numeric_ability_variables',
            'executable_abilities', 'current_patch_training_ready', 'blockers']}
    except (OSError, ValueError, TypeError):
        return None


def scene_learning_jobs(db_path: Path | None):
    """Report heldout errors and artifact integrity without loading the network."""
    if db_path is None:
        return []
    jobs = []
    for folder in sorted((Path(db_path).parent / 'vision-runs').glob('*'), reverse=True)[:10]:
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            report = small_json(folder / 'report.json')
            if (not isinstance(report, dict) or report.get('kind') != 'scene_gate_training'
                    or report.get('scope') != 'board_visible_only'):
                continue
            matrix = report.get('confusion_matrix')
            if (not isinstance(matrix, list) or len(matrix) != 2
                    or any(not isinstance(r, list) or len(r) != 2 for r in matrix)
                    or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for r in matrix for v in r)
                    or sum(sum(r) for r in matrix) != report.get('holdout_frames')
                    or matrix[0][0] + matrix[1][1] != report.get('holdout_correct')):
                continue
            model = folder / 'scene-gate.onnx'
            if model.is_symlink() or model.stat().st_size > 2 * 1024 * 1024:
                continue
            row = {k: report.get(k) for k in ['status', 'train_frames', 'holdout_frames',
                'train_matches', 'holdout_matches', 'holdout_correct', 'holdout_accuracy',
                'confusion_matrix', 'optimizer_steps', 'changed_parameter_tensors',
                'model_bytes', 'parameter_count', 'inference_cpu_ms_p95', 'timing_scope',
                'peak_rss_mib', 'training_seconds', 'limitations']}
            row.update(id=folder.name, runtime_promoted=False, strategic_learning=False,
                       human_verified=report.get('human_verified') is True,
                       artifact_verified=hashlib.sha256(model.read_bytes()).hexdigest() == report.get('model_sha256'))
            jobs.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return jobs
