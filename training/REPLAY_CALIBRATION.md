# Replay calibration

`training/replay_calibration.py` summarizes telemetry produced by a replay or
lab session.

It reports:

- HUD/state field coverage;
- shop known/unknown coverage;
- board and lobby observation coverage;
- Opportunity cycle counts;
- `NO_CONFIDENT_CANDIDATE` rate;
- remote-evaluation triggers;
- evaluator feedback snapshot count;
- p50/p95/max for numeric telemetry metrics.

Example:

```bash
python -m training.replay_calibration   telemetry/data/match.jsonl   --output telemetry/data/match-calibration.json
```

Important: **coverage is not accuracy**.

Accuracy requires ground-truth annotations from real screenshots/replays. The
tool deliberately does not label an observed value as correct merely because it
exists.
