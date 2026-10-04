"""Paired laboratory evaluation against scripted opponents, separate from training."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from .selfplay import ADAPTER, PIN, atomic_json, load_engine, sha


def evaluate(project, run, output, games=8, seconds=300):
    if not 2 <= games <= 100 or not 1 <= seconds <= 3600:
        raise ValueError('Evaluation budget outside limits')
    if output.exists():
        raise ValueError('Use a new evaluation file')
    load_engine(project.resolve())
    import numpy as np
    import torch
    from tft_goat.agent.evaluate import eval_vs_opponents
    from tft_goat.agent.network import ActorCritic
    from tft_goat.data.sample import build_sample_content
    from tft_goat.engine.resolver import EngineResolver
    from tft_goat.env.tft_env import TftEnv

    config = json.loads((run / 'config.json').read_text())
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    seal = json.loads((run / 'checkpoint.json').read_text())
    if Path(seal['path']).name != seal['path']:
        raise ValueError('Invalid checkpoint path')
    path = run / seal['path']
    if sha(path) != seal['sha256']:
        raise ValueError('Checkpoint hash mismatch')
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    if checkpoint['adapter'] != ADAPTER or checkpoint['upstream'] != PIN or checkpoint['config_sha256'] != config_hash:
        raise ValueError('Evaluation engine or config mismatch')
    torch.set_num_threads(config['threads'])
    torch.set_num_interop_threads(1)
    torch.manual_seed(config['seed'])
    start = time.monotonic()

    class BoundedEnv(TftEnv):
        def step(self, actions):
            if time.monotonic() - start > seconds:
                raise TimeoutError('Evaluation budget exhausted; no complete result published')
            return super().step(actions)

    env = BoundedEnv(set_content=build_sample_content(), resolver=EngineResolver())
    initial = ActorCritic(env.encoder.n_champ, env.encoder.n_trait, hidden_dim=128)
    candidate = ActorCritic(env.encoder.n_champ, env.encoder.n_trait, hidden_dim=128)
    candidate.load_state_dict(checkpoint['policy'])
    initial.eval(); candidate.eval()
    pairs = []
    for index in range(games):
        # Training seeds are nonnegative and monotonically increasing. Keep a
        # separate, explicitly bounded domain for reproducible evaluation seeds.
        seed = 2**63 + index
        seat = f'player_{index % 8}'
        row = dict(seed=seed, seat=seat)
        for name, model in [('initial', initial), ('candidate', candidate)]:
            result = eval_vs_opponents(model, env, opponent='scripted', n_games=1, seat=seat, seed=seed)
            row[name] = result['mean_placement']
        pairs.append(row)
        print(json.dumps(row), flush=True)
    differences = np.array([p['candidate'] - p['initial'] for p in pairs])
    report = dict(schema_version=1, kind='policy_paired_evaluation', scope='synthetic_laboratory',
                  checkpoint_sha256=seal['sha256'], games_per_policy=games,
                  evaluation_matches=games*2, opponent='scripted', seed_domain='2**63 + index',
                  pairs=pairs, initial_mean_placement=float(np.mean([p['initial'] for p in pairs])),
                  candidate_mean_placement=float(np.mean([p['candidate'] for p in pairs])),
                  paired_placement_delta=float(differences.mean()),
                  lower_placement_is_better=True,
                  training_improvement_proven=False, real_tft_accuracy=None,
                  runtime_promoted=False, elapsed_seconds=time.monotonic()-start,
                  caveat='Small synthetic evaluation measures this laboratory only, not real TFT skill')
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, report)
    print(json.dumps(report), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('.'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--games', type=int, default=8)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    evaluate(args.project, args.run, args.output, args.games, args.seconds)


if __name__ == '__main__':
    main()
