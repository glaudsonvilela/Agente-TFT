"""Bounded offline PPO with tick combat, resumable checkpoints and honest counters.

Only the explicitly synthetic laboratory is implemented. Current-patch runs fail
before importing a model. No artifacts from this worker are promoted to the HUD.
The external MIT engine is pinned by scripts/bootstrap_tft_goat.sh.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

PIN = 'd5358e9402569f745bea81b61c5aed0500c57d66'
ADAPTER = 'tft_goat_synthetic_tick_v1'


def atomic_json(path: Path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gae(rewards, values, dones, bootstrap, gamma=.997, lam=.95):
    """Bootstrap a bounded rollout; an eliminated player has zero future value."""
    advantages = [0.0] * len(rewards)
    last = 0.0
    for t in reversed(range(len(rewards))):
        next_value = values[t + 1] if t + 1 < len(values) else bootstrap
        live = 0.0 if dones[t] else 1.0
        delta = rewards[t] + gamma * next_value * live - values[t]
        last = delta + gamma * lam * live * last
        advantages[t] = last
    return advantages, [a + v for a, v in zip(advantages, values)]


def load_engine(project):
    upstream = project / 'training/upstream/TFT_GOAT'
    actual = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    changes = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain', '--untracked-files=normal'], text=True)
    if actual != PIN or changes.strip():
        raise ValueError('Upstream pin or working tree changed; run bootstrap_tft_goat.sh')
    sys.path.insert(0, str(upstream / 'src'))


@contextmanager
def exclusive_worker(output):
    # flock releases even on SIGKILL; stale PID files cannot block a restart.
    import fcntl
    with (output / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('A worker already owns this output directory') from error
        yield


class StopWorker(Exception):
    pass


class Monitor:
    def __init__(self, output, seconds, memory_mib):
        self.output, self.seconds, self.memory_mib = output, seconds, memory_mib
        self.started = time.monotonic()
        self.previous = 0.0
        self.stopping = False
        self.row = dict(schema_version=1, kind='policy_selfplay', adapter=ADAPTER,
                        scope='synthetic_laboratory', status='initializing',
                        official_patch=None, current_patch_training_ready=False,
                        runtime_promoted=False, matches_completed=0, transitions=0,
                        iterations=0, optimizer_steps=0, changed_parameter_tensors=0,
                        combat_calls=0, training_improvement_proven=False,
                        pid=os.getpid())

    def check(self):
        elapsed = time.monotonic() - self.started
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if self.stopping or (self.output / 'STOP').exists():
            raise StopWorker('stop_requested')
        if elapsed >= self.seconds:
            raise StopWorker('time_budget_exhausted')
        if rss > self.memory_mib:
            raise StopWorker('memory_budget_exhausted')
        if elapsed - self.previous >= 5:
            self.publish()

    def publish(self, **values):
        self.row.update(values)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self.row.update(updated_at_ms=time.time_ns() // 1_000_000,
                        elapsed_seconds=time.monotonic() - self.started,
                        peak_rss_mib=usage.ru_maxrss / 1024,
                        process_cpu_seconds=usage.ru_utime + usage.ru_stime)
        atomic_json(self.output / 'progress.json', self.row)
        self.previous = self.row['elapsed_seconds']


class Collector:
    """Keep game state between bounded batches, never retain a whole match's frames."""
    def __init__(self, env, policy, monitor, seed):
        self.env, self.policy, self.monitor = env, policy, monitor
        self.next_seed = seed
        self.obs = self.infos = None

    def collect(self, target, cfg):
        import numpy as np
        import torch
        from tft_goat.agent.obs import batch_obs, batch_masks
        from tft_goat.agent.rollout import Batch
        trajectories = []
        active = {}
        count = 0
        completed = 0
        with torch.inference_mode():
            while count < target:
                self.monitor.check()
                if not self.env.agents or self.obs is None:
                    self.obs, self.infos = self.env.reset(seed=self.next_seed)
                    self.next_seed += 1
                    active = {}
                agents = list(self.env.agents)
                ob = [self.obs[a] for a in agents]
                masks = [self.infos[a]['action_mask'] for a in agents]
                actions, logps, values = self.policy.act(batch_obs(ob, 'cpu'), batch_masks(masks, 'cpu'))
                actions, logps, values = (v.numpy() for v in (actions, logps, values))
                for i, agent in enumerate(agents):
                    if agent not in active:
                        active[agent] = dict(obs=[], masks=[], actions=[], logprobs=[], values=[], rewards=[], dones=[])
                        trajectories.append(active[agent])
                    t = active[agent]
                    for key, value in [('obs', ob[i]), ('masks', masks[i]), ('actions', int(actions[i])),
                                       ('logprobs', float(logps[i])), ('values', float(values[i]))]:
                        t[key].append(value)
                self.obs, rewards, terms, truncs, self.infos = self.env.step(dict(zip(agents, map(int, actions))))
                for a in agents:
                    active[a]['rewards'].append(float(rewards[a]))
                    active[a]['dones'].append(bool(terms[a] or truncs[a]))
                    if terms[a] or truncs[a]:
                        active[a]['bootstrap'] = 0.0
                count += len(agents)
                if not self.env.agents:
                    completed += 1
                    self.monitor.row['matches_completed'] += 1
                    goal = self.monitor.row.get('matches_goal')
                    if goal is not None and self.monitor.row['matches_completed'] >= goal:
                        break
            if self.env.agents:
                agents = list(self.env.agents)
                _, values = self.policy(batch_obs([self.obs[a] for a in agents], 'cpu'),
                                        batch_masks([self.infos[a]['action_mask'] for a in agents], 'cpu'))
                for a, value in zip(agents, values):
                    active[a]['bootstrap'] = float(value)
        columns = {k: [] for k in ['obs', 'masks', 'actions', 'logprobs', 'values', 'advantages', 'returns']}
        for t in trajectories:
            advantage, returns = gae(t['rewards'], t['values'], t['dones'], t.get('bootstrap', 0), cfg.gamma, cfg.gae_lambda)
            t.update(advantages=advantage, returns=returns)
            for key in columns:
                columns[key].extend(t[key])
        for key in ['actions', 'logprobs', 'values', 'advantages', 'returns']:
            columns[key] = np.asarray(columns[key], dtype=np.int64 if key == 'actions' else np.float32)
        return Batch(**columns, mean_game_reward=0.0, mean_game_len=0.0, n_games=completed)


