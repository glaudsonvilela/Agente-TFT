"""Train a small board-visible classifier with a whole-match holdout.

This gate cannot identify champions, ownership, actions or combat outcomes.
It produces diagnostic candidates and never promotes itself into the HUD.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

from training.board_review import validate, require
from training.simulator_lab.selfplay import atomic_json


def split_frames(document, holdout):
    groups = document.get('match_group_reviews', [])
    frame_groups = {f['sha256']: f.get('match_group') for f in document['frames']}
    for group in groups:
        require(all(frame_groups.get(h) == group.get('id')
                    for h in group.get('evidence_frame_sha256', [])), 'match evidence outside its group')
    reviewed = {g['id'] for g in groups if g.get('method') in
                {'assistant_visual_roster_review', 'human_visual_roster_review'}
                and g.get('evidence_frame_sha256')}
    require(holdout in reviewed, 'holdout match needs roster review evidence')
    train, test = [], []
    for f in document['frames']:
        require(f.get('match_group') in reviewed, 'every frame needs a reviewed match group')
        (test if f['match_group'] == holdout else train).append(f)
    require(train and test, 'train and holdout must be nonempty')
    require(not ({f['session_id'] for f in train} & {f['session_id'] for f in test}), 'session leakage')
    require(not ({f['pixel_sha256'] for f in train} & {f['pixel_sha256'] for f in test}), 'pixel leakage')
    for rows in (train, test):
        require({f['scene'] == 'board' for f in rows} == {True, False}, 'both classes needed in each split')
    return train, test


def run(annotations, output, holdout, steps=400):
    import numpy as np
    from PIL import Image
    import torch
    from torch import nn
    from torch.nn import functional as F
    import onnxruntime as ort

    require(50 <= steps <= 2000, 'step budget must be 50..2000')
    require(not output.exists(), 'use a new output directory')
    raw = annotations.read_bytes()
    doc = json.loads(raw)
    review_summary = validate(doc, annotations.parent)
    train, test = split_frames(doc, holdout)
    output.mkdir(parents=True)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(20261004)
    np.random.seed(20261004)
    def tensors(rows):
        arrays = []
        for f in rows:
            with Image.open(annotations.parent / f['image']) as im:
                arrays.append(np.asarray(im.convert('RGB').resize((160, 90), Image.Resampling.BILINEAR)))
        return (torch.from_numpy(np.stack(arrays).transpose(0, 3, 1, 2).copy()).float() / 255,
                torch.tensor([int(f['scene'] == 'board') for f in rows]))
    x, y = tensors(train)
    model = nn.Sequential(nn.Conv2d(3, 8, 5, stride=2, padding=2), nn.ReLU(),
                          nn.Conv2d(8, 16, 3, stride=2, padding=1), nn.ReLU(),
                          nn.Conv2d(16, 24, 3, stride=2, padding=1), nn.ReLU(),
                          nn.AdaptiveAvgPool2d((3, 5)), nn.Flatten(), nn.Linear(360, 2))
    initial = [p.detach().clone() for p in model.parameters()]
    optimizer = torch.optim.AdamW(model.parameters(), lr=.002)
    weights = 1 / torch.bincount(y).float()
    weights /= weights.sum()
    started = time.monotonic()
    losses = []
    with (output / 'training.jsonl').open('x') as log:
        for step in range(steps):
            indices = torch.randint(len(train), (24,))
            batch = (x[indices] * (torch.rand(24, 1, 1, 1) * .4 + .8)
                     + torch.randn(24, 3, 90, 160) * .015).clamp(0, 1)
            loss = F.cross_entropy(model(batch), y[indices], weight=weights)
            require(bool(torch.isfinite(loss)), 'nonfinite training loss')
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
            if step % 25 == 0 or step == steps - 1:
                progress = dict(kind='scene_gate_training', status='training', optimizer_steps=step + 1,
                                loss=losses[-1], elapsed_seconds=time.monotonic() - started,
                                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
                atomic_json(output / 'progress.json', progress)
                log.write(json.dumps(progress) + '\n'); log.flush()
    # Fixed final checkpoint; holdout is not used for early stopping or model selection.
    model.eval()
    xt, yt = tensors(test)
    with torch.inference_mode():
        probabilities = model(xt).softmax(1)[:, 1]
        predictions = probabilities >= .5
    confusion = [[0, 0], [0, 0]]
    for actual, predicted in zip(yt.tolist(), predictions.int().tolist()):
        confusion[actual][predicted] += 1
    torch.onnx.export(model, torch.zeros(1, 3, 90, 160), str(output / 'scene-gate.onnx'),
                      input_names=['frames'], output_names=['logits'],
                      dynamic_axes={'frames': {0: 'batch'}, 'logits': {0: 'batch'}},
                      opset_version=17, dynamo=False)
    options = ort.SessionOptions(); options.intra_op_num_threads = 1; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(output / 'scene-gate.onnx'), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    with torch.inference_mode():
        max_error = float(np.abs(session.run(None, {'frames': xt.numpy()})[0] - model(xt).numpy()).max())
    require(max_error < .001, 'ONNX parity failed')
    sample = xt[:1].numpy()
    for _ in range(10):
        session.run(None, {'frames': sample})
    timings = []
    for _ in range(100):
        before = time.perf_counter(); session.run(None, {'frames': sample})
        timings.append((time.perf_counter() - before) * 1000)
    report = dict(schema_version=1, kind='scene_gate_training', status='trained_evaluated',
                  scope='board_visible_only', annotation_sha256=hashlib.sha256(raw).hexdigest(),
                  review=review_summary, train_frames=len(train), holdout_frames=len(test),
                  train_matches=len({f['match_group'] for f in train}), holdout_matches=1,
                  split_method='whole_match_visual_roster_review', holdout_match=holdout,
                  input_size=[160, 90], optimizer_steps=steps,
                  parameter_count=sum(p.numel() for p in model.parameters()),
                  changed_parameter_tensors=sum(not torch.equal(a, b) for a, b in zip(initial, model.parameters())),
                  first_25_loss_mean=sum(losses[:25])/25, last_25_loss_mean=sum(losses[-25:])/25,
                  confusion_matrix=confusion, class_order=['not_board', 'board'],
                  holdout_correct=int((predictions == yt.bool()).sum()),
                  holdout_accuracy=float((predictions == yt.bool()).float().mean()),
                  onnx_max_absolute_error=max_error,
                  inference_cpu_ms_p50=float(np.percentile(timings, 50)),
                  inference_cpu_ms_p95=float(np.percentile(timings, 95)),
                  timing_scope='inference_only_excludes_capture_resize_transport',
                  model_sha256=hashlib.sha256((output / 'scene-gate.onnx').read_bytes()).hexdigest(),
                  model_bytes=(output / 'scene-gate.onnx').stat().st_size,
                  training_seconds=time.monotonic()-started,
                  peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                  human_verified=False, strategic_learning=False, runtime_promoted=False,
                  limitations=['Single heldout match; labels reviewed by assistant, not independently by human',
                               'Board visibility does not establish ownership, planning phase or tactical readiness'])
    atomic_json(output / 'report.json', report)
    atomic_json(output / 'predictions.json', [dict(sha256=f['sha256'], scene=f['scene'],
                board_probability=float(p)) for f, p in zip(test, probabilities)])
    atomic_json(output / 'metadata.json', dict(schema_version=1, kind='scene_gate', input_size=[160, 90],
                resize='bilinear_rgb', scale=1/255, classes=['not_board', 'board'],
                model_sha256=report['model_sha256'], game_state_write_allowed=False,
                runtime_promoted=False, patch_independent=True))
    atomic_json(output / 'COMPLETE.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.iterdir() if p.name not in {'progress.json', 'COMPLETE.json'}})
    atomic_json(output / 'progress.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--holdout-match', required=True)
    parser.add_argument('--steps', type=int, default=400)
    args = parser.parse_args()
    run(args.annotations, args.output, args.holdout_match, args.steps)