def save_checkpoint(output, policy, optimizer, collector, monitor, config_hash):
    import numpy as np
    import torch
    number = monitor.row['iterations']
    path = output / f'checkpoint-{number:06d}.pt'
    temp = path.with_suffix('.tmp')
    state = np.random.get_state()
    torch.save(dict(adapter=ADAPTER, config_sha256=config_hash, upstream=PIN,
                    policy=policy.state_dict(), optimizer=optimizer.state_dict(),
                    next_seed=collector.next_seed, torch_rng=torch.get_rng_state(),
                    numpy_rng=[state[0], state[1].tolist(), state[2], state[3], state[4]],
                    counters={k: monitor.row[k] for k in ['iterations', 'optimizer_steps', 'transitions',
                                                        'matches_completed', 'combat_calls']},
                    # Resume deliberately starts a new episode, never reuses a seed.
                    partial_episode_discarded_on_resume=bool(collector.env.agents)), temp)
    temp.replace(path)
    seal = dict(path=path.name, sha256=sha(path), config_sha256=config_hash, runtime_promoted=False)
    atomic_json(output / 'checkpoint.json', seal)
    monitor.row.update(checkpoint_sha256=seal['sha256'], checkpoint_iteration=number)
    for old in sorted(output.glob('checkpoint-*.pt'))[:-2]:
        old.unlink()


def restore(output, policy, optimizer, monitor, config_hash):
    import numpy as np
    import torch
    seal = json.loads((output / 'checkpoint.json').read_text())
    path = output / seal['path']
    if path.parent != output or path.name != seal['path'] or sha(path) != seal['sha256']:
        raise ValueError('Checkpoint path or hash mismatch')
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    if checkpoint['config_sha256'] != config_hash or checkpoint['adapter'] != ADAPTER or checkpoint['upstream'] != PIN:
        raise ValueError('Checkpoint belongs to different content/engine/configuration')
    policy.load_state_dict(checkpoint['policy'])
    optimizer.load_state_dict(checkpoint['optimizer'])
    torch.set_rng_state(checkpoint['torch_rng'])
    state = checkpoint['numpy_rng']
    np.random.set_state((state[0], np.array(state[1], dtype=np.uint32), *state[2:]))
    monitor.row.update(checkpoint['counters'])
    monitor.row['resumed_partial_episode_discarded'] = checkpoint['partial_episode_discarded_on_resume']
    return checkpoint['next_seed']


def run(args):
    if args.profile != 'synthetic-lab':
        raise ValueError('Set18 training blocked: run training.simulator_lab.coverage for missing rules; no fallback to Set17')
    if not 1 <= args.threads <= 4 or not 64 <= args.batch_steps <= 4096:
        raise ValueError('Use 1..4 CPU threads and 64..4096 transitions per batch')
    if not 1 <= args.iterations <= 100000 or not 1 <= args.seconds <= 86400 or not 256 <= args.memory_mib <= 8192:
        raise ValueError('Invalid iteration, time or memory budget')
    if not 0 <= args.seed < 2**32 or (args.matches is not None and not 1 <= args.matches <= 1000000):
        raise ValueError('Invalid seed or match target')
    project, output = args.project.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with exclusive_worker(output):
        if not args.resume and any((output / n).exists() for n in ('config.json', 'checkpoint.json')):
            raise ValueError('Existing experiment: use --resume or a new output')
        config = dict(adapter=ADAPTER, pin=PIN, profile=args.profile, seed=args.seed,
                      threads=args.threads, batch_steps=args.batch_steps,
                      laboratory=json.loads((project / 'configs/simulation/laboratory-v1.json').read_text()))
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        if args.resume:
            if json.loads((output / 'config.json').read_text()) != config:
                raise ValueError('Resume configuration changed')
        else:
            atomic_json(output / 'config.json', config)
        monitor = Monitor(output, args.seconds, args.memory_mib)
        previous_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(sig, lambda *_: setattr(monitor, 'stopping', True))
        monitor.publish()
        try:
            load_engine(project)
            import numpy as np
            import torch
            from tft_goat.agent.config import PPOConfig
            from tft_goat.agent.network import ActorCritic
            from tft_goat.agent.ppo import ppo_update
            from tft_goat.data.sample import build_sample_content
            from tft_goat.engine.resolver import EngineResolver
            from tft_goat.env.tft_env import TftEnv
            torch.set_num_threads(args.threads)
            torch.set_num_interop_threads(1)
            torch.manual_seed(args.seed)
            np.random.seed(args.seed)
            cfg = PPOConfig(rollout_steps=args.batch_steps, minibatch_size=128, hidden_dim=128, update_epochs=2)

            class MeasuredResolver(EngineResolver):
                def resolve(self, *a, **kw):
                    monitor.check()
                    result = super().resolve(*a, **kw)
                    monitor.row['combat_calls'] += 1
                    return result

            env = TftEnv(set_content=build_sample_content(), resolver=MeasuredResolver())
            env.agents = []
            policy = ActorCritic(env.encoder.n_champ, env.encoder.n_trait, hidden_dim=128)
            optimizer = torch.optim.Adam(policy.parameters(), lr=cfg.lr)
            seed = restore(output, policy, optimizer, monitor, config_hash) if args.resume else args.seed
            collector = Collector(env, policy, monitor, seed)
            monitor.row.update(parameter_count=sum(p.numel() for p in policy.parameters()),
                               memory_limit_mib=args.memory_mib, cpu_threads=args.threads,
                               matches_goal=args.matches, torch_version=str(torch.__version__),
                               numpy_version=np.__version__)
            initial = [p.detach().clone() for p in policy.parameters()]
            start_iteration = monitor.row['iterations']
            for _ in range(args.iterations):
                if args.matches is not None and monitor.row['matches_completed'] >= args.matches:
                    break
                monitor.publish(status='collecting')
                batch = collector.collect(args.batch_steps, cfg)
                monitor.check()
                monitor.publish(status='optimizing')
                metrics = ppo_update(policy, optimizer, batch, cfg)
                if not all(math.isfinite(v) for v in metrics.values()) or not all(torch.isfinite(p).all() for p in policy.parameters()):
                    raise ValueError('Nonfinite policy update; checkpoint not written')
                monitor.row['iterations'] += 1
                monitor.row['optimizer_steps'] += cfg.update_epochs * math.ceil(len(batch) / cfg.minibatch_size)
                monitor.row['transitions'] += len(batch)
                monitor.row['changed_parameter_tensors'] = sum(not torch.equal(a, b) for a, b in zip(initial, policy.parameters()))
                monitor.row.update(metrics)
                save_checkpoint(output, policy, optimizer, collector, monitor, config_hash)
                monitor.publish(status='checkpoint_saved')
                with (output / 'metrics.jsonl').open('a') as stream:
                    stream.write(json.dumps(monitor.row, allow_nan=False) + '\n')
                print(json.dumps(monitor.row), flush=True)
                del batch
            monitor.publish(status='completed', invocation_iterations=monitor.row['iterations'] - start_iteration)
        except StopWorker as error:
            monitor.publish(status='stopped', reason=str(error),
                            unsaved_batch_discarded=True)
        except Exception as error:
            monitor.publish(status='failed', error=f'{type(error).__name__}: {error}')
            raise
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=['synthetic-lab', 'current-patch'], default='current-patch')
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--batch-steps', type=int, default=2048)
    parser.add_argument('--seconds', type=float, default=3600)
    parser.add_argument('--memory-mib', type=float, default=1536)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--seed', type=int, default=20261004)
    parser.add_argument('--matches', type=int, help='Stop after this total number of completed matches, including restored matches')
    parser.add_argument('--resume', action='store_true')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
